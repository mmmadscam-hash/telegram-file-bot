#!/usr/bin/env python3
# Telegram file bot for Termux
# Python 3.10+ | python-telegram-bot 21.x

import logging
import os
import sqlite3
from pathlib import Path

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

# ========== CONFIG: EDIT THESE VALUES ==========
BOT_TOKEN = "PASTE_BOT_TOKEN_HERE"
ADMIN_IDS = {123456789}  # Replace with your numeric Telegram user ID
REQUIRED_CHANNELS = [
    "@your_channel_1",
    "@your_channel_2",
    "@your_channel_3",
]
# Optional: public channel links shown in the join screen.
CHANNEL_LINKS = [
    "https://t.me/your_channel_1",
    "https://t.me/your_channel_2",
    "https://t.me/your_channel_3",
]
# ===============================================

DB_PATH = Path(__file__).with_name("bot_data.sqlite3")
CATEGORIES = {
    "movies": "🎬 فیلم و سریال",
    "music": "🎵 موسیقی",
    "books": "📚 کتاب",
    "other": "📦 سایر فایل‌ها",
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("filebot")


def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("""CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            file_id TEXT NOT NULL, file_type TEXT NOT NULL, caption TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def check_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    missing = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                missing.append(channel)
        except Exception:
            # The bot must be an administrator in each channel to verify membership.
            log.exception("Could not check membership for %s", channel)
            missing.append(channel)
    return missing


def join_keyboard():
    rows = []
    for i, link in enumerate(CHANNEL_LINKS, start=1):
        rows.append([InlineKeyboardButton(f"عضویت در کانال {i}", url=link)])
    rows.append([InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


async def send_join_prompt(update_or_query, context):
    text = "برای استفاده از ربات، ابتدا در هر ۳ کانال عضو شو و سپس «بررسی عضویت» را بزن."
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=join_keyboard())
    else:
        await update_or_query.edit_message_text(text, reply_markup=join_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_name) VALUES(?,?,?)",
            (user.id, user.username or "", user.first_name or ""),
        )
    missing = await check_membership(context, user.id)
    if missing and not is_admin(user.id):
        await send_join_prompt(update, context)
        return
    await show_categories(update.message, context)


async def show_categories(message, context):
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"cat:{key}")]
        for key, label in CATEGORIES.items()
    ]
    await message.reply_text(
        "سلام! دسته‌بندی موردنظرت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "check_join":
        missing = await check_membership(context, query.from_user.id)
        if missing and not is_admin(query.from_user.id):
            await query.answer("هنوز عضویت هر ۳ کانال تأیید نشده است.", show_alert=True)
            return
        await query.edit_message_text("✅ عضویت تأیید شد. دستور /start را بزن.")
        return

    if data.startswith("cat:"):
        missing = await check_membership(context, query.from_user.id)
        if missing and not is_admin(query.from_user.id):
            await send_join_prompt(query, context)
            return
        category = data.split(":", 1)[1]
        if category not in CATEGORIES:
            return
        with db() as con:
            rows = con.execute(
                "SELECT id, caption, file_type FROM files WHERE category=? ORDER BY id DESC",
                (category,),
            ).fetchall()
        if not rows:
            await query.edit_message_text("فعلاً فایلی در این دسته ثبت نشده است. /start")
            return
        keyboard = [
            [InlineKeyboardButton((caption or f"فایل شماره {fid}")[:60],
                                  callback_data=f"file:{fid}")]
            for fid, caption, _ in rows
        ]
        await query.edit_message_text(
            f"دسته: {CATEGORIES[category]}\nفایل موردنظر را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith("file:"):
        missing = await check_membership(context, query.from_user.id)
        if missing and not is_admin(query.from_user.id):
            await send_join_prompt(query, context)
            return
        try:
            file_pk = int(data.split(":", 1)[1])
        except ValueError:
            return
        with db() as con:
            row = con.execute(
                "SELECT file_id, file_type, caption FROM files WHERE id=?",
                (file_pk,),
            ).fetchone()
        if not row:
            await query.message.reply_text("این فایل پیدا نشد.")
            return
        file_id, file_type, caption = row
        caption = caption or ""
        if file_type == "document":
            await context.bot.send_document(query.message.chat_id, file_id, caption=caption)
        elif file_type == "video":
            await context.bot.send_video(query.message.chat_id, file_id, caption=caption)
        elif file_type == "audio":
            await context.bot.send_audio(query.message.chat_id, file_id, caption=caption)
        elif file_type == "photo":
            await context.bot.send_photo(query.message.chat_id, file_id, caption=caption)
        else:
            await query.message.reply_text("نوع این فایل پشتیبانی نمی‌شود.")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = (
        "🛠 پنل مدیریت\n\n"
        "/stats — آمار کاربران و فایل‌ها\n"
        "/addfile movies — افزودن فایل به فیلم و سریال\n"
        "/addfile music — افزودن فایل به موسیقی\n"
        "/addfile books — افزودن فایل به کتاب\n"
        "/addfile other — افزودن فایل به سایر\n"
        "/cancel — لغو افزودن فایل\n"
        "/start — منوی اصلی"
    )
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    with db() as con:
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        per_category = con.execute(
            "SELECT category, COUNT(*) FROM files GROUP BY category"
        ).fetchall()
    details = "\n".join(
        f"{CATEGORIES.get(cat, cat)}: {count}" for cat, count in per_category
    ) or "هنوز فایلی ثبت نشده."
    await update.message.reply_text(
        f"📊 آمار ربات\nکاربران: {users}\nکل فایل‌ها: {total_files}\n\n{details}"
    )


async def addfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or context.args[0] not in CATEGORIES:
        await update.message.reply_text(
            "دسته را مشخص کن:\n/addfile movies\n/addfile music\n/addfile books\n/addfile other"
        )
        return
    category = context.args[0]
    context.user_data["waiting_file_category"] = category
    await update.message.reply_text(
        f"فایل را همین‌جا ارسال کن تا در دسته «{CATEGORIES[category]}» ذخیره شود.\n"
        "برای لغو: /cancel"
    )


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    category = context.user_data.get("waiting_file_category")
    if not category:
        return
    msg = update.message
    file_id = None
    file_type = None
    if msg.document:
        file_id, file_type = msg.document.file_id, "document"
    elif msg.video:
        file_id, file_type = msg.video.file_id, "video"
    elif msg.audio:
        file_id, file_type = msg.audio.file_id, "audio"
    elif msg.photo:
        file_id, file_type = msg.photo[-1].file_id, "photo"
    else:
        await msg.reply_text("لطفاً فایل، ویدیو، موسیقی یا عکس ارسال کن.")
        return

    caption = msg.caption or ""
    with db() as con:
        con.execute(
            "INSERT INTO files(category, file_id, file_type, caption) VALUES(?,?,?,?)",
            (category, file_id, file_type, caption),
        )
    context.user_data.pop("waiting_file_category", None)
    await msg.reply_text("✅ فایل با موفقیت ذخیره شد.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("waiting_file_category", None)
    await update.message.reply_text("عملیات لغو شد.")


def main():
    if BOT_TOKEN == "PASTE_BOT_TOKEN_HERE" or not BOT_TOKEN.strip():
        raise SystemExit("ابتدا BOT_TOKEN را در ابتدای فایل وارد کن.")
    if not ADMIN_IDS or 123456789 in ADMIN_IDS:
        raise SystemExit("عدد 123456789 را با شناسه عددی تلگرام خودت عوض کن.")
    if any("your_channel" in ch for ch in REQUIRED_CHANNELS):
        raise SystemExit("نام هر ۳ کانال را در تنظیمات فایل وارد کن.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("addfile", addfile))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO,
        receive_file,
    ))
    log.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
