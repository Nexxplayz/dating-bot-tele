# Anonymous Dating Bot (Telegram)

Random/anonymous chat bot — jaisa aapne bataya: register profile, find male/female/partner,
skip/stop, anonymous profile card (name hidden), thumbs up/down rating, report + auto-block,
aur premium request jo owner ko DM chali jaati hai.

## 1. Setup

```bash
pip install -r requirements.txt
```

## 2. Create your bot

1. Telegram par [@BotFather](https://t.me/BotFather) ko message karo
2. `/newbot` bhejo, name aur username choose karo
3. Woh jo token dega (kuch aisa: `123456789:ABCdefGhIJklmNoPQRstuVwxYZ`), copy kar lo

## 3. Get your own numeric Telegram ID (for owner/premium DMs)

- [@userinfobot](https://t.me/userinfobot) ko message karo, woh aapki numeric ID de dega

## 4. Configure

Environment variables set karo (ya seedha `bot.py` ke top me BOT_TOKEN / OWNER_ID daal do):

```bash
export BOT_TOKEN="your_bot_token_here"
export OWNER_ID="your_numeric_telegram_id"
```

## 5. Run

```bash
python bot.py
```

Bot 24/7 chalane ke liye isko kisi VPS / server (Railway, Render, a cheap VPS, etc.) par host
karna hoga — jab tak script chal rahi hai, tabhi tak bot respond karega.

## 6. Deploy for free (24/7 hosting)

Your bot uses **polling**, so it just needs to keep running somewhere. Three free options:

### Option A — Render.com (easiest, no credit card)
1. Push this folder to a GitHub repo (public or private).
2. Go to [render.com](https://render.com) → New → **Web Service** → connect your repo.
3. Settings:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python bot.py`
4. Add environment variables in the Render dashboard: `BOT_TOKEN`, `OWNER_ID`.
5. Deploy. Render's free tier **sleeps after 15 min of no HTTP traffic** — the bot
   already opens a small keep-alive port for this (see `keep_alive()` in `bot.py`).
   Go to [uptimerobot.com](https://uptimerobot.com) (free) and add an HTTP monitor
   pinging your Render URL every 5 minutes so it never sleeps.

### Option B — Replit
1. Create a new Python Repl, upload these files.
2. Add `BOT_TOKEN` / `OWNER_ID` as Repl **Secrets** (not hardcoded).
3. Run it — Replit gives you a URL; same UptimeRobot trick keeps it awake on the free plan.

### Option C — Oracle Cloud Free Tier (best if you want it truly always-on, more setup)
1. Sign up for [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) — includes a
   permanently free small VM (Always Free, no time limit, no credit-card charge if you
   stay in free-tier limits).
2. SSH in, install Python 3.11+, `git clone` your repo, `pip install -r requirements.txt`.
3. Run with `nohup python3 bot.py &` or set up a `systemd` service so it restarts on reboot.
4. No keep-alive trick needed — a VM doesn't sleep.

**Recommendation:** start with **Render + UptimeRobot** today (5 minutes to set up),
move to **Oracle Free Tier** later if you want zero sleep risk and full control.

## 7. Bot name ideas

Telegram bot usernames must end in `bot`. A few options in the anonymous/secret-chat spirit
(check availability in @BotFather — first come, first served):

- `ChupkeMeetBot` — "chupke" = secretly
- `AnjaanDilBot` — "stranger's heart"
- `RaazDateBot` — "raaz" = secret
- `PardaDateBot` — "parda" = veil/curtain
- `GupChupChatBot` — "gupchup" = hush-hush
- `MaskLoveBot`
- `WhisperMatchBot`
- `NaqaabDateBot` — "naqaab" = mask
- `SecretSetuBot` — "setu" = bridge
- `AnonMilanBot` — "milan" = meeting/union

Pick one, type it into @BotFather when creating the bot (`/newbot` → it'll ask for a
username ending in "bot"), and if it's taken try a small variation.


## Features implemented

Bottom persistent menu (before matching): **⚡ Find a Partner / 👩 Match with girls / 👦 Match with boys / 👤 My Profile / ⚙️ Settings / 💎 Premium**
While in a chat, the menu switches to: **Next / Stop / Gift**

| Feature | Command |
|---|---|
| Register (name, gender, age, location, interests, bio) | `/start` |
| Find any partner | `/search` or 🔍 Find a partner |
| End chat & find new match | `/next` or ⏭ Next |
| End chat / cancel search | `/stop` or ⏹ Stop |
| Cancel current action | `/cancel` |
| Choose partner's gender **(VIP only)** | 👩 Match with girls / 👦 Match with boys, or `/filter` |
| Interest-based match | ⚙️ Settings → 💘 Flirt Chat |
| Settings menu (Flirt Chat, Media Protection, Referral, Rules) | ⚙️ Settings |
| Share your Telegram username with partner | `/link` |
| View partner's full info — name, age, bio **(VIP only)** | `/info` |
| Reconnect with your last chat partner **(VIP only)** | `/reopen` |
| Translate a replied-to message to your language | `/translate` |
| Send/receive a Truth question (shared with partner if in chat) | `/truth` |
| Send/receive a Dare challenge (shared with partner if in chat) | `/dare` |
| Send a virtual gift to your partner | 🎁 Gift |
| Show main menu again | `/menu` |
| Search filter (choose gender) | `/filter` |
| Toggle Media Protection (blur + block forwarding, all media) | `/hide` |
| Send your next photo/video as one-time view (auto-deletes in 30s) | `/once` |
| Read community terms of use | `/rules` |
| VIP pricing menu (Stars) + free-via-referral option | `/vip` (alias `/premium`) |
| Get your referral link | `/refer` |
| Owner: grant permanent VIP | `/grant <user_id>` |
| Rate partner after chat | 👍 Like / 👎 Dislike buttons |
| Report abusive partner | 🚫 Report button |
| Auto-ban after repeated reports | automatic (3 reports by default) |

## Media Protection

- **`/hide`** — toggles a persistent setting. When ON, every photo/video you send to a
  partner is delivered blurred (Telegram's native "spoiler" effect — tap to reveal) and
  protected from forwarding/saving.
- **`/once`** — a one-shot version: your very next photo/video is sent blurred, and the
  bot automatically deletes it from your partner's chat **30 seconds** after delivery.
  This uses a timer, not a true "view-once" tap detector — the Bot API doesn't expose
  when a spoiler photo is actually opened, so the 30s window is the closest reliable
  equivalent. Adjust the delay in the `_delete_after(...)` call inside `relay_message()`.

## Partner-left flow

When one side ends the chat, the **other** person sees:

```
🔴 Your partner has left the chat

🌟 Rate your partner so I can find better matches for you.
[👍 Like] [👎 Dislike]
[🚫 Report]
```

## VIP (Premium)

Two ways to unlock VIP:

1. **Buy with Telegram Stars** — `/vip` shows 4 pricing tiers (1/3/6/12 months). Tapping a
   tier sends a native Telegram Stars invoice. Stars payments go **directly to your own
   Telegram account balance** as the bot owner — no extra payment setup needed. Real-money
   value and cash-out are handled by Telegram itself (Settings → Stars in the Telegram app).
   Adjust prices/durations in the `VIP_TIERS` list in `bot.py`.
2. **Refer friends for free** — `/refer` gives a personal invite link. Every
   `REFERRALS_FOR_PREMIUM` (default 2) successful referrals grants the referrer
   `REFERRAL_PREMIUM_HOURS` (default **1 hour**) of VIP automatically. Both constants are
   at the top of `bot.py`.

VIP unlocks: Search by gender, `/info` (full partner profile), `/reopen` (reconnect with
last partner), and a free rating reset button inside `/vip`.

## What's anonymized

Real name is **never** shown to a partner by default. Only ratings and shared interests
appear on the match card. Full profile (name, age, location, bio) is only visible via
`/info`, and only to VIP users.

## Notes / next steps you may want

- **Stars payouts**: Telegram Stars revenue accrues to the bot owner's Telegram account —
  check Telegram's official docs for current withdrawal/conversion terms.
- **Scale**: SQLite is fine for a few hundred concurrent users. For bigger scale, swap to
  PostgreSQL later — the queries are simple enough to port directly.
- **Moderation**: report threshold (`REPORTS_TO_AUTOBAN`) is set to 3 in `bot.py`, change as needed.
- **Media**: photos/videos/voice notes/stickers are relayed too (via `copy_message`), not just text.
- **Translation**: `/translate` uses the free `deep-translator` package (Google Translate backend);
  no API key needed, but it depends on an external service being reachable from your host.
