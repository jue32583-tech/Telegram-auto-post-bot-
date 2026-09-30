"""
Telegram Multi-Platform Publisher — button-driven production foundation.

This version implements the Telegram-side workflow:
- Burmese-first inline-button menu
- Photo/text/video draft intake
- Movie caption, synopsis, hashtags, and up to two video-link fields
- Telegram target-channel selection
- External platform selection placeholders
- Account-slot selection for future platform adapters
- Preview, admin-only publish, duplicate protection, and result status

External Facebook, Instagram, X, and Threads publishing is intentionally marked
as NOT_CONFIGURED until official API credentials and permissions are verified.
Video files are never downloaded by this workflow; only Telegram file IDs and
links are retained.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from platform_adapters import PlatformPublishError, publish_to_platform

load_dotenv()

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PRIVATE_GROUP_LINK = os.getenv("TELEGRAM_PRIVATE_GROUP_LINK", "").strip()
STATE_FILE = Path(os.getenv("BOT_STATE_FILE", "bot_state.json"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
AUTO_FORWARD_ENABLED = os.getenv("AUTO_FORWARD_ENABLED", "False").lower() == "true"
AUTO_FORWARD_NOTIFY_ADMINS = os.getenv("AUTO_FORWARD_NOTIFY_ADMINS", "True").lower() == "true"


def parse_chat_refs(raw: str) -> list[int | str]:
    refs: list[int | str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item.lstrip("-").isdigit():
            refs.append(int(item))
        else:
            refs.append(item.lower().lstrip("@"))
    return refs

ADMIN_IDS: set[int] = set()
for raw_id in os.getenv("TELEGRAM_ADMIN_IDS", "").split(","):
    raw_id = raw_id.strip()
    if raw_id.isdigit():
        ADMIN_IDS.add(int(raw_id))

try:
    TARGET_CHANNELS: dict[str, str] = json.loads(
        os.getenv("TELEGRAM_TARGET_CHANNELS", "{}")
    )
    if not isinstance(TARGET_CHANNELS, dict):
        TARGET_CHANNELS = {}
except json.JSONDecodeError:
    TARGET_CHANNELS = {}

SOURCE_CHATS = parse_chat_refs(os.getenv("TELEGRAM_SOURCE_CHATS", ""))

SUPPORTED_PLATFORMS = ("facebook", "instagram", "x", "threads")
MAX_LINKS = 2
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram-publisher")

# -----------------------------------------------------------------------------
# Small JSON state store
# -----------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"drafts": {}, "publish_log": {}, "forward_log": {}}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value.setdefault("drafts", {})
            value.setdefault("publish_log", {})
            value.setdefault("forward_log", {})
            return value
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load state file: %s", exc)
    return {"drafts": {}, "publish_log": {}, "forward_log": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{STATE_FILE.name}.", dir=str(STATE_FILE.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            json.dump(state, temp_file, ensure_ascii=False, indent=2)
        os.replace(temp_name, STATE_FILE)
    except OSError:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


STATE = load_state()

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def is_admin(user_id: int | None) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def new_draft(user_id: int, chat_id: int) -> dict[str, Any]:
    draft_id = f"{user_id}-{int(time.time() * 1000)}"
    draft = {
        "draft_id": draft_id,
        "owner_user_id": user_id,
        "source_chat_id": chat_id,
        "source_message_id": None,
        "caption": "",
        "image_file_id": None,
        "video_file_id": None,
        "logo_file_id": None,
        "video_links": [],
        "telegram_targets": list(TARGET_CHANNELS.keys()),
        "platform_targets": [],
        "account_slots": {platform: "round_robin" for platform in SUPPORTED_PLATFORMS},
        "status": "draft",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "publish_results": {},
    }
    STATE["drafts"][draft_id] = draft
    save_state(STATE)
    return draft


def current_draft(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    draft_id = context.user_data.get("draft_id")
    if not draft_id:
        return None
    draft = STATE["drafts"].get(draft_id)
    return draft if isinstance(draft, dict) else None


def touch(draft: dict[str, Any]) -> None:
    draft["updated_at"] = utc_now()
    save_state(STATE)


def extract_links(text: str) -> list[str]:
    links: list[str] = []
    for raw_url in URL_RE.findall(text or ""):
        clean_url = raw_url.rstrip(".,;!?)]}")
        if clean_url not in links and valid_url(clean_url):
            links.append(clean_url)
        if len(links) == MAX_LINKS:
            break
    return links


def valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def chat_matches_ref(chat: Any, ref: int | str) -> bool:
    if chat is None:
        return False
    if isinstance(ref, int):
        return chat.id == ref
    username = (getattr(chat, "username", None) or "").lower().lstrip("@")
    return username == ref or str(chat.id) == ref


def is_source_chat(chat: Any) -> bool:
    return bool(SOURCE_CHATS) and any(chat_matches_ref(chat, ref) for ref in SOURCE_CHATS)


def is_same_chat_as_target(chat: Any, target: str) -> bool:
    target_ref = str(target).lower().lstrip("@")
    username = (getattr(chat, "username", None) or "").lower().lstrip("@")
    return target_ref in {username, str(getattr(chat, "id", ""))}


async def auto_forward_message(
    context: ContextTypes.DEFAULT_TYPE,
    message: Any,
) -> bool:
    """Forward configured source-chat posts to Telegram target channels once."""
    if not AUTO_FORWARD_ENABLED or not is_source_chat(getattr(message, "chat", None)):
        return False

    source_chat_id = getattr(message, "chat_id", None)
    source_message_id = getattr(message, "message_id", None)
    if source_chat_id is None or source_message_id is None:
        return False

    event_key = f"{source_chat_id}:{source_message_id}"
    if event_key in STATE["forward_log"]:
        logger.info("Skipping duplicate source post %s", event_key)
        return True

    results: dict[str, str] = {}
    for channel_name, target in TARGET_CHANNELS.items():
        if is_same_chat_as_target(getattr(message, "chat", None), target):
            continue
        try:
            await context.bot.forward_message(
                chat_id=target,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            results[channel_name] = "forwarded"
        except Exception as exc:
            results[channel_name] = f"failed: {str(exc)[:160]}"
            logger.exception("Auto-forward failed for %s", channel_name)

    STATE["forward_log"][event_key] = {
        "source_chat_id": source_chat_id,
        "source_message_id": source_message_id,
        "results": results,
        "at": utc_now(),
    }
    save_state(STATE)

    if AUTO_FORWARD_NOTIFY_ADMINS and ADMIN_IDS:
        forwarded = sum(status == "forwarded" for status in results.values())
        failed = sum(status.startswith("failed") for status in results.values())
        notice = (
            "🔁 Auto-forward result\n\n"
            f"Source message: {source_message_id}\n"
            f"✅ Forwarded: {forwarded}\n"
            f"❌ Failed: {failed}"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=notice)
            except Exception:
                logger.debug("Could not notify admin %s", admin_id)
    return True


def display_platform(platform: str) -> str:
    return {"facebook": "Facebook", "instagram": "Instagram", "x": "X", "threads": "Threads"}.get(
        platform, platform
    )


def required_platform_env(platform: str, slot: str) -> list[str]:
    if platform == "facebook":
        return [f"FACEBOOK_ACCOUNT_{slot}_PAGE_ID", f"FACEBOOK_ACCOUNT_{slot}_TOKEN"]
    if platform == "instagram":
        return [f"INSTAGRAM_ACCOUNT_{slot}_IG_ID", f"INSTAGRAM_ACCOUNT_{slot}_TOKEN"]
    if platform == "threads":
        return [f"THREADS_ACCOUNT_{slot}_USER_ID", f"THREADS_ACCOUNT_{slot}_TOKEN"]
    if platform == "x":
        return [f"X_ACCOUNT_{slot}_USER_ACCESS_TOKEN"]
    return []


def choose_account_slot(platform: str, requested: str) -> str:
    if requested != "round_robin":
        return requested
    cursor_key = f"account_cursor:{platform}"
    start = int(STATE["publish_log"].get(cursor_key, 0)) % 5
    for offset in range(5):
        slot_number = ((start + offset) % 5) + 1
        slot = str(slot_number)
        if all(os.getenv(key, "").strip() for key in required_platform_env(platform, slot)):
            STATE["publish_log"][cursor_key] = slot_number
            return slot
    return "round_robin"


def composed_caption(draft: dict[str, Any]) -> str:
    pieces: list[str] = []
    caption = str(draft.get("caption", "")).strip()
    if caption:
        pieces.append(caption)
    for index, link in enumerate(draft.get("video_links", [])[:MAX_LINKS], start=1):
        pieces.append(f"Video link {index}: {link}")
    return "\n\n".join(pieces).strip() or "(No caption)"


def preview_text(draft: dict[str, Any]) -> str:
    telegram_targets = draft.get("telegram_targets", [])
    platform_targets = draft.get("platform_targets", [])
    account_slots = draft.get("account_slots", {})
    platform_lines = []
    for platform in platform_targets:
        slot = account_slots.get(platform, "round_robin")
        platform_lines.append(f"• {display_platform(platform)} — {slot}")
    if not platform_lines:
        platform_lines.append("• None selected")

    return (
        "🧾 POST PREVIEW\n\n"
        f"Draft: {draft['draft_id']}\n"
        f"Image: {'Yes' if draft.get('image_file_id') else 'No'}\n"
        f"Video: {'Yes' if draft.get('video_file_id') else 'No'}\n"
        f"User logo overlay: {'Yes' if draft.get('logo_file_id') else 'No'}\n\n"
        f"Caption and links:\n{composed_caption(draft)}\n\n"
        f"Telegram channels ({len(telegram_targets)}):\n"
        f"{', '.join(telegram_targets) if telegram_targets else 'None selected'}\n\n"
        "External platforms:\n"
        + "\n".join(platform_lines)
        + "\n\n"
        "External publishing will show NOT_CONFIGURED until official API credentials pass a health check."
    )


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ New Post / ပို့စ်အသစ်", callback_data="new_post")],
            [
                InlineKeyboardButton("📚 My Drafts", callback_data="my_drafts"),
                InlineKeyboardButton("📊 Status", callback_data="status"),
            ],
            [InlineKeyboardButton("❓ Help / အကူအညီ", callback_data="help")],
        ]
    )


def editor_keyboard(draft: dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎬 Add Video", callback_data="video"),
                InlineKeyboardButton("📝 Caption", callback_data="edit_caption"),
                InlineKeyboardButton("🔗 Link 1", callback_data="link:0"),
                InlineKeyboardButton("🔗 Link 2", callback_data="link:1"),
            ],
            [
                InlineKeyboardButton("📡 Telegram Channels", callback_data="channels"),
                InlineKeyboardButton("🌐 Platforms", callback_data="platforms"),
            ],
            [
                InlineKeyboardButton("👤 Account Slots", callback_data="accounts"),
                InlineKeyboardButton("🖼 My Logo", callback_data="logo"),
                InlineKeyboardButton("👁 Preview", callback_data="preview"),
            ],
            [
                InlineKeyboardButton("✅ Publish", callback_data="publish"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_draft"),
            ],
        ]
    )


def channels_keyboard(draft: dict[str, Any]) -> InlineKeyboardMarkup:
    selected = set(draft.get("telegram_targets", []))
    rows: list[list[InlineKeyboardButton]] = []
    names = list(TARGET_CHANNELS.keys())
    for start in range(0, len(names), 2):
        row: list[InlineKeyboardButton] = []
        for index in range(start, min(start + 2, len(names))):
            name = names[index]
            mark = "✅" if name in selected else "⬜"
            row.append(InlineKeyboardButton(f"{mark} {name}", callback_data=f"channel:{index}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("↩️ Back to editor", callback_data="editor")])
    return InlineKeyboardMarkup(rows)


def platforms_keyboard(draft: dict[str, Any]) -> InlineKeyboardMarkup:
    selected = set(draft.get("platform_targets", []))
    rows = []
    for platform in SUPPORTED_PLATFORMS:
        mark = "✅" if platform in selected else "⬜"
        rows.append(
            [InlineKeyboardButton(f"{mark} {display_platform(platform)}", callback_data=f"platform:{platform}")]
        )
    rows.append([InlineKeyboardButton("↩️ Back to editor", callback_data="editor")])
    return InlineKeyboardMarkup(rows)


def accounts_keyboard(draft: dict[str, Any]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for platform in SUPPORTED_PLATFORMS:
        current = draft.get("account_slots", {}).get(platform, "round_robin")
        buttons = [
            InlineKeyboardButton(
                f"{display_platform(platform)}: {current}", callback_data=f"account:{platform}:round_robin"
            )
        ]
        for slot in range(1, 6):
            buttons.append(
                InlineKeyboardButton(str(slot), callback_data=f"account:{platform}:{slot}")
            )
        rows.append(buttons)
    rows.append([InlineKeyboardButton("↩️ Back to editor", callback_data="editor")])
    return InlineKeyboardMarkup(rows)


async def compose_photo_with_logo(context: ContextTypes.DEFAULT_TYPE, draft: dict[str, Any]) -> BytesIO | None:
    """Download only the Telegram photo/logo, composite in memory, and return JPEG bytes."""
    image_file_id = draft.get("image_file_id")
    logo_file_id = draft.get("logo_file_id")
    if not image_file_id:
        return None
    if not logo_file_id:
        return None

    image_file = await context.bot.get_file(image_file_id)
    logo_file = await context.bot.get_file(logo_file_id)
    image_bytes = await image_file.download_as_bytearray()
    logo_bytes = await logo_file.download_as_bytearray()

    base = Image.open(BytesIO(image_bytes)).convert("RGBA")
    logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
    max_width = max(1, int(base.width * 0.22))
    scale = min(1.0, max_width / max(1, logo.width))
    logo = logo.resize((max(1, int(logo.width * scale)), max(1, int(logo.height * scale))), Image.LANCZOS)
    margin = max(12, int(min(base.width, base.height) * 0.025))
    position = (base.width - logo.width - margin, base.height - logo.height - margin)
    base.alpha_composite(logo, dest=position)

    output = BytesIO()
    base.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
    output.seek(0)
    output.name = "telegram_post_with_logo.jpg"
    return output


async def safe_edit(query: Any, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await query.edit_message_text(text=text, reply_markup=markup)
    except Exception as exc:
        logger.debug("Could not edit callback message: %s", exc)


async def send_editor(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    draft = current_draft(context)
    if not draft:
        await update.effective_message.reply_text("Draft မရှိသေးပါ။ New Post ကိုနှိပ်ပါ။", reply_markup=menu_keyboard())
        return
    message = (note + "\n\n" if note else "") + "Draft ကို ခလုပ်များဖြင့် ပြင်နိုင်ပါပြီ။"
    await update.effective_message.reply_text(message, reply_markup=editor_keyboard(draft))

# -----------------------------------------------------------------------------
# Telegram commands and intake
# -----------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name if update.effective_user else "User"
    await update.effective_message.reply_text(
        f"မင်္ဂလာပါ {user_name}။\n\nTelegram post ကို channel များနှင့် platform များသို့ ပို့ရန် အောက်က ခလုပ်ကို သုံးပါ။",
        reply_markup=menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "အသုံးပြုပုံ:\n\n"
        "1. New Post ကိုနှိပ်ပါ။\n"
        "2. 🎬 Add Video မှာ video ပို့ပါ (သို့) ပုံနှင့် caption ပို့ပါ။\n"
        "3. Movie ဇာတ်ညွှန်း၊ Link 1/Link 2၊ hashtag များထည့်ပါ။\n"
        "4. Channel နှင့် platform ရွေးပါ။\n"
        "5. Preview ကြည့်ပြီး admin က Publish ကိုနှိပ်ပါ။\n\n"
        "Video ကို bot က server သို့ download မလုပ်ဘဲ Telegram file_id ဖြင့် channel များသို့ ပို့ပါမည်။",
        reply_markup=menu_keyboard(),
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "🟢 Telegram publisher is running\n\n"
        f"Telegram channels configured: {len(TARGET_CHANNELS)}\n"
        f"Admin IDs configured: {len(ADMIN_IDS)}\n"
        f"Auto-forward: {'ON' if AUTO_FORWARD_ENABLED else 'OFF'}\n"
        f"Source chats configured: {len(SOURCE_CHATS)}\n"
        "Facebook/Instagram/X/Threads: adapter stage, credentials required\n"
        f"State file: {STATE_FILE.name}",
        reply_markup=menu_keyboard(),
    )


async def new_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    draft = new_draft(user.id, chat.id)
    context.user_data["draft_id"] = draft["draft_id"]
    context.user_data["mode"] = "awaiting_media"
    await update.effective_message.reply_text(
        "📥 Draft အသစ်ဖန်တီးပြီးပါပြီ။\n\n"
        "🎬 Add Video မှာ video ပို့ပါ၊ သို့မဟုတ် ပုံ/စာသား ပို့ပါ။ Movie ဇာတ်ညွှန်း၊ link နှစ်ခုနှင့် hashtag များကို ခလုတ်များဖြင့် ပြင်ဆင်နိုင်ပါတယ်။"
    )
