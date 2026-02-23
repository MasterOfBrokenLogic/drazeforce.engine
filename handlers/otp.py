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
#  MENU
# ─────────────────────────────────────────────

async def otpMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        total = cursor.execute(
            "SELECT COUNT(*) FROM folders WHERE otp_required=1"
        ).fetchone()[0]
        pending = cursor.execute(
            "SELECT COUNT(*) FROM folder_otps WHERE status='pending'"
        ).fetchone()[0]
    except Exception:
        total = pending = 0

    await safeEdit(
        query,
        "<b>OTP Access</b>\n\n"
        f"<code>OTP-protected folders  :  {total}</code>\n"
        f"<code>Pending OTP requests   :  {pending}</code>\n\n"
        "To require OTP on a folder, open the folder menu and tap <b>Require OTP</b>.\n\n"
        "<i>Only the Super Admin can enable or disable OTP access on folders.</i>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("View Folders", callback_data="view_folders")],
            [InlineKeyboardButton("Main Menu",    callback_data="back_main")],
        ]),
        parse_mode="HTML",
    )


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
    user = update.effective_user

    await update.message.reply_text(
        f"<b>OTP Required</b>\n\n"
        f"<code>Folder  :  {folderName}</code>\n\n"
        "This folder is protected by a One-Time Password.\n"
        "Tap the button below to request an OTP from the admin.\n\n"
        "<i>Once the admin sends your OTP, come back here and enter it.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Request OTP",
                callback_data=f"otp_request_{folderId}"
            )],
        ]),
    )

    # Store pending folder for when user enters OTP
    context.user_data["awaiting_otp_entry"] = True
    context.user_data["otp_folder_id"]       = folderId
    context.user_data["otp_attempts"]        = 0


# ─────────────────────────────────────────────
#  USER — TAPS REQUEST OTP BUTTON
# ─────────────────────────────────────────────

async def otpRequestCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User taps Request OTP — bot pings SA with Generate OTP button."""
    query    = update.callback_query
    await query.answer("Request sent to admin.", show_alert=False)

    folderId = int(query.data.replace("otp_request_", ""))
    user     = query.from_user

    try:
        folderName = cursor.execute(
            "SELECT name FROM folders WHERE id=?", (folderId,)
        ).fetchone()
        folderName = folderName[0] if folderName else "Unknown"
    except sqlite3.Error:
        folderName = "Unknown"

    # Store state so user can enter OTP when it arrives
    context.user_data["awaiting_otp_entry"] = True
    context.user_data["otp_folder_id"]       = folderId
    context.user_data["otp_attempts"]        = 0

    # Ping SA in-bot
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"<b>OTP Access Request</b>\n\n"
                f"<code>Folder    :  {folderName}</code>\n"
                f"<code>User ID   :  {user.id}</code>\n"
                f"<code>Username  :  @{user.username or 'N/A'}</code>\n"
                f"<code>Name      :  {user.first_name}</code>\n\n"
                "Tap Generate OTP to create a one-time code for this user."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "Generate OTP",
                    callback_data=f"otp_gen_{folderId}_{user.id}"
                )]
            ]),
        )
    except Exception as e:
        logging.error(f"otpRequestCallback notify SA: {e}")

    # Update the user's message to confirm request sent
    try:
        await query.edit_message_text(
            f"<b>OTP Requested</b>\n\n"
            f"<code>Folder  :  {folderName}</code>\n\n"
            "Your request has been sent to the admin.\n"
            "You will receive your OTP shortly.\n\n"
            "<i>Once you have it, type it here in the chat.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
#  SA — GENERATE OTP (called from messages.py)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  SA — GENERATE & SEND OTP IN ONE TAP
# ─────────────────────────────────────────────

async def otpGenerateCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """SA taps Generate & Send OTP — creates code and delivers it to user instantly."""
    query = update.callback_query
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

        userRow   = cursor.execute(
            "SELECT first_name, username FROM subscribers WHERE user_id=?", (userId,)
        ).fetchone()
        firstName = userRow[0] if userRow else "User"
        username  = userRow[1] if userRow else "N/A"

        code      = _genOtp()
        expiresAt = (datetime.now() + timedelta(minutes=expiryMins)).isoformat()

        # Revoke any old pending OTPs for this user+folder
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

    # Send OTP directly to user
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
        logging.error(f"otpGenerate deliver: {e}")
        await safeEdit(
            query,
            "<b>Failed to Send</b>\n\n"
            "Could not deliver the OTP to the user.\n"
            "They may not have started the bot yet.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return

    # Update SA's message to confirm
    await safeEdit(
        query,
        f"<b>OTP Sent</b>\n\n"
        f"<code>Folder   :  {folderName}</code>\n"
        f"<code>User     :  {firstName}  (@{username})</code>\n"
        f"<code>OTP Code :  {code}</code>\n"
        f"<code>Expires  :  {expiryMins} minute(s)</code>\n\n"
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