import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor, ADMIN_ID
from helpers import (
    isAdmin, isSuperAdmin, isBanned, trackUser,
    validateFolderName, validateMinutes, randomFolderName,
    generateToken, generateMessageId, deleteAll, fmtDt
)
from keyboards import kbHome, kbUser, kbBack
from handlers.start import _deliverFolder


# ─────────────────────────────────────────────
#  UNIFIED MESSAGE HANDLER
# ─────────────────────────────────────────────

async def messageHandler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user   = update.effective_user
    userId = user.id
    text   = update.message.text.strip() if update.message.text else None

    # Ban check
    if isBanned(userId) and not isAdmin(userId):
        return

    # ── Secret folder codeword check (all users, any message) ────────────
    if text and not isAdmin(userId):
        try:
            secret = cursor.execute(
                "SELECT id FROM folders WHERE is_secret=1 AND LOWER(secret_code)=LOWER(?)",
                (text.strip(),)
            ).fetchone()
        except sqlite3.Error:
            secret = None
        if secret:
            folderId = secret[0]
            # Check for folder password
            folderRow      = cursor.execute("SELECT password FROM folders WHERE id=?", (folderId,)).fetchone()
            folderPassword = folderRow[0] if folderRow else None

            # Secret folders deliver directly — no link required
            if folderPassword:
                context.user_data.update({
                    "awaiting_password_verify": True,
                    "verify_folder_id":         folderId,
                    "correct_password":         folderPassword,
                    "access_token":             None,   # secret access — no token
                    "password_attempts":        0,
                })
                await update.message.reply_text(
                    "<b>Password Required</b>\n\n"
                    "This folder is protected.\n"
                    "Enter the password to proceed:",
                    parse_mode="HTML",
                )
            else:
                await _deliverFolder(update, context, folderId, None, user)
            return

    # ── Broadcast password verification ──────────────────────────────────
    if context.user_data.get("broadcast_verify_mode"):
        code    = context.user_data.get("broadcast_verify_code")
        correct = context.user_data.get("broadcast_verify_password")

        if not text:
            await update.message.reply_text("Please enter the password as text.")
            return

        if text != correct:
            attempts = context.user_data.get("broadcast_verify_attempts", 0) + 1
            context.user_data["broadcast_verify_attempts"] = attempts
            if attempts >= 3:
                context.user_data.clear()
                await update.message.reply_text(
                    "<b>Access Denied</b>\n\nToo many incorrect attempts.",
                    parse_mode="HTML",
                )
                # Notify SA about failed attempts
                try:
                    from config import ADMIN_ID as SA_ID
                    brow = cursor.execute(
                        "SELECT created_by FROM broadcasts WHERE broadcast_code=?", (code,)
                    ).fetchone()
                    notify_id = brow[0] if brow else SA_ID
                    await context.bot.send_message(
                        chat_id=notify_id,
                        text="<b>Broadcast  —  Password Alert</b>\n\n"
                             f"<code>User ID   :  {userId}</code>\n"
                             f"<code>Username  :  {user.username or 'N/A'}</code>\n"
                             f"<code>Code      :  {code}</code>\n\n"
                             "This user failed 3 password attempts and has been blocked from this broadcast.",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logging.error(f"broadcast fail notify: {e}")
                return
            await update.message.reply_text(
                f"<b>Incorrect Password</b>\n\nAttempt {attempts} of 3.",
                parse_mode="HTML",
            )
            return

        context.user_data.clear()
        try:
            row = cursor.execute(
                "SELECT id, expiry_minutes, forwardable FROM broadcasts WHERE broadcast_code=?", (code,)
            ).fetchone()
            if not row:
                await update.message.reply_text("Broadcast not found.")
                return
            bId, expMin, fwd = row
            files = cursor.execute(
                "SELECT file_id, file_type, text_content FROM broadcast_files WHERE broadcast_id=?", (bId,)
            ).fetchall()
        except sqlite3.Error as e:
            logging.error(f"broadcast verify: {e}")
            await update.message.reply_text("A database error occurred.")
            return

        protect = fwd == 0
        await update.message.reply_text(
            "<b>Access Granted</b>\n\nLoading broadcast content...",
            parse_mode="HTML",
        )
        sentMsgs = []
        if expMin:
            m = await update.message.reply_text(
                f"<b>Note</b>\n\nThis content will be deleted in <code>{expMin}</code> minute(s).",
                parse_mode="HTML",
            )
            sentMsgs.append(m)
        for fid, ftype, txt in files:
            try:
                if ftype == "text":
                    m = await update.message.reply_text(txt)
                elif ftype == "video":
                    m = await update.message.reply_video(fid, protect_content=protect, has_spoiler=True)
                elif ftype == "photo":
                    m = await update.message.reply_photo(fid, protect_content=protect, has_spoiler=True)
                elif ftype == "document":
                    m = await update.message.reply_document(fid, protect_content=protect)
                else:
                    m = await update.message.reply_document(fid, protect_content=protect)
                sentMsgs.append(m)
            except Exception as e:
                logging.error(f"broadcast verify send: {e}")
        if expMin:
            asyncio.create_task(deleteAll(sentMsgs, expMin * 60))
        return

    # ── Contact admin mode ────────────────────────────────────────────────
    if context.user_data.get("contact_admin_mode"):
        if text and text.upper() == "CANCEL":
            context.user_data.clear()
            await update.message.reply_text("Cancelled.", reply_markup=kbUser())
            return

        if text and text.upper() == "SEND":
            contactFiles = context.user_data.get("contact_files", [])
            if not contactFiles:
                await update.message.reply_text(
                    "<b>Nothing to Send</b>\n\nAdd a message or files before typing SEND.",
                    parse_mode="HTML",
                    reply_markup=kbUser(),
                )
                context.user_data.clear()
                return

            recipientId      = context.user_data.get("contact_recipient_id", ADMIN_ID)
            recipientIsSuper = context.user_data.get("contact_recipient_is_super", 1)
            recipientLabel   = context.user_data.get("contact_recipient_label", "Admin")
            msgId            = generateMessageId()
            sender           = user.username or user.first_name or str(userId)

            try:
                cursor.execute("""
                    INSERT INTO user_messages
                        (user_id, username, first_name, message_id, sent_at, recipient_admin_id, recipient_is_super)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    userId, user.username, user.first_name,
                    msgId, datetime.now().isoformat(),
                    recipientId, recipientIsSuper
                ))
                for fd in contactFiles:
                    cursor.execute("""
                        INSERT INTO user_message_files (message_id, file_id, file_type, text_content)
                        VALUES (?, ?, ?, ?)
                    """, (msgId, fd.get("file_id"), fd.get("file_type"), fd.get("text_content")))
                conn.commit()
            except sqlite3.Error as e:
                logging.error(f"contact admin DB: {e}")
                await update.message.reply_text("Failed to send message.", reply_markup=kbUser())
                return

            # Notify the recipient admin
            notif_text = (
                f"<b>📩 New Message</b>\n\n"
                f"<code>From     :  {sender}</code>\n"
                f"<code>User ID  :  {userId}</code>\n"
                f"<code>Items    :  {len(contactFiles)}</code>\n"
                f"<code>Time     :  {fmtDt(datetime.now().isoformat())}</code>"
            )
            notif_btn = InlineKeyboardMarkup([[InlineKeyboardButton("View Message", callback_data=f"viewmsg_{msgId}")]])
            try:
                await context.bot.send_message(chat_id=recipientId, text=notif_text, parse_mode="HTML", reply_markup=notif_btn)
            except Exception as e:
                logging.error(f"notify admin {recipientId}: {e}")
                # fallback: always try to notify SA
                try:
                    await context.bot.send_message(chat_id=ADMIN_ID, text=notif_text, parse_mode="HTML", reply_markup=notif_btn)
                except Exception as e2:
                    logging.error(f"notify SA fallback: {e2}")

            # Always copy to SA if sent to a regular admin
            if not recipientIsSuper and recipientId != ADMIN_ID:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"<b>Message Copy</b>\n\n"
                             f"<code>From  :  {sender}  ({userId})</code>\n"
                             f"<code>To    :  {recipientLabel}</code>\n"
                             f"<code>Items :  {len(contactFiles)}</code>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("View", callback_data=f"viewmsg_{msgId}")]]),
                    )
                except Exception as e:
                    logging.error(f"SA copy: {e}")

            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Message Sent</b>\n\n"
                f"Delivered to <b>{recipientLabel}</b>.\n"
                "You will be notified when they reply.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("My Inbox", callback_data="user_inbox")],
                    [InlineKeyboardButton("Main Menu", callback_data="user_menu")],
                ]),
            )
            return

        # Collect files for contact
        fid, ftype, txt = None, None, None
        if update.message.video:
            fid, ftype = update.message.video.file_id, "video"
        elif update.message.photo:
            fid, ftype = update.message.photo[-1].file_id, "photo"
        elif update.message.document:
            fid, ftype = update.message.document.file_id, "document"
        elif text:
            ftype, txt = "text", text

        if ftype:
            context.user_data.setdefault("contact_files", []).append(
                {"file_id": fid, "file_type": ftype, "text_content": txt}
            )
            cnt = len(context.user_data["contact_files"])
            await update.message.reply_text(
                f"<b>Added</b>  |  {cnt} item(s) queued\n\n"
                "Type <code>SEND</code> when you are ready to deliver.",
                parse_mode="HTML",
            )
        return

    # ── Admin reply to user — must be before admin gate ──────────────────
    if context.user_data.get("awaiting_admin_reply"):
        if text and text.upper() == "CANCEL":
            msgId = context.user_data.get("reply_to_msg_id")
            context.user_data.clear()
            await update.message.reply_text("Reply cancelled.", reply_markup=kbHome())
            return

        toUserId = context.user_data.get("reply_to_user_id")
        msgId    = context.user_data.get("reply_to_msg_id")

        # Collect reply files — text check must not block media
        fid, ftype, ftxt = None, None, None
        if update.message.video:
            fid, ftype = update.message.video.file_id, "video"
        elif update.message.photo:
            fid, ftype = update.message.photo[-1].file_id, "photo"
        elif update.message.document:
            fid, ftype = update.message.document.file_id, "document"
        elif text and text.upper() not in ("SEND", "CANCEL"):
            ftype, ftxt = "text", text

        if ftype:
            context.user_data.setdefault("reply_files", []).append(
                {"file_id": fid, "file_type": ftype, "text_content": ftxt}
            )
            cnt = len(context.user_data["reply_files"])
            await update.message.reply_text(
                f"<b>Added</b>  |  {cnt} item(s) queued\n\nType <code>SEND</code> when done.",
                parse_mode="HTML"
            )
            return

        if text and text.upper() == "SEND":
            replyFiles = context.user_data.get("reply_files", [])
            if not replyFiles:
                await update.message.reply_text("<b>Nothing to send.</b> Add some content first, then type SEND.", parse_mode="HTML")
                return

            # Save reply + files to DB
            replyId   = str(uuid.uuid4())[:12]
            adminId   = userId
            adminRow  = cursor.execute("SELECT username FROM admins WHERE user_id=?", (adminId,)).fetchone()
            adminName = (adminRow[0] if adminRow else None) or f"Admin {adminId}"
            textOnly  = " | ".join(f["text_content"] for f in replyFiles if f.get("text_content")) or None
            try:
                cursor.execute("""
                    INSERT INTO message_replies (reply_id, message_id, from_admin_id, to_user_id, content, sent_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (replyId, msgId, adminId, toUserId, textOnly, datetime.now().isoformat()))
                for rf in replyFiles:
                    cursor.execute("""
                        INSERT INTO message_reply_files (reply_id, file_id, file_type, text_content)
                        VALUES (?, ?, ?, ?)
                    """, (replyId, rf.get("file_id"), rf["file_type"], rf.get("text_content")))
                conn.commit()
            except sqlite3.Error as e:
                logging.error(f"save reply: {e}")
                await update.message.reply_text("Failed to save reply.", reply_markup=kbHome())
                context.user_data.clear()
                return

            # Notify user and deliver content directly
            try:
                await context.bot.send_message(
                    chat_id=toUserId,
                    text=f"📩 <b>You Got a Reply</b>\n\n"
                         f"<code>{adminName}</code> replied to your message.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("View Reply", callback_data=f"viewreply_{replyId}")],
                        [InlineKeyboardButton("My Inbox",   callback_data="user_inbox")],
                    ]),
                )
                for rf in replyFiles:
                    try:
                        if rf["file_type"] == "text":
                            await context.bot.send_message(chat_id=toUserId, text=rf["text_content"])
                        elif rf["file_type"] == "video":
                            await context.bot.send_video(chat_id=toUserId, video=rf["file_id"])
                        elif rf["file_type"] == "photo":
                            await context.bot.send_photo(chat_id=toUserId, photo=rf["file_id"])
                        elif rf["file_type"] == "document":
                            await context.bot.send_document(chat_id=toUserId, document=rf["file_id"])
                    except Exception as e:
                        logging.error(f"reply deliver: {e}")
            except Exception as e:
                logging.error(f"reply notify: {e}")

            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Reply Sent</b>\n\nYour reply has been delivered to the user.",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            return
        return

    # ── Password verify (link access) — must be before admin gate ─────────
    if context.user_data.get("awaiting_password_verify"):
        folderId = context.user_data.get("verify_folder_id")
        correct  = context.user_data.get("correct_password")
        token    = context.user_data.get("access_token")

        if not text:
            await update.message.reply_text("Please enter the password as text.")
            return

        if text != correct:
            attempts = context.user_data.get("password_attempts", 0) + 1
            context.user_data["password_attempts"] = attempts
            if attempts >= 3:
                context.user_data.clear()
                await update.message.reply_text(
                    "<b>Access Denied</b>\n\nToo many incorrect attempts.",
                    parse_mode="HTML",
                    reply_markup=kbUser(),
                )
                return
            await update.message.reply_text(
                f"<b>Incorrect Password</b>\n\nAttempt {attempts} of 3.",
                parse_mode="HTML",
            )
            return

        context.user_data.clear()
        await _deliverFolder(update, context, folderId, token, user)
        return

    # ── Admin-only from here ──────────────────────────────────────────────
    if not isAdmin(userId):
        return

    # ── Welcome message ───────────────────────────────────────────────────
    if context.user_data.get("awaiting_welcome_msg"):
        if not text:
            await update.message.reply_text("Please send text for the welcome message.")
            return
        context.user_data.clear()
        if text.upper() == "RESET":
            cursor.execute("DELETE FROM bot_settings WHERE key='welcome_message'")
            conn.commit()
            await update.message.reply_text(
                "<b>Welcome Message Reset</b>\n\nDefault greeting restored.",
                parse_mode="HTML",
                reply_markup=kbBack("settings_welcome"),
            )
        else:
            cursor.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('welcome_message', ?)", (text,)
            )
            conn.commit()
            await update.message.reply_text(
                f"<b>Welcome Message Saved</b>\n\n{text}",
                parse_mode="HTML",
                reply_markup=kbBack("settings_menu"),
            )
        return

    # ── Add quote — step 1: quote text ───────────────────────────────────
    if context.user_data.get("awaiting_quote"):
        if not text:
            await update.message.reply_text("Please send the quote as text.")
            return
        context.user_data["quote_text"]     = text
        context.user_data["awaiting_quote"] = False
        context.user_data["awaiting_quote_author"] = True
        await update.message.reply_text(
            f"<b>Quote saved:</b>\n<i>{text}</i>\n\n"
            "Who said this? Type their name, or type <code>none</code> to leave it anonymous.",
            parse_mode="HTML",
        )
        return

    # ── Add quote — step 2: author ────────────────────────────────────────
    if context.user_data.get("awaiting_quote_author"):
        quote_text = context.user_data.get("quote_text", "")
        author     = None if (not text or text.lower() == "none") else text.strip()
        context.user_data.clear()
        try:
            cursor.execute(
                "INSERT INTO quotes (text, author, added_by, added_at) VALUES (?, ?, ?, ?)",
                (quote_text, author, userId, datetime.now().isoformat())
            )
            conn.commit()
            author_line = f"\n<code>By  :  {author}</code>" if author else ""
            await update.message.reply_text(
                f"<b>Quote Added</b>\n\n"
                f"<i>{quote_text}</i>{author_line}\n\n"
                "It will appear in the daily rotation.",
                parse_mode="HTML",
                reply_markup=kbBack("settings_quotes"),
            )
        except sqlite3.Error as e:
            logging.error(f"addQuote: {e}")
            await update.message.reply_text("Failed to save quote.", reply_markup=kbBack("settings_quotes"))
        return

    # ── Secret folder codeword ────────────────────────────────────────────
    if context.user_data.get("awaiting_secret_code"):
        folderId = context.user_data.get("secret_folder_id")
        context.user_data.clear()
        if text:
            cursor.execute(
                "UPDATE folders SET is_secret=1, secret_code=? WHERE id=?", (text.strip(), folderId)
            )
            conn.commit()
            await update.message.reply_text(
                f"<b>Secret Folder Configured</b>\n\n"
                f"<code>Codeword  :  {text.strip()}</code>\n\n"
                "Users who type this codeword will receive the folder content.",
                parse_mode="HTML",
                reply_markup=kbBack("settings_secrets"),
            )
        return

    # ── Trending label ────────────────────────────────────────────────────
    if context.user_data.get("awaiting_trending_label"):
        folderId = context.user_data.get("trending_folder_id")
        context.user_data.clear()
        folder   = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
        label    = folder[0] if (not text or text.upper() == "SKIP") else text
        expires  = (datetime.now() + timedelta(hours=24)).isoformat()
        try:
            # Remove existing entry for this folder if any
            cursor.execute("DELETE FROM trending WHERE folder_id=?", (folderId,))
            cursor.execute("""
                INSERT INTO trending (folder_id, label, added_by, added_at, expires_at, sort_order)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (folderId, label, userId, datetime.now().isoformat(), expires))
            conn.commit()
            await update.message.reply_text(
                f"<b>Added to Trending</b>\n\n"
                f"<code>Label    :  {label}</code>\n"
                f"<code>Expires  :  24 hours</code>",
                parse_mode="HTML",
                reply_markup=kbBack("trending_menu"),
            )
        except sqlite3.Error as e:
            logging.error(f"trending label save: {e}")
            await update.message.reply_text("Failed to add to trending.", reply_markup=kbHome())
        return

    # ── Poll creation flow ────────────────────────────────────────────────
    poll_step = context.user_data.get("poll_create_step")
    if poll_step:
        poll_data = context.user_data.setdefault("poll_data", {})
        steps     = ["question", "option_a", "option_b", "option_c", "option_d", "duration"]
        labels    = ["Question", "Option A", "Option B", "Option C (optional)", "Option D (optional)", "Duration (minutes)"]
        step_idx  = steps.index(poll_step) if poll_step in steps else -1

        if not text:
            await update.message.reply_text("Please send text.")
            return

        # Optional options: skip with SKIP
        if poll_step in ("option_c", "option_d") and text.upper() == "SKIP":
            poll_data[poll_step] = None
        elif poll_step == "duration":
            valid, result = validateMinutes(text)
            if not valid:
                await update.message.reply_text(f"<b>Invalid</b>\n\n{result}", parse_mode="HTML")
                return
            poll_data["duration"] = result
        else:
            poll_data[poll_step] = text

        # Advance to next step
        next_idx = step_idx + 1
        if next_idx < len(steps):
            next_step = steps[next_idx]
            context.user_data["poll_create_step"] = next_step
            skip_hint = "\n\nType <code>SKIP</code> to leave this option blank." if next_step in ("option_c", "option_d") else ""
            await update.message.reply_text(
                f"<b>Create Poll  —  Step {next_idx + 1} of {len(steps)}</b>\n\n"
                f"Enter <b>{labels[next_idx]}</b>:{skip_hint}",
                parse_mode="HTML",
            )
        else:
            # All steps done — save poll and send to subscribers
            closes_at = (datetime.now() + timedelta(minutes=poll_data["duration"])).isoformat()
            try:
                cursor.execute("""
                    INSERT INTO polls (question, option_a, option_b, option_c, option_d,
                                       created_by, created_at, closes_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """, (
                    poll_data.get("question"),
                    poll_data.get("option_a"),
                    poll_data.get("option_b"),
                    poll_data.get("option_c"),
                    poll_data.get("option_d"),
                    userId,
                    datetime.now().isoformat(),
                    closes_at,
                ))
                pollId = cursor.lastrowid
                conn.commit()
            except sqlite3.Error as e:
                logging.error(f"poll save: {e}")
                await update.message.reply_text("Failed to create poll.", reply_markup=kbHome())
                context.user_data.clear()
                return

            context.user_data.clear()

            # Build vote buttons
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup # type: ignore 
            opts    = [(k, poll_data.get(k)) for k in ("option_a","option_b","option_c","option_d")]
            buttons = []
            row     = []
            choice_map = {"option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D"}
            for key, val in opts:
                if val:
                    letter = choice_map[key]
                    row.append(InlineKeyboardButton(f"{letter}  —  {val}", callback_data=f"vote_{pollId}_{letter}"))
                    if len(row) == 2:
                        buttons.append(row)
                        row = []
            if row:
                buttons.append(row)

            msg = (
                f"<b>New Poll</b>\n\n"
                f"<b>{poll_data['question']}</b>\n\n"
            )
            for key, val in opts:
                if val:
                    msg += f"<code>{choice_map[key]}</code>  {val}\n"
            msg += f"\n<code>Closes  :  {fmtDt(closes_at)}</code>"

            subs = cursor.execute(
                "SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL"
            ).fetchall()
            sent = 0
            for (uid,) in subs:
                try:
                    await context.bot.send_message(
                        uid, msg,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                    sent += 1
                except Exception:
                    pass

            await update.message.reply_text(
                f"<b>Poll Created and Sent</b>\n\n"
                f"<code>Poll ID   :  {pollId}</code>\n"
                f"<code>Sent to   :  {sent} subscribers</code>\n"
                f"<code>Closes    :  {fmtDt(closes_at)}</code>",
                parse_mode="HTML",
                reply_markup=kbBack("poll_menu"),
            )
        return
    if context.user_data.get("awaiting_password"):
        if not text:
            await update.message.reply_text("Please enter the password as text.")
            return
        folderId = context.user_data.get("set_password_folder_id")
        if not folderId:
            context.user_data.clear()
            await update.message.reply_text("Session expired. Please try again.", reply_markup=kbHome())
            return
        try:
            cursor.execute("UPDATE folders SET password=? WHERE id=?", (text, folderId))
            conn.commit()
            folderName = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
            folderName = folderName[0] if folderName else str(folderId)
            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Password Set</b>\n\n"
                f"<code>Folder    :  {folderName}</code>\n"
                f"<code>Password  :  {text}</code>",
                parse_mode="HTML",
                reply_markup=kbBack(f"foldermenu_{folderId}"),
            )
        except sqlite3.Error as e:
            logging.error(f"setPassword: {e}")
            await update.message.reply_text("Failed to set password.", reply_markup=kbHome())
        return

    # ── Ban ID input ──────────────────────────────────────────────────────
    if context.user_data.get("awaiting_ban_id"):
        try:
            targetId = int(text)
        except (ValueError, TypeError):
            await update.message.reply_text("Invalid input. Send a numeric User ID.")
            return

        try:
            row      = cursor.execute("SELECT username FROM subscribers WHERE user_id=?", (targetId,)).fetchone()
            username = row[0] if row else None
            cursor.execute("""
                INSERT OR REPLACE INTO banned_users (user_id, username, reason, banned_at, banned_by)
                VALUES (?, ?, 'Banned via admin panel', ?, ?)
            """, (targetId, username, datetime.now().isoformat(), userId))
            conn.commit()
            context.user_data.clear()
            await update.message.reply_text(
                f"<b>User Banned</b>\n\n<code>{targetId}</code> has been added to the ban list.",
                parse_mode="HTML",
                reply_markup=kbBack("admin_menu"),
            )
            # Notify the banned user
            try:
                await context.bot.send_message(
                    chat_id=targetId,
                    text="<b>Account Restricted</b>\n\n"
                         "Your access to this service has been restricted by an administrator.\n\n"
                         "If you believe this is an error, you will need to contact the administrator directly.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except sqlite3.Error as e:
            logging.error(f"banUser: {e}")
            await update.message.reply_text("Failed to ban user.", reply_markup=kbBack("admin_menu"))
        return

    # ── Add admin ─────────────────────────────────────────────────────────
    if context.user_data.get("awaiting_admin_id"):
        newId = None
        newUsername = None
        if update.message.forward_origin and hasattr(update.message.forward_origin, "sender_user"):
            su          = update.message.forward_origin.sender_user
            newId       = su.id
            newUsername = su.username
        else:
            try:
                newId = int(text)
            except (ValueError, TypeError):
                await update.message.reply_text(
                    "<b>Invalid Input</b>\n\n"
                    "Forward a message from the user, or send their numeric User ID.",
                    parse_mode="HTML",
                    reply_markup=kbBack("admin_menu"),
                )
                return
        try:
            cursor.execute("""
                INSERT INTO admins (user_id, username, added_by, added_at, is_super_admin)
                VALUES (?, ?, ?, ?, 0)
            """, (newId, newUsername, userId, datetime.now().isoformat()))
            conn.commit()
            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Admin Added</b>\n\n"
                f"<code>{newId}</code> has been granted admin access.",
                parse_mode="HTML",
                reply_markup=kbBack("admin_menu"),
            )
            # Notify the new admin
            try:
                await context.bot.send_message(
                    chat_id=newId,
                    text="<b>You Have Been Promoted</b>\n\n"
                         "You now have admin access to this bot.\n\n"
                         "<b>Admin Commands</b>\n"
                         "<code>/start</code>   Open the control panel\n"
                         "<code>/help</code>    List all commands\n"
                         "<code>/stats</code>   Quick analytics\n"
                         "<code>/search</code>  Search folders\n"
                         "<code>/cancel</code>  Cancel any operation",
                    parse_mode="HTML",
                )
            except Exception as e:
                logging.error(f"promote notify: {e}")
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "<b>Already an Admin</b>\n\nThis user already has admin access.",
                parse_mode="HTML",
                reply_markup=kbBack("admin_menu"),
            )
        except sqlite3.Error as e:
            logging.error(f"addAdmin: {e}")
            await update.message.reply_text("Failed to add administrator.", reply_markup=kbBack("admin_menu"))
        return

    # ── Folder name ───────────────────────────────────────────────────────
    if context.user_data.get("awaiting_folder_name"):
        if not text:
            await update.message.reply_text("Please enter a valid folder name.", reply_markup=kbHome())
            return
        folderName = randomFolderName() if text.upper() == "RANDOM" else text
        if text.upper() != "RANDOM":
            ok, err = validateFolderName(folderName)
            if not ok:
                await update.message.reply_text(
                    f"<b>Invalid Name</b>\n\n{err}",
                    parse_mode="HTML",
                    reply_markup=kbHome(),
                )
                return
        try:
            cursor.execute(
                "INSERT INTO folders (name, created_at) VALUES (?, ?)",
                (folderName, datetime.now().isoformat())
            )
            conn.commit()
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "<b>Name Taken</b>\n\nA folder with that name already exists.",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            return
        except sqlite3.Error as e:
            logging.error(f"createFolder: {e}")
            await update.message.reply_text("Database error.", reply_markup=kbHome())
            return

        context.user_data.clear()
        context.user_data["upload_mode"]      = folderName
        context.user_data["file_count"]       = 0
        await update.message.reply_text(
            f"<b>Folder Created</b>  |  <code>{folderName}</code>\n\n"
            "Send files, photos, videos or text messages to add them.\n\n"
            "Type <code>END</code> when you are done uploading.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    # ── Folder note ───────────────────────────────────────────────────────
    if context.user_data.get("awaiting_note"):
        folderId = context.user_data.get("note_folder_id")
        context.user_data.clear()
        if text and text.upper() == "CLEAR":
            cursor.execute("UPDATE folders SET note=NULL WHERE id=?", (folderId,))
            conn.commit()
            await update.message.reply_text(
                "<b>Note Removed</b>",
                parse_mode="HTML",
                reply_markup=kbBack(f"foldermenu_{folderId}"),
            )
        else:
            cursor.execute("UPDATE folders SET note=? WHERE id=?", (text, folderId))
            conn.commit()
            await update.message.reply_text(
                "<b>Note Saved</b>",
                parse_mode="HTML",
                reply_markup=kbBack(f"foldermenu_{folderId}"),
            )
        return

    # ── Folder search ─────────────────────────────────────────────────────
    if context.user_data.get("awaiting_search"):
        context.user_data.clear()
        keyword = text or ""
        try:
            results = cursor.execute("""
                SELECT f.id, f.name, COUNT(fi.id)
                FROM folders f
                LEFT JOIN files fi ON f.id = fi.folder_id
                WHERE f.name LIKE ?
                GROUP BY f.id ORDER BY f.created_at DESC
            """, (f"%{keyword}%",)).fetchall()
        except sqlite3.Error:
            await update.message.reply_text("Search failed.", reply_markup=kbHome())
            return

        if not results:
            await update.message.reply_text(
                f"<b>No Results</b>\n\nNo folders matched <code>{keyword}</code>.",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            return

        lines = [f"<b>Search Results</b>  |  {len(results)} found\n"]
        for fid, name, count in results:
            lines.append(f"\n<code>{name}</code>  |  {count} file(s)")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=kbHome())
        return

    # ── Preview time ──────────────────────────────────────────────────────
    if context.user_data.get("awaiting_preview_time"):
        valid, result = validateMinutes(text)
        folderId      = context.user_data.get("preview_folder_id")
        if not valid:
            await update.message.reply_text(
                f"<b>Invalid Input</b>\n\n{result}",
                parse_mode="HTML",
                reply_markup=kbBack(f"foldermenu_{folderId}"),
            )
            return
        context.user_data.clear()
        try:
            files      = cursor.execute(
                "SELECT file_id, file_type, text_content FROM files WHERE folder_id=?", (folderId,)
            ).fetchall()
            folderName = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()[0]
        except sqlite3.Error:
            await update.message.reply_text("Database error.", reply_markup=kbHome())
            return
        if not files:
            await update.message.reply_text(
                "<b>Empty Folder</b>\n\nThis folder has no files to preview.",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            return
        infoMsg = await update.message.reply_text(
            f"<b>Preview</b>  |  <code>{folderName}</code>  |  {result} min",
            parse_mode="HTML",
        )
        sentMsgs = [infoMsg]
        for fid, ftype, txt in files:
            try:
                if ftype == "text":
                    m = await update.message.reply_text(txt)
                elif ftype == "video":
                    m = await update.message.reply_video(fid, has_spoiler=True)
                elif ftype == "photo":
                    m = await update.message.reply_photo(fid, has_spoiler=True)
                else:
                    m = await update.message.reply_document(fid)
                sentMsgs.append(m)
            except Exception as e:
                logging.error(f"preview send: {e}")
        asyncio.create_task(deleteAll(sentMsgs, result * 60))
        await update.message.reply_text(
            f"<b>Preview Sent</b>\n\nAuto-deletes in <code>{result}</code> minute(s).",
            parse_mode="HTML",
            reply_markup=kbBack(f"foldermenu_{folderId}"),
        )
        return

    # ── Link: auto_delete input ───────────────────────────────────────────
    if context.user_data.get("link_step") == "auto_delete":
        valid, result = validateMinutes(text) if text != "0" else (True, 0)
        if not valid:
            await update.message.reply_text(
                f"<b>Invalid Input</b>\n\n{result}",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            return
        context.user_data["auto_delete"] = result
        singleUse = context.user_data.get("link_single_use", 0)

        if singleUse:
            # Single-use links don't need expiry — auto-set 7 days and generate immediately
            folderId    = context.user_data.get("link_folder_id")
            forwardable = context.user_data.get("forwardable", 1)
            autoDelete  = result
            try:
                cursor.execute(
                    "UPDATE folders SET forwardable=?, auto_delete_minutes=? WHERE id=?",
                    (forwardable, autoDelete if autoDelete else None, folderId)
                )
                token  = generateToken()
                expiry = (datetime.now() + timedelta(days=7)).isoformat()
                cursor.execute(
                    "INSERT INTO links (folder_id, token, expiry, created_at, single_use) VALUES (?, ?, ?, ?, ?)",
                    (folderId, token, expiry, datetime.now().isoformat(), 1)
                )
                conn.commit()
                botName = context.bot.username
                linkUrl = f"https://t.me/{botName}?start={token}"
                context.user_data.clear()
                await update.message.reply_text(
                    f"<b>Single-Use Link Generated</b>\n\n"
                    f"<code>{linkUrl}</code>\n\n"
                    f"<code>Type         :  Single-use — revokes after first open</code>\n"
                    f"<code>Auto-delete  :  {str(autoDelete) + ' min' if autoDelete else 'Off'}</code>\n"
                    f"<code>Forwardable  :  {'Yes' if forwardable else 'No'}</code>",
                    parse_mode="HTML",
                    reply_markup=kbHome(),
                )
            except sqlite3.Error as e:
                logging.error(f"singleUseLink: {e}")
                await update.message.reply_text("Failed to generate link.", reply_markup=kbHome())
        else:
            context.user_data["link_step"] = "expiry"
            await update.message.reply_text(
                "<b>Link Expiry</b>\n\n"
                "How many minutes should the link remain valid?\n\n"
                "Enter a number between 1 and 10080:",
                parse_mode="HTML",
            )
        return

    # ── Link: expiry input ────────────────────────────────────────────────
    if context.user_data.get("link_step") == "expiry":
        valid, expiryMins = validateMinutes(text)
        if not valid:
            await update.message.reply_text(
                f"<b>Invalid Input</b>\n\n{expiryMins}",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            return
        folderId    = context.user_data.get("link_folder_id")
        forwardable = context.user_data.get("forwardable", 1)
        autoDelete  = context.user_data.get("auto_delete", 0)
        singleUse   = context.user_data.get("link_single_use", 0)
        if not folderId:
            await update.message.reply_text(
                "<b>Session Expired</b>\n\nPlease start again.",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
            context.user_data.clear()
            return
        try:
            cursor.execute(
                "UPDATE folders SET forwardable=?, auto_delete_minutes=? WHERE id=?",
                (forwardable, autoDelete if autoDelete else None, folderId)
            )
            token  = generateToken()
            expiry = (datetime.now() + timedelta(minutes=expiryMins)).isoformat()
            cursor.execute(
                "INSERT INTO links (folder_id, token, expiry, created_at, single_use) VALUES (?, ?, ?, ?, ?)",
                (folderId, token, expiry, datetime.now().isoformat(), singleUse)
            )
            conn.commit()
            botName = context.bot.username
            linkUrl = f"https://t.me/{botName}?start={token}"
            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Link Generated</b>\n\n"
                f"<code>{linkUrl}</code>\n\n"
                f"<code>Expires      :  {expiryMins} min</code>\n"
                f"<code>Auto-delete  :  {str(autoDelete) + ' min' if autoDelete else 'Off'}</code>\n"
                f"<code>Forwardable  :  {'Yes' if forwardable else 'No'}</code>\n"
                f"<code>Single-use   :  {'Yes — revokes after first open' if singleUse else 'No'}</code>",
                parse_mode="HTML",
                reply_markup=kbHome(),
            )
        except sqlite3.Error as e:
            logging.error(f"linkExpiry: {e}")
            await update.message.reply_text("Failed to generate link.", reply_markup=kbHome())
        return

    # ── Broadcast: password input ─────────────────────────────────────────
    if context.user_data.get("broadcast_step") == "password_input":
        if not text:
            await update.message.reply_text("Please enter a valid password.")
            return
        context.user_data["broadcast_password"] = text
        context.user_data["broadcast_step"]     = "expiry"
        await update.message.reply_text(
            "<b>Auto-Delete</b>\n\n"
            "Should the broadcast content auto-delete after being received?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Yes", callback_data="broadcast_exp_yes"),
                    InlineKeyboardButton("No",  callback_data="broadcast_exp_no"),
                ]
            ]),
        )
        return

    # ── Broadcast: expiry input ───────────────────────────────────────────
    if context.user_data.get("broadcast_step") == "expiry_input":
        valid, result = validateMinutes(text)
        if not valid:
            await update.message.reply_text(
                f"<b>Invalid Input</b>\n\n{result}",
                parse_mode="HTML",
            )
            return
        context.user_data["broadcast_expiry"] = result
        context.user_data["broadcast_step"]   = "forwardable"
        await update.message.reply_text(
            "<b>Forward Permission</b>\n\n"
            "Should recipients be allowed to forward the broadcast content?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Allow", callback_data="broadcast_fwd_yes"),
                    InlineKeyboardButton("Block", callback_data="broadcast_fwd_no"),
                ]
            ]),
        )
        return

    # ── Broadcast: collect files ──────────────────────────────────────────
    if context.user_data.get("broadcast_mode"):
        if text and text.upper() == "END":
            cnt = len(context.user_data.get("broadcast_files", []))
            if cnt == 0:
                await update.message.reply_text(
                    "<b>No Content</b>\n\nAdd at least one file or message before ending.",
                    parse_mode="HTML",
                    reply_markup=kbHome(),
                )
                context.user_data.clear()
                return
            context.user_data["broadcast_step"] = "password"
            await update.message.reply_text(
                f"<b>{cnt} item(s) ready</b>\n\n"
                "Should this broadcast require a password?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Yes", callback_data="broadcast_pass_yes"),
                        InlineKeyboardButton("No",  callback_data="broadcast_pass_no"),
                    ]
                ]),
            )
            return

        fid, ftype, fsize, txt = None, None, None, None
        if update.message.video:
            fid, ftype, fsize = update.message.video.file_id, "video", update.message.video.file_size
        elif update.message.photo:
            fid, ftype, fsize = update.message.photo[-1].file_id, "photo", update.message.photo[-1].file_size
        elif update.message.document:
            fid, ftype, fsize = update.message.document.file_id, "document", update.message.document.file_size
        elif text:
            ftype, txt = "text", text

        if ftype:
            context.user_data.setdefault("broadcast_files", []).append(
                {"file_id": fid, "file_type": ftype, "text_content": txt}
            )
            cnt = len(context.user_data["broadcast_files"])
            await update.message.reply_text(
                f"<b>{ftype.upper()} added</b>  |  Total: {cnt}\n\n"
                "Type <code>END</code> when you are done.",
                parse_mode="HTML",
            )
        return

    # ── Upload mode (new folder) ──────────────────────────────────────────
    if context.user_data.get("upload_mode"):
        folderName = context.user_data["upload_mode"]
        if text and text.upper() == "END":
            count    = context.user_data.get("file_count", 0)
            folderId = cursor.execute("SELECT id FROM folders WHERE name=?", (folderName,)).fetchone()[0]
            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Upload Complete</b>\n\n"
                f"<code>{folderName}</code>  |  {count} file(s) added",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Generate Link", callback_data=f"link_{folderId}")],
                    [InlineKeyboardButton("Main Menu",    callback_data="back_main")],
                ]),
            )
            return

        fid, ftype, fsize, txt = None, None, None, None
        if update.message.video:
            fid, ftype, fsize = update.message.video.file_id, "video", update.message.video.file_size
        elif update.message.photo:
            fid, ftype, fsize = update.message.photo[-1].file_id, "photo", update.message.photo[-1].file_size
        elif update.message.document:
            fid, ftype, fsize = update.message.document.file_id, "document", update.message.document.file_size
        elif text:
            ftype, txt, fsize = "text", text, len(text.encode())
        if ftype:
            try:
                folderId = cursor.execute("SELECT id FROM folders WHERE name=?", (folderName,)).fetchone()[0]
                cursor.execute(
                    "INSERT INTO files (folder_id, file_id, file_type, file_size, uploaded_at, text_content) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (folderId, fid, ftype, fsize, datetime.now().isoformat(), txt)
                )
                conn.commit()
                context.user_data["file_count"] += 1
                await update.message.reply_text(
                    f"<b>{ftype.upper()} saved</b>  |  Total: {context.user_data['file_count']}"
                )
            except sqlite3.Error as e:
                logging.error(f"upload: {e}")
                await update.message.reply_text("Failed to save file.", reply_markup=kbHome())
        return

    # ── Add media mode (existing folder) ─────────────────────────────────
    if context.user_data.get("add_media_mode"):
        folderName = context.user_data["add_media_mode"]
        folderId   = context.user_data["add_media_folder_id"]
        if text and text.upper() == "DONE":
            count = context.user_data.get("file_count", 0)
            context.user_data.clear()
            await update.message.reply_text(
                f"<b>Done</b>\n\n{count} file(s) added to <code>{folderName}</code>.",
                parse_mode="HTML",
                reply_markup=kbBack(f"foldermenu_{folderId}"),
            )
            return

        fid, ftype, fsize, txt = None, None, None, None
        if update.message.video:
            fid, ftype, fsize = update.message.video.file_id, "video", update.message.video.file_size
        elif update.message.photo:
            fid, ftype, fsize = update.message.photo[-1].file_id, "photo", update.message.photo[-1].file_size
        elif update.message.document:
            fid, ftype, fsize = update.message.document.file_id, "document", update.message.document.file_size
        elif text:
            ftype, txt, fsize = "text", text, len(text.encode())
        if ftype:
            try:
                cursor.execute(
                    "INSERT INTO files (folder_id, file_id, file_type, file_size, uploaded_at, text_content) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (folderId, fid, ftype, fsize, datetime.now().isoformat(), txt)
                )
                conn.commit()
                context.user_data["file_count"] = context.user_data.get("file_count", 0) + 1
                await update.message.reply_text(
                    f"<b>{ftype.upper()} added</b>  |  Total: {context.user_data['file_count']}"
                )
            except sqlite3.Error as e:
                logging.error(f"addMedia: {e}")
                await update.message.reply_text("Failed to add file.", reply_markup=kbBack(f"foldermenu_{folderId}"))
        return