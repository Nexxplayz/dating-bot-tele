"""
Anonymous Dating / Random Chat Telegram Bot
--------------------------------------------
UI/flow matches the reference screenshots:
  Bottom menu: Find a partner / Search by gender / Flirt chat / My profile
  Match card:  Start chatting! / Info: premium required / Ratings: up/down /
               Common interests: ... / /link / /stop

Setup:
  1. pip install -r requirements.txt
  2. Create a bot with @BotFather on Telegram, copy the token
  3. Fill BOT_TOKEN and OWNER_ID below (or set as environment variables)
  4. python bot.py
"""

import os
import re
import sqlite3
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DB_PATH = os.environ.get("DB_PATH", "dating_bot.db")
REPORTS_TO_AUTOBAN = 3
REFERRALS_FOR_PREMIUM = 2
INTEREST_TAGS = [
    "Communication", "Friendship", "Relationship", "Dating",
    "Fun", "Flirting", "Serious Relationship", "Networking",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
NAME, GENDER, AGE, LOCATION, INTERESTS, BIO = range(6)

# Main menu button labels
BTN_FIND = "🔍 Find a partner"
BTN_GENDER = "💑 Search by gender"
BTN_FLIRT = "💘 Flirt chat"
BTN_PROFILE = "👤 My profile"

# ----------------------------------------------------------------------------
# DATABASE
# ----------------------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            gender TEXT,
            age INTEGER,
            location TEXT,
            interests TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            premium INTEGER DEFAULT 0,
            thumbs_up INTEGER DEFAULT 0,
            thumbs_down INTEGER DEFAULT 0,
            reports INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            registered_at TEXT
        )
    """)
    # migrations for DBs created before referral columns existed
    for col, coltype in (("referred_by", "INTEGER"), ("referral_count", "INTEGER DEFAULT 0")):
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass
    c.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            user_id INTEGER PRIMARY KEY,
            mode TEXT,
            joined_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_rating (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER
        )
    """)
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def is_registered(user_id):
    return get_user(user_id) is not None


def user_interests(user_row):
    return set(t for t in (user_row["interests"] or "").split(",") if t)


# ----------------------------------------------------------------------------
# MENUS
# ----------------------------------------------------------------------------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_FIND], [BTN_GENDER], [BTN_FLIRT, BTN_PROFILE]],
        resize_keyboard=True,
    )


def gender_pick_keyboard():
    keyboard = [
        [InlineKeyboardButton("👨 Male", callback_data="find_male")],
        [InlineKeyboardButton("👩 Female", callback_data="find_female")],
    ]
    return InlineKeyboardMarkup(keyboard)


def rating_keyboard(partner_id):
    keyboard = [
        [
            InlineKeyboardButton("👍", callback_data=f"rate_up_{partner_id}"),
            InlineKeyboardButton("👎", callback_data=f"rate_down_{partner_id}"),
        ],
        [InlineKeyboardButton("🚩 Report", callback_data=f"report_{partner_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def interest_keyboard(selected):
    rows = []
    for tag in INTEREST_TAGS:
        mark = "✅ " if tag in selected else ""
        rows.append([InlineKeyboardButton(f"{mark}{tag}", callback_data=f"regint_{tag}")])
    rows.append([InlineKeyboardButton("Done ✅", callback_data="regint_done")])
    return InlineKeyboardMarkup(rows)


# ----------------------------------------------------------------------------
# REGISTRATION FLOW
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_registered(user_id):
        await update.message.reply_text(
            "Welcome back! Choose an option below 👇", reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # capture referral deep-link: t.me/<bot>?start=ref_<referrer_id>
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].split("_", 1)[1])
            if referrer_id != user_id and get_user(referrer_id):
                context.user_data["referred_by"] = referrer_id
        except ValueError:
            pass

    await update.message.reply_text(
        "Welcome to Anonymous Dating Bot! 🎭\n\n"
        "Your identity stays private — partners never see your real name.\n\n"
        "Let's set up your profile. What's your name? (only used internally, never shown to others)"
    )
    return NAME


async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reg_name"] = update.message.text.strip()[:50]
    keyboard = ReplyKeyboardMarkup([["Male", "Female"]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Select your gender:", reply_markup=keyboard)
    return GENDER


async def reg_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text not in ("male", "female"):
        await update.message.reply_text("Please tap Male or Female.")
        return GENDER
    context.user_data["reg_gender"] = text
    await update.message.reply_text("How old are you? (numbers only)", reply_markup=ReplyKeyboardRemove())
    return AGE


async def reg_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or not (13 <= int(text) <= 99):
        await update.message.reply_text("Please enter a valid age (13-99).")
        return AGE
    context.user_data["reg_age"] = int(text)
    await update.message.reply_text("Which city/country are you from?")
    return LOCATION


async def reg_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reg_location"] = update.message.text.strip()[:50]
    context.user_data["reg_interests"] = set()
    await update.message.reply_text(
        "Select your interests (tap to toggle, then Done):",
        reply_markup=interest_keyboard(context.user_data["reg_interests"]),
    )
    return INTERESTS


async def reg_interest_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = context.user_data.setdefault("reg_interests", set())

    if data == "regint_done":
        await query.edit_message_text("Interests saved ✅")
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Add a short bio (shown only to premium users), or send 'skip' to leave it blank:",
        )
        return BIO

    tag = data.split("_", 1)[1]
    if tag in selected:
        selected.discard(tag)
    else:
        selected.add(tag)
    await query.edit_message_reply_markup(reply_markup=interest_keyboard(selected))
    return INTERESTS


async def reg_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    bio = "" if text.lower() == "skip" else text[:200]
    user_id = update.effective_user.id
    interests = ",".join(sorted(context.user_data.get("reg_interests", set())))

    conn = db()
    conn.execute(
        "INSERT INTO users (user_id, name, gender, age, location, interests, bio, registered_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            user_id,
            context.user_data["reg_name"],
            context.user_data["reg_gender"],
            context.user_data["reg_age"],
            context.user_data["reg_location"],
            interests,
            bio,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    referrer_id = context.user_data.get("referred_by")
    if referrer_id:
        conn = db()
        conn.execute(
            "UPDATE users SET referred_by=? WHERE user_id=?", (referrer_id, user_id)
        )
        conn.execute(
            "UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?", (referrer_id,)
        )
        conn.commit()
        referrer = conn.execute("SELECT * FROM users WHERE user_id=?", (referrer_id,)).fetchone()
        conn.close()
        if referrer and not referrer["premium"] and referrer["referral_count"] >= REFERRALS_FOR_PREMIUM:
            conn = db()
            conn.execute("UPDATE users SET premium=1 WHERE user_id=?", (referrer_id,))
            conn.commit()
            conn.close()
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"🎉 You referred {REFERRALS_FOR_PREMIUM} friends — Premium unlocked for free!",
            )
        elif referrer:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"👋 Someone joined using your referral link! ({referrer['referral_count']}/{REFERRALS_FOR_PREMIUM} for free Premium)",
            )

    await update.message.reply_text(
        "✅ Profile created! Your name and exact identity are always hidden from partners.\n\n"
        "Choose an option below to start chatting:",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled. Send /start to try again.")
    return ConversationHandler.END


# ----------------------------------------------------------------------------
# MATCHING LOGIC
# ----------------------------------------------------------------------------
def user_in_chat(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM active_chats WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def remove_from_queue(user_id):
    conn = db()
    conn.execute("DELETE FROM queue WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def find_candidate(user_id, mode, gender, interests):
    """mode: 'any' | 'male' | 'female' | 'flirt'"""
    conn = db()
    candidates = conn.execute("SELECT * FROM queue").fetchall()
    conn.close()
    for cand in candidates:
        if cand["user_id"] == user_id:
            continue
        cand_user = get_user(cand["user_id"])
        if not cand_user or cand_user["banned"]:
            continue
        cand_mode = cand["mode"]
        cand_gender = cand_user["gender"]

        if mode == "flirt" or cand_mode == "flirt":
            # Flirt chat: gender-open, but must share >=1 interest
            shared = interests & user_interests(cand_user)
            if not shared:
                continue
            return cand
        else:
            this_wants_ok = (mode == "any" or mode == cand_gender)
            cand_wants_ok = (cand_mode == "any" or cand_mode == gender)
            if this_wants_ok and cand_wants_ok:
                return cand
    return None


async def begin_match(context, user_a, user_b):
    conn = db()
    conn.execute("DELETE FROM queue WHERE user_id IN (?,?)", (user_a, user_b))
    conn.execute("INSERT OR REPLACE INTO active_chats (user_id, partner_id) VALUES (?,?)", (user_a, user_b))
    conn.execute("INSERT OR REPLACE INTO active_chats (user_id, partner_id) VALUES (?,?)", (user_b, user_a))
    conn.commit()
    conn.close()

    user_a_row = get_user(user_a)
    user_b_row = get_user(user_b)
    common = user_interests(user_a_row) & user_interests(user_b_row)
    common_text = ", ".join(sorted(common)) if common else "None"

    for uid, partner in ((user_a, user_b_row), (user_b, user_a_row)):
        card = (
            "🎭 Start chatting!\n\n"
            "Info: premium required\n"
            f"Ratings: {partner['thumbs_up']} 👍  {partner['thumbs_down']} 👎\n\n"
            f"Common interests: {common_text}\n\n"
            "/info - view full profile (Premium)\n"
            "/link - share link\n"
            "/stop - end chat"
        )
        await context.bot.send_message(chat_id=uid, text=card)


async def search_partner(context, user_id, mode):
    user = get_user(user_id)
    if not user:
        return
    if user["banned"]:
        await context.bot.send_message(chat_id=user_id, text="🚫 Your account has been suspended due to reports.")
        return
    if user_in_chat(user_id):
        await context.bot.send_message(chat_id=user_id, text="You're already in a chat. Use /stop first.")
        return

    interests = user_interests(user)
    candidate = find_candidate(user_id, mode, user["gender"], interests)
    if candidate:
        await begin_match(context, user_id, candidate["user_id"])
    else:
        conn = db()
        conn.execute(
            "INSERT OR REPLACE INTO queue (user_id, mode, joined_at) VALUES (?,?,?)",
            (user_id, mode, datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
        await context.bot.send_message(
            chat_id=user_id, text="🔎 Searching for a partner... you'll be notified when matched."
        )


async def end_chat(context, user_id, notify_partner=True):
    row = user_in_chat(user_id)
    if not row:
        return None
    partner_id = row["partner_id"]
    conn = db()
    conn.execute("DELETE FROM active_chats WHERE user_id IN (?,?)", (user_id, partner_id))
    conn.execute("INSERT OR REPLACE INTO pending_rating (user_id, partner_id) VALUES (?,?)", (user_id, partner_id))
    conn.execute("INSERT OR REPLACE INTO pending_rating (user_id, partner_id) VALUES (?,?)", (partner_id, user_id))
    conn.commit()
    conn.close()

    await context.bot.send_message(
        chat_id=user_id, text="Chat ended. Rate your partner:", reply_markup=rating_keyboard(partner_id)
    )
    if notify_partner:
        await context.bot.send_message(
            chat_id=partner_id, text="Your partner left the chat. Rate them:", reply_markup=rating_keyboard(user_id)
        )
    return partner_id


# ----------------------------------------------------------------------------
# COMMANDS
# ----------------------------------------------------------------------------
async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_in_chat(user_id):
        await end_chat(context, user_id)
    else:
        remove_from_queue(user_id)
    await search_partner(context, user_id, "any")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_in_chat(user_id):
        await end_chat(context, user_id)
    else:
        remove_from_queue(user_id)
        await update.message.reply_text("Search stopped. Main menu:", reply_markup=main_menu_keyboard())


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    interests = ", ".join(user_interests(user)) or "None set"
    text = (
        "👤 Your Profile\n\n"
        f"Gender: {user['gender'].title()}\n"
        f"Age: {user['age']}\n"
        f"Location: {user['location']}\n"
        f"Interests: {interests}\n"
        f"Premium: {'✅' if user['premium'] else '❌'}\n"
        f"Rating: 👍 {user['thumbs_up']}  👎 {user['thumbs_down']}\n"
        f"Reports against you: {user['reports']}"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    await update.message.reply_text(
        "⭐ Premium unlocks:\n"
        "• Full partner Info (name, age, bio) via /info\n"
        "• Search by gender (choose Male/Female)\n\n"
        f"Get it free by referring {REFERRALS_FOR_PREMIUM} friends — send /refer for your link.\n"
        "Or your request has been sent to the admin — they'll DM you shortly."
    )
    if OWNER_ID:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                f"💰 Premium request\nUser ID: {user_id}\nLocation: {user['location']}\n"
                f"Gender: {user['gender']}\nAge: {user['age']}\n\n"
                f"To approve: /grant {user_id}"
            ),
        )


async def refer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    remaining = max(0, REFERRALS_FOR_PREMIUM - user["referral_count"])
    status = "✅ You already have Premium!" if user["premium"] else f"{remaining} more referral(s) needed for free Premium."
    await update.message.reply_text(
        f"🎁 Invite friends to unlock Premium free!\n\n"
        f"Your link:\n{link}\n\n"
        f"Referrals so far: {user['referral_count']}/{REFERRALS_FOR_PREMIUM}\n{status}"
    )


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /grant <user_id>")
        return
    target_id = int(context.args[0])
    conn = db()
    conn.execute("UPDATE users SET premium=1 WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Premium granted to {target_id}")
    await context.bot.send_message(chat_id=target_id, text="🎉 Premium activated! Use /info in a chat to view partner bios.")


async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = user_in_chat(user_id)
    if not row:
        await update.message.reply_text("You're not in a chat right now.")
        return
    partner_id = row["partner_id"]
    username = update.effective_user.username
    if not username:
        await update.message.reply_text(
            "You don't have a Telegram username set, so there's nothing to share. "
            "Set one in Telegram Settings first."
        )
        return
    await context.bot.send_message(chat_id=partner_id, text=f"🔗 Your partner shared their profile: @{username}")
    await update.message.reply_text("Your profile link has been shared with your partner.")


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = user_in_chat(user_id)
    if not row:
        await update.message.reply_text("You're not in a chat right now.")
        return
    user = get_user(user_id)
    if not user["premium"]:
        await update.message.reply_text("🔒 Info: premium required. Use /premium to unlock.")
        return
    partner = get_user(row["partner_id"])
    bio = partner["bio"] or "This user hasn't added a bio yet."
    interests = ", ".join(user_interests(partner)) or "None set"
    await update.message.reply_text(
        f"ℹ️ Partner Info\n\n"
        f"Name: {partner['name']}\n"
        f"Gender: {partner['gender'].title()}\n"
        f"Age: {partner['age']}\n"
        f"Location: {partner['location']}\n"
        f"Bio: {bio}\n"
        f"Interests: {interests}"
    )


# ----------------------------------------------------------------------------
# MAIN MENU BUTTON HANDLER (persistent bottom keyboard)
# ----------------------------------------------------------------------------
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return

    user = get_user(user_id)

    if text == BTN_FIND:
        await search_partner(context, user_id, "any")
    elif text == BTN_GENDER:
        if not user["premium"]:
            await update.message.reply_text(
                "🔒 Choosing your partner's gender is a Premium feature.\n"
                "Use /premium to request access, or /refer to unlock it free."
            )
            return
        await update.message.reply_text("Who would you like to chat with?", reply_markup=gender_pick_keyboard())
    elif text == BTN_FLIRT:
        await search_partner(context, user_id, "flirt")
    elif text == BTN_PROFILE:
        await profile_cmd(update, context)


# ----------------------------------------------------------------------------
# INLINE BUTTON HANDLER (gender pick, rating, report)
# ----------------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_registered(user_id):
        await query.message.reply_text("Please /start first to register.")
        return

    if data in ("find_male", "find_female"):
        user = get_user(user_id)
        if not user["premium"]:
            await query.edit_message_text("🔒 This is a Premium feature. Use /premium or /refer to unlock.")
            return
        gender = "male" if data == "find_male" else "female"
        await query.edit_message_text(f"Searching for a {gender} partner...")
        await search_partner(context, user_id, gender)
    elif data.startswith("rate_up_") or data.startswith("rate_down_"):
        partner_id = int(data.rsplit("_", 1)[1])
        col = "thumbs_up" if data.startswith("rate_up_") else "thumbs_down"
        conn = db()
        conn.execute(f"UPDATE users SET {col} = {col} + 1 WHERE user_id=?", (partner_id,))
        conn.execute("DELETE FROM pending_rating WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("Thanks for rating! 🙏")
        await context.bot.send_message(chat_id=user_id, text="Main menu:", reply_markup=main_menu_keyboard())
    elif data.startswith("report_"):
        reported_id = int(data.split("_", 1)[1])
        conn = db()
        conn.execute("UPDATE users SET reports = reports + 1 WHERE user_id=?", (reported_id,))
        row = conn.execute("SELECT reports FROM users WHERE user_id=?", (reported_id,)).fetchone()
        if row and row["reports"] >= REPORTS_TO_AUTOBAN:
            conn.execute("UPDATE users SET banned=1 WHERE user_id=?", (reported_id,))
        conn.execute("DELETE FROM pending_rating WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("🚩 Report submitted. Thank you for keeping the community safe.")
        await context.bot.send_message(chat_id=user_id, text="Main menu:", reply_markup=main_menu_keyboard())


# ----------------------------------------------------------------------------
# RELAY MESSAGES BETWEEN MATCHED PARTNERS (keeps both anonymous)
# ----------------------------------------------------------------------------
async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = user_in_chat(user_id)
    if not row:
        return
    partner_id = row["partner_id"]
    try:
        await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=update.effective_chat.id,
            message_id=update.effective_message.message_id,
        )
    except Exception as e:
        logger.warning("Relay failed: %s", e)


# ----------------------------------------------------------------------------
# KEEP-ALIVE SERVER (needed on free hosts like Render/Replit that require a
# listening port and sleep the service without incoming HTTP traffic).
# Ping this URL every 5 min with UptimeRobot (free) to keep the bot awake.
# Safe to ignore if you're hosting on a real VPS (Oracle Cloud, etc.) — it
# just opens a harmless extra port.
# ----------------------------------------------------------------------------
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass  # silence default request logging


def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _PingHandler)
    server.serve_forever()


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    init_db()
    threading.Thread(target=keep_alive, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_gender)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_age)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_location)],
            INTERESTS: [CallbackQueryHandler(reg_interest_toggle, pattern="^regint_")],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_bio)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(reg_conv)
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("refer", refer_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(MessageHandler(filters.Text([BTN_FIND, BTN_GENDER, BTN_FLIRT, BTN_PROFILE]), menu_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    # Relay everything else (text, photo, sticker, voice...) while in an active chat
    app.add_handler(MessageHandler(~filters.COMMAND, relay_message))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
