# Telegram Auto Post Bot

This repository contains a Telethon-based Telegram bot for **authorized** source-to-target posting. The active entry point is `bot.py`.

## What the bot can do

- Show Burmese button menus to the three configured administrators.
- Read new posts from source channels only when the bot/account has access to those channels.
- Format source posts for Channel A, B, and C.
- Use one Gemini AI key to understand a movie image, write a Burmese caption, and create exactly five hashtags.
- Receive a movie image directly in the bot, read up to two video links from the image caption, and post to one selected target channel.
- Forward or repost media to target channels where the bot has permission to post.
- Create a movie post directly from the bot: send a poster/video, generate a Burmese AI synopsis and hashtags, add a channel name and video link, then publish to the next configured channel with buttons.
- Run in Termux, a VPS, or another persistent worker host.
- Optionally synchronize configuration with a compatible web-dashboard bridge through `BRIDGE_BASE_URL` and `TELEGRAM_BOT_BRIDGE_TOKEN`.

The bot **cannot** read a private or inaccessible channel merely because somebody sends a link. It cannot bypass Telegram permissions, remove other people's watermarks, or hide copyright/source information.

## Administrators

The current code allows these Telegram IDs to use the control buttons:

| Username | Telegram ID |
|---|---:|
| `@waiyanphyo99` | `6081621017` |
| `@waiyan7861` | `6940887457` |
| `@Bingopop1991` | `6432487408` |

## File guide

| File | Purpose |
|---|---|
| `bot.py` | **Active Telethon bot.** Commands, Burmese buttons, source monitoring, formatting, AI caption rewriting, and Telegram posting live here. |
| `bot_complete.py` | Separate experimental `python-telegram-bot` draft workflow for post drafts and external platforms. It is **not** used by `bot.py` and should not be run together with it. |
| `platform_adapters.py` | Official-API adapters for Facebook, Instagram, Threads, and X used only by `bot_complete.py`; missing credentials produce an explicit error. |
| `.env.example` | Safe configuration template. Copy it to `.env`; never commit real values. |
| `requirements.txt` | Python dependencies. It currently includes both Telethon and the separate draft bot's dependencies. |
| `render.yaml` | Render Worker configuration; it is not required for Termux or other hosts. |
| `deploy.sh` | Secret-safe start/stop/restart helper for a persistent Linux host. |
| `deploy_restart.sh` | Legacy restart helper; prefer `deploy.sh restart`. |
| `test_channel.py` | Optional diagnostic helper for checking Telegram channel access with environment variables. |
| `encrypt_keys.py` | Optional local Fernet-encryption utility; encrypted files are not a substitute for host secret variables. |
| `ran_termux.sh` | Termux helper script, if present in the checkout. |

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Fill `.env` with real values obtained from the official sources:

```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_new_bot_token
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
BRIDGE_BASE_URL=
TELEGRAM_BOT_BRIDGE_TOKEN=
SESSION_NAME=auto_post_bot_session
DATA_FILE=bot_data.json
```

`API_ID` and `API_HASH` must come from the same application at [my.telegram.org](https://my.telegram.org). `BOT_TOKEN` comes from `@BotFather`; it is separate from the API credentials.

## Telegram permissions

For every target channel, add the bot as an administrator with permission to post messages. For every source channel, the bot or user session must have legitimate access to read posts. Add only channels you own or are explicitly authorized to repost.

## Run the active bot

For a foreground test:

```bash
python3 bot.py
```

For a persistent Linux host:

```bash
bash deploy.sh
bash deploy.sh restart
bash deploy.sh stop
tail -f logs/bot.log
```

Do not run `python3 bot.py` and the deployment helper at the same time; both would use the same Telethon session and may cause `database is locked` or `wrong session ID` errors.

## Telegram workflow

1. Send `/start` from one of the three administrator accounts.
2. Use **Channel Setup** to add an authorized source and target channels in A/B/C order.
3. Choose a forwarding mode in **Settings**.
4. Press **Start Forwarding**.
5. Use **Status** to verify source access and target configuration.

### Simple Movie Post workflow

1. Send `/start`, then press **🎬 Movie Post တင်ရန်**.
2. Send the movie poster image or video to the bot.
3. Press **🤖 AI ဇာတ်ညွှန်း + #ထုတ်ရန်**. If `OPENAI_API_KEY` is configured, the bot reads the poster image and prepares a Burmese caption with hashtags.
4. Optionally press **Channel Name** and **Video Link** to add those lines to the post.
5. Press **📤 နောက် channel သို့တင်မည်**. One post goes to one channel at a time: A → B → C → A. The next post advances only after the previous upload succeeds.

The automatic source-monitoring path also uploads video and document media to Channels A and C; it no longer sends only a text notice for those media types.

## Direct movie post workflow

This is the simpler one-movie-at-a-time flow:

1. Send `/start` as an administrator.
2. Press **🎯 Direct Target** and send one channel username or link. This must be a channel you own or are explicitly authorized to manage.
3. Press **🎬 Direct Movie Post**.
4. Send one movie image. Put one or two video URLs in the image caption, separated by spaces or new lines.
5. Gemini Vision reads the image and returns a short Burmese caption plus exactly five hashtags. The bot posts the image, caption, links, and hashtags to the selected target channel.

The direct workflow posts to one target per request so that each movie goes to one channel at a time. To use another channel, press **🎯 Direct Target** again and replace the target. The bot must be an administrator with permission to post in every target channel. The bot does not bypass private-channel permissions or remove other people's watermarks.

## Security

If a token or API hash was ever committed, shown in a screenshot, or pasted into chat, revoke/rotate it before using the bot. Never commit `.env`, session files, encrypted key files, or real tokens. The repository's templates contain placeholders only.
