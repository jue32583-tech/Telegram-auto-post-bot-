"""
Telegram Auto Post Bot v4.9 (Bot Token Login - Official API ID fallback)
=========================================================================
Button နှိပ်ရုံဖြင့် အသုံးပြုနိုင်သော Bot
Source Channel post များကို AI ဖြင့် caption ပြောင်းပြီး
Configured target channels သို့ post တစ်ခုစီကို အလှည့်ကျတင်ပေးသော Bot

v4.9 Changes:
- Uses BOT_TOKEN login (no phone OTP needed)
- Uses official Telegram fallback API_ID 2000000 with known hash
  (documented by Telegram for bot MTProto login)
- Source channel reading works only if bot is member of source channel
  (add bot to source channel via invite link)
- Target channels (A, B, C) need bot added as admin
"""

import os
import json
import asyncio
import re
import base64
import mimetypes
from datetime import datetime
from dotenv import load_dotenv

from telethon import TelegramClient, events, Button


def load_encrypted_env():
    """Method 2: Load API keys from encrypted .env.encrypted file (optional)."""
    encrypted_file = ".env.encrypted"
    key_file = ".env.key"
    if os.path.exists(encrypted_file) and os.path.exists(key_file):
        try:
            from cryptography.fernet import Fernet  # noqa: F401
        except ImportError:
            print("⚠️ cryptography package not installed. Using embedded API keys.")
            return False
        try:
            with open(key_file, "rb") as f:
                key = f.read().strip()
            with open(encrypted_file, "rb") as f:
                encrypted = f.read()
            content = Fernet(key).decrypt(encrypted).decode("utf-8")
            for line in content.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            print("🔐 Loaded keys from .env.encrypted (Fernet 256-bit)")
            return True
        except Exception as e:
            print(f"⚠️ Encrypted env failed: {e}")
    return False


load_dotenv()
load_encrypted_env()

# ========================
# Configuration
# ========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# Telegram application credentials must be supplied by the operator; never guess or embed them.
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
SESSION_NAME = "auto_post_bot_session"
DATA_FILE = "bot_data.json"
POLL_INTERVAL = max(3, int(os.getenv("POLL_INTERVAL", "5")))
AI_TIMEOUT = max(3, int(os.getenv("AI_TIMEOUT", "8")))
CHANNEL_A_LINK = "https://t.me/+qQzDp0NEes85Zjg1"
FIXED_VIDEO_LINK = os.getenv("FIXED_VIDEO_LINK", "https://t.me/addlist/YuaibAle-uEwMWQ9").strip()

# Only these Telegram users may use configuration, monitoring, and test controls.
DESIGNATED_ADMIN_IDS = {6081621017, 6940887457, 6432487408}
DESIGNATED_ADMIN_USERNAMES = {"waiyanphyo99", "waiyan7861", "bingopop1991"}
BRIDGE_BASE_URL = os.getenv("BRIDGE_BASE_URL", "").rstrip("/")
BRIDGE_TOKEN = os.getenv("TELEGRAM_BOT_BRIDGE_TOKEN", "")

SYSTEM_PROMPT = (
    "You are a social media caption writer. Rewrite the given caption in an engaging, "
    "attractive style that draws attention. Keep the same meaning but make it more "
    "exciting and clickable. Add appropriate emojis. Return ONLY the rewritten caption, "
    "no explanations."
)

VISION_PROMPT = (
    "Look at this movie poster or movie still and create a ready-to-post Burmese movie entry. "
    "Return valid JSON only with keys movie_name, year, genre, caption, and hashtags. "
    "Use an empty string for year or genre when it cannot be read reliably. caption must be "
    "a concise, attractive Burmese synopsis based only on visible or clearly known information; "
    "do not invent actors, ratings, release years, or links. hashtags must contain exactly 5 "
    "short hashtags, without spaces inside a hashtag. Write Burmese when possible."
)


def rewrite_with_openai(original_text: str) -> str:
    """Rewrite caption using OpenAI GPT-4o-mini."""
    if not OPENAI_API_KEY:
        raise ValueError("No OpenAI API key")
    import requests
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Rewrite this caption: {original_text}"}
        ],
        "max_tokens": 500
    }
    resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=AI_TIMEOUT)
    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"]
    raise Exception(f"OpenAI error: {resp.status_code}")


def rewrite_with_gemini(original_text: str) -> str:
    """Rewrite caption using Google Gemini (Flash)."""
    if not GEMINI_API_KEY:
        raise ValueError("No Gemini API key")
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    data = {
        "contents": [
            {"parts": [{"text": f"{SYSTEM_PROMPT}\n\nRewrite this caption: {original_text}"}]}
        ],
        "generationConfig": {
            "maxOutputTokens": 500,
            "temperature": 0.9
        }
    }
    resp = requests.post(url, json=data, timeout=AI_TIMEOUT)
    if resp.status_code == 200:
        result = resp.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]
    raise Exception(f"Gemini error: {resp.status_code}")


def rewrite_caption_ai(original_text: str) -> str:
    """Rewrite text with the single configured Gemini provider."""
    if not original_text:
        return ""
    if GEMINI_API_KEY:
        try:
            result = rewrite_with_gemini(original_text)
            if result and result.strip():
                print("✅ AI: Gemini Flash")
                return result.strip()
        except Exception as e:
            print(f"⚠️ Gemini failed: {e}")

    return original_text


def analyze_image_with_gemini(image_bytes: bytes, mime_type: str, extra_text: str = "") -> dict:
    """Use Gemini vision to create a structured Burmese caption from one image."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is required for image captioning")
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    prompt = VISION_PROMPT + (f"\nUser-provided text and links: {extra_text}" if extra_text else "")
    payload = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
    ]}], "generationConfig": {"temperature": 0.7, "maxOutputTokens": 500, "responseMimeType": "application/json"}}
    response = requests.post(url, json=payload, timeout=AI_TIMEOUT)
    response.raise_for_status()
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.IGNORECASE).strip()
    result = json.loads(text)
    return {
        "movie_name": str(result.get("movie_name", "Movie")).strip(),
        "year": str(result.get("year", "")).strip(),
        "genre": str(result.get("genre", "")).strip(),
        "caption": str(result.get("caption", "")).strip(),
        "hashtags": result.get("hashtags", []),
    }


async def analyze_image_with_gemini_async(image_bytes: bytes, mime_type: str, extra_text: str = "") -> dict:
    return await asyncio.to_thread(analyze_image_with_gemini, image_bytes, mime_type, extra_text)


async def rewrite_caption_ai_async(original_text: str) -> str:
    """Run blocking AI HTTP calls in a worker thread, never in Telethon's loop."""
    if not original_text or (not OPENAI_API_KEY and not GEMINI_API_KEY):
        return original_text or ""
    return await asyncio.to_thread(rewrite_caption_ai, original_text)


# ========================
# Data Management
# ========================
def default_data() -> dict:
    return {
        "channels": {"source": [], "channel_a": "", "channel_b": "", "channel_c": "", "direct_target": ""},
        "forwarding": {"enabled": False, "last_message_id": {}, "mode": "text_and_video", "next_target_index": 0},
        "movie_draft": None,
        "owner_id": None,
        "status": "inactive",
    }


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return default_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        defaults = default_data()
        defaults["channels"].update(data.get("channels", {}))
        defaults["forwarding"].update(data.get("forwarding", {}))
        defaults["movie_draft"] = data.get("movie_draft")
        defaults["owner_id"] = data.get("owner_id")
        defaults["status"] = data.get("status", "inactive")
        return defaults
    except (OSError, json.JSONDecodeError) as error:
        print(f"⚠️ {DATA_FILE} is unreadable; starting with empty configuration: {error}")
        return default_data()


def save_data(data: dict):
    temporary_file = f"{DATA_FILE}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temporary_file, DATA_FILE)


def configured_targets(data: dict) -> list[tuple[str, str]]:
    """Return configured destinations in stable A/B/C order for round-robin posting."""
    channels = data.get("channels", {})
    return [(label, channels.get(key, "")) for label, key in (("A", "channel_a"), ("B", "channel_b"), ("C", "channel_c")) if channels.get(key)]


def next_target(data: dict) -> tuple[str, str] | None:
    targets = configured_targets(data)
    if not targets:
        return None
    index = int(data["forwarding"].get("next_target_index", 0)) % len(targets)
    return targets[index]


def advance_target(data: dict) -> None:
    targets = configured_targets(data)
    if targets:
        data["forwarding"]["next_target_index"] = (int(data["forwarding"].get("next_target_index", 0)) + 1) % len(targets)


def movie_draft_text(draft: dict) -> str:
    """Human-readable preview for the button-driven movie post editor."""
    return (
        "🎬 <b>Movie Post Draft</b>\n\n"
        f"Media: {'✅' if draft.get('media_path') else '❌'}\n"
        f"AI ဇာတ်ညွှန်း: {'✅' if draft.get('caption') else '❌ မထုတ်ရသေး'}\n"
        f"Hashtag: {'✅' if draft.get('hashtags') else '❌ မထုတ်ရသေး'}\n"
        f"Channel name: {draft.get('channel_name') or 'မထည့်ရသေး'}\n"
        f"Video link: {draft.get('video_link') or 'မထည့်ရသေး'}\n\n"
        f"<b>Caption preview</b>\n{draft.get('caption') or 'AI Caption ခလုပ်နှိပ်ပါ'}"
    )


def movie_editor_keyboard():
    return [
        [Button.inline("🤖 AI ဇာတ်ညွှန်း + #ထုတ်ရန်", b"movie_ai")],
        [Button.inline("✏️ Channel Name", b"movie_channel_name"), Button.inline("🔗 Video Link", b"movie_video_link")],
        [Button.inline("📤 နောက် channel သို့တင်မည်", b"movie_publish")],
        [Button.inline("❌ Draft ဖျက်မည်", b"movie_cancel"), Button.inline("↩️ Main Menu", b"back_main")],
    ]


def movie_caption_prompt(original: str, channel_name: str, video_link: str) -> str:
    return (
        "Write a Burmese movie post caption. Extract or infer the movie title and story details "
        "from the attached poster/image when available. Return only a ready-to-post caption with "
        "a short synopsis, attractive but accurate wording, 5-8 Burmese/English hashtags, and a "
        "video link line if provided. Do not invent specific actors or facts that are not visible.\n\n"
        f"Existing caption: {original or '(none)'}\nChannel name: {channel_name or '(none)'}\nVideo link: {video_link or '(none)'}"
    )


def rewrite_movie_with_openai(image_bytes: bytes | None, original: str, channel_name: str, video_link: str, mime_type: str = "image/jpeg") -> str:
    """Use OpenAI vision when a poster image is available, otherwise text-only AI."""
    if not OPENAI_API_KEY:
        raise ValueError("No OpenAI API key")
    import requests
    user_content = [{"type": "text", "text": movie_caption_prompt(original, channel_name, video_link)}]
    if image_bytes:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        user_content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}})
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": "gpt-4o-mini", "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}], "max_tokens": 700},
        timeout=AI_TIMEOUT,
    )
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"OpenAI vision error: {response.status_code} {response.text[:200]}")


async def generate_movie_caption(draft: dict) -> str:
    """Generate the guided movie caption with Gemini Vision only."""
    image_bytes = None
    mime_type = "image/jpeg"
    media_path = draft.get("media_path")
    if media_path and draft.get("media_kind") == "photo" and os.path.exists(media_path):
        with open(media_path, "rb") as media_file:
            image_bytes = media_file.read()
        mime_type = mimetypes.guess_type(media_path)[0] or mime_type
    if GEMINI_API_KEY:
        try:
            if image_bytes:
                analysis = await analyze_image_with_gemini_async(
                    image_bytes,
                    mime_type,
                    f"Existing caption: {draft.get('original_caption', '')}\nChannel name: {draft.get('channel_name', '')}\nVideo link: {draft.get('video_link', '')}",
                )
                return build_direct_caption(
                    analysis,
                    [draft["video_link"]] if draft.get("video_link") else [],
                    draft.get("channel_name") or "Movie Channel",
                )
            rewritten = await rewrite_caption_ai_async(draft.get("original_caption", ""))
            return build_direct_caption({"movie_name": "Movie", "caption": rewritten, "hashtags": []}, [], draft.get("channel_name") or "Movie Channel")
        except Exception as error:
            print(f"⚠️ Movie AI failed: {error}")
    return draft.get("original_caption", "") or "Movie post caption မရရှိပါ။"


def cleanup_movie_draft(draft: dict | None):
    if not draft:
        return
    path = draft.get("media_path")
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ========================
# Utility Functions
# ========================
def extract_channel_from_link(link: str) -> str:
    patterns = [
        r't\.me/(\+[\w-]+)',
        r't\.me/([\w-]+)',
        r'telegram\.me/([\w-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    if link.startswith("@"):
        return link[1:]
    return link


def get_channel_display_name(channel: str) -> str:
    if channel.startswith("@"):
        return channel
    return f"@{channel}"


def is_designated_admin(event) -> bool:
    """Server-side Telegram authorization for all control-surface actions."""
    sender_id = getattr(event, "sender_id", None)
    if sender_id is not None and int(sender_id) in DESIGNATED_ADMIN_IDS:
        return True
    sender = getattr(event, "sender", None)
    username = getattr(sender, "username", None)
    return bool(username and username.lower() in DESIGNATED_ADMIN_USERNAMES)


def public_button(text: str) -> bool:
    """Buttons that ordinary users may use without changing bot configuration."""
    return text in {"🎬 Direct Movie Post", "❓ Help"}


async def deny_non_admin(event):
    try:
        await event.respond("⛔ Channel setting နှင့် forwarding control များကို Admin များသာ အသုံးပြုနိုင်ပါတယ်။\n🎬 Direct Movie Post ကိုတော့ အသုံးပြုနိုင်ပါတယ်။")
    except Exception:
        try:
            await event.answer("⛔ Admin only", alert=True)
        except Exception:
            pass


def bridge_enabled() -> bool:
    return bool(BRIDGE_BASE_URL and BRIDGE_TOKEN)


def bridge_request(method: str, path: str, payload=None):
    if not bridge_enabled():
        return None
    import requests
    response = requests.request(
        method,
        f"{BRIDGE_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json() if response.content else None


async def bridge_sync_from_web(data: dict):
    """Pull web changes into the local worker config before monitoring."""
    if not bridge_enabled():
        return data
    try:
        remote = await asyncio.to_thread(bridge_request, "GET", "/api/bridge/config")
        if not remote:
            return data
        data["channels"]["source"] = remote.get("sourceChannels", [])
        data["channels"]["channel_a"] = remote.get("channelA", "")
        data["channels"]["channel_b"] = remote.get("channelB", "")
        data["channels"]["channel_c"] = remote.get("channelC", "")
        data["forwarding"]["mode"] = remote.get("forwardingMode", "text_and_video")
        data["forwarding"]["enabled"] = bool(remote.get("enabled", False))
        data["status"] = "active" if data["forwarding"]["enabled"] else "inactive"
        save_data(data)
    except Exception as error:
        print(f"⚠️ Bridge config sync failed: {error}")
    return data


async def bridge_push_config(data: dict, updated_by: str):
    if not bridge_enabled():
        return
    payload = {
        "sourceChannels": data["channels"].get("source", []),
        "channelA": data["channels"].get("channel_a", ""),
        "channelB": data["channels"].get("channel_b", ""),
        "channelC": data["channels"].get("channel_c", ""),
        "forwardingMode": data["forwarding"].get("mode", "text_and_video"),
        "enabled": bool(data["forwarding"].get("enabled", False)),
        "updatedBy": str(updated_by),
    }
    try:
        await asyncio.to_thread(bridge_request, "PUT", "/api/bridge/config", payload)
    except Exception as error:
        print(f"⚠️ Bridge config update failed: {error}")


async def bridge_record_activity(source: str, destination: str, content_type: str, status: str, message_id=None, error_message=None):
    if not bridge_enabled():
        return
    try:
        await asyncio.to_thread(bridge_request, "POST", "/api/bridge/activity", {
            "sourceChannel": source,
            "destinationChannel": destination,
            "contentType": content_type,
            "status": status,
            "messageId": str(message_id) if message_id is not None else None,
            "errorMessage": error_message,
        })
    except Exception as error:
        print(f"⚠️ Bridge activity write failed: {error}")


async def bridge_process_test_requests(tg_client):
    """Execute queued safe tests and report the actual Telegram result."""
    if not bridge_enabled():
        return
    try:
        response = await asyncio.to_thread(bridge_request, "GET", "/api/bridge/test-requests")
        for request in (response or {}).get("requests", []):
            status = "sent"
            message = f"✅ Bridge test from Telegram worker. Request #{request['id']}"
            try:
                await tg_client.send_message(request["targetAddress"], message)
                result_text = "Telegram worker delivered a test message successfully."
            except Exception as error:
                status = "failed"
                result_text = f"Telegram worker failed to send: {error}"
            await asyncio.to_thread(bridge_request, "POST", f"/api/bridge/test-requests/{request['id']}/result", {
                "status": status,
                "responseMessage": result_text,
            })
    except Exception as error:
        print(f"⚠️ Bridge test queue failed: {error}")


# ========================
# Keyboard Functions
# ========================
def get_main_keyboard():
    return [
        [Button.text("🎬 Movie Post တင်ရန်")],
        [Button.text("⚙️ Channel Setup"), Button.text("📊 Status")],
        [Button.text("🔄 Start Forwarding"), Button.text("⏹️ Stop Forwarding")],
        [Button.text("🎬 Direct Movie Post"), Button.text("🎯 Direct Target")],
        [Button.text("❓ Help"), Button.text("🔧 Settings")],
    ]


def get_setup_keyboard():
    return [
        [Button.inline("➕ Source Channel ထည့်ရန်", b"set_source")],
        [Button.inline("➕ Channel A ထည့်ရန်", b"set_channel_a")],
        [Button.inline("➕ Channel B ထည့်ရန်", b"set_channel_b")],
        [Button.inline("➕ Channel C ထည့်ရန်", b"set_channel_c")],
        [Button.inline("📋 View Channels", b"view_channels")],
        [Button.inline("↩️ Back", b"back_main")],
    ]


def get_forward_mode_keyboard():
    return [
        [Button.inline("📝 Text + Video", b"mode_text_video")],
        [Button.inline("🔄 Full Forward", b"mode_forward")],
        [Button.inline("📄 Text Only", b"mode_text")],
        [Button.inline("↩️ Back", b"back_main")],
    ]


def get_settings_keyboard():
    return [
        [Button.inline("🔁 Forward Mode ပြောင်းရန်", b"change_mode")],
        [Button.inline("🗑️ Reset All Data", b"reset_data")],
        [Button.inline("↩️ Back", b"back_main")],
    ]


# ========================
# Caption Formatter (Auto Format for Channel A)
# ========================
async def format_channel_a_caption(source_channel: str, original_text: str = "", media_type: str = "") -> str:
    """Format caption for Channel A: ပုံ + ဇာတ်ညွန် + Channel Link + Video Link"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ai_text = await rewrite_caption_ai_async(original_text)

    caption = ""
    if ai_text:
        caption += f"{ai_text}\n\n"

    caption += "━━━━━━━━━━━━━━━━━━━━\n"
    caption += f"📎 Source: {source_channel}\n"
    caption += f"📅 {now}\n"
    caption += "━━━━━━━━━━━━━━━━━━━━\n"
    if media_type:
        caption += f"🏷️ {media_type}\n"
    caption += f"🔗 Join: {CHANNEL_A_LINK}\n"
    caption += f"📺 Channel: {source_channel}"
    return caption


async def format_caption(source_channel: str, original_text: str, media_type: str) -> str:
    return await format_channel_a_caption(source_channel, original_text, media_type)


# ========================
# Create Client
# ========================
def create_client():
    """Create a Telethon client and recover from an incompatible legacy SQLite session."""
    try:
        return TelegramClient(SESSION_NAME, API_ID, API_HASH)
    except ValueError as error:
        message = str(error).lower()
        if "too many values to unpack" not in message and "not enough values to unpack" not in message:
            raise
        session_path = f"{SESSION_NAME}.session"
        if os.path.exists(session_path):
            backup_path = f"{session_path}.legacy-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            os.replace(session_path, backup_path)
            print(f"⚠️ Legacy Telethon session backed up to {backup_path}")
        print("ℹ️ A fresh Telegram session will be created. PM2 must be started once interactively if Telegram requests login.")
        return TelegramClient(SESSION_NAME, API_ID, API_HASH)


def ensure_event_loop():
    """Python 3.14 no longer creates a MainThread loop implicitly."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


ensure_event_loop()
client = create_client()


# ========================
# /start Handler - Main Menu
# ========================
async def start_handler(event):
    """Handle /start - Show main menu with buttons."""
    admin = is_designated_admin(event)
    data = load_data()
    data["owner_id"] = event.chat_id
    save_data(data)

    buttons = get_main_keyboard() if admin else [
        [Button.text("🎬 Direct Movie Post")],
        [Button.text("❓ Help")],
    ]
    admin_line = "⚙️ Admin Controls - Channel/Forwarding setting\n" if admin else ""
    welcome = (
        "🤖 <b>Telegram Auto Post Bot</b>\n\n"
        "👋 ကြိုဆိုပါတယ်! Button နှိပ်ပြီး အသုံးပြုပါ\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎬 Direct Movie Post - ပုံပို့ပြီး AI caption တင်\n"
        "❓ Help - အသုံးပြုနည်း\n"
        + admin_line
        + "━━━━━━━━━━━━━━━━━━━━\n\n"
        + "👇 အောက်က Button များကို နှိပ်ပါ"
    )
    await event.respond(
        welcome,
        parse_mode="HTML",
        buttons=buttons
    )


# ========================
# Button Press Handler
# ========================
async def handle_button_press(event):
    """Handle all button presses."""
    if not is_designated_admin(event) and not public_button(event.raw_text):
        await deny_non_admin(event)
        return
    text = event.raw_text

    if text == "🎬 Movie Post တင်ရန်":
        data = load_data()
        data["movie_draft"] = {"media_path": None, "media_kind": None, "original_caption": "", "caption": "", "hashtags": "", "channel_name": "", "video_link": "", "owner_id": event.sender_id or event.chat_id}
        data["pending_action"] = "movie_media"
        data["pending_chat_id"] = event.chat_id
        save_data(data)
        await event.respond(
            "🎬 <b>Movie Post အသစ်</b>\n\nMovie poster <b>ပုံ</b> သို့မဟုတ် <b>video</b> ကို အခု chat ထဲ ပို့ပါ။\nပြီးရင် AI ခလုပ်နဲ့ ဇာတ်ညွှန်း၊ hashtag ထုတ်ပြီး အလှည့်ကျ နောက် channel သို့ တင်နိုင်ပါတယ်။",
            parse_mode="HTML",
            buttons=[[Button.inline("❌ Cancel", b"movie_cancel")]],
        )
        return

    if text == "⚙️ Channel Setup":
        data = load_data()
        current = ""
        if data["channels"]["source"]:
            current += f"Source: {', '.join(data['channels']['source'])}\n"
        if data["channels"]["channel_a"]:
            current += f"Channel A: {data['channels']['channel_a']}\n"
        if data["channels"]["channel_b"]:
            current += f"Channel B: {data['channels']['channel_b']}\n"
        if data["channels"]["channel_c"]:
            current += f"Channel C: {data['channels']['channel_c']}\n"

        if not current:
            current = "Channel များ မထည့်ရသေးပါ"

        await event.respond(
            f"⚙️ <b>Channel Setup</b>\n\n{current}\n\nButton နှိပ်ပါ:",
            parse_mode="HTML",
            buttons=get_setup_keyboard()
        )

    elif text == "🔄 Start Forwarding":
        data = load_data()
        if not data["channels"]["source"]:
            await event.respond("⚠️ Source Channel မထည့်ရသေးပါ!\n⚙️ Channel Setup → Source Channel ထည့်ပါ")
            return
        if not configured_targets(data):
            await event.respond("⚠️ Target channel တစ်ခုမှ မထည့်ရသေးပါ!\n⚙️ Channel Setup ကို နှိပ်ပါ")
            return

        data["forwarding"]["enabled"] = True
        data["status"] = "active"
        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))

        await event.respond(
            f"✅ <b>Forwarding စတင်ပါပြီ!</b>\n\n"
            f"Source: {', '.join(data['channels']['source'])}\n"
            f"Channel A: {data['channels']['channel_a']}\n"
            f"Channel B: {data['channels']['channel_b']}\n"
            f"Channel C: {data['channels']['channel_c'] or 'မသတ်မှတ်ရသေး'}\n\n"
            f"Status: <b>ACTIVE</b>\n\n"
            f"Post တစ်ခုစီကို target channel တစ်ခုစီ အလှည့်ကျတင်ပါမည် (A → B → C → A)။",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )

    elif text == "⏹️ Stop Forwarding":
        data = load_data()
        data["forwarding"]["enabled"] = False
        data["status"] = "inactive"
        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))
        await event.respond(
            "⏹️ <b>Forwarding ရပ်ဆိုင်းပါပြီ</b>\n\n"
            "🔄 Start Forwarding နှိပ်ပြီး ပြန်စနိုင်ပါသည်။",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )

    elif text == "📊 Status":
        data = load_data()
        forwarding = data["forwarding"]["enabled"]
        status_text = "🟢 ACTIVE" if forwarding else "🔴 INACTIVE"

        # Verify source channel access
        source_check = "နှိပ်ပြီး စစ်ပါ"
        if data["channels"]["source"]:
            try:
                src = data["channels"]["source"][0].replace("@", "")
                entity = await client.get_entity(src)
                source_check = f"✅ ရ (ID: {entity.id})"
            except Exception as e:
                source_check = f"❌ မရ: {e}"

        await event.respond(
            f"📊 <b>Bot Status</b>\n\n"
            f"Forwarding: {status_text}\n"
            f"Mode: {data['forwarding']['mode']}\n\n"
            f"Source: {', '.join(data['channels']['source']) if data['channels']['source'] else 'မထည့်ရသေး'}\n"
            f"Source Access: {source_check}\n"
            f"Channel A: {data['channels']['channel_a'] or 'မထည့်ရသေး'}\n"
            f"Channel B: {data['channels']['channel_b'] or 'မထည့်ရသေး'}\n"
            f"Channel C: {data['channels']['channel_c'] or 'မထည့်ရသေး'}",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )

    elif text == "🎯 Direct Target":
        current = load_data()["channels"].get("direct_target", "") or "မထည့်ရသေးပါ"
        await event.respond(
            "🎯 <b>Direct Target Channel</b>\n\n"
            f"လက်ရှိ: {current}\n\n"
            "ကိုယ်ပိုင် channel link သို့မဟုတ် @username တစ်ခု ပေးပို့ပါ။\n"
            "Bot ကို အဲဒီ channel မှာ administrator အဖြစ် ထည့်ထားရပါမယ်။",
            parse_mode="HTML",
            buttons=[Button.inline("↩️ Back", b"back_main")]
        )
        data["pending_action"] = "set_direct_target"
        data["pending_chat_id"] = event.chat_id
        save_data(data)

    elif text == "🎬 Direct Movie Post":
        target = load_data()["channels"].get("direct_target", "")
        if not target:
            await event.respond("⚠️ အရင် 🎯 Direct Target ကိုနှိပ်ပြီး ကိုယ်ပိုင် channel တစ်ခု ထည့်ပါ။", buttons=get_main_keyboard())
            return
        await event.respond(
            "🎬 <b>Direct Movie Post</b>\n\n"
            "1) Movie ပုံပို့ပါ\n"
            "2) ပုံ caption ထဲမှာ video link ၁ ခု ထည့်ပါ (ဒုတိယ link ကို bot က အမြဲထည့်ပါမယ်)\n"
            "3) Gemini AI တစ်မျိုးတည်းက ပုံကြည့်ပြီး မြန်မာ caption + hashtag ၅ ခု ရေးပါမယ်\n"
            "4) ရွေးထားသော target channel တစ်ခုထဲသို့ auto တင်ပါမယ်\n\n"
            f"Target: {target}", parse_mode="HTML", buttons=get_main_keyboard()
        )

    elif text == "❓ Help":
        await event.respond(
            "❓ <b>Bot အသုံးပြုပုံ</b>\n\n"
            "<b>Step 1:</b> ⚙️ Channel Setup နှိပ်ပါ\n"
            "  → Source Channel Link ထည့်\n"
            "  → Channel A/B/C ထည့်\n\n"
            "<b>Step 2:</b> 🔄 Start Forwarding နှိပ်ပါ\n\n"
            "<b>Step 3:</b> Source Channel မှာ post အသစ်တင်လျှင်:\n"
            "  → Post (၁): Channel A\n"
            "  → Post (၂): Channel B\n"
            "  → Post (၃): Channel C\n"
            "  → ပြီးရင် A ကနေ ပြန်စပါမည်\n\n"
            "⚠️ Bot ကို Channel A, B, C တွင် Admin ထည့်ရမည်!\n"
            "Bot ကို Source Channel ထဲလည်း Member အဖြစ် ထည့်ပါ!\n\n"
            "🎬 Direct Movie Post: Bot ထံ movie ပုံပို့ပြီး caption ထဲ video link ထည့်ပါ။ Gemini AI က ပုံကိုဖတ်၍ caption နှင့် hashtag ၅ ခုရေးပြီး Direct Target channel သို့ တင်ပါမယ်။",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )

    elif text == "🔧 Settings":
        await event.respond(
            "🔧 <b>Settings</b>\n\nMode နှင့် Data Management:",
            parse_mode="HTML",
            buttons=get_settings_keyboard()
        )


# ========================
# Callback Query Handler (Inline Buttons)
# ========================
async def handle_callback(event):
    """Handle inline button callback queries."""
    if not is_designated_admin(event):
        await event.answer("⛔ Admin only", alert=True)
        return
    data = load_data()
    await event.answer()
    action = event.data.decode()

    if action == "movie_cancel":
        cleanup_movie_draft(data.get("movie_draft"))
        data["movie_draft"] = None
        data["pending_action"] = None
        data["pending_chat_id"] = None
        save_data(data)
        await event.edit("✅ Movie draft ဖျက်ပြီးပါပြီ။", buttons=get_main_keyboard())
        return

    if action == "movie_editor":
        draft = data.get("movie_draft")
        await event.edit(movie_draft_text(draft), parse_mode="HTML", buttons=movie_editor_keyboard()) if draft else await event.edit("⚠️ Movie draft မရှိပါ။", buttons=get_main_keyboard())
        return

    if action == "movie_ai":
        draft = data.get("movie_draft")
        if not draft or not draft.get("media_path"):
            await event.edit("⚠️ အရင်ဆုံး movie ပုံ/video ပို့ပါ။", buttons=movie_editor_keyboard())
            return
        await event.edit("🤖 AI က movie ပုံကိုဖတ်ပြီး ဇာတ်ညွှန်းနဲ့ hashtag ရေးနေပါတယ်... ခဏစောင့်ပါ။")
        draft["caption"] = await generate_movie_caption(draft)
        save_data(data)
        await event.respond(movie_draft_text(draft), parse_mode="HTML", buttons=movie_editor_keyboard())
        return

    if action in {"movie_channel_name", "movie_video_link"}:
        data["pending_action"] = action
        data["pending_chat_id"] = event.chat_id
        save_data(data)
        prompt = "📺 Channel name ပို့ပါ" if action == "movie_channel_name" else "🔗 Video link ပို့ပါ"
        await event.edit(prompt, buttons=[[Button.inline("↩️ Movie Editor", b"movie_editor")]])
        return

    if action == "movie_publish":
        draft = data.get("movie_draft")
        if not draft or not draft.get("media_path"):
            await event.edit("⚠️ Movie ပုံ/video မရှိသေးပါ။", buttons=movie_editor_keyboard())
            return
        target = next_target(data)
        target_text = f"Channel {target[0]} ({target[1]})" if target else "နောက် channel"
        await event.edit(f"📤 {target_text} သို့ movie post တင်နေပါတယ်... ခဏစောင့်ပါ။")
        results = await publish_movie_draft(client, draft, data)
        cleanup_movie_draft(draft)
        data["movie_draft"] = None
        data["pending_action"] = None
        data["pending_chat_id"] = None
        save_data(data)
        await event.respond("✅ Movie post တင်ပြီးပါပြီ။\n\n" + "\n".join(results), buttons=get_main_keyboard())
        return

    if action == "back_main":
        await event.edit(
            "🤖 <b>Telegram Auto Post Bot</b>\n\n"
            "Button နှိပ်ပြီး အသုံးပြုပါ:",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )
        return

    # ===== CHANNEL SETUP =====
    elif action == "set_source":
        await event.edit(
            "➕ <b>Source Channel Link ထည့်ပါ</b>\n\n"
            "Channel link ပေးပို့ပါ:\n\n"
            "Example: https://t.me/channelname\n"
            "Example: https://t.me/+invite_link\n\n"
            "⚠️ Bot ကို Source Channel ထဲ Member ထည့်ပါ!\n\n"
            "Link ပေးပို့ပါ:",
            parse_mode="HTML",
            buttons=[Button.inline("↩️ Back", b"back_main")]
        )
        data["pending_action"] = "set_source"
        data["pending_chat_id"] = event.chat_id
        save_data(data)
        return

    elif action == "set_channel_a":
        await event.edit(
            "➕ <b>Channel A ထည့်ပါ</b>\n\n"
            "ပုံ + ဇာတ်ညွန် + link တင်မည့် Channel\n\n"
            "⚠️ Bot ကို Channel A တွင် Admin ထည့်ရမည်!\n\n"
            "Example: https://t.me/channel_a",
            parse_mode="HTML",
            buttons=[Button.inline("↩️ Back", b"back_main")]
        )
        data["pending_action"] = "set_channel_a"
        data["pending_chat_id"] = event.chat_id
        save_data(data)
        return

    elif action == "set_channel_b":
        await event.edit(
            "➕ <b>Channel B ထည့်ပါ</b>\n\n"
            "Video တင်မည့် Channel\n\n"
            "⚠️ Bot ကို Channel B တွင် Admin ထည့်ရမည်!\n\n"
            "Example: https://t.me/channel_b",
            parse_mode="HTML",
            buttons=[Button.inline("↩️ Back", b"back_main")]
        )
        data["pending_action"] = "set_channel_b"
        data["pending_chat_id"] = event.chat_id
        save_data(data)
        return

    elif action == "set_channel_c":
        await event.edit(
            "➕ <b>Channel C ထည့်ပါ</b>\n\n"
            "နောက်ထပ် post တင်မည့် Channel\n\n"
            "⚠️ Bot ကို Channel C တွင် Admin ထည့်ရမည်!\n\n"
            "Example: https://t.me/channel_c",
            parse_mode="HTML",
            buttons=[Button.inline("↩️ Back", b"back_main")]
        )
        data["pending_action"] = "set_channel_c"
        data["pending_chat_id"] = event.chat_id
        save_data(data)
        return

    elif action == "view_channels":
        current = load_data()
        msg = "📋 <b>Current Channels</b>\n\n"
        msg += f"Source: {', '.join(current['channels']['source']) if current['channels']['source'] else 'မထည့်ရသေး'}\n"
        msg += f"Channel A: {current['channels']['channel_a'] or 'မထည့်ရသေး'}\n"
        msg += f"Channel B: {current['channels']['channel_b'] or 'မထည့်ရသေး'}\n"
        msg += f"Channel C: {current['channels']['channel_c'] or 'မထည့်ရသေး'}\n"
        msg += f"\nMode: {current['forwarding']['mode']}\n"
        msg += f"Status: {'🟢 ACTIVE' if current['forwarding']['enabled'] else '🔴 INACTIVE'}"
        await event.edit(msg, parse_mode="HTML", buttons=get_setup_keyboard())
        return

    # ===== SETTINGS =====
    elif action == "change_mode":
        current = load_data()
        await event.edit(
            f"📝 <b>Forward Mode ရွေးပါ</b>\n\nCurrent: {current['forwarding']['mode']}",
            parse_mode="HTML",
            buttons=get_forward_mode_keyboard()
        )
        return

    elif action == "mode_text_video":
        data["forwarding"]["mode"] = "text_and_video"
        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))
        await event.edit(
            "✅ Mode: <b>Text + Video</b>\n\nChannel A: ပုံ + ဇာတ်ညွန် + link\nChannel B: Video forward",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )
        return

    elif action == "mode_forward":
        data["forwarding"]["mode"] = "full_forward"
        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))
        await event.edit(
            "✅ Mode: <b>Full Forward</b>\n\nPost အားလုံးကို forward ပုံစံဖြင့် တင်",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )
        return

    elif action == "mode_text":
        data["forwarding"]["mode"] = "text_only"
        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))
        await event.edit(
            "✅ Mode: <b>Text Only</b>\n\nText post များကိုသာ repost",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )
        return

    elif action == "reset_data":
        await event.edit(
            "🗑️ <b>Data အားလုံး ဖျက်မည်လား?</b>\n\n"
            "⚠️ ပြန်လည်ရယူ၍ မရနိုင်ပါ!",
            parse_mode="HTML",
            buttons=[
                [Button.inline("✅ Yes, Reset", b"confirm_reset")],
                [Button.inline("❌ No, Cancel", b"back_main")]
            ]
        )
        return

    elif action == "confirm_reset":
        cleanup_movie_draft(data.get("movie_draft"))
        default = {
            "channels": {"source": [], "channel_a": "", "channel_b": "", "channel_c": ""},
            "forwarding": {"enabled": False, "last_message_id": {}, "mode": "text_and_video", "next_target_index": 0},
            "movie_draft": None,
            "owner_id": data.get("owner_id"),
            "status": "inactive",
        }
        save_data(default)
        await event.edit(
            "✅ Data အားလုံး Reset ပြီးပါပြီ!\n\nChannel များကို ပြန်ထည့်ပါ။",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )
        return


# ========================
# Text Message Handler (Channel Input)
# ========================
async def handle_movie_media(event):
    """Capture a movie photo/video sent to the bot for the active draft."""
    if not is_designated_admin(event):
        return
    data = load_data()
    if data.get("pending_action") != "movie_media" or data.get("pending_chat_id") != event.chat_id:
        return
    message = event.message
    if not (message.photo or message.video or message.document):
        return
    draft = data.get("movie_draft") or {}
    media_kind = "photo" if message.photo else "video" if message.video else "document"
    media_path = await message.download_media(file="movie_media")
    if not media_path:
        await event.respond("❌ Media download မအောင်မြင်ပါ။ ထပ်ပို့ကြည့်ပါ။")
        return
    cleanup_movie_draft(draft)
    draft.update({"media_path": media_path, "media_kind": media_kind, "original_caption": message.text or ""})
    data["movie_draft"] = draft
    data["pending_action"] = None
    data["pending_chat_id"] = None
    save_data(data)
    await event.respond(movie_draft_text(draft), parse_mode="HTML", buttons=movie_editor_keyboard())


async def handle_text_message(event):
    """Handle text messages for channel input."""
    if not is_designated_admin(event):
        return
    data = load_data()
    pending_action = data.get("pending_action")
    pending_chat_id = data.get("pending_chat_id")

    if not pending_action or pending_chat_id != event.chat_id:
        return

    text = event.message.text.strip()
    if not text:
        return

    if pending_action in {"movie_channel_name", "movie_video_link"}:
        draft = data.get("movie_draft") or {}
        if pending_action == "movie_channel_name":
            draft["channel_name"] = text
        else:
            draft["video_link"] = text
        data["movie_draft"] = draft
        data["pending_action"] = None
        data["pending_chat_id"] = None
        save_data(data)
        await event.respond(movie_draft_text(draft), parse_mode="HTML", buttons=movie_editor_keyboard())
        return

    if pending_action == "set_source":
        channel_name = extract_channel_from_link(text)
        display = f"@{channel_name}" if not channel_name.startswith("@") else channel_name

        if display not in data["channels"]["source"]:
            data["channels"]["source"].append(display)
        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))

        await event.respond(
            f"✅ Source ထည့်ပါပြီ: <b>{display}</b>\n\n"
            f"Sources: {', '.join(data['channels']['source'])}\n\n"
            f"ထပ်ထည့်လိုပါက Link ထပ်ပေးပို့ပါ",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )

    elif pending_action == "set_direct_target":
        channel_name = extract_channel_from_link(text)
        display = f"@{channel_name}" if not channel_name.startswith("@") else channel_name
        data["channels"]["direct_target"] = display
        save_data(data)
        await event.respond(
            f"✅ Direct Target ထည့်ပြီးပါပြီ: <b>{display}</b>\n\n"
            "အခု 🎬 Direct Movie Post ကိုနှိပ်ပြီး movie ပုံပို့နိုင်ပါပြီ။",
            parse_mode="HTML", buttons=get_main_keyboard()
        )

    elif pending_action in ["set_channel_a", "set_channel_b", "set_channel_c"]:
        channel_name = extract_channel_from_link(text)
        display = f"@{channel_name}" if not channel_name.startswith("@") else channel_name

        if pending_action == "set_channel_a":
            data["channels"]["channel_a"] = display
            label = "Channel A (ပုံ+ဇာတ်ညွန်+link)"
        elif pending_action == "set_channel_b":
            data["channels"]["channel_b"] = display
            label = "Channel B (Video)"
        else:
            data["channels"]["channel_c"] = display
            label = "Channel C (နောက်ထပ် post)"

        save_data(data)
        await bridge_push_config(data, str(event.sender_id or event.chat_id))

        await event.respond(
            f"✅ {label}: <b>{display}</b>\n\n"
            f"နောက် Channel ထည့်လိုပါက ⚙️ Channel Setup နှိပ်ပါ",
            parse_mode="HTML",
            buttons=get_main_keyboard()
        )

    # Clear pending
    data["pending_action"] = None
    data["pending_chat_id"] = None
    save_data(data)


async def publish_movie_draft(tg_client, draft: dict, data: dict) -> list[str]:
    """Publish one movie post to the next configured channel in round-robin order."""
    media_path = draft.get("media_path")
    if not media_path or not os.path.exists(media_path):
        return ["❌ Media file မတွေ့ပါ"]
    caption_parts = [str(draft.get("caption") or draft.get("original_caption") or "Movie Post").strip()]
    if draft.get("channel_name"):
        caption_parts.append(f"📺 Channel: {draft['channel_name']}")
    if draft.get("video_link"):
        caption_parts.append(f"🔗 Video: {draft['video_link']}")
    caption = "\n\n".join(part for part in caption_parts if part)
    target = next_target(data)
    if not target:
        return ["❌ Target channel မသတ်မှတ်ရသေးပါ"]
    label, destination = target
    try:
        await tg_client.send_file(destination, media_path, caption=caption, supports_streaming=draft.get("media_kind") == "video")
        advance_target(data)
        save_data(data)
        return [f"✅ Channel {label}: {destination}\nနောက် post ကို နောက် channel သို့ အလှည့်ကျတင်ပါမည်။"]
    except Exception as error:
        return [f"❌ Channel {label}: {str(error)[:150]}\nမအောင်မြင်သောကြောင့် next channel သို့ မရွှေ့သေးပါ။"]


# ========================
# Source Channel Monitoring
# ========================
async def check_source_channels(tg_client):
    """Periodically check source channels for new posts."""
    while True:
        await asyncio.sleep(POLL_INTERVAL)

        try:
            data = load_data()
            data = await bridge_sync_from_web(data)
            await bridge_process_test_requests(tg_client)
            if not data["forwarding"]["enabled"]:
                continue

            source_channels = data["channels"].get("source", [])
            if not source_channels:
                continue

            for source in source_channels:
                try:
                    channel_username = source.replace("@", "")
                    entity = await tg_client.get_entity(channel_username)
                    messages = await tg_client.get_messages(entity, limit=5)

                    if not messages:
                        continue

                    for message in reversed(messages):
                        msg_id = f"{source}:{message.id}"
                        if msg_id in data["forwarding"]["last_message_id"]:
                            continue

                        await process_and_repost(tg_client, message, entity, data, source)

                        data["forwarding"]["last_message_id"][msg_id] = message.id

                        if len(data["forwarding"]["last_message_id"]) > 100:
                            keys = list(data["forwarding"]["last_message_id"].keys())
                            for old_key in keys[:-100]:
                                del data["forwarding"]["last_message_id"][old_key]

                        save_data(data)

                except Exception as e:
                    print(f"Error checking {source}: {e}")
                    continue

        except Exception as e:
            print(f"Monitoring loop error: {e}")
            continue


# ========================
# Process and Repost
# ========================
async def process_and_repost(tg_client, message, entity, data, source_name):
    source_display = get_channel_display_name(source_name)

    try:
        destination_label, destination = await handle_round_robin_repost(tg_client, message, entity, data, source_display)

        content_type = "video" if message.video else "photo" if message.photo else "document" if message.document else "text"
        await bridge_record_activity(source_display, destination, content_type, "success", message.id)

        # Notify owner
        owner_id = data.get("owner_id")
        if owner_id:
            try:
                await tg_client.send_message(
                    owner_id,
                    f"✅ Post forward ပြီးပါပြီ!\nSource: {source_display}\nTarget: Channel {destination_label} ({destination})\nMessage ID: {message.id}"
                )
            except Exception:
                pass

    except Exception as e:
        print(f"Error reposting message {message.id}: {e}")
        await bridge_record_activity(source_display, "round-robin target", "unknown", "failed", message.id, str(e))
        owner_id = data.get("owner_id")
        if owner_id:
            try:
                await tg_client.send_message(owner_id, f"❌ Forward error: {e}\nSource: {source_display}")
            except Exception:
                pass


async def handle_round_robin_repost(tg_client, message, entity, data, source_display):
    """Send one source post to the current target, then advance after success."""
    target = next_target(data)
    if not target:
        raise RuntimeError("Target channel မသတ်မှတ်ရသေးပါ")
    label, destination = target
    caption = await format_channel_a_caption(
        source_display,
        message.text or "",
        "Video" if message.video else "Photo" if message.photo else "Document" if message.document else "Text",
    )
    try:
        if message.photo:
            await tg_client.send_file(destination, message.photo, caption=caption)
        elif message.video:
            await tg_client.send_file(destination, message.video, caption=caption, supports_streaming=True)
        elif message.document:
            await tg_client.send_file(destination, message.document, caption=caption)
        else:
            await tg_client.send_message(destination, caption)
    except Exception:
        raise
    advance_target(data)
    save_data(data)
    return label, destination


async def handle_text_video_mode(tg_client, message, entity, channel_a, channel_b, channel_c, source_display):
    channel_a_name = channel_a.replace("@", "")
    channel_b_name = channel_b.replace("@", "")
    channel_c_name = channel_c.replace("@", "")

    # ===== Channel A: Auto Format (ပုံ + ဇာတ်ညွန် + Channel Link + Video Link) =====
    media_type = ""
    if message.photo:
        media_type = "Photo"
    elif message.video:
        media_type = "Video"
    elif message.document:
        media_type = "Document"
    else:
        media_type = "Text"

    # Auto Format caption with AI rewrite
    caption_a = await format_channel_a_caption(source_display, message.text or "", media_type)

    if message.photo:
        await tg_client.send_file(channel_a_name, message.photo, caption=caption_a)
    elif message.video:
        await tg_client.send_file(channel_a_name, message.video, caption=caption_a, supports_streaming=True)
    elif message.document:
        await tg_client.send_file(channel_a_name, message.document, caption=caption_a)
    else:
        await tg_client.send_message(channel_a_name, caption_a)

    # ===== Channel B: Video Forward =====
    if message.video or message.video_note or message.gif:
        await tg_client.forward_messages(channel_b_name, message.id, entity)
    elif message.photo:
        await tg_client.forward_messages(channel_b_name, message.id, entity)

    # ===== Channel C: Next Post Auto Format =====
    caption_c = await format_channel_a_caption(source_display, message.text or "", "Next Post")
    if message.photo:
        await tg_client.send_file(channel_c_name, message.photo, caption=caption_c)
    elif message.video:
        await tg_client.send_file(channel_c_name, message.video, caption=caption_c, supports_streaming=True)
    elif message.document:
        await tg_client.send_file(channel_c_name, message.document, caption=caption_c)
    else:
        await tg_client.send_message(channel_c_name, caption_c)


async def handle_full_forward_mode(tg_client, message, channel_a, channel_b, channel_c):
    channel_a_name = channel_a.replace("@", "")
    channel_b_name = channel_b.replace("@", "")
    channel_c_name = channel_c.replace("@", "")

    try:
        await tg_client.forward_messages(channel_a_name, message.id, message.chat_id)
    except Exception:
        pass
    try:
        if message.video or message.video_note or message.gif or message.photo:
            await tg_client.forward_messages(channel_b_name, message.id, message.chat_id)
    except Exception:
        pass
    try:
        await tg_client.forward_messages(channel_c_name, message.id, message.chat_id)
    except Exception:
        pass


async def handle_text_only_mode(tg_client, message, entity, channel_a, channel_c, source_display):
    channel_a_name = channel_a.replace("@", "")
    channel_c_name = channel_c.replace("@", "")

    caption = await format_caption(source_display, message.text or "", "Text")
    await tg_client.send_message(channel_a_name, caption)
    await tg_client.send_message(channel_c_name, caption)


# ========================
# Direct Movie Post Workflow
# ========================
def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://\S+", text or "")
    links = []
    for url in urls:
        url = url.rstrip(".,)]}>")
        if url and url not in links:
            links.append(url)
        if len(links) == 1:
            break
    if FIXED_VIDEO_LINK and FIXED_VIDEO_LINK not in links:
        links.append(FIXED_VIDEO_LINK)
    return links[:2]


def hashtag_token(value: str) -> str:
    value = re.sub(r"[^\w\u1000-\u109F]+", "", str(value or ""), flags=re.UNICODE)
    return f"#{value}" if value else ""


def build_direct_caption(analysis: dict, links: list[str], target: str) -> str:
    movie_name = analysis.get("movie_name") or "Movie"
    year = analysis.get("year") or ""
    genre = analysis.get("genre") or ""
    caption = analysis.get("caption") or "Movie post"
    raw_hashtags = analysis.get("hashtags") or []
    hashtags = []
    for item in raw_hashtags:
        token = hashtag_token(item)
        if token and token.lower() not in {value.lower() for value in hashtags}:
            hashtags.append(token)
    fallbacks = [hashtag_token(movie_name), "#MyanmarMovie", hashtag_token(target), "#Movie", "#Telegram"]
    for item in fallbacks:
        if item and item.lower() not in {value.lower() for value in hashtags}:
            hashtags.append(item)
        if len(hashtags) == 5:
            break
    hashtags = hashtags[:5]
    title_line = f"🎬 Title: {movie_name}{f' [{year}]' if year else ''}"
    metadata = [title_line]
    if year:
        metadata.append(f"🗓 Year: {year}")
    if genre:
        metadata.append(f"🎭 Genre: {genre}")
    metadata.append(f"📺 Channel: {target}")
    metadata_text = "\n".join(metadata[1:])
    link_text = "\n".join(f"🔗 {link}" for link in links)
    link_section = f"\n\n👇 Video Link\n{link_text}" if link_text else ""
    return f"{title_line}\n\n💬 {caption}\n\n{metadata_text}\n\n{' '.join(hashtags)}{link_section}"


async def handle_direct_movie_post(event):
    """Receive one admin photo/video and post it to the selected direct target."""
    data = load_data()
    if data.get("pending_action") == "movie_media":
        # The admin guided editor owns this media message; avoid double posting.
        return
    target = data["channels"].get("direct_target", "")
    if not target:
        await event.respond("⚠️ အရင် 🎯 Direct Target channel ထည့်ပါ။", buttons=get_main_keyboard())
        return
    message = event.message
    links = extract_urls(message.text or "")
    try:
        if message.photo:
            image_bytes = await message.download_media(file=bytes)
            mime_type = getattr(getattr(message, "file", None), "mime_type", None) or "image/jpeg"
            analysis = await analyze_image_with_gemini_async(image_bytes, mime_type, message.text or "")
            caption = build_direct_caption(analysis, links, target)
            await client.send_file(target, image_bytes, caption=caption, force_document=False)
        elif message.video or message.document:
            rewritten = await rewrite_caption_ai_async(message.text or "")
            caption = build_direct_caption({"movie_name": "Movie", "caption": rewritten, "hashtags": []}, links, target)
            await client.send_file(target, message.media, caption=caption)
        else:
            await event.respond("⚠️ ပုံ သို့မဟုတ် video file ပို့ပါ။")
            return
        await event.respond(f"✅ Direct Movie Post အောင်မြင်ပါပြီ။\nTarget: {target}\nHashtags: ၅ ခု ထည့်ပြီးပါပြီ။", buttons=get_main_keyboard())
    except Exception as error:
        print(f"❌ Direct movie post failed: {error}")
        await event.respond(f"❌ Post မတင်နိုင်ပါ: {error}\nGemini key နှင့် target channel admin permission ကို စစ်ပါ။", buttons=get_main_keyboard())


# ========================
# Main Entry Point
# ========================
def validate_configuration():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN မရှိပါ။ .env သို့မဟုတ် host environment ထဲ BOT_TOKEN ထည့်ပါ။")
    if API_ID <= 0 or not API_HASH:
        raise RuntimeError("API_ID/API_HASH မရှိပါ။ my.telegram.org မှာ ကိုယ့် App API credentials ရယူပြီး .env ထဲ ထည့်ပါ။")
    if not GEMINI_API_KEY:
        print("⚠️ GEMINI_API_KEY မရှိပါ။ Direct Movie Post ၏ image caption AI မအလုပ်လုပ်ပါ။")


async def main():
    validate_configuration()
    print("🤖 Telegram Auto Post Bot v5.2 စတင်ပါပြီ...")
    print(f"   API_ID: {API_ID}")
    print(f"   Session: {SESSION_NAME}")

    # Bot token login - no phone OTP needed
    try:
        await client.start(bot_token=BOT_TOKEN)
    except Exception as error:
        print(f"❌ Telegram login မအောင်မြင်ပါ: {error}")
        print("   API_ID/API_HASH/BOT_TOKEN ကို environment variables ထဲတွင် စစ်ပါ။")
        raise
    me = await client.get_me()
    print(f"✅ Logged in as: {me.first_name} (@{me.username})")
    print("📌 Bot token login - Bot ကို channel တိုင်းတွင် member/admin ထည့်ရန် လို")
    if bridge_enabled():
        print(f"🔗 Shared dashboard bridge enabled: {BRIDGE_BASE_URL}")
    else:
        print("⚠️ Shared dashboard bridge disabled: set BRIDGE_BASE_URL and TELEGRAM_BOT_BRIDGE_TOKEN")

    # Register handlers - EXACT button text match
    button_texts = [
        "🎬 Movie Post တင်ရန်",
        "⚙️ Channel Setup",
        "🔄 Start Forwarding",
        "⏹️ Stop Forwarding",
        "🎬 Direct Movie Post",
        "🎯 Direct Target",
        "📊 Status",
        "❓ Help",
        "🔧 Settings",
    ]
    pattern = r"^(" + "|".join(re.escape(t) for t in button_texts) + r")$"

    client.add_event_handler(
        handle_button_press,
        events.NewMessage(pattern=pattern)
    )

    client.add_event_handler(
        handle_movie_media,
        events.NewMessage(func=lambda e: bool(e.message and (e.message.photo or e.message.video or e.message.document)))
    )

    client.add_event_handler(
        handle_callback,
        events.CallbackQuery
    )

    client.add_event_handler(
        handle_direct_movie_post,
        events.NewMessage(func=lambda e: e.is_private and bool(e.photo or e.video or e.document))
    )

    client.add_event_handler(
        handle_text_message,
        events.NewMessage(func=lambda e: e.text and not e.text.startswith("/"))
    )

    client.add_event_handler(
        start_handler,
        events.NewMessage(pattern=r"^/start$")
    )

    print("📋 /start")
    print(f"🔄 Source Channel monitoring: every {POLL_INTERVAL}s")
    print("━━━━━━━━━━━━━━━━━━━━")
    print("⏳ Waiting for commands...")

    asyncio.ensure_future(check_source_channels(client))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
