"""
Anonymous Dating / Random Chat Telegram Bot
--------------------------------------------
Matches the "Tikible"-style reference UI:
  - Command menu: /search /next /stop /link /reopen /translate /vip /cancel /truth /dare
  - In-chat persistent keyboard: Next | Stop | Gift
  - Partner-left flow: "Your partner has left the chat" + Like/Dislike/Report
  - /vip: benefits text + 4 Stars pricing tiers + "Get it free (refer 2)" + back

Setup:
  1. pip install -r requirements.txt
  2. Create a bot with @BotFather on Telegram, copy the token
  3. Fill BOT_TOKEN and OWNER_ID below (or set as environment variables)
  4. python bot.py
"""

import os
import random
import asyncio
import sqlite3
import logging
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    LabeledPrice,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

try:
    from deep_translator import GoogleTranslator
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DB_PATH = os.environ.get("DB_PATH", "dating_bot.db")

REPORTS_TO_AUTOBAN = 3
REFERRALS_FOR_PREMIUM = 2
REFERRAL_PREMIUM_HOURS = 1  # free premium earned per successful referral pair

INTEREST_TAGS = [
    "Communication", "Friendship", "Relationship", "Dating",
    "Fun", "Flirting", "Serious Relationship", "Networking",
]

VIP_TIERS = [
    {"stars": 100, "days": 30, "label": "100 ⭐ – 1 month"},
    {"stars": 999, "days": 90, "label": "999 ⭐ / $19.99 – 3 months"},
    {"stars": 1499, "days": 180, "label": "1499 ⭐ / $29.99 – 6 months"},
    {"stars": 2499, "days": 365, "label": "2499 ⭐ / $49.99 – 12 months"},
]

TRUTH_QUESTIONS = [
    "What's something you've never told anyone?",
    "What's your biggest fear in relationships?",
    "What's the most romantic thing you've done for someone?",
    "What's a secret talent no one knows about?",
    "What's your idea of a perfect first date?",
    "What's the last lie you told?",
    "What's something you're proud of but never talk about?",
    "What's your biggest regret so far?",
    "What quality attracts you most in a person?",
    "What's a habit you wish you could break?",
]

DARE_CHALLENGES = [
    "Send a voice note saying something in a funny accent.",
    "Describe yourself using only 3 emojis.",
    "Send your partner a compliment right now.",
    "Type your next message using only questions.",
    "Share your favorite song lyric.",
    "Send a message using only capital letters for 1 sentence.",
    "Describe your day like a movie trailer.",
    "Send the last photo-worthy thing you saw (describe it in words).",
    "Give your partner a fun nickname.",
    "Tell a two-line joke.",
]

GIFT_OPTIONS = ["🌹 Rose", "🍫 Chocolate", "💐 Bouquet", "🧸 Teddy Bear", "💎 Diamond"]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
NAME, GENDER, AGE, LOCATION, INTERESTS, BIO = range(6)

# Main menu button labels
BTN_FIND = "⚡ Find a Partner"
BTN_GIRLS = "👩 Match with girls"
BTN_BOYS = "👦 Match with boys"
BTN_PROFILE = "👤 My Profile"
BTN_SETTINGS = "⚙️ Settings"
BTN_PREMIUM = "💎 Premium"

# In-chat persistent keyboard labels
BTN_NEXT = "⏭ Next"
BTN_STOP = "⏹ Stop"
BTN_GIFT = "🎁 Gift"

MENU_TEXTS = [
    BTN_FIND, BTN_GIRLS, BTN_BOYS, BTN_PROFILE, BTN_SETTINGS, BTN_PREMIUM,
    BTN_NEXT, BTN_STOP, BTN_GIFT,
]

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
            premium_expires TEXT,
            thumbs_up INTEGER DEFAULT 0,
            thumbs_down INTEGER DEFAULT 0,
            reports INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            last_partner_id INTEGER,
            media_protected INTEGER DEFAULT 0,
            registered_at TEXT
        )
    """)
    for col, coltype in (
        ("referred_by", "INTEGER"),
        ("referral_count", "INTEGER DEFAULT 0"),
        ("premium_expires", "TEXT"),
        ("last_partner_id", "INTEGER"),
        ("media_protected", "INTEGER DEFAULT 0"),
    ):
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


def is_premium(user_id):
    """True if premium is active; auto-revokes expired premium in the DB."""
    user = get_user(user_id)
    if not user or not user["premium"]:
        return False
    expires = user["premium_expires"]
    if expires:
        try:
            if datetime.utcnow() > datetime.fromisoformat(expires):
                conn = db()
                conn.execute(
                    "UPDATE users SET premium=0, premium_expires=NULL WHERE user_id=?", (user_id,)
                )
                conn.commit()
                conn.close()
                return False
        except ValueError:
            pass
    return True


def grant_premium(user_id, hours=None):
    """hours=None -> permanent (owner override). A number -> timed pass."""
    conn = db()
    if hours is None:
        conn.execute("UPDATE users SET premium=1, premium_expires=NULL WHERE user_id=?", (user_id,))
    else:
        expiry = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
        conn.execute("UPDATE users SET premium=1, premium_expires=? WHERE user_id=?", (expiry, user_id))
    conn.commit()
    conn.close()


# ----------------------------------------------------------------------------
# MENUS
# ----------------------------------------------------------------------------
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_FIND], [BTN_GIRLS, BTN_BOYS], [BTN_PROFILE, BTN_SETTINGS], [BTN_PREMIUM]],
        resize_keyboard=True,
    )


def in_chat_keyboard():
    return ReplyKeyboardMarkup(
        [[BTN_NEXT, BTN_STOP], [BTN_GIFT]],
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
            InlineKeyboardButton("👍 Like", callback_data=f"rate_up_{partner_id}"),
            InlineKeyboardButton("👎 Dislike", callback_data=f"rate_down_{partner_id}"),
        ],
        [InlineKeyboardButton("🚫 Report", callback_data=f"report_{partner_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def interest_keyboard(selected):
    rows = []
    for tag in INTEREST_TAGS:
        mark = "✅ " if tag in selected else ""
        rows.append([InlineKeyboardButton(f"{mark}{tag}", callback_data=f"regint_{tag}")])
    rows.append([InlineKeyboardButton("Done ✅", callback_data="regint_done")])
    return InlineKeyboardMarkup(rows)


def vip_keyboard():
    rows = []
    for i, tier in enumerate(VIP_TIERS):
        rows.append([InlineKeyboardButton(tier["label"], callback_data=f"buyvip_{i}")])
    rows.append([InlineKeyboardButton("🔄 Reset My Rating (VIP)", callback_data="reset_rating")])
    rows.append([InlineKeyboardButton(f"🎁 Get it for free ({REFERRALS_FOR_PREMIUM} refers)", callback_data="vip_free")])
    rows.append([InlineKeyboardButton("⬅ back", callback_data="vip_back")])
    return InlineKeyboardMarkup(rows)


def gift_keyboard():
    rows = [[InlineKeyboardButton(g, callback_data=f"sendgift_{g}")] for g in GIFT_OPTIONS]
    return InlineKeyboardMarkup(rows)


VIP_INTRO_TEXT = (
    "🔥 --VIP Users get Premium features + extra benefits:--\n\n"
    "⏱ Priority Search – VIP users are matched faster and get priority based on preferred gender.\n\n"
    "👑 VIP Badge – Every partner will see your VIP status, which increases trust and interest.\n\n"
    "🔄 Reconnect Option – Ability to reopen or reconnect with a previously closed chat.\n\n"
    "🔄 Reset Rating – You can reset your rating for free so that your partners show more interest."
)


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
        conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer_id, user_id))
        conn.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?", (referrer_id,))
        conn.commit()
        referrer = conn.execute("SELECT * FROM users WHERE user_id=?", (referrer_id,)).fetchone()
        conn.close()
        if referrer and referrer["referral_count"] >= REFERRALS_FOR_PREMIUM:
            conn = db()
            conn.execute("UPDATE users SET referral_count=0 WHERE user_id=?", (referrer_id,))
            conn.commit()
            conn.close()
            grant_premium(referrer_id, hours=REFERRAL_PREMIUM_HOURS)
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"🎉 You referred {REFERRALS_FOR_PREMIUM} friends — {REFERRAL_PREMIUM_HOURS}hr free Premium unlocked!",
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
        vip_badge = " 👑" if partner["premium"] else ""
        card = (
            f"🎭 Start chatting!{vip_badge}\n\n"
            "Info: premium required\n"
            f"Ratings: {partner['thumbs_up']} 👍  {partner['thumbs_down']} 👎\n\n"
            f"Common interests: {common_text}\n\n"
            "/info - view full profile (VIP)\n"
            "/link - share link\n"
            "/next - skip to new partner\n"
            "/stop - end chat"
        )
        await context.bot.send_message(chat_id=uid, text=card, reply_markup=in_chat_keyboard())


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
    conn.execute("UPDATE users SET last_partner_id=? WHERE user_id=?", (partner_id, user_id))
    conn.execute("UPDATE users SET last_partner_id=? WHERE user_id=?", (user_id, partner_id))
    conn.commit()
    conn.close()

    # the person who left/ended the chat
    await context.bot.send_message(
        chat_id=user_id,
        text="🌟 Rate your partner so I can find better matches for you.",
        reply_markup=rating_keyboard(partner_id),
    )
    # the partner who is passively notified
    if notify_partner:
        await context.bot.send_message(chat_id=partner_id, text="🔴 Your partner has left the chat")
        await context.bot.send_message(
            chat_id=partner_id,
            text="🌟 Rate your partner so I can find better matches for you.",
            reply_markup=rating_keyboard(user_id),
        )
    return partner_id


# ----------------------------------------------------------------------------
# COMMANDS — matching / chat control
# ----------------------------------------------------------------------------
async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return
    await search_partner(context, user_id, "any")


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return
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


async def generic_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_in_chat(user_id):
        await end_chat(context, user_id)
        await update.message.reply_text("Chat ended.")
    else:
        remove_from_queue(user_id)
        await update.message.reply_text("Cancelled. Main menu:", reply_markup=main_menu_keyboard())


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    interests = ", ".join(user_interests(user)) or "None set"
    premium_active = is_premium(user_id)
    if premium_active and user["premium_expires"]:
        premium_status = f"✅ (expires {user['premium_expires'][:16].replace('T',' ')} UTC)"
    elif premium_active:
        premium_status = "✅ (lifetime)"
    else:
        premium_status = "❌"
    text = (
        "👤 Your Profile\n\n"
        f"Gender: {user['gender'].title()}\n"
        f"Age: {user['age']}\n"
        f"Location: {user['location']}\n"
        f"Interests: {interests}\n"
        f"VIP: {premium_status}\n"
        f"Rating: 👍 {user['thumbs_up']}  👎 {user['thumbs_down']}\n"
        f"Reports against you: {user['reports']}"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


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
    if not is_premium(user_id):
        await update.message.reply_text("🔒 Info: premium required. Use /vip to unlock.")
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


async def reopen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    if not is_premium(user_id):
        await update.message.reply_text("🔒 Reconnect Option is a VIP feature. Use /vip to unlock.")
        return
    if not user["last_partner_id"]:
        await update.message.reply_text("You don't have a previous conversation to reopen yet.")
        return
    if user_in_chat(user_id):
        await update.message.reply_text("You're already in a chat. Use /stop first.")
        return
    last_partner_id = user["last_partner_id"]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"reopen_yes_{user_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"reopen_no_{user_id}"),
        ]
    ])
    try:
        await context.bot.send_message(
            chat_id=last_partner_id,
            text="🔄 Your previous chat partner wants to reconnect. Accept?",
            reply_markup=keyboard,
        )
        await update.message.reply_text("Reconnect request sent — waiting for a response.")
    except Exception:
        await update.message.reply_text("Couldn't reach your previous partner right now.")


async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to a text message with /translate to translate it.")
        return
    if not TRANSLATION_AVAILABLE:
        await update.message.reply_text("Translation isn't available right now.")
        return
    text = update.message.reply_to_message.text
    lang = (update.effective_user.language_code or "en").split("-")[0]
    try:
        translated = GoogleTranslator(source="auto", target=lang).translate(text)
        await update.message.reply_text(f"🌐 {translated}")
    except Exception as e:
        logger.warning("Translation failed: %s", e)
        await update.message.reply_text("Sorry, translation failed. Try again later.")


async def truth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    question = f"🤔 Truth: {random.choice(TRUTH_QUESTIONS)}"
    row = user_in_chat(user_id)
    await update.message.reply_text(question)
    if row:
        await context.bot.send_message(chat_id=row["partner_id"], text=question)


async def dare_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    dare = f"🎲 Dare: {random.choice(DARE_CHALLENGES)}"
    row = user_in_chat(user_id)
    await update.message.reply_text(dare)
    if row:
        await context.bot.send_message(chat_id=row["partner_id"], text=dare)


async def prompt_gender_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shared by the 💑 Search by gender button and /filter command."""
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text(
            "🔒 Choosing your partner's gender is a VIP feature.\n"
            "Use /vip to unlock (or refer friends for free)."
        )
        return
    await update.message.reply_text("Who would you like to chat with?", reply_markup=gender_pick_keyboard())


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return
    kb = in_chat_keyboard() if user_in_chat(user_id) else main_menu_keyboard()
    await update.message.reply_text("Main menu:", reply_markup=kb)


async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return
    await prompt_gender_search(update, context)


async def hide_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    new_val = 0 if user["media_protected"] else 1
    conn = db()
    conn.execute("UPDATE users SET media_protected=? WHERE user_id=?", (new_val, user_id))
    conn.commit()
    conn.close()
    status = "ON 🙈" if new_val else "OFF"
    await update.message.reply_text(
        f"Media Protection is now {status}.\n\n"
        "When ON, every photo/video you send is blurred until your partner taps to view it, "
        "and forwarding/saving is blocked.\n\n"
        "Want a single photo/video to disappear after viewing? Use /once right before sending it."
    )


async def once_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not user_in_chat(user_id):
        await update.message.reply_text("You need to be in a chat to send a one-time photo/video.")
        return
    context.user_data["once_pending"] = True
    await update.message.reply_text(
        "🔥 Your next photo or video will be sent blurred and will disappear from your "
        "partner's chat 30 seconds after it's delivered. Send it now."
    )


RULES_TEXT = (
    "📜 Terms of Use\n\n"
    "1. You must be 18+ to use this bot.\n"
    "2. No harassment, hate speech, or illegal content.\n"
    "3. Don't share others' private information.\n"
    "4. Repeated reports lead to an automatic ban.\n"
    "5. Use Media Protection (/hide) and one-time media (/once) responsibly — "
    "always respect your partner's consent.\n\n"
    "By using this bot, you agree to these terms."
)


async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES_TEXT)


def settings_keyboard(user):
    hide_status = "ON 🙈" if user["media_protected"] else "OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💘 Flirt Chat", callback_data="settings_flirt")],
        [InlineKeyboardButton(f"🙈 Media Protection: {hide_status}", callback_data="settings_toggle_hide")],
        [InlineKeyboardButton("🎁 Referral Link", callback_data="settings_refer")],
        [InlineKeyboardButton("📜 Rules", callback_data="settings_rules")],
    ])


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    await update.message.reply_text("⚙️ Settings", reply_markup=settings_keyboard(user))


async def gender_match(update: Update, context: ContextTypes.DEFAULT_TYPE, gender):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text(
            "🔒 Matching by gender is a VIP feature.\nUse /vip to unlock (or refer friends for free)."
        )
        return
    await search_partner(context, user_id, gender)


# ----------------------------------------------------------------------------
# VIP / PREMIUM
# ----------------------------------------------------------------------------
async def vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return
    await update.message.reply_text(VIP_INTRO_TEXT, reply_markup=vip_keyboard())


async def refer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text("Please /start first to register.")
        return
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    remaining = max(0, REFERRALS_FOR_PREMIUM - user["referral_count"])
    await update.message.reply_text(
        f"🎁 Invite friends to unlock {REFERRAL_PREMIUM_HOURS}hr free VIP!\n\n"
        f"Your link:\n{link}\n\n"
        f"Referrals so far: {user['referral_count']}/{REFERRALS_FOR_PREMIUM}\n"
        f"{remaining} more referral(s) needed."
    )


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /grant <user_id>")
        return
    target_id = int(context.args[0])
    grant_premium(target_id, hours=None)
    await update.message.reply_text(f"✅ Permanent VIP granted to {target_id}")
    await context.bot.send_message(chat_id=target_id, text="🎉 VIP activated! Use /vip anytime to see your perks.")


async def send_vip_invoice(context, chat_id, tier_index):
    tier = VIP_TIERS[tier_index]
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="VIP Membership",
        description=f"VIP for {tier['days']} days — priority search, VIP badge, reconnect option, free rating reset.",
        payload=f"vip_{tier['days']}",
        provider_token="",  # empty string required for Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(f"VIP {tier['days']} days", tier["stars"])],
    )


async def precheckout_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    try:
        days = int(payload.split("_", 1)[1])
    except (IndexError, ValueError):
        days = 30
    grant_premium(user_id, hours=days * 24)
    await update.message.reply_text(f"🎉 Payment received! VIP activated for {days} days. Thank you!")


# ----------------------------------------------------------------------------
# MAIN MENU / IN-CHAT BUTTON HANDLER (persistent bottom keyboard)
# ----------------------------------------------------------------------------
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if not is_registered(user_id):
        await update.message.reply_text("Please /start first to register.")
        return

    if text == BTN_FIND:
        await search_partner(context, user_id, "any")
    elif text == BTN_GIRLS:
        await gender_match(update, context, "female")
    elif text == BTN_BOYS:
        await gender_match(update, context, "male")
    elif text == BTN_PROFILE:
        await profile_cmd(update, context)
    elif text == BTN_SETTINGS:
        await settings_menu(update, context)
    elif text == BTN_PREMIUM:
        await vip_cmd(update, context)
    elif text == BTN_NEXT:
        await next_cmd(update, context)
    elif text == BTN_STOP:
        await stop_cmd(update, context)
    elif text == BTN_GIFT:
        row = user_in_chat(user_id)
        if not row:
            await update.message.reply_text("You need to be in a chat to send a gift.")
            return
        await update.message.reply_text("Choose a gift to send:", reply_markup=gift_keyboard())


# ----------------------------------------------------------------------------
# INLINE BUTTON HANDLER
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
        if not is_premium(user_id):
            await query.edit_message_text("🔒 This is a VIP feature. Use /vip to unlock.")
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
        await query.edit_message_text("🚫 Report submitted. Thank you for keeping the community safe.")
        await context.bot.send_message(chat_id=user_id, text="Main menu:", reply_markup=main_menu_keyboard())

    elif data.startswith("buyvip_"):
        tier_index = int(data.split("_", 1)[1])
        await send_vip_invoice(context, user_id, tier_index)

    elif data == "reset_rating":
        if not is_premium(user_id):
            await query.message.reply_text("🔒 VIP required to reset your rating. Use /vip to unlock.")
            return
        conn = db()
        conn.execute("UPDATE users SET thumbs_up=0, thumbs_down=0 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        await query.message.reply_text("🔄 Your rating has been reset!")

    elif data == "vip_free":
        user = get_user(user_id)
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        remaining = max(0, REFERRALS_FOR_PREMIUM - user["referral_count"])
        await query.message.reply_text(
            f"🎁 Invite friends to unlock {REFERRAL_PREMIUM_HOURS}hr free VIP!\n\n"
            f"Your link:\n{link}\n\n"
            f"Referrals so far: {user['referral_count']}/{REFERRALS_FOR_PREMIUM}\n"
            f"{remaining} more referral(s) needed."
        )

    elif data == "vip_back":
        await query.edit_message_text("👍 Okay! Type /vip anytime to see this again.")

    elif data == "settings_flirt":
        await query.edit_message_text("🔎 Searching for a Flirt Chat partner...")
        await search_partner(context, user_id, "flirt")

    elif data == "settings_toggle_hide":
        user = get_user(user_id)
        new_val = 0 if user["media_protected"] else 1
        conn = db()
        conn.execute("UPDATE users SET media_protected=? WHERE user_id=?", (new_val, user_id))
        conn.commit()
        conn.close()
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(get_user(user_id)))

    elif data == "settings_refer":
        user = get_user(user_id)
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        remaining = max(0, REFERRALS_FOR_PREMIUM - user["referral_count"])
        await query.message.reply_text(
            f"🎁 Invite friends to unlock {REFERRAL_PREMIUM_HOURS}hr free VIP!\n\n"
            f"Your link:\n{link}\n\n"
            f"Referrals so far: {user['referral_count']}/{REFERRALS_FOR_PREMIUM}\n"
            f"{remaining} more referral(s) needed."
        )

    elif data == "settings_rules":
        await query.message.reply_text(RULES_TEXT)

    elif data.startswith("sendgift_"):
        gift = data.split("_", 1)[1]
        row = user_in_chat(user_id)
        if not row:
            await query.edit_message_text("You're not in a chat anymore.")
            return
        await query.edit_message_text(f"🎁 You sent: {gift}")
        await context.bot.send_message(chat_id=row["partner_id"], text=f"🎁 Your partner sent you a gift: {gift}")

    elif data.startswith("reopen_yes_") or data.startswith("reopen_no_"):
        requester_id = int(data.rsplit("_", 1)[1])
        if data.startswith("reopen_no_"):
            await query.edit_message_text("Declined.")
            await context.bot.send_message(chat_id=requester_id, text="Your reconnect request was declined.")
            return
        if user_in_chat(user_id) or user_in_chat(requester_id):
            await query.edit_message_text("One of you is already in another chat.")
            return
        await query.edit_message_text("Reconnecting... 🔄")
        await begin_match(context, requester_id, user_id)


# ----------------------------------------------------------------------------
# RELAY MESSAGES BETWEEN MATCHED PARTNERS (keeps both anonymous)
# ----------------------------------------------------------------------------
async def _delete_after(context, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = user_in_chat(user_id)
    if not row:
        return
    partner_id = row["partner_id"]
    msg = update.effective_message
    user = get_user(user_id)

    supports_spoiler = bool(msg.photo or msg.video or msg.animation)
    once_flag = context.user_data.pop("once_pending", False) and supports_spoiler
    protect = bool(user["media_protected"]) or once_flag

    kwargs = {}
    if protect:
        kwargs["protect_content"] = True
        if supports_spoiler:
            kwargs["has_spoiler"] = True

    try:
        sent = await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            **kwargs,
        )
        if once_flag:
            await update.message.reply_text("🔥 Sent as one-time view — it'll disappear from your partner's chat in 30s.")
            asyncio.create_task(_delete_after(context, partner_id, sent.message_id, 30))
    except Exception as e:
        logger.warning("Relay failed: %s", e)


# ----------------------------------------------------------------------------
# KEEP-ALIVE SERVER (for free hosts like Render that need a listening port)
# ----------------------------------------------------------------------------
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass


def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _PingHandler)
    server.serve_forever()


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Start chat"),
        BotCommand("next", "Next chat"),
        BotCommand("stop", "End chat"),
        BotCommand("menu", "Main menu"),
        BotCommand("filter", "Search filter (choose gender)"),
        BotCommand("premium", "Premium / VIP"),
        BotCommand("hide", "Media Protection (blur + no forward)"),
        BotCommand("once", "Send next photo/video as one-time view"),
        BotCommand("rules", "Terms of use"),
        BotCommand("link", "Share your profile link"),
        BotCommand("info", "View partner's full info (VIP)"),
        BotCommand("reopen", "Reconnect with your last partner (VIP)"),
        BotCommand("translate", "Translate a replied-to message"),
        BotCommand("truth", "Receive a Truth question"),
        BotCommand("dare", "Receive a Dare challenge"),
        BotCommand("refer", "Get your referral link"),
    ])


def main():
    init_db()
    threading.Thread(target=keep_alive, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

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
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("cancel", generic_cancel_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("reopen", reopen_cmd))
    app.add_handler(CommandHandler("translate", translate_cmd))
    app.add_handler(CommandHandler("truth", truth_cmd))
    app.add_handler(CommandHandler("dare", dare_cmd))
    app.add_handler(CommandHandler("vip", vip_cmd))
    app.add_handler(CommandHandler("premium", vip_cmd))
    app.add_handler(CommandHandler("refer", refer_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("filter", filter_cmd))
    app.add_handler(CommandHandler("hide", hide_cmd))
    app.add_handler(CommandHandler("once", once_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(MessageHandler(filters.Text(MENU_TEXTS), menu_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout_cb))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_cb))
    # Relay everything else (text, photo, sticker, voice...) while in an active chat
    app.add_handler(MessageHandler(~filters.COMMAND, relay_message))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
