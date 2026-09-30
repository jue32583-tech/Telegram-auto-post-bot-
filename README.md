# Telegram Auto Post Bot

> Source Channel က post များကို auto-repost လုပ်ပေးသော Telegram Bot
>
> **Admin မဖြစ်ဘဲ Channel Link ပေးရုံဖြင့် post ဖတ်နိုင်ပါသည်!**
> **ဖုန်းပိတ်ထားလဲ Server မှာ 24/7 run ထားနိုင်ပါသည်!**

---

## 📋 Bot ၏ လုပ်ဆောင်ချက်များ

| Button | လုပ်ဆောင်ချက် |
|---|---|
| ⚙️ Channel Setup | Source Channel နှင့် Target Channel (A, B, C) ထည့်သွင်း |
| 🔄 Start Forwarding | Auto-forward စတင် |
| ⏹️ Stop Forwarding | Auto-forward ရပ်ဆိုင်း |
| 📊 Status | Bot Status ကြည့်ရှု |
| 🔧 Settings | Forward Mode ပြောင်း, Data Reset |
| ❓ Help | အကူအညီ |

---

## 📤 Channel Format

| Channel | ပုံစံ |
|---|---|
| **Channel A** | ပုံ + ဇာတ်ညွန် + Channel Link + Video Link (text) |
| **Channel B** | Video forward |
| **Channel C** | နောက်ထပ် post (ပုံ + ဇာတ်ညွန်) |

---

## 🚀 Quick Start

### Step 1: Clone and Install

```bash
git clone https://github.com/jue32583-tech/telegram-auto-post-bot.git
cd telegram-auto-post-bot
pip3 install -r requirements.txt
```

### Step 2: Setup .env

```bash
cp .env.example .env
```

`.env` file ကို editပါ။ အောက်ပါ credentials တွေကို GitHub သို့ မတင်ပါနှင့်။
```
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
BRIDGE_BASE_URL=https://your-dashboard-domain.manus.space
TELEGRAM_BOT_BRIDGE_TOKEN=the_same_private_token_configured_for_the_dashboard
```

### Step 3: Run

**Local testing:**
```bash
python3 bot.py
```

**24/7 Server (ဖုန်းပိတ်ထားလဲ run):**
```bash
bash deploy.sh
```

**Restart:**
```bash
bash deploy_restart.sh
```

---

## 📱 Telegram မှာ အသုံးပြုပုံ

1. Bot ကို `/start` ပေးပို့ပါ
2. ⚙️ Channel Setup → Source Channel Link ထည့်ပါ
3. Channel A, B, C ထည့်ပါ (Bot ကို target channels တွင် admin ထည့်ရမည်)
4. 🔄 Start Forwarding နှိပ်ပါ
5. Web dashboard သုံးမည်ဆိုလျှင် BRIDGE_BASE_URL နှင့် TELEGRAM_BOT_BRIDGE_TOKEN ကို ထည့်ပြီး worker ကို restart လုပ်ပါ

---

## 🔐 Admin နှင့် shared dashboard bridge

Button controls ကို အောက်ပါ Telegram admins သုံးဦးသာ အသုံးပြုနိုင်ပါသည်။

| Username | Telegram ID |
|---|---:|
| @waiyanphyo99 | 6081621017 |
| @waiyan7861 | 6940887457 |
| @Bingopop1991 | 6432487408 |

Web dashboard နှင့် Telegram buttons သည် bridge token ဖြင့် shared database ကို အသုံးပြုပါသည်။ Web မှ configuration ပြောင်းလျှင် worker က နောက် monitoring cycle တွင် sync လုပ်ပြီး Telegram မှ ပြောင်းလျှင် web database ထဲ ပြန်ရေးပါသည်။ Channel test request များကို worker က အမှန်တကယ်ပို့ပြီး sent/failed ရလဒ်ကို ပြန်ပို့ပါသည်။

## ⚠️ အရေးကြီး

- **Source Channel:** Admin မလိုဟု မယူဆပါနှင့်။ Bot သို့မဟုတ် user session သည် source ကို ဖတ်နိုင်သော membership/access ရှိရပါမည်။
- **Target Channel (A, B, C):** Bot ကို Admin ထည့်ထားရမည်
- **30 စက္ကန့်တိုင်း** source channel ကို auto-check
- **ကြိုက်သလောက်** Source Channel Link ထည့်နိုင်
- **Server မှာ run ထားရင်** ဖုန်းပိတ်ထားလဲ auto-forward အလုပ်လုပ်

---

## 🖥️ Server မှာ 24/7 Run ထားဖို့

### Always-on hosting
Run the worker on Termux with PM2, or on a persistent server. The worker must remain online for queued tests and new posts to be processed. Configure `API_ID`, `API_HASH`, `BOT_TOKEN`, `BRIDGE_BASE_URL`, and `TELEGRAM_BOT_BRIDGE_TOKEN` as environment variables; never commit real values to GitHub.

### VPS (DigitalOcean, AWS)
```bash
sudo apt update && sudo apt install python3 python3-pip -y
git clone https://github.com/jue32583-tech/telegram-auto-post-bot.git
cd telegram-auto-post-bot
pip3 install -r requirements.txt
bash deploy.sh
```

---

## 🔧 Commands

| Command | Description |
|---|---|
| `python3 bot.py` | Bot run (foreground) |
| `bash deploy.sh` | Bot run (background, 24/7) |
| `bash deploy_restart.sh` | Bot restart |
| `tail -f logs/bot.log` | Log ကြည့် |
| `kill $(cat bot.pid)` | Bot stop |

---

## 📝 License

MIT License - Free to use and modify
