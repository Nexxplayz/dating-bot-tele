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


| Feature | Command / Button |
|---|---|
| Register (name, gender, age, location, interests, bio) | `/start` |
| Find any partner | 🔍 Find a partner |
| Find specific gender | 💑 Search by gender → 👨 Male / 👩 Female |
| Interest-based match | 💘 Flirt chat (matches users sharing ≥1 interest tag) |
| Choose partner's gender **(Premium only)** | 💑 Search by gender → 👨 Male / 👩 Female |
| View own profile + rating | 👤 My profile or `/profile` |
| Skip current partner | `/skip` |
| End chat / stop searching | `/stop` |
| Share your Telegram username with current partner | `/link` |
| View partner's full info — **name, age, bio** — **(Premium only)** | `/info` |
| Request premium (DMs owner) | `/premium` |
| Get Premium free by referring friends | `/refer` |
| Owner approves premium | `/grant <user_id>` (owner only) |
| Rate partner after chat | 👍 / 👎 buttons |
| Report abusive partner | 🚩 Report button |
| Auto-ban after repeated reports | automatic (3 reports by default) |

## Premium gating

Non-premium users can only:
- Find a partner (any gender) or use Flirt chat (interest-based)
- See ratings and common interests on the match card

Premium unlocks:
- **Search by gender** — pick Male or Female specifically
- **`/info`** — full partner profile: real name, age, location, bio

Premium can be unlocked two ways:
1. Owner manually approves via `/grant <user_id>` (triggered by `/premium`)
2. **Referral**: user sends `/refer` for their personal invite link
   (`https://t.me/<bot>?start=ref_<user_id>`). Once 2 people join through their link
   and complete registration, Premium is granted automatically — change the
   `REFERRALS_FOR_PREMIUM` constant in `bot.py` to adjust the count.

## Match card (what users see)

```
🎭 Start chatting!

Info: premium required
Ratings: 428 👍  4896 👎

Common interests: Communication, Friendship, Relationship

/link - share link
/stop - end chat
```

## What's anonymized

Real name is **never** shown to a partner. Only registered profile fields (age, location,
interests) and rating counts appear on the match card. Full "Info" (bio) requires premium
and is fetched with `/info`. A user can voluntarily reveal their Telegram username to their
current partner with `/link`.

## Notes / next steps you may want

- **Payments**: `/premium` currently just pings you (the owner) to manually `/grant` access.
  If you want auto-payments, you'd need to integrate Telegram Payments API or a UPI/Razorpay
  webhook — happy to add that next if you want it.
- **Scale**: SQLite is fine for a few hundred concurrent users. For bigger scale, swap to
  PostgreSQL later — the queries are simple enough to port directly.
- **Moderation**: report threshold (`REPORTS_TO_AUTOBAN`) is set to 3 in `bot.py`, change as needed.
- **Media**: photos/videos/voice notes/stickers are relayed too (via `copy_message`), not just text.
