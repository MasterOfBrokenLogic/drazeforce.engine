import logging
import random
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor, ADMIN_ID
from helpers import safeEdit, isSuperAdmin, fmtDt
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def _genOtp() -> str:
    return str(random.randint(100000, 999999))


def _otpFolderInfo(folderId: int):
    return cursor.execute(
        "SELECT name, otp_expiry_minutes FROM folders WHERE id=? AND otp_required=1",
        (folderId,)
    ).fetchone()


# ─────────────────────────────────────────────
#  FOLDER MENU — OTP TOGGLE (Super Admin only)
# ─────────────────────────────────────────────

async def otpToggleCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()

    if not isSuperAdmin(query.from_user.id):
        await query.answer("Only the Super Admin can toggle OTP.", show_alert=True)
        return

    folderId = int(query.data.replace("otp_toggle_", ""))
    try:
        row = cursor.execute(
            "SELECT otp_required, otp_expiry_minutes FROM folders WHERE id=?", (folderId,)
        ).fetchone()
        if not row:
            await safeEdit(query, "Folder not found.", markup=kbHome())
            return

        current, expiry = row
        if current:
            # Turn off
            cursor.execute(
                "UPDATE folders SET otp_required=0, otp_expiry_minutes=NULL WHERE id=?",
                (folderId,)
            )
            conn.commit()
            await query.answer("OTP requirement removed.", show_alert=False)
            # Reload folder menu
            from handlers.folders import folderMenuCallback
            await folderMenuCallback(update, context)
        else:
            # Turn on — ask expiry first
            context.user_data["otp_setup_folder_id"] = folderId
            context.user_data["awaiting_otp_expiry"]  = True
            await safeEdit(
                query,
                "<b>OTP Access  —  Set Expiry</b>\n\n"
                "How many minutes should each OTP be valid for?\n\n"
                "<i>Enter a number between 1 and 60.</i>",
                markup=kbBack(f"foldermenu_{folderId}"),
                parse_mode="HTML",
            )
    except sqlite3.Error as e:
        logging.error(f"otpToggle: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())


# ─────────────────────────────────────────────
#  USER — REQUEST OTP (from folder deep link)
# ─────────────────────────────────────────────

async def sendOtpRequestScreen(update, context, folderId: int, folderName: str):
    """Called from start.py when folder has otp_required=1."""
    user    = update.effective_user
    botName = (await context.bot.get_me()).username

    # Pre-typed message that opens SA chat
    saUsername = "drazeforce"
    pretext    = (
        f"Hi, I need an OTP to access the folder: {folderName}\n"
        f"My User ID: {user.id}\n"
        f"My Username: @{user.username or 'N/A'}"
    )
    import urllib.parse
    saLink = f"https://t.me/{saUsername}?text={urllib.parse.quote(pretext)}"

    await update.message.reply_text(
        f"<b>OTP Required</b>\n\n"
        f"<code>Folder  :  {folderName}</code>\n\n"
        "This folder is protected by a One-Time Password.\n"
        "You must request an OTP from the admin to gain access.\n\n"
        "Once you have your OTP, come back here and enter it.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Request OTP from Admin", url=saLink)],
        ]),
    )

    # Store pending folder for when user enters OTP
    context.user_data["awaiting_otp_entry"] = True
    context.user_data["otp_folder_id"]       = folderId
    context.user_data["otp_attempts"]        = 0


# ─────────────────────────────────────────────
#  SA — GENERATE OTP (called from messages.py)
# ─────────────────────────────────────────────

async def otpGenerateCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SA taps Generate OTP button from the in-bot alert."""
    query    = update.callback_query
    await query.answer()

    if not isSuperAdmin(query.from_user.id):
        await query.answer("Only the Super Admin can generate OTPs.", show_alert=True)
        return

    # callback_data = "otp_gen_{folderId}_{userId}"
    parts    = query.data.replace("otp_gen_", "").split("_")
    folderId = int(parts[0])
    userId   = int(parts[1])

    try:
        row = cursor.execute(
            "SELECT name, otp_expiry_minutes FROM folders WHERE id=?", (folderId,)
        ).fetchone()
        if not row:
            await query.answer("Folder not found.", show_alert=True)
            return
        folderName, expiryMins = row

        # Check user exists
        userRow = cursor.execute(
            "SELECT first_name, username FROM subscribers WHERE user_id=?", (userId,)
        ).fetchone()
        firstName = userRow[0] if userRow else "Unknown"
        username  = userRow[1] if userRow else "N/A"

        code      = _genOtp()
        expiresAt = (datetime.now() + timedelta(minutes=expiryMins)).isoformat()

        # Invalidate any old pending OTPs for this user+folder
        cursor.execute(
            "UPDATE folder_otps SET status='revoked' WHERE folder_id=? AND user_id=? AND status='pending'",
            (folderId, userId)
        )
        cursor.execute(
            "INSERT INTO folder_otps (folder_id, user_id, code, created_at, expires_at, status)"
            " VALUES (?, ?, ?, ?, ?, 'pending')",
            (folderId, userId, code, datetime.now().isoformat(), expiresAt)
        )
        conn.commit()

    except sqlite3.Error as e:
        logging.error(f"otpGenerate: {e}")
        await query.answer("Database error.", show_alert=True)
        return

    await safeEdit(
        query,
        f"<b>OTP Generated</b>\n\n"
        f"<code>Folder   :  {folderName}</code>\n"
        f"<code>User     :  {firstName}  (@{username})</code>\n"
        f"<code>User ID  :  {userId}</code>\n\n"
        f"<code>OTP Code :  {code}</code>\n\n"
        f"<code>Expires  :  {expiryMins} minute(s) after delivery</code>\n\n"
        "Tap Send to deliver this OTP to the user.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Send OTP to User",
                callback_data=f"otp_send_{folderId}_{userId}"
            )],
            [InlineKeyboardButton("Cancel", callback_data="back_main")],
        ]),
    )


async def otpSendCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SA taps Send OTP to User — bot delivers OTP message to the user."""
    query = update.callback_query
    await query.answer()

    if not isSuperAdmin(query.from_user.id):
        await query.answer("Only the Super Admin can send OTPs.", show_alert=True)
        return

    parts    = query.data.replace("otp_send_", "").split("_")
    folderId = int(parts[0])
    userId   = int(parts[1])

    try:
        otpRow = cursor.execute(
            "SELECT code, expires_at FROM folder_otps "
            "WHERE folder_id=? AND user_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (folderId, userId)
        ).fetchone()
        if not otpRow:
            await query.answer("No pending OTP found. Generate one first.", show_alert=True)
            return

        code, expiresAt = otpRow
        folderName = cursor.execute(
            "SELECT name FROM folders WHERE id=?", (folderId,)
        ).fetchone()[0]
        expiryMins = cursor.execute(
            "SELECT otp_expiry_minutes FROM folders WHERE id=?", (folderId,)
        ).fetchone()[0]

    except sqlite3.Error as e:
        logging.error(f"otpSend: {e}")
        await query.answer("Database error.", show_alert=True)
        return

    try:
        await context.bot.send_message(
            chat_id=userId,
            text=(
                f"<b>Your One-Time Password</b>\n\n"
                f"<code>Folder   :  {folderName}</code>\n\n"
                f"<code>OTP Code :  {code}</code>\n\n"
                f"<code>Expires  :  {expiryMins} minute(s) from now</code>\n\n"
                "Go back to the bot and enter this code to access the folder.\n"
                "<i>This code can only be used once.</i>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"otpSend deliver: {e}")
        await safeEdit(
            query,
            "<b>Failed to Send</b>\n\nCould not deliver OTP to the user.\n"
            "They may not have started the bot yet.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return

    await safeEdit(
        query,
        f"<b>OTP Sent</b>\n\n"
        f"<code>Code  :  {code}</code>\n"
        f"<code>User  :  {userId}</code>\n\n"
        "The OTP has been delivered to the user.",
        markup=kbHome(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  USER — ENTER OTP (handled in messages.py)
# ─────────────────────────────────────────────

async def verifyOtpEntry(update, context, text: str) -> bool:
    """
    Called from messages.py when user is in awaiting_otp_entry state.
    Returns True if handled (whether success or failure), False if not in OTP state.
    """
    if not context.user_data.get("awaiting_otp_entry"):
        return False

    folderId = context.user_data.get("otp_folder_id")
    userId   = update.effective_user.id
    attempts = context.user_data.get("otp_attempts", 0)

    code = text.strip()

    try:
        otpRow = cursor.execute(
            "SELECT id, code, expires_at FROM folder_otps "
            "WHERE folder_id=? AND user_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (folderId, userId)
        ).fetchone()
    except sqlite3.Error as e:
        logging.error(f"verifyOtp: {e}")
        await update.message.reply_text("A database error occurred. Please try again.")
        return True

    if not otpRow:
        await update.message.reply_text(
            "<b>No Active OTP</b>\n\n"
            "You do not have a valid OTP for this folder.\n"
            "Please request a new one from the admin.",
            parse_mode="HTML",
        )
        context.user_data.clear()
        return True

    otpId, correctCode, expiresAt = otpRow

    # Check expiry
    if datetime.now() > datetime.fromisoformat(expiresAt):
        cursor.execute("UPDATE folder_otps SET status='expired' WHERE id=?", (otpId,))
        conn.commit()
        await update.message.reply_text(
            "<b>OTP Expired</b>\n\n"
            "This OTP is no longer valid.\n"
            "Please request a new one from the admin.",
            parse_mode="HTML",
        )
        context.user_data.clear()
        return True

    # Check code
    if code != correctCode:
        attempts += 1
        context.user_data["otp_attempts"] = attempts
        remaining = 3 - attempts
        if remaining <= 0:
            cursor.execute("UPDATE folder_otps SET status='revoked' WHERE id=?", (otpId,))
            conn.commit()
            await update.message.reply_text(
                "<b>Too Many Attempts</b>\n\n"
                "You have entered the wrong OTP 3 times.\n"
                "Please request a new OTP from the admin.",
                parse_mode="HTML",
            )
            context.user_data.clear()
        else:
            await update.message.reply_text(
                f"<b>Incorrect OTP</b>\n\n"
                f"<code>Attempts remaining  :  {remaining}</code>",
                parse_mode="HTML",
            )
        return True

    # Correct — mark used
    cursor.execute("UPDATE folder_otps SET status='used' WHERE id=?", (otpId,))
    conn.commit()
    context.user_data.clear()

    # Deliver the folder — reuse existing delivery logic from start.py
    from handlers.start import _deliverFolderOtp
    await _deliverFolderOtp(update, context, folderId)
    return True