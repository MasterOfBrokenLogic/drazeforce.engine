import asyncio
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor, ADMIN_ID
from helpers import safeEdit, generateBroadcastCode, isAdmin, isSuperAdmin, deleteAll
from keyboards import kbHome


# ─────────────────────────────────────────────
#  START BROADCAST
# ─────────────────────────────────────────────

async def broadcastCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        await query.answer("Only super admins can send broadcasts.", show_alert=True)
        return
    context.user_data["broadcast_mode"]  = True
    context.user_data["broadcast_files"] = []
    await safeEdit(
        query,
        "<b>New Broadcast</b>\n\n"
        "Send the content you want to broadcast to all subscribers.\n"
        "You can send multiple files, photos, videos, and text messages.\n\n"
        "Type <code>END</code> when you are done uploading.",
        markup=kbHome(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  PASSWORD STEP
# ─────────────────────────────────────────────

async def broadcastPasswordCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "broadcast_pass_yes":
        context.user_data["broadcast_step"] = "password_input"
        await safeEdit(
            query,
            "<b>Broadcast Password</b>\n\nEnter the password subscribers must provide to access this broadcast:",
        )
    else:
        context.user_data["broadcast_password"] = None
        context.user_data["broadcast_step"]     = "expiry"
        await safeEdit(
            query,
            "<b>Auto-Delete</b>\n\n"
            "Should the broadcast content auto-delete after being received%s",
            markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Yes", callback_data="broadcast_exp_yes"),
                    InlineKeyboardButton("No",  callback_data="broadcast_exp_no"),
                ]
            ]),
        )


# ─────────────────────────────────────────────
#  EXPIRY STEP
# ─────────────────────────────────────────────

async def broadcastExpiryCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "broadcast_exp_yes":
        context.user_data["broadcast_step"] = "expiry_input"
        await safeEdit(query, "<b>Auto-Delete Timer</b>\n\nEnter the number of minutes before content auto-deletes:")
    else:
        context.user_data["broadcast_expiry"] = None
        context.user_data["broadcast_step"]   = "forwardable"
        await safeEdit(
            query,
            "<b>Forward Permission</b>\n\n"
            "Should recipients be allowed to forward the broadcast content%s",
            markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Allow", callback_data="broadcast_fwd_yes"),
                    InlineKeyboardButton("Block", callback_data="broadcast_fwd_no"),
                ]
            ]),
        )


# ─────────────────────────────────────────────
#  FORWARDABLE STEP
# ─────────────────────────────────────────────

async def broadcastForwardCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["broadcast_forwardable"] = 1 if query.data == "broadcast_fwd_yes" else 0

    count    = len(context.user_data.get("broadcast_files", []))
    password = context.user_data.get("broadcast_password")
    expiry   = context.user_data.get("broadcast_expiry")
    fwd      = context.user_data.get("broadcast_forwardable")

    await safeEdit(
        query,
        f"<b>Broadcast Summary</b>\n\n"
        f"<code>Items       :  {count}</code>\n"
        f"<code>Password    :  {password if password else 'None'}</code>\n"
        f"<code>Auto-delete :  {str(expiry) + ' min' if expiry else 'Off'}</code>\n"
        f"<code>Forwardable :  {'Yes' if fwd else 'No'}</code>\n\n"
        "Ready to send to all subscribers%s",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Send Now", callback_data="broadcast_publish"),
                InlineKeyboardButton("Cancel",   callback_data="broadcast_cancel"),
            ]
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  PUBLISH BROADCAST
# ─────────────────────────────────────────────

async def broadcastPublishCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Sending...", show_alert=False)

    try:
        subscribers = cursor.execute(
            "SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL"
        )
        subscribers = cursor.fetchall()
    except Exception as e:
        logging.error(f"broadcastPublish sub: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())
        context.user_data.clear()
        return

    if not subscribers:
        await safeEdit(
            query,
            "<b>No Subscribers</b>\n\nThere are no subscribers to send this broadcast to.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        context.user_data.clear()
        return

    pwd     = context.user_data.get("broadcast_password")
    expiry  = context.user_data.get("broadcast_expiry")
    fwd     = context.user_data.get("broadcast_forwardable", 1)
    files   = context.user_data.get("broadcast_files", [])
    protect = fwd == 0
    code    = generateBroadcastCode()

    try:
        cursor.execute("""
            INSERT INTO broadcasts
                (broadcast_code, created_by, created_at, password, expiry_minutes, forwardable, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'sent')
        """, (code, query.from_user.id, datetime.now().isoformat(), pwd, expiry, fwd))
        broadcastId = cursor.fetchone()[0]
        for f in files:
            cursor.execute(
                "INSERT INTO broadcast_files (broadcast_id, file_id, file_type, text_content) VALUES (%s, %s, %s, %s)",
                (broadcastId, f.get("file_id"), f.get("file_type"), f.get("text_content"))
            )
        conn.commit()
    except Exception as e:
        logging.error(f"broadcastPublish save: {e}")
        await safeEdit(query, "Failed to save broadcast.", markup=kbHome())
        context.user_data.clear()
        return

    await safeEdit(
        query,
        f"<b>Sending Broadcast</b>\n\n"
        f"Delivering to {len(subscribers)} subscriber(s)...\n\n"
        "Please wait.",
        parse_mode="HTML",
    )

    sent = failed = 0
    for (uid,) in subscribers:
        if isAdmin(uid):
            continue
        try:
            if pwd:
                await context.bot.send_message(
                    chat_id=uid,
                    text="<b>New Broadcast</b>\n\n"
                         "You have received a new broadcast message.\n"
                         "This broadcast is password-protected.\n\n"
                         "Reply with the password to unlock the content.\n\n"
                         f"<code>Code  :  {code}</code>",
                    parse_mode="HTML",
                )
            else:
                sentMsgs = []
                alert = await context.bot.send_message(
                    chat_id=uid,
                    text="<b>New Broadcast</b>\n\n"
                         "You have a new message from the administrator.",
                    parse_mode="HTML",
                )
                sentMsgs.append(alert)

                if expiry:
                    m = await context.bot.send_message(
                        uid,
                        f"<b>Note</b>\n\n"
                        f"This content will be automatically deleted in <code>{expiry}</code> minute(s).",
                        parse_mode="HTML",
                    )
                    sentMsgs.append(m)

                for f in files:
                    fid, ftype, txt = f.get("file_id"), f.get("file_type"), f.get("text_content")
                    if ftype == "text":
                        m = await context.bot.send_message(uid, txt)
                    elif ftype == "video":
                        m = await context.bot.send_video(uid, fid, protect_content=protect, has_spoiler=True)
                    elif ftype == "photo":
                        m = await context.bot.send_photo(uid, fid, protect_content=protect, has_spoiler=True)
                    else:
                        m = await context.bot.send_document(uid, fid, protect_content=protect)
                    sentMsgs.append(m)

                if expiry:
                    asyncio.create_task(deleteAll(sentMsgs, expiry * 60))

            sent += 1
        except Exception as e:
            logging.error(f"broadcastPublish uid={uid}: {e}")
            failed += 1

    try:
        cursor.execute(
            "UPDATE broadcasts SET total_sent=%s, total_failed=%s WHERE id=%s",
            (sent, failed, broadcastId)
        )
        conn.commit()
    except Exception:
        pass

    context.user_data.clear()
    await safeEdit(
        query,
        f"<b>Broadcast Complete</b>\n\n"
        f"<code>Sent    :  {sent}</code>\n"
        f"<code>Failed  :  {failed}</code>\n"
        f"<code>Code    :  {code}</code>",
        markup=kbHome(),
        parse_mode="HTML",
    )


async def broadcastCancelCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await safeEdit(
        query,
        "<b>Broadcast Cancelled</b>\n\nNo messages were sent.",
        markup=kbHome(),
        parse_mode="HTML",
    )
