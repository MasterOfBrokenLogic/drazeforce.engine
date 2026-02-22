import asyncio
import logging
from datetime import datetime

from telegram import Update  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor, ADMIN_ID
from helpers import isAdmin, isSuperAdmin, isBanned, trackUser, deleteAll, fmtDt
from keyboards import kbMain, kbUser, kbHome


# ─────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    userId = user.id

    # Check ban
    if isBanned(userId) and not isAdmin(userId):
        await update.message.reply_text(
            "<b>Access Denied</b>\n\n"
            "Your account has been restricted from using this service.\n\n"
            "If you believe this is an error, contact the administrator directly.",
            parse_mode="HTML",
        )
        return

    if not isAdmin(userId):
        trackUser(user)

    # Deep-link token
    if context.args:
        token = context.args[0]
        await _handleToken(update, context, token, user)
        return

    if isAdmin(userId):
        role = "Super Admin" if isSuperAdmin(userId) else "Admin"
        await update.message.reply_text(
            f"<b>Welcome back, {user.first_name}</b>\n"
            f"<code>Role  :  {role}</code>\n\n"
            "Select an option from the control panel below.",
            parse_mode="HTML",
            reply_markup=kbMain(),
        )
    else:
        # Check for custom welcome message
        custom = cursor.execute(
            "SELECT value FROM bot_settings WHERE key='welcome_message'"
        )
        custom = cursor.fetchone()
        welcome_text = custom[0] if custom else (
            f"<b>Hello, {user.first_name}</b>\n\n"
            "Use the options below to get started.\n"
            "If you have a private access link, open it directly to receive content."
        )
        await update.message.reply_text(
            welcome_text,
            parse_mode="HTML",
            reply_markup=kbUser(),
        )


async def _handleToken(update, context, token, user):
    userId = user.id

    # Short link redirect
    if token.startswith("s_"):
        from handlers.shortener import handleShortLink
        await handleShortLink(update, context, token[2:])
        return

    if isBanned(userId) and not isAdmin(userId):
        await update.message.reply_text(
            "<b>Access Denied</b>\n\n"
            "Your account is restricted. You cannot use access links.",
            parse_mode="HTML",
        )
        return

    try:
        link = cursor.execute(
            "SELECT folder_id, expiry, revoked, single_use, used_by FROM links WHERE token=%s", (token,)
        )
        link = cursor.fetchone()
    except Exception as e:
        logging.error(f"_handleToken DB: {e}")
        await update.message.reply_text("A database error occurred. Please try again later.")
        return

    if not link:
        await update.message.reply_text(
            "<b>Invalid Link</b>\n\n"
            "This access link does not exist or has already been removed.",
            parse_mode="HTML",
            reply_markup=kbUser() if not isAdmin(userId) else kbHome(),
        )
        return

    folderId, expiry, revoked, singleUse, usedBy = link

    if revoked:
        await update.message.reply_text(
            "<b>Link Revoked</b>\n\n"
            "This access link has been deactivated by the administrator.",
            parse_mode="HTML",
            reply_markup=kbUser() if not isAdmin(userId) else kbHome(),
        )
        return

    # Single-use: block if already used by someone else
    if singleUse and usedBy and usedBy != userId:
        await update.message.reply_text(
            "<b>Link Unavailable</b>\n\n"
            "This was a single-use link and has already been redeemed.",
            parse_mode="HTML",
            reply_markup=kbUser() if not isAdmin(userId) else kbHome(),
        )
        return

    if datetime.now() > datetime.fromisoformat(expiry):
        await update.message.reply_text(
            "<b>Link Expired</b>\n\n"
            "This access link is no longer valid.\n"
            "Please request a new one from the administrator.",
            parse_mode="HTML",
            reply_markup=kbUser() if not isAdmin(userId) else kbHome(),
        )
        return

    try:
        row = cursor.execute(
            "SELECT password FROM folders WHERE id=%s", (folderId,)
        )
        row = cursor.fetchone()
        folderPassword = row[0] if row else None
    except Exception as e:
        logging.error(f"_handleToken folder: {e}")
        await update.message.reply_text("A database error occurred.")
        return

    if folderPassword:
        context.user_data.update({
            "awaiting_password_verify": True,
            "verify_folder_id":         folderId,
            "correct_password":         folderPassword,
            "access_token":             token,
            "password_attempts":        0,
        })
        await update.message.reply_text(
            "<b>Password Required</b>\n\n"
            "This folder is protected.\n"
            "Enter the password to proceed:",
            parse_mode="HTML",
        )
        return

    await _deliverFolder(update, context, folderId, token, user)


async def _deliverFolder(update, context, folderId, token, user):
    try:
        files = cursor.execute(
            "SELECT file_id, file_type, text_content FROM files WHERE folder_id=%s", (folderId,)
        )
        files = cursor.fetchall()
        folder = cursor.execute(
            "SELECT forwardable, auto_delete_minutes, name FROM folders WHERE id=%s", (folderId,)
        )
        folder = cursor.fetchone()
        linkRow = cursor.execute(
            "SELECT id, single_use FROM links WHERE token=%s", (token,)
        )
        linkRow = cursor.fetchone()
    except Exception as e:
        logging.error(f"_deliverFolder: {e}")
        await update.message.reply_text("A database error occurred.")
        return

    if not files:
        await update.message.reply_text(
            "<b>Empty Folder</b>\n\nThis folder currently has no content.",
            parse_mode="HTML",
        )
        return

    forwardable, autoDelete, folderName = folder
    protect = forwardable == 0

    # ── Single-use: revoke IMMEDIATELY before sending anything ──
    if linkRow:
        linkId, singleUse = linkRow
        if singleUse:
            try:
                now_str = datetime.now().isoformat()
                cursor.execute(
                    "UPDATE links SET revoked=1, used_by=%s, used_at=%s WHERE token=%s AND revoked=0",
                    (user.id, now_str, token)
                )
                conn.commit()
                if cursor.rowcount == 0:
                    await update.message.reply_text(
                        "<b>Link Unavailable</b>\n\nThis single-use link has already been redeemed.",
                        parse_mode="HTML",
                    )
                    return
            except Exception as e:
                logging.error(f"single-use revoke: {e}")

    # ── Send cancel button FIRST — user can stop delivery ──
    cancelKey  = f"cancel_delivery_{user.id}"
    context.bot_data[cancelKey] = False

    cancelMsg = await update.message.reply_text(
        f"<b>Access Granted</b>\n\n"
        f"<code>Folder  :  {folderName}</code>\n"
        f"<code>Files   :  {len(files)}</code>\n\n"
        "Sending content now...",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel Delivery", callback_data=f"cancel_delivery_{user.id}")]
        ]),
    )

    sentMessages = [cancelMsg]

    if autoDelete:
        msg = await update.message.reply_text(
            f"<b>Note</b>\n\nThis content will be automatically deleted in "
            f"<code>{autoDelete}</code> minute(s). Save anything you need before then.",
            parse_mode="HTML",
        )
        sentMessages.append(msg)

    for fileId, fileType, textContent in files:
        # Check if user pressed cancel before each file
        if context.bot_data.get(cancelKey):
            try:
                await update.message.reply_text(
                    "<b>Delivery Cancelled</b>\n\nContent delivery was stopped.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            context.bot_data.pop(cancelKey, None)
            return

        try:
            if fileType == "text":
                msg = await update.message.reply_text(textContent)
            elif fileType == "video":
                msg = await update.message.reply_video(fileId, protect_content=protect, has_spoiler=True)
            elif fileType == "photo":
                msg = await update.message.reply_photo(fileId, protect_content=protect, has_spoiler=True)
            elif fileType == "document":
                msg = await update.message.reply_document(fileId, protect_content=protect)
            else:
                msg = await update.message.reply_document(fileId, protect_content=protect)
            sentMessages.append(msg)
        except Exception as e:
            logging.error(f"_deliverFolder send: {e}")

    # Remove cancel button after delivery completes
    context.bot_data.pop(cancelKey, None)
    try:
        await cancelMsg.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if autoDelete:
        asyncio.create_task(deleteAll(sentMessages, autoDelete * 60))

    try:
        now = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO logs (user_id, username, folder_id, accessed_at) VALUES (%s, %s, %s, %s)",
            (user.id, user.username, folderId, now),
        )
        cursor.execute(
            "UPDATE links SET access_count = access_count + 1 WHERE token=%s", (token,)
        )
        if linkRow:
            linkId, singleUse = linkRow
            cursor.execute(
                "INSERT INTO link_access_log (link_id, folder_id, user_id, username, accessed_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (linkId, folderId, user.id, user.username, now)
            )
            if singleUse:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text="<b>Single-Use Link Redeemed</b>\n\n"
                             f"<code>Folder    :  {folderName}</code>\n"
                             f"<code>User ID   :  {user.id}</code>\n"
                             f"<code>Username  :  {user.username or 'N/A'}</code>\n"
                             f"<code>Time      :  {fmtDt(now)}</code>\n\n"
                             "The link has been automatically revoked.",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logging.error(f"single-use notify: {e}")
        conn.commit()
    except Exception as e:
        logging.error(f"_deliverFolder log: {e}")


async def cancelDeliveryCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer("Cancelling delivery...", show_alert=False)
    userId = int(query.data.replace("cancel_delivery_", ""))

    # Only the recipient can cancel their own delivery
    if query.from_user.id != userId:
        await query.answer("This is not your delivery.", show_alert=True)
        return

    cancelKey = f"cancel_delivery_{userId}"
    context.bot_data[cancelKey] = True

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


# ─────────────────────────────────────────────
#  BACK TO MAIN (callback)
# ─────────────────────────────────────────────

async def backMainCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    user = query.from_user
    from helpers import safeEdit

    if isAdmin(user.id):
        role = "Super Admin" if isSuperAdmin(user.id) else "Admin"
        await safeEdit(
            query,
            f"<b>Welcome back, {user.first_name}</b>\n"
            f"<code>Role  :  {role}</code>\n\n"
            "Select an option from the control panel below.",
            markup=kbMain(),
            parse_mode="HTML",
        )
    else:
        custom = cursor.execute(
            "SELECT value FROM bot_settings WHERE key='welcome_message'"
        )
        custom = cursor.fetchone()
        welcome_text = custom[0] if custom else (
            f"<b>Hello, {user.first_name}</b>\n\n"
            "Use the options below to get started."
        )
        await safeEdit(
            query,
            welcome_text,
            markup=kbUser(),
            parse_mode="HTML",
        )


async def userMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    from helpers import safeEdit
    await safeEdit(
        query,
        f"<b>Hello, {query.from_user.first_name}</b>\n\n"
        "Use the options below to get started.",
        markup=kbUser(),
        parse_mode="HTML",
    )
