import logging
import uuid
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor, ADMIN_ID
from helpers import safeEdit, isSuperAdmin, isAdmin, fmtDt
from keyboards import kbHome, kbBack, kbUser


# ─────────────────────────────────────────────
#  ADMIN INBOX
# ─────────────────────────────────────────────

async def userMessagesCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query         = update.callback_query
    await query.answer()
    viewerId      = query.from_user.id
    viewerIsSuper = isSuperAdmin(viewerId)

    try:
        if viewerIsSuper:
            cursor.execute("SELECT COUNT(*) FROM user_messages")
            total = cursor.fetchone()
            total = total[0] if total else None
            cursor.execute("SELECT COUNT(*) FROM user_messages WHERE status='unread'")
            unread = cursor.fetchone()
            unread = unread[0] if unread else None
            msgs   = cursor.execute("""
                SELECT message_id, user_id, username, first_name, sent_at, status,
                       recipient_admin_id, recipient_is_super
                FROM user_messages ORDER BY sent_at DESC LIMIT 20
            """)
            msgs = cursor.fetchall()
        else:
            cursor.execute("SELECT COUNT(*) FROM user_messages WHERE recipient_admin_id=%s", (viewerId,))
            total = cursor.fetchone()
            total = total[0] if total else None
            cursor.execute("SELECT COUNT(*) FROM user_messages WHERE recipient_admin_id=%s AND status='unread'", (viewerId,))
            unread = cursor.fetchone()
            unread = unread[0] if unread else None
            msgs   = cursor.execute("""
                SELECT message_id, user_id, username, first_name, sent_at, status,
                       recipient_admin_id, recipient_is_super
                FROM user_messages WHERE recipient_admin_id=%s
                ORDER BY sent_at DESC LIMIT 20
            """, (viewerId,))
            msgs = cursor.fetchall()
    except Exception as e:
        logging.error(f"userMessages: {e}")
        await safeEdit(query, "Failed to load inbox.", markup=kbHome())
        return

    if total == 0:
        await safeEdit(query, "<b>Inbox</b>\n\nNo messages yet.", markup=kbHome(), parse_mode="HTML")
        return

    buttons = []
    for msgId, userId, username, firstName, sentAt, status, recipId, recipIsSuper in msgs:
        label  = username or firstName or str(userId)
        prefix = "[New]  " if status == "unread" else ""
        if viewerIsSuper:
            if recipId:
                cursor.execute("SELECT username FROM admins WHERE user_id=%s", (recipId,))
                recipRow = cursor.fetchone()
            else:
                recipRow = None
            recipName = (recipRow[0] if recipRow else None) or (f"Admin {recipId}" if recipId else "Super Admin")
            label    += f"  →  {recipName}"
        buttons.append([InlineKeyboardButton(f"{prefix}{label}  |  {fmtDt(sentAt)}", callback_data=f"viewmsg_{msgId}")])

    buttons.append([InlineKeyboardButton("Mark All Read", callback_data="mark_all_read"), InlineKeyboardButton("Clear All", callback_data="clear_all_messages")])
    buttons.append([InlineKeyboardButton("Main Menu", callback_data="back_main")])

    await safeEdit(query, f"<b>Inbox</b>\n\n<code>Total   :  {total}</code>\n<code>Unread  :  {unread}</code>",
                   markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


# ─────────────────────────────────────────────
#  VIEW MESSAGE
# ─────────────────────────────────────────────

async def viewMessageCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    msgId    = query.data.replace("viewmsg_", "")
    viewerId = query.from_user.id

    try:
        msg = cursor.execute(
            "SELECT user_id, username, first_name, sent_at, recipient_admin_id, recipient_is_super FROM user_messages WHERE message_id=?",
            (msgId,)
        )
        msg = cursor.fetchone()
        if not msg:
            await safeEdit(query, "Message not found.", markup=kbBack("user_messages"))
            return

        userId, username, firstName, sentAt, recipId, recipIsSuper = msg

        if not isSuperAdmin(viewerId):
            if recipIsSuper or recipId != viewerId:
                await safeEdit(query, "<b>Access Denied</b>", markup=kbBack("user_messages"), parse_mode="HTML")
                return

        cursor.execute("SELECT file_id, file_type, text_content FROM user_message_files WHERE message_id=%s", (msgId,))
        files = cursor.fetchall()

        cursor.execute("SELECT status FROM user_messages WHERE message_id=%s", (msgId,))
        was_unread = cursor.fetchone()
        is_first_read = was_unread and was_unread[0] == "unread"

        cursor.execute("UPDATE user_messages SET status='read', viewed_at=%s WHERE message_id=%s", (datetime.now().isoformat(), msgId))
        conn.commit()

        if is_first_read:
            cursor.execute("SELECT username FROM admins WHERE user_id=%s", (viewerId,))
            adminRow = cursor.fetchone()
            adminName = (adminRow[0] if adminRow else None) or f"Admin {viewerId}"
            try:
                await context.bot.send_message(chat_id=userId, text=f"<b>Message Seen</b>\n\n<code>{adminName}</code> has read your message.", parse_mode="HTML")
            except Exception as e:
                logging.error(f"read receipt: {e}")

    except Exception as e:
        logging.error(f"viewMessage: {e}")
        await safeEdit(query, "Failed to load message.", markup=kbBack("user_messages"))
        return

    sender   = username or firstName or str(userId)
    if recipId:
        cursor.execute("SELECT username FROM admins WHERE user_id=%s", (recipId,))
        recipRow = cursor.fetchone()
    else:
        recipRow = None
    recipName = (recipRow[0] if recipRow else None) or (f"Admin {recipId}" if recipId else "Unknown")
    if recipIsSuper:
        recipName += "  [Super Admin]"

    await safeEdit(query,
        f"<b>Message from {sender}</b>\n\n"
        f"<code>User ID     :  {userId}</code>\n"
        f"<code>Sent to     :  {recipName}</code>\n"
        f"<code>Received    :  {fmtDt(sentAt)}</code>\n"
        f"<code>Attachments :  {len(files)}</code>",
        markup=None, parse_mode="HTML")

    sentMsgIds = [query.message.message_id]
    for fileId, fileType, textContent in files:
        try:
            if fileType == "text":   m = await query.message.reply_text(textContent)
            elif fileType == "video": m = await query.message.reply_video(fileId)
            elif fileType == "photo": m = await query.message.reply_photo(fileId)
            else:                     m = await query.message.reply_document(fileId)
            sentMsgIds.append(m.message_id)
        except Exception as e:
            logging.error(f"viewMessage send: {e}")

    context.bot_data[f"inbox_msgs_{msgId}"] = sentMsgIds

    prompt = await query.message.reply_text(
        "<b>Message displayed above.</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Reply",         callback_data=f"replyto_{msgId}_{userId}"),
             InlineKeyboardButton("Delete",        callback_data=f"delmsg_{msgId}")],
            [InlineKeyboardButton("Keep",          callback_data=f"keepmsg_{msgId}"),
             InlineKeyboardButton("Back to Inbox", callback_data="user_messages")],
        ]),
    )
    context.bot_data[f"inbox_msgs_{msgId}"].append(prompt.message_id)


# ─────────────────────────────────────────────
#  ADMIN → REPLY TO USER
# ─────────────────────────────────────────────

async def replyToUserCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    # callback_data = replyto_{msgId}_{userId}  (userId is always last segment)
    parts  = query.data.split("_")
    userId = int(parts[-1])
    msgId  = "_".join(parts[1:-1])

    context.user_data["awaiting_admin_reply"]  = True
    context.user_data["reply_to_msg_id"]       = msgId
    context.user_data["reply_to_user_id"]      = userId
    context.user_data["reply_files"]           = []

    await safeEdit(query,
        "<b>Reply to User</b>\n\n"
        "Send your reply — text, photos, videos, or documents.\n\n"
        "Type <code>SEND</code> when done, or <code>CANCEL</code> to abort.",
        markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=f"viewmsg_{msgId}")]]),
        parse_mode="HTML")


# ─────────────────────────────────────────────
#  USER INBOX (admin replies)
# ─────────────────────────────────────────────

async def userInboxCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    userId = query.from_user.id

    try:
        replies = cursor.execute("""
            SELECT reply_id, from_admin_id, content, sent_at, status
            FROM message_replies WHERE to_user_id=%s
            ORDER BY sent_at DESC LIMIT 20
        """, (userId,))
        replies = cursor.fetchall()
    except Exception as e:
        logging.error(f"userInbox: {e}")
        await safeEdit(query, "Failed to load inbox.", markup=kbBack("user_menu"))
        return

    if not replies:
        await safeEdit(query, "<b>Your Inbox</b>\n\nNo replies from admin yet.",
                       markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="user_menu")]]),
                       parse_mode="HTML")
        return

    unread  = sum(1 for r in replies if r[4] == "unread")
    buttons = []
    for replyId, fromAdminId, content, sentAt, status in replies:
        cursor.execute("SELECT username FROM admins WHERE user_id=%s", (fromAdminId,))
        adminRow = cursor.fetchone()
        adminName = (adminRow[0] if adminRow else None) or f"Admin {fromAdminId}"
        prefix    = "[New]  " if status == "unread" else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{adminName}  |  {fmtDt(sentAt)}", callback_data=f"viewreply_{replyId}")])

    buttons.append([InlineKeyboardButton("Back", callback_data="user_menu")])

    await safeEdit(query,
        f"<b>Your Inbox</b>\n\n<code>Replies  :  {len(replies)}</code>\n<code>Unread   :  {unread}</code>",
        markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


async def viewReplyCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    replyId = query.data.replace("viewreply_", "")
    userId  = query.from_user.id

    try:
        reply = cursor.execute(
            "SELECT reply_id, from_admin_id, message_id, content, sent_at FROM message_replies WHERE reply_id=? AND to_user_id=?",
            (replyId, userId)
        )
        reply = cursor.fetchone()
    except Exception as e:
        logging.error(f"viewReply: {e}")
        await safeEdit(query, "Failed to load reply.", markup=kbBack("user_inbox"))
        return

    if not reply:
        await safeEdit(query, "Reply not found.", markup=kbBack("user_inbox"))
        return

    replyId, fromAdminId, origMsgId, content, sentAt = reply
    cursor.execute("UPDATE message_replies SET status='read' WHERE reply_id=%s", (replyId,))
    conn.commit()

    cursor.execute("SELECT username FROM admins WHERE user_id=%s", (fromAdminId,))
    adminRow = cursor.fetchone()
    adminName = (adminRow[0] if adminRow else None) or f"Admin {fromAdminId}"

    await safeEdit(query,
        f"<b>Reply from {adminName}</b>\n\n<code>Received  :  {fmtDt(sentAt)}</code>",
        markup=None, parse_mode="HTML")

    if content:
        await query.message.reply_text(content)

    await query.message.reply_text(
        "<b>What would you like to do?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Reply Back", callback_data=f"userreply_{origMsgId}_{fromAdminId}"),
             InlineKeyboardButton("Delete",     callback_data=f"delreply_{replyId}")],
            [InlineKeyboardButton("Inbox",      callback_data="user_inbox")],
        ]),
    )


async def deleteReplyCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    replyId = query.data.replace("delreply_", "")
    try:
        cursor.execute("DELETE FROM message_replies WHERE reply_id=%s", (replyId,))
        conn.commit()
    except Exception as e:
        logging.error(f"deleteReply: {e}")
    await safeEdit(query, "<b>Deleted</b>\n\nReply removed.",
                   markup=InlineKeyboardMarkup([[InlineKeyboardButton("Inbox", callback_data="user_inbox")]]),
                   parse_mode="HTML")


async def userReplyBackCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    parts   = query.data.split("_")   # userreply_{origMsgId}_{adminId}
    adminId = int(parts[-1])

    context.user_data["contact_admin_mode"]         = True
    context.user_data["contact_files"]              = []
    context.user_data["contact_recipient_id"]       = adminId
    context.user_data["contact_recipient_is_super"] = 1 if isSuperAdmin(adminId) else 0
    context.user_data["contact_recipient_label"]    = f"Admin {adminId}"

    await safeEdit(query,
        "<b>Reply to Admin</b>\n\n"
        "Send your reply — text, photos, or videos.\n\nType <code>SEND</code> when ready.",
        markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="user_inbox")]]),
        parse_mode="HTML")


# ─────────────────────────────────────────────
#  DELETE / KEEP / MARK READ / CLEAR
# ─────────────────────────────────────────────

async def deleteMsgFromChatCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    msgId   = query.data.replace("delmsg_", "")
    chatId  = query.message.chat_id
    tracked = context.bot_data.pop(f"inbox_msgs_{msgId}", [])
    for mid in tracked:
        try:
            await context.bot.delete_message(chat_id=chatId, message_id=mid)
        except Exception:
            pass
    try:
        cursor.execute("DELETE FROM user_message_files WHERE message_id=%s", (msgId,))
        cursor.execute("DELETE FROM user_messages        WHERE message_id=%s", (msgId,))
        conn.commit()
    except Exception as e:
        logging.error(f"deleteMsgFromChat DB: {e}")
    await context.bot.send_message(chat_id=chatId, text="<b>Message Deleted</b>", parse_mode="HTML", reply_markup=kbBack("user_messages"))


async def keepMsgCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.bot_data.pop(f"inbox_msgs_{query.data.replace('keepmsg_', '')}", None)
    await safeEdit(query, "<b>Message Kept</b>\n\nStill in your inbox.", markup=kbBack("user_messages"), parse_mode="HTML")


async def markAllReadCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    viewerId = query.from_user.id
    if isSuperAdmin(viewerId):
        cursor.execute("UPDATE user_messages SET status='read' WHERE status='unread'")
    else:
        cursor.execute("UPDATE user_messages SET status='read' WHERE status='unread' AND recipient_admin_id=%s", (viewerId,))
    conn.commit()
    await safeEdit(query, "<b>All Read</b>\n\nAll messages marked as read.", markup=kbBack("user_messages"), parse_mode="HTML")


async def clearAllMessagesCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safeEdit(query,
        "<b>Clear Inbox</b>\n\nPermanently delete all messages. Are you sure?",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirm", callback_data="confirm_clear_messages"),
             InlineKeyboardButton("Cancel",  callback_data="user_messages")]
        ]), parse_mode="HTML")


async def confirmClearMessagesCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    viewerId = query.from_user.id
    try:
        if isSuperAdmin(viewerId):
            cursor.execute("DELETE FROM user_message_files")
            cursor.execute("DELETE FROM user_messages")
        else:
            cursor.execute("SELECT message_id FROM user_messages WHERE recipient_admin_id=%s", (viewerId,))
            ownedIds = [r[0] for r in cursor.fetchall()]
            if ownedIds:
                ph = ",".join(["%s"] * len(ownedIds))
                cursor.execute(f"DELETE FROM user_message_files WHERE message_id IN ({ph})", ownedIds)
                cursor.execute(f"DELETE FROM user_messages        WHERE message_id IN ({ph})", ownedIds)
        conn.commit()
        await safeEdit(query, "<b>Inbox Cleared</b>", markup=kbHome(), parse_mode="HTML")
    except Exception as e:
        logging.error(f"clearMessages: {e}")
        await safeEdit(query, "Failed to clear inbox.", markup=kbHome())


# ─────────────────────────────────────────────
#  CONTACT ADMIN
# ─────────────────────────────────────────────

async def contactAdminCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        cursor.execute("SELECT user_id, username, is_super_admin FROM admins ORDER BY is_super_admin DESC, added_at ASC")
        admins = cursor.fetchall()
    except Exception as e:
        logging.error(f"contactAdmin: {e}")
        await safeEdit(query, "Could not load admin list.", markup=kbBack("user_menu"))
        return

    if not admins:
        await safeEdit(query, "<b>Contact Admin</b>\n\nNo administrators available.", markup=kbBack("user_menu"), parse_mode="HTML")
        return

    buttons = []
    for adminId, username, isSuper in admins:
        label = ("[Super]  " if isSuper else "") + (username or f"Admin {adminId}")
        buttons.append([InlineKeyboardButton(label, callback_data=f"contact_select_{adminId}")])
    buttons.append([InlineKeyboardButton("Cancel", callback_data="user_menu")])

    await safeEdit(query, "<b>Contact Admin</b>\n\nSelect who you want to message.",
                   markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")


async def selectAdminToContactCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    recipientId = int(query.data.replace("contact_select_", ""))

    try:
        cursor.execute("SELECT username, is_super_admin FROM admins WHERE user_id=%s", (recipientId,))
        row = cursor.fetchone()
    except Exception as e:
        logging.error(f"selectAdminToContact: {e}")
        await safeEdit(query, "Could not find that admin.", markup=kbBack("contact_admin"))
        return

    if not row:
        await safeEdit(query, "Admin not found.", markup=kbBack("contact_admin"))
        return

    username, isSuper  = row
    recipientLabel     = ("[Super]  " if isSuper else "") + (username or f"Admin {recipientId}")

    context.user_data["contact_admin_mode"]         = True
    context.user_data["contact_files"]              = []
    context.user_data["contact_recipient_id"]       = recipientId
    context.user_data["contact_recipient_is_super"] = int(isSuper)
    context.user_data["contact_recipient_label"]    = recipientLabel

    await safeEdit(query,
        f"<b>Message to  :  {recipientLabel}</b>\n\n"
        "Send text, photos, videos, or documents.\n\nType <code>SEND</code> when ready.",
        markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="user_menu")]]),
        parse_mode="HTML")
