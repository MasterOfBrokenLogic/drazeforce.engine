import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, isSuperAdmin, fmtDt
from keyboards import kbHome, kbBack, kbMain


# ─────────────────────────────────────────────
#  SETTINGS MENU
# ─────────────────────────────────────────────

async def settingsMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        await query.answer("Super admins only.", show_alert=True)
        return

    welcome = cursor.execute(
        "SELECT value FROM bot_settings WHERE key='welcome_message'"
    )
    welcome = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM quotes")
    quote_count = cursor.fetchone()
    quote_count = quote_count[0] if quote_count else None
    qotd_time   = cursor.execute(
        "SELECT value FROM bot_settings WHERE key='qotd_time'"
    )
    qotd_time = cursor.fetchone()

    await safeEdit(
        query,
        "<b>Bot Settings</b>\n\n"
        f"<code>Welcome msg   :  {'Custom' if welcome else 'Default'}</code>\n"
        f"<code>Quotes pool   :  {quote_count}</code>\n"
        f"<code>QOTD time     :  {qotd_time[0] if qotd_time else '12:00 UTC'}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Welcome Message",   callback_data="settings_welcome")],
            [InlineKeyboardButton("Manage Quotes",     callback_data="settings_quotes")],
            [InlineKeyboardButton("Secret Folders",    callback_data="settings_secrets")],
            [InlineKeyboardButton("Link Analytics",    callback_data="settings_linkstats")],
            [InlineKeyboardButton("Main Menu",         callback_data="back_main")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  WELCOME MESSAGE
# ─────────────────────────────────────────────

async def settingsWelcomeCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = cursor.execute(
        "SELECT value FROM bot_settings WHERE key='welcome_message'"
    )
    current = cursor.fetchone()

    await safeEdit(
        query,
        "<b>Welcome Message</b>\n\n"
        f"<b>Current:</b>\n{current[0] if current else '<i>Default (not set)</i>'}\n\n"
        "Type a new welcome message to replace it.\n"
        "HTML formatting is supported.\n\n"
        "Type <code>RESET</code> to restore the default.",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Back", callback_data="settings_menu")]
        ]),
        parse_mode="HTML",
    )
    context.user_data["awaiting_welcome_msg"] = True


# ─────────────────────────────────────────────
#  QUOTES
# ─────────────────────────────────────────────

async def settingsQuotesCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        quotes = cursor.execute(
            "SELECT id, text, author, last_sent FROM quotes ORDER BY added_at DESC LIMIT 15"
        )
        quotes = cursor.fetchall()
    except Exception as e:
        logging.error(f"settingsQuotes: {e}")
        await safeEdit(query, "Failed to load quotes.", markup=kbBack("settings_menu"))
        return

    lines = [f"<b>Quote Pool</b>  |  {len(quotes)} quote(s)\n"]
    for qid, text, author, last_sent in quotes:
        short      = text[:55] + "..." if len(text) > 55 else text
        author_tag = f"  — {author}" if author else ""
        lines.append(f"\n<code>[{qid}]</code>  {short}{author_tag}")

    await safeEdit(
        query,
        "\n".join(lines) if lines else "<b>No quotes yet.</b>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Quote",    callback_data="quote_add")],
            [InlineKeyboardButton("Delete Quote", callback_data="quote_delete")],
            [InlineKeyboardButton("Send Now",     callback_data="qotd_send_now")],
            [InlineKeyboardButton("Back",         callback_data="settings_menu")],
        ]),
        parse_mode="HTML",
    )


async def quoteAddCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_quote"] = True
    await safeEdit(
        query,
        "<b>Add Quote</b>\n\nType the quote you want to add to the daily pool:",
        markup=kbBack("settings_quotes"),
        parse_mode="HTML",
    )


async def quoteDeleteCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        quotes = cursor.execute(
            "SELECT id, text FROM quotes ORDER BY added_at DESC LIMIT 15"
        )
        quotes = cursor.fetchall()
    except Exception as e:
        logging.error(f"quoteDelete: {e}")
        await safeEdit(query, "Failed to load quotes.", markup=kbBack("settings_quotes"))
        return

    if not quotes:
        await safeEdit(
            query,
            "<b>No Quotes</b>\n\nQuote pool is empty.",
            markup=kbBack("settings_quotes"),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(
            text[:40] + "..." if len(text) > 40 else text,
            callback_data=f"quote_del_{qid}"
        )]
        for qid, text in quotes
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="settings_quotes")])
    await safeEdit(
        query,
        "<b>Delete Quote</b>\n\nSelect a quote to remove:",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def quoteDelConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qid   = int(query.data.replace("quote_del_", ""))
    try:
        cursor.execute("DELETE FROM quotes WHERE id=%s", (qid,))
        conn.commit()
        await safeEdit(
            query,
            "<b>Quote Deleted</b>",
            markup=kbBack("settings_quotes"),
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"quoteDelConfirm: {e}")
        await safeEdit(query, "Failed to delete quote.", markup=kbBack("settings_quotes"))


async def qotdSendNowCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _sendQotd(context)
    await safeEdit(
        query,
        "<b>Quote Sent</b>\n\nA random quote has been sent to all subscribers.",
        markup=kbBack("settings_quotes"),
        parse_mode="HTML",
    )


async def _sendQotd(context):
    """Pick a random quote and broadcast it to all subscribers."""
    try:
        quote = cursor.execute(
            "SELECT id, text, author FROM quotes ORDER BY RANDOM() LIMIT 1"
        )
        quote = cursor.fetchone()
        if not quote:
            return
        subs = cursor.execute(
            "SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL"
        )
        subs = cursor.fetchall()
    except Exception as e:
        logging.error(f"sendQotd: {e}")
        return

    qid, text, author = quote
    author_line = f"\n\n— <i>{author}</i>" if author else ""
    msg = f"<b>Quote of the Day</b>\n\n<i>{text}</i>{author_line}"

    for (uid,) in subs:
        try:
            await context.bot.send_message(uid, msg, parse_mode="HTML")
        except Exception:
            pass

    try:
        cursor.execute(
            "UPDATE quotes SET last_sent=? WHERE id=?",
            (datetime.now().isoformat(), qid)
        )
        conn.commit()
    except Exception:
        pass


# ─────────────────────────────────────────────
#  SECRET FOLDERS
# ─────────────────────────────────────────────

async def settingsSecretsCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        secrets = cursor.execute(
            "SELECT id, name, secret_code FROM folders WHERE is_secret=1"
        )
        secrets = cursor.fetchall()
    except Exception as e:
        logging.error(f"settingsSecrets: {e}")
        await safeEdit(query, "Failed to load secret folders.", markup=kbBack("settings_menu"))
        return

    lines = [f"<b>Secret Folders</b>  |  {len(secrets)} configured\n"]
    for fid, fname, code in secrets:
        lines.append(f"\n<code>{fname}</code>\n<code>Code  :  {code or 'not set'}</code>")

    if not secrets:
        lines.append("\n<i>No secret folders configured.</i>\n\n"
                     "Mark a folder as secret from the folder settings.")

    await safeEdit(
        query,
        "\n".join(lines),
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Mark Folder as Secret", callback_data="secret_make")],
            [InlineKeyboardButton("Unmark Secret Folder",  callback_data="secret_unmark")],
            [InlineKeyboardButton("Back",                  callback_data="settings_menu")],
        ]),
        parse_mode="HTML",
    )


async def secretMakeCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        folders = cursor.execute(
            "SELECT id, name FROM folders WHERE is_secret=0 ORDER BY name"
        )
        folders = cursor.fetchall()
    except Exception as e:
        logging.error(f"secretMake: {e}")
        await safeEdit(query, "Failed to load folders.", markup=kbBack("settings_secrets"))
        return

    if not folders:
        await safeEdit(
            query,
            "<b>No Folders</b>\n\nAll folders are already marked as secret, or no folders exist.",
            markup=kbBack("settings_secrets"),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(name, callback_data=f"secret_pick_{fid}")]
        for fid, name in folders
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="settings_secrets")])

    await safeEdit(
        query,
        "<b>Mark as Secret</b>\n\nSelect a folder to make secret.\n"
        "You will then set the codeword users must type to access it.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def secretPickCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("secret_pick_", ""))
    context.user_data["secret_folder_id"]   = folderId
    context.user_data["awaiting_secret_code"] = True
    await safeEdit(
        query,
        "<b>Set Codeword</b>\n\n"
        "Type the secret codeword users must enter to unlock this folder.\n\n"
        "Keep it short and memorable.\n"
        "<i>Example: drazeforce2024</i>",
        markup=kbBack("secret_make"),
        parse_mode="HTML",
    )


async def secretUnmarkCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        secrets = cursor.execute(
            "SELECT id, name FROM folders WHERE is_secret=1"
        )
        secrets = cursor.fetchall()
    except Exception as e:
        logging.error(f"secretUnmark: {e}")
        await safeEdit(query, "Failed to load secrets.", markup=kbBack("settings_secrets"))
        return

    if not secrets:
        await safeEdit(
            query,
            "<b>No Secret Folders</b>",
            markup=kbBack("settings_secrets"),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(name, callback_data=f"secret_unmark_{fid}")]
        for fid, name in secrets
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="settings_secrets")])

    await safeEdit(
        query,
        "<b>Unmark Secret Folder</b>\n\nSelect a folder to make public again:",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def secretUnmarkConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("secret_unmark_", ""))
    try:
        cursor.execute(
            "UPDATE folders SET is_secret=0, secret_code=NULL WHERE id=?", (folderId,)
        )
        conn.commit()
        await safeEdit(
            query,
            "<b>Folder Unmarked</b>\n\nThis folder is now public.",
            markup=kbBack("settings_secrets"),
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"secretUnmarkConfirm: {e}")
        await safeEdit(query, "Failed to unmark folder.", markup=kbBack("settings_secrets"))


# ─────────────────────────────────────────────
#  LINK ANALYTICS
# ─────────────────────────────────────────────

async def settingsLinkstatsCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        folders = cursor.execute(
            "SELECT id, name FROM folders ORDER BY name"
        )
        folders = cursor.fetchall()
    except Exception as e:
        logging.error(f"settingsLinkstats: {e}")
        await safeEdit(query, "Failed to load folders.", markup=kbBack("settings_menu"))
        return

    if not folders:
        await safeEdit(
            query,
            "<b>Link Analytics</b>\n\nNo folders found.",
            markup=kbBack("settings_menu"),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(name, callback_data=f"linkstats_{fid}")]
        for fid, name in folders
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="settings_menu")])

    await safeEdit(
        query,
        "<b>Link Analytics</b>\n\nSelect a folder to view its link stats:",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def linkstatsViewCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("linkstats_", ""))

    try:
        cursor.execute("SELECT name FROM folders WHERE id=%s", (folderId,))
        folder = cursor.fetchone()
        links  = cursor.execute("""
            SELECT l.id, l.token, l.created_at, l.expiry, l.revoked, l.single_use,
                   l.access_count,
                   COUNT(DISTINCT la.user_id) as unique_users,
                   MAX(la.accessed_at) as last_access
            FROM links l
            LEFT JOIN link_access_log la ON l.id = la.link_id
            WHERE l.folder_id=%s
            GROUP BY l.id
            ORDER BY l.created_at DESC
            LIMIT 10
        """, (folderId,))
        links = cursor.fetchall()
    except Exception as e:
        logging.error(f"linkstatsView: {e}")
        await safeEdit(query, "Failed to load link stats.", markup=kbBack("settings_linkstats"))
        return

    if not links:
        await safeEdit(
            query,
            f"<b>Link Analytics</b>  |  {folder[0]}\n\nNo links have been generated for this folder.",
            markup=kbBack("settings_linkstats"),
            parse_mode="HTML",
        )
        return

    lines = [f"<b>Link Analytics</b>  |  {folder[0]}\n"]
    for lid, token, created, expiry, revoked, single_use, total, unique, last in links:
        status = "Revoked" if revoked else ("Used" if single_use and total > 0 else "Active")
        short  = token[:8] + "..."
        # unique may be 0 if link predates v3 access logging — fall back to total opens
        unique_display = unique if unique > 0 else (f"~{total} (est.)" if total > 0 else "0")
        lines.append(
            f"\n<code>{short}</code>\n"
            f"<code>Status   :  {status}</code>\n"
            f"<code>Opens    :  {total}  |  Unique: {unique_display}</code>\n"
            f"<code>Created  :  {fmtDt(created)}</code>\n"
            f"<code>Last     :  {fmtDt(last) if last else 'Never'}</code>"
        )

    await safeEdit(
        query,
        "\n".join(lines),
        markup=kbBack("settings_linkstats"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  USER — GET QUOTE (user-facing, no admin needed)
# ─────────────────────────────────────────────

async def getQuoteCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User requests a random quote on demand."""
    query = update.callback_query
    await query.answer()
    try:
        quote = cursor.execute(
            "SELECT text, author FROM quotes ORDER BY RANDOM() LIMIT 1"
        )
        quote = cursor.fetchone()
    except Exception as e:
        logging.error(f"getQuote: {e}")
        quote = None

    if not quote:
        await safeEdit(
            query,
            "<b>No Quotes Yet</b>\n\nCheck back soon.",
            markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Another", callback_data="get_quote")],
                [InlineKeyboardButton("Back",    callback_data="user_menu")],
            ]),
            parse_mode="HTML",
        )
        return

    text, author = quote
    author_line  = f"\n\n— <i>{author}</i>" if author else ""

    await safeEdit(
        query,
        f"<b>Quote</b>\n\n<i>{text}</i>{author_line}",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Another ↺", callback_data="get_quote")],
            [InlineKeyboardButton("Back",       callback_data="user_menu")],
        ]),
        parse_mode="HTML",
    )
