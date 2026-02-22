import logging
import secrets
import string
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, isAdmin
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  MENU
# ─────────────────────────────────────────────

async def shortenerMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        total  = cursor.execute(
            "SELECT COUNT(*) FROM shortened_links WHERE created_by=?", (query.from_user.id,)
        )
        total = cursor.fetchone()
        total = total[0] if total else None
        clicks = cursor.execute(
            "SELECT COALESCE(SUM(clicks),0) FROM shortened_links WHERE created_by=?",
            (query.from_user.id,)
        )
        clicks = cursor.fetchone()
        clicks = clicks[0] if clicks else None
    except Exception:
        total = clicks = 0

    await safeEdit(
        query,
        "<b>Link Shortener</b>\n\n"
        f"<code>Your links   :  {total}</code>\n"
        f"<code>Total clicks :  {clicks}</code>\n\n"
        "Choose a mode:",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Single 🔗",  callback_data="shorten_single"),
                InlineKeyboardButton("Bulk 📋",    callback_data="shorten_bulk"),
            ],
            [InlineKeyboardButton("My Links",      callback_data="shorten_mylinks")],
            [InlineKeyboardButton("Main Menu",     callback_data="back_main")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  SINGLE
# ─────────────────────────────────────────────

async def shortenerSingleCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["awaiting_shorten_single"] = True
    await safeEdit(
        query,
        "<b>Shorten  —  Single</b>\n\n"
        "Send the full URL you want to shorten:",
        markup=kbBack("shortener_menu"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  BULK
# ─────────────────────────────────────────────

async def shortenerBulkCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["awaiting_shorten_bulk"] = True
    context.user_data["bulk_urls"]             = []
    await safeEdit(
        query,
        "<b>Shorten  —  Bulk</b>\n\n"
        "Send your URLs one by one, or paste multiple lines at once.\n"
        "Type <code>DONE</code> when finished.\n\n"
        "<i>URLs must start with http:// or https://</i>",
        markup=kbBack("shortener_menu"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  MY LINKS
# ─────────────────────────────────────────────

async def shortenerMyLinksCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()

    try:
        links = cursor.execute("""
            SELECT short_code, original_url, clicks, created_at
            FROM shortened_links
            WHERE created_by=%s
            ORDER BY created_at DESC LIMIT 20
        """, (query.from_user.id,))
        links = cursor.fetchall()
    except Exception as e:
        logging.error(f"myLinks: {e}")
        await safeEdit(query, "Failed to load links.", markup=kbBack("shortener_menu"))
        return

    if not links:
        await safeEdit(
            query,
            "<b>My Links</b>\n\nNo shortened links yet.",
            markup=kbBack("shortener_menu"),
            parse_mode="HTML",
        )
        return

    botName = (await context.bot.get_me()).username
    lines   = [f"<b>My Shortened Links</b>  |  {len(links)}\n"]
    for code, url, clicks, created_at in links:
        short   = f"https://t.me/{botName}?start=s_{code}"
        preview = url[:45] + "..." if len(url) > 45 else url
        lines.append(
            f"\n🔗 <code>{short}</code>\n"
            f"<code>→  {preview}</code>\n"
            f"<code>Clicks  :  {clicks}</code>"
        )

    await safeEdit(
        query,
        "\n".join(lines),
        markup=kbBack("shortener_menu"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  HELPERS (called from messages.py)
# ─────────────────────────────────────────────

def _makeCode() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(7))


async def processSingleShorten(update, context, url: str):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "<b>Invalid URL</b>\n\nMust start with <code>http://</code> or <code>https://</code>",
            parse_mode="HTML",
        )
        return

    code = _makeCode()
    try:
        cursor.execute("""
            INSERT INTO shortened_links (short_code, original_url, created_by, created_at, clicks)
            VALUES (%s, %s, %s, %s, 0)
        """, (code, url, update.effective_user.id, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        logging.error(f"processSingleShorten: {e}")
        await update.message.reply_text("Failed to shorten link.", reply_markup=kbHome())
        return

    botName = (await context.bot.get_me()).username
    short   = f"https://t.me/{botName}?start=s_{code}"
    context.user_data.clear()
    await update.message.reply_text(
        f"<b>Link Shortened ✅</b>\n\n"
        f"<code>{short}</code>\n\n"
        f"<code>Original  :  {url[:55]}{'...' if len(url)>55 else ''}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Shorten Another", callback_data="shorten_single")],
            [InlineKeyboardButton("My Links",        callback_data="shorten_mylinks")],
            [InlineKeyboardButton("Main Menu",       callback_data="back_main")],
        ]),
    )


async def processBulkShorten(update, context):
    urls    = context.user_data.get("bulk_urls", [])
    userId  = update.effective_user.id
    botName = (await context.bot.get_me()).username
    results = []
    ok = fail = 0

    for url in urls:
        url = url.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            results.append(f"❌ <code>{url[:45]}</code>")
            fail += 1
            continue
        code = _makeCode()
        try:
            cursor.execute("""
                INSERT INTO shortened_links (short_code, original_url, created_by, created_at, clicks)
                VALUES (%s, %s, %s, %s, 0)
            """, (code, url, userId, datetime.now().isoformat()))
            conn.commit()
            short = f"https://t.me/{botName}?start=s_{code}"
            results.append(f"✅ <code>{short}</code>")
            ok += 1
        except Exception as e:
            logging.error(f"bulkShorten: {e}")
            results.append(f"❌ Failed: <code>{url[:45]}</code>")
            fail += 1

    context.user_data.clear()
    body = "\n".join(results) if results else "No URLs provided."
    await update.message.reply_text(
        f"<b>Bulk Shorten Complete</b>\n"
        f"<code>Success  :  {ok}</code>  |  <code>Failed  :  {fail}</code>\n\n"
        f"{body}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("My Links",  callback_data="shorten_mylinks")],
            [InlineKeyboardButton("Main Menu", callback_data="back_main")],
        ]),
    )


async def handleShortLink(update, context, code: str):
    """Called from start.py when token starts with s_"""
    try:
        row = cursor.execute(
            "SELECT original_url FROM shortened_links WHERE short_code=?", (code,)
        )
        row = cursor.fetchone()
    except Exception as e:
        logging.error(f"handleShortLink: {e}")
        await update.message.reply_text("Error loading link.")
        return

    if not row:
        await update.message.reply_text(
            "<b>Link Not Found</b>\n\nThis short link does not exist or has expired.",
            parse_mode="HTML",
        )
        return

    original = row[0]
    try:
        cursor.execute(
            "UPDATE shortened_links SET clicks=clicks+1 WHERE short_code=?", (code,)
        )
        conn.commit()
    except Exception:
        pass

    await update.message.reply_text(
        f"<b>Opening Link</b>\n\n<code>{original[:80]}{'...' if len(original)>80 else ''}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Open 🔗", url=original)]
        ]),
    )
