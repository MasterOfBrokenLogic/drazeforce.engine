import logging
import sqlite3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, fmtDt, isSuperAdmin
from keyboards import kbHome, kbBack


async def subscribersCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        total      = cursor.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
        active     = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE datetime(last_active) > datetime('now', '-1 day')"
        ).fetchone()[0]
        banned     = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE banned=1"
        ).fetchone()[0]
        verified   = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE phone_verified=1"
        ).fetchone()[0]
        unverified = total - verified
        users      = cursor.execute(
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

    buttons.append([
        InlineKeyboardButton(f"Verified  ({verified})",   callback_data="sub_verified_list"),
        InlineKeyboardButton(f"Unverified  ({unverified})", callback_data="sub_unverified_list"),
    ])
    buttons.append([InlineKeyboardButton("Main Menu", callback_data="back_main")])

    await safeEdit(
        query,
        "<b>Subscribers</b>\n\n"
        f"<code>Total      :  {total}</code>\n"
        f"<code>Active     :  {active}  (last 24h)</code>\n"
        f"<code>Banned     :  {banned}</code>\n"
        f"<code>Verified   :  {verified}</code>\n"
        f"<code>Unverified :  {unverified}</code>\n\n"
        "Tap a name to view details, or browse by verification status below.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  VERIFIED LIST
# ─────────────────────────────────────────────

async def subVerifiedListCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        users = cursor.execute(
            "SELECT user_id, username, first_name FROM subscribers WHERE phone_verified=1 ORDER BY subscribed_at DESC"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"subVerifiedList: {e}")
        await safeEdit(query, "Failed to load verified users.", markup=kbBack("subscribers"))
        return

    if not users:
        await safeEdit(
            query,
            "<b>Verified Users</b>\n\nNo verified users yet.",
            markup=kbBack("subscribers"),
            parse_mode="HTML",
        )
        return

    buttons = []
    for uid, username, firstName in users:
        label = username or firstName or str(uid)
        buttons.append([InlineKeyboardButton(label, callback_data=f"sub_info_{uid}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="subscribers")])

    await safeEdit(
        query,
        f"<b>Verified Users</b>  |  {len(users)}\n\nTap a name to view details.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  UNVERIFIED LIST
# ─────────────────────────────────────────────

async def subUnverifiedListCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        users = cursor.execute(
            "SELECT user_id, username, first_name FROM subscribers WHERE phone_verified=0 ORDER BY subscribed_at DESC"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"subUnverifiedList: {e}")
        await safeEdit(query, "Failed to load unverified users.", markup=kbBack("subscribers"))
        return

    if not users:
        await safeEdit(
            query,
            "<b>Unverified Users</b>\n\nAll users are verified.",
            markup=kbBack("subscribers"),
            parse_mode="HTML",
        )
        return

    buttons = []
    for uid, username, firstName in users:
        label = username or firstName or str(uid)
        buttons.append([InlineKeyboardButton(label, callback_data=f"sub_info_{uid}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="subscribers")])

    await safeEdit(
        query,
        f"<b>Unverified Users</b>  |  {len(users)}\n\nTap a name to view details.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  SUBSCRIBER DETAIL
# ─────────────────────────────────────────────

async def subInfoCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = int(query.data.replace("sub_info_", ""))
    row    = cursor.execute(
        "SELECT user_id, username, first_name, subscribed_at, last_active, banned, phone_verified, phone_number FROM subscribers WHERE user_id=?",
        (userId,)
    ).fetchone()
    if not row:
        await safeEdit(query, "Subscriber not found.", markup=kbBack("subscribers"))
        return

    uid, username, firstName, subAt, lastActive, isBanned, phoneVerified, phoneNumber = row
    statusLabel   = "Banned"  if isBanned      else "Active"
    verifiedLabel = "Yes"     if phoneVerified  else "No"

    action_buttons = []
    if isBanned:
        action_buttons.append(InlineKeyboardButton("Unban", callback_data=f"unban_{uid}"))
    else:
        action_buttons.append(InlineKeyboardButton("Ban User", callback_data=f"ban_info_{uid}"))

    # Revoke verification — only Super Admin, only if currently verified
    if isSuperAdmin(query.from_user.id) and phoneVerified:
        action_buttons.append(InlineKeyboardButton("Revoke Verification", callback_data=f"sub_revoke_{uid}"))

    await safeEdit(
        query,
        "<b>Subscriber Details</b>\n\n"
        f"<code>Name        :  {firstName or 'N/A'}</code>\n"
        f"<code>Username    :  {'@' + username if username else 'N/A'}</code>\n"
        f"<code>User ID     :  {uid}</code>\n"
        f"<code>Status      :  {statusLabel}</code>\n"
        f"<code>Verified    :  {verifiedLabel}</code>\n"
        f"<code>Phone       :  {phoneNumber or 'N/A'}</code>\n"
        f"<code>Joined      :  {fmtDt(subAt)}</code>\n"
        f"<code>Last active :  {fmtDt(lastActive)}</code>",
        markup=InlineKeyboardMarkup([
            action_buttons,
            [InlineKeyboardButton("Back", callback_data="subscribers")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  REVOKE VERIFICATION
# ─────────────────────────────────────────────

async def subRevokeVerifyCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()

    if not isSuperAdmin(query.from_user.id):
        await query.answer("Only the Super Admin can revoke verification.", show_alert=True)
        return

    userId = int(query.data.replace("sub_revoke_", ""))
    try:
        row = cursor.execute(
            "SELECT first_name, username FROM subscribers WHERE user_id=?", (userId,)
        ).fetchone()
        firstName = row[0] if row else "User"
        username  = row[1] if row else None

        cursor.execute(
            "UPDATE subscribers SET phone_verified=0, phone_number=NULL WHERE user_id=?",
            (userId,)
        )
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"subRevokeVerify: {e}")
        await safeEdit(query, "Failed to revoke verification.", markup=kbBack("subscribers"))
        return

    # Notify the user
    try:
        await context.bot.send_message(
            chat_id=userId,
            text=(
                "<b>Verification Revoked</b>\n\n"
                "Your phone verification has been removed by the admin.\n"
                "Please verify your number again to regain full access."
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"subRevokeVerify notify: {e}")

    name = f"@{username}" if username else firstName
    await safeEdit(
        query,
        f"<b>Verification Revoked</b>\n\n"
        f"<code>{name}</code> has been unverified.\n"
        "They will need to re-verify before accessing restricted features.",
        markup=kbBack("subscribers"),
        parse_mode="HTML",
    )