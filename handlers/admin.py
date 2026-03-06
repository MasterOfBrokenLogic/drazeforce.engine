import logging
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor, ADMIN_ID
from helpers import isAdmin, isSuperAdmin, safeEdit, fmtDt
from keyboards import kbAdminPanel, kbHome, kbBack


# ─────────────────────────────────────────────
#  ADMIN MENU
# ─────────────────────────────────────────────

async def adminMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        await safeEdit(
            query,
            "<b>Access Denied</b>\n\nOnly the Super Admin can access this panel.",
            markup=kbBack("back_main"),
            parse_mode="HTML",
        )
        return
    await safeEdit(
        query,
        "<b>Admin Panel</b>\n\nManage administrator accounts and user access controls.",
        markup=kbAdminPanel(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  ADD ADMIN
# ─────────────────────────────────────────────

async def addAdminCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_admin_id"] = True
    await safeEdit(
        query,
        "<b>Add Administrator</b>\n\n"
        "To add an admin, use one of these methods:\n\n"
        "<code>Method 1</code>  Forward any message from the target user\n"
        "<code>Method 2</code>  Type their numeric Telegram User ID directly\n\n"
        "The user must have started this bot at least once.",
        markup=kbBack("admin_menu"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  LIST ADMINS
# ─────────────────────────────────────────────

async def listAdminsCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admins = cursor.execute(
        "SELECT user_id, username, added_at, is_super_admin FROM admins ORDER BY is_super_admin DESC, added_at ASC"
    ).fetchall()

    buttons = []
    for userId, username, addedAt, isSuper in admins:
        tag   = "[Super]  " if isSuper else "[Admin]  "
        label = f"{tag}{username or str(userId)}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"admin_info_{userId}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="admin_menu")])

    await safeEdit(
        query,
        f"<b>Administrators</b>  |  {len(admins)} total\n\nTap a name to view details.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def adminInfoCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = int(query.data.replace("admin_info_", ""))
    row    = cursor.execute(
        "SELECT user_id, username, added_at, is_super_admin FROM admins WHERE user_id=?", (userId,)
    ).fetchone()
    if not row:
        await safeEdit(query, "Administrator not found.", markup=kbBack("list_admins"))
        return
    uid, username, addedAt, isSuper = row
    role = "Super Admin" if isSuper else "Admin"
    await safeEdit(
        query,
        "<b>Admin Details</b>\n\n"
        f"<code>Name     :  {username or 'N/A'}</code>\n"
        f"<code>Role     :  {role}</code>\n"
        f"<code>User ID  :  {uid}</code>\n"
        f"<code>Added    :  {fmtDt(addedAt)}</code>",
        markup=kbBack("list_admins"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  REMOVE ADMIN
# ─────────────────────────────────────────────

async def removeAdminCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admins = cursor.execute(
        "SELECT user_id, username FROM admins WHERE user_id != ? AND is_super_admin = 0", (ADMIN_ID,)
    ).fetchall()
    if not admins:
        await safeEdit(
            query,
            "<b>No Admins to Remove</b>\n\nThere are no regular admins to demote.",
            markup=kbBack("admin_menu"),
            parse_mode="HTML",
        )
        return
    buttons = [
        [InlineKeyboardButton(username or str(uid), callback_data=f"remove_admin_{uid}")]
        for uid, username in admins
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="admin_menu")])
    await safeEdit(
        query,
        "<b>Remove Administrator</b>\n\nSelect the admin you want to demote to regular user.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def removeAdminConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = int(query.data.replace("remove_admin_", ""))

    # Get admin info before deleting
    adminRow = cursor.execute(
        "SELECT username FROM admins WHERE user_id=? AND is_super_admin=0", (userId,)
    ).fetchone()
    if not adminRow:
        await safeEdit(query, "Admin not found or cannot be removed.", markup=kbBack("admin_menu"))
        return

    username = adminRow[0]

    # Who is doing the demoting
    demotedByRow  = cursor.execute("SELECT username FROM admins WHERE user_id=?", (query.from_user.id,)).fetchone()
    demotedByName = (demotedByRow[0] if demotedByRow else None) or f"Admin {query.from_user.id}"

    try:
        cursor.execute("DELETE FROM admins WHERE user_id=? AND is_super_admin=0", (userId,))
        conn.commit()
        displayName = f"@{username}" if username else str(userId)
        await safeEdit(
            query,
            f"<b>Admin Removed</b>\n\n"
            f"<code>{displayName}</code> has been demoted to regular user and has been notified.",
            markup=kbBack("admin_menu"),
            parse_mode="HTML",
        )
        # Notify the demoted user
        try:
            await context.bot.send_message(
                chat_id=userId,
                text=f"<b>Admin Access Removed</b>\n\n"
                     f"<code>Removed by  :  @{demotedByName}</code>\n\n"
                     "Your administrator access to this bot has been revoked.\n"
                     "You can still use the bot as a regular user.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except sqlite3.Error as e:
        logging.error(f"removeAdmin: {e}")
        await safeEdit(query, "Failed to remove administrator.", markup=kbBack("admin_menu"))


# ─────────────────────────────────────────────
#  BAN / UNBAN
# ─────────────────────────────────────────────

async def banUserCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_ban_id"] = True
    await safeEdit(
        query,
        "<b>Ban User</b>\n\n"
        "Send the numeric Telegram User ID of the account you want to restrict.\n\n"
        "Banned users cannot access any links, request OTPs, vote on polls, or contact admins.",
        markup=kbBack("admin_menu"),
        parse_mode="HTML",
    )


async def bannedListCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        bans = cursor.execute(
            "SELECT user_id, username, reason, banned_at FROM banned_users ORDER BY banned_at DESC"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"bannedList: {e}")
        await safeEdit(query, "Failed to load ban list.", markup=kbBack("admin_menu"))
        return

    if not bans:
        await safeEdit(
            query,
            "<b>Banned Users</b>\n\nNo users are currently banned.",
            markup=kbBack("admin_menu"),
            parse_mode="HTML",
        )
        return

    buttons = []
    for uid, username, reason, bannedAt in bans:
        label = f"{username or uid}  |  {fmtDt(bannedAt)}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"ban_info_{uid}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="admin_menu")])

    await safeEdit(
        query,
        f"<b>Banned Users</b>  |  {len(bans)} total\n\nTap a name to view details or unban.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def banInfoCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = int(query.data.replace("ban_info_", ""))
    row    = cursor.execute(
        "SELECT user_id, username, reason, banned_at FROM banned_users WHERE user_id=?", (userId,)
    ).fetchone()
    if not row:
        await safeEdit(query, "Ban record not found.", markup=kbBack("banned_list"))
        return
    uid, username, reason, bannedAt = row
    await safeEdit(
        query,
        "<b>Ban Details</b>\n\n"
        f"<code>User ID  :  {uid}</code>\n"
        f"<code>Username :  {username or 'N/A'}</code>\n"
        f"<code>Reason   :  {reason or 'Not specified'}</code>\n"
        f"<code>Banned   :  {fmtDt(bannedAt)}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Unban This User", callback_data=f"unban_{uid}")],
            [InlineKeyboardButton("Back",            callback_data="banned_list")],
        ]),
        parse_mode="HTML",
    )


async def unbanCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = int(query.data.replace("unban_", ""))
    try:
        # Remove from both tables
        cursor.execute("DELETE FROM banned_users WHERE user_id=?", (userId,))
        cursor.execute(
            "UPDATE subscribers SET banned=0, ban_reason=NULL WHERE user_id=?", (userId,)
        )
        conn.commit()
        await safeEdit(
            query,
            f"<b>User Unbanned</b>\n\n"
            f"<code>{userId}</code> has been removed from the ban list and can access the bot again.",
            markup=kbBack("admin_menu"),
            parse_mode="HTML",
        )
        try:
            await context.bot.send_message(
                chat_id=userId,
                text="<b>Access Restored</b>\n\n"
                     "Your access to this service has been reinstated by an administrator.\n\n"
                     "You can now use the bot normally again.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except sqlite3.Error as e:
        logging.error(f"unban: {e}")
        await safeEdit(query, "Failed to unban user.", markup=kbBack("banned_list"))