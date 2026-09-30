"""
Telegram Auto Post Bot v4.9 (Bot Token Login - Official API ID fallback)
=========================================================================
Button နှိပ်ရုံဖြင့် အသုံးပြုနိုင်သော Bot
Source Channel post များကို AI ဖြင့် caption ပြောင်းပြီး
Channel A/B/C မှာ Auto Format ဖြင့် တင်ပေးသော Bot

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
BOT_TOKEN = os.getenv("BOT_TOKEN", "8249701481:AAGsVCusZe5Dn8MJkPwGqMyeFVsJtlij3Bo")
# Official Telegram fallback API credentials for bot MTProto login
API_ID = int(os.getenv("API_ID", "2000000"))
API_HASH = os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")
# Embedded API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-89VAtJz2LmK0bYpQ4xRsTuVwXyZ6CdEfGhIjKlMnOpQrStUvWxYz")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SESSION_NAME = "auto_post_bot_session"
DATA_FILE = "bot_data.json"
CHANNEL_A_LINK = "https://t.me/+qQzDp0NEes85Zjg1"

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
    resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=30)
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
    resp = requests.post(url, json=data, timeout=30)
    if resp.status_code == 200:
        result = resp.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]
    raise Exception(f"Gemini error: {resp.status_code}")


def rewrite_caption_ai(original_text: str) -> str:
    """Rewrite caption using OpenAI first, fallback to Gemini, then original text."""
    if not original_text:
        return ""

    if OPENAI_API_KEY:
        try:
            result = rewrite_with_openai(original_text)
            if result and result.strip():
                print("✅ AI: OpenAI GPT-4o-mini")
                return result.strip()
        except Exception as e:
            print(f"⚠️ OpenAI failed: {e}")

    if GEMINI_API_KEY:
        try:
            result = rewrite_with_gemini(original_text)
            if result and result.strip():
                print("✅ AI: Gemini Flash")
                return result.strip()
        except Exception as e:
            print(f"⚠️ Gemini failed: {e}")

    return original_text


# ========================
# Data Management
# ========================
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "channels": {
            "source": [],
            "channel_a": "",
            "channel_b": "",
            "channel_c": "",
        },
        "forwarding": {
            "enabled": False,
            "last_message_id": {},
            "mode": "text_and_video",
        },
        "owner_id": None,
        "status": "inactive",
    }


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


async def deny_non_admin(event):
    try:
        await event.respond("⛔ ဒီ Bot ရဲ့ control buttons ကို သတ်မှတ်ထားသော admin များသာ အသုံးပြုနိုင်ပါတယ်။")
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
        [Button.text("⚙️ Channel Setup"), Button.text("📊 Status")],
        [Button.text("🔄 Start Forwarding"), Button.text("⏹️ Stop Forwarding")],
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
def format_channel_a_caption(source_channel: str, original_text: str = "", media_type: str = "") -> str:
    """Format caption for Channel A: ပုံ + ဇာတ်ညွန် + Channel Link + Video Link"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ai_text = rewrite_caption_ai(original_text)

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


def format_caption(source_channel: str, original_text: str, media_type: str) -> str:
    return format_channel_a_caption(source_channel, original_text, media_type)


# ========================
# Create Client
# ========================
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


# ========================
# /start Handler - Main Menu
# ========================
async def start_handler(event):
    """Handle /start - Show main menu with buttons."""
    if not is_designated_admin(event):
        await deny_non_admin(event)
        return
    data = load_data()
    data["owner_id"] = event.chat_id
    save_data(data)

    await event.respond(
        "🤖 <b>Telegram Auto Post Bot</b>\n\n"
        "👋 ကြိုဆိုပါတယ့်! Button နှိပ်ပြီး အသုံးပြုပါ\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ Channel Setup - Channel များ ထည့်\n"
        "🔄 Start Forwarding - Auto forward စတင်\n"
        "⏹️ Stop Forwarding - Auto forward ရပ်\n"
        "📊 Status - Bot Status ကြည့်\n"
        "🔧 Settings - Mode ပြောင်း\n"
        "❓ Help - အကူအညီ\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 အောက်က Button များကို နှိပ်ပါ",
        parse_mode="HTML",
        buttons=get_main_keyboard()
    )


# ========================
# Button Press Handler
# ========================
async def handle_button_press(event):
    """Handle all button presses."""
    if not is_designated_admin(event):
        await deny_non_admin(event)
        return
    text = event.raw_text

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
        if not all([data["channels"]["channel_a"], data["channels"]["channel_b"], data["channels"]["channel_c"]]):
            await event.respond("⚠️ Channel A, B, C မထည့်ရသေးပါ!\n⚙️ Channel Setup ကို နှိပ်ပါ")
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
            f"Channel C: {data['channels']['channel_c']}\n\n"
            f"Status: <b>ACTIVE</b>\n\n"
            f"Source Channel မှာ post အသစ်တင်လျှင် auto-repost လုပ်ပါမည်။",
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

    elif text == "❓ Help":
        await event.respond(
            "❓ <b>Bot အသုံးပြုပုံ</b>\n\n"
            "<b>Step 1:</b> ⚙️ Channel Setup နှိပ်ပါ\n"
            "  → Source Channel Link ထည့်\n"
            "  → Channel A/B/C ထည့်\n\n"
            "<b>Step 2:</b> 🔄 Start Forwarding နှိပ်ပါ\n\n"
            "<b>Step 3:</b> Source Channel မှာ post အသစ်တင်လျှင်:\n"
            "  → Channel A: ပုံ + ဇာတ်ညွန် + link\n"
            "  → Channel B: Video forward\n"
            "  → Channel C: နောက်ထပ် post\n\n"
            "⚠️ Bot ကို Channel A, B, C တွင် Admin ထည့်ရမည်!\n"
            "Bot ကို Source Channel ထဲလည်း Member အဖြစ် ထည့်ပါ!",
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
        default = {
            "channels": {"source": [], "channel_a": "", "channel_b": "", "channel_c": ""},
            "forwarding": {"enabled": False, "last_message_id": {}, "mode": "text_and_video"},
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


# ========================
# Source Channel Monitoring
# ========================
async def check_source_channels(tg_client):
    """Periodically check source channels for new posts."""
    while True:
        await asyncio.sleep(30)

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

                    for message in messages:
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
    channel_a = data["channels"]["channel_a"]
    channel_b = data["channels"]["channel_b"]
    channel_c = data["channels"]["channel_c"]
    mode = data["forwarding"]["mode"]

    source_display = get_channel_display_name(source_name)

    try:
        if mode == "text_and_video":
            await handle_text_video_mode(tg_client, message, entity, channel_a, channel_b, channel_c, source_display)
        elif mode == "full_forward":
            await handle_full_forward_mode(tg_client, message, channel_a, channel_b, channel_c)
        elif mode == "text_only":
            await handle_text_only_mode(tg_client, message, entity, channel_a, channel_c, source_display)

        content_type = "video" if message.video else "photo" if message.photo else "document" if message.document else "text"
        for destination in (channel_a, channel_b, channel_c):
            if destination:
                await bridge_record_activity(source_display, destination, content_type, "success", message.id)

        # Notify owner
        owner_id = data.get("owner_id")
        if owner_id:
            try:
                await tg_client.send_message(
                    owner_id,
                    f"✅ Post forward ပြီးပါပြီ!\nSource: {source_display}\nMessage ID: {message.id}"
                )
            except Exception:
                pass

    except Exception as e:
        print(f"Error reposting message {message.id}: {e}")
        await bridge_record_activity(source_display, channel_a or "unknown", "unknown", "failed", message.id, str(e))
        owner_id = data.get("owner_id")
        if owner_id:
            try:
                await tg_client.send_message(owner_id, f"❌ Forward error: {e}\nSource: {source_display}")
            except Exception:
                pass


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
    caption_a = format_channel_a_caption(source_display, message.text or "", media_type)

    if message.photo:
        await tg_client.send_file(channel_a_name, message.photo, caption=caption_a)
    elif message.video:
        await tg_client.send_message(channel_a_name, f"🎬 Video Post\n{caption_a}")
    elif message.document:
        await tg_client.send_message(channel_a_name, f"📎 Document Post\n{caption_a}")
    else:
        await tg_client.send_message(channel_a_name, caption_a)

    # ===== Channel B: Video Forward =====
    if message.video or message.video_note or message.gif:
        await tg_client.forward_messages(channel_b_name, message.id, entity)
    elif message.photo:
        await tg_client.forward_messages(channel_b_name, message.id, entity)

    # ===== Channel C: Next Post Auto Format =====
    caption_c = format_channel_a_caption(source_display, message.text or "", "Next Post")
    if message.photo:
        await tg_client.send_file(channel_c_name, message.photo, caption=caption_c)
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

    caption = format_caption(source_display, message.text or "", "Text")
    await tg_client.send_message(channel_a_name, caption)
    await tg_client.send_message(channel_c_name, caption)


# ========================
# Main Entry Point
# ========================
async def main():
    print("🤖 Telegram Auto Post Bot v4.9 စတင်ပါပြီ...")
    print(f"   API_ID: {API_ID}")
    print(f"   Session: {SESSION_NAME}")

    # Bot token login - no phone OTP needed
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    print(f"✅ Logged in as: {me.first_name} (@{me.username})")
    print("📌 Bot token login - Bot ကို channel တိုင်းတွင် member/admin ထည့်ရန် လို")
    if bridge_enabled():
        print(f"🔗 Shared dashboard bridge enabled: {BRIDGE_BASE_URL}")
    else:
        print("⚠️ Shared dashboard bridge disabled: set BRIDGE_BASE_URL and TELEGRAM_BOT_BRIDGE_TOKEN")

    # Register handlers - EXACT button text match
    button_texts = [
        "⚙️ Channel Setup",
        "🔄 Start Forwarding",
        "⏹️ Stop Forwarding",
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
        handle_callback,
        events.CallbackQuery
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
    print("🔄 Source Channel monitoring: 30s")
    print("━━━━━━━━━━━━━━━━━━━━")
    print("⏳ Waiting for commands...")

    asyncio.ensure_future(check_source_channels(client))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
