import logging
import sqlite3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, fmtDt
from keyboards import kbHome, kbBack


async def subscribersCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        total   = cursor.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
        active  = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE datetime(last_active) > datetime('now', '-1 day')"
        ).fetchone()[0]
        banned  = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE banned=1"
        ).fetchone()[0]
        users   = cursor.execute(
            "SELECT user_id, username, first_name, banned FROM subscribers ORDER BY subscribed_at DESC LIMIT 20"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"subscribers: {e}")
        await safeEdit(query, "Failed to load subscribers.", markup=kbHome())
        return

    buttons = []
    for uid, username, firstName, isBanned in users:
        label = username or firstName or str(uid)
        if isBanned:
            label = "[Banned]  " + label
        buttons.append([InlineKeyboardButton(label, callback_data=f"sub_info_{uid}")])
    buttons.append([InlineKeyboardButton("Main Menu", callback_data="back_main")])

    await safeEdit(
        query,
        "<b>Subscribers</b>\n\n"
        f"<code>Total   :  {total}</code>\n"
        f"<code>Active  :  {active}  (last 24h)</code>\n"
        f"<code>Banned  :  {banned}</code>\n\n"
        "Tap a name to view details.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def subInfoCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = int(query.data.replace("sub_info_", ""))
    row    = cursor.execute(
        "SELECT user_id, username, first_name, subscribed_at, last_active, banned FROM subscribers WHERE user_id=?",
        (userId,)
    ).fetchone()
    if not row:
        await safeEdit(query, "Subscriber not found.", markup=kbBack("subscribers"))
        return

    uid, username, firstName, subAt, lastActive, isBanned = row
    statusLabel = "Banned" if isBanned else "Active"

    ban_buttons = []
    if isBanned:
        ban_buttons.append(InlineKeyboardButton("Unban", callback_data=f"unban_{uid}"))
    else:
        ban_buttons.append(InlineKeyboardButton("Ban User", callback_data=f"ban_info_{uid}"))

    await safeEdit(
        query,
        "<b>Subscriber Details</b>\n\n"
        f"<code>Name        :  {firstName or 'N/A'}</code>\n"
        f"<code>Username    :  {'@' + username if username else 'N/A'}</code>\n"
        f"<code>User ID     :  {uid}</code>\n"
        f"<code>Status      :  {statusLabel}</code>\n"
        f"<code>Joined      :  {fmtDt(subAt)}</code>\n"
        f"<code>Last active :  {fmtDt(lastActive)}</code>",
        markup=InlineKeyboardMarkup([
            ban_buttons,
            [InlineKeyboardButton("Back", callback_data="subscribers")],
        ]),
        parse_mode="HTML",
    )
