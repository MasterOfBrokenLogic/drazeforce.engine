import sqlite3
import io
import csv
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import cursor, conn, START_TIME, BOT_VERSION, ADMIN_ID
from helpers import isAdmin, isSuperAdmin, isBanned, fmtSize, fmtDt, fmtUptime
from keyboards import kbHome, kbUser


# ─────────────────────────────────────────────
#  /help
# ─────────────────────────────────────────────

async def cmdHelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    userId = update.effective_user.id
    if isAdmin(userId):
        await update.message.reply_text(
            "<b>Admin Commands</b>\n\n"
            "<code>/start</code>        Open the main control panel\n"
            "<code>/help</code>         Show this message\n"
            "<code>/stats</code>        Full analytics dashboard\n"
            "<code>/search</code>       Search folders by name\n"
            "<code>/quota</code>        Storage usage per folder\n"
            "<code>/purge</code>        Remove expired and revoked links\n"
            "<code>/export</code>       Export subscriber list as CSV\n"
            "<code>/status</code>       Bot health and uptime\n"
            "<code>/pin</code>          Send announcement to all subscribers\n"
            "<code>/note</code>         Add note to a folder  —  /note FolderName text\n"
            "<code>/welcome</code>      Set welcome message  —  /welcome text\n"
            "<code>/linkinfo</code>     Inspect a link  —  /linkinfo TOKEN\n"
            "<code>/block</code>        Interactive ban/unban manager\n"
            "<code>/broadcast</code>    Quick text broadcast\n"
            "<code>/ban</code>          Ban a user  —  /ban user_id reason\n"
            "<code>/unban</code>        Unban a user  —  /unban user_id\n"
            "<code>/myid</code>         Your account details\n"
            "<code>/cancel</code>       Cancel the current operation",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
    else:
        await update.message.reply_text(
            "<b>Commands</b>\n\n"
            "<code>/start</code>    Open the menu\n"
            "<code>/help</code>     Show this message\n"
            "<code>/myid</code>     Your account info\n"
            "<code>/cancel</code>   Cancel current action",
            parse_mode="HTML",
            reply_markup=kbUser(),
        )


# ─────────────────────────────────────────────
#  /stats
# ─────────────────────────────────────────────

async def cmdStats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    try:
        fc        = cursor.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
        fil       = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        totalSize = cursor.execute("SELECT SUM(file_size) FROM files").fetchone()[0] or 0
        sub       = cursor.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
        newSubs   = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE datetime(subscribed_at) > datetime('now', '-1 day')"
        ).fetchone()[0]
        lnk       = cursor.execute(
            "SELECT COUNT(*) FROM links WHERE revoked=0 AND datetime(expiry) > datetime('now')"
        ).fetchone()[0]
        opens     = cursor.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        opens24h  = cursor.execute(
            "SELECT COUNT(*) FROM logs WHERE datetime(accessed_at) > datetime('now', '-1 day')"
        ).fetchone()[0]
        banned    = cursor.execute("SELECT COUNT(*) FROM banned_users").fetchone()[0]
        topToday  = cursor.execute("""
            SELECT f.name, COUNT(l.id) as cnt FROM folders f
            JOIN logs l ON f.id = l.folder_id
            WHERE datetime(l.accessed_at) > datetime('now', '-1 day')
            GROUP BY f.id ORDER BY cnt DESC LIMIT 1
        """).fetchone()
        topAll    = cursor.execute("""
            SELECT f.name, COUNT(l.id) as cnt FROM folders f
            JOIN logs l ON f.id = l.folder_id
            GROUP BY f.id ORDER BY cnt DESC LIMIT 1
        """).fetchone()
        activePolls = cursor.execute("SELECT COUNT(*) FROM polls WHERE status='open'").fetchone()[0]
        trending    = cursor.execute(
            "SELECT COUNT(*) FROM trending WHERE datetime(expires_at) > datetime('now')"
        ).fetchone()[0]
    except sqlite3.Error as e:
        await update.message.reply_text(f"Database error: {e}")
        return

    top_today = f"\n<code>Top today    :  {topToday[0]}  ({topToday[1]} opens)</code>" if topToday else ""
    top_all   = f"\n<code>Top all-time :  {topAll[0]}  ({topAll[1]} opens)</code>"   if topAll   else ""

    await update.message.reply_text(
        "<b>Analytics Dashboard</b>\n\n"
        "<b>Content</b>\n"
        f"<code>Folders      :  {fc}</code>\n"
        f"<code>Files        :  {fil}</code>\n"
        f"<code>Storage      :  {fmtSize(totalSize)}</code>\n\n"
        "<b>Links</b>\n"
        f"<code>Active links :  {lnk}</code>\n\n"
        "<b>Traffic</b>\n"
        f"<code>Total opens  :  {opens}</code>\n"
        f"<code>Last 24h     :  {opens24h}</code>"
        f"{top_today}"
        f"{top_all}\n\n"
        "<b>Users</b>\n"
        f"<code>Subscribers  :  {sub}</code>\n"
        f"<code>New today    :  {newSubs}</code>\n"
        f"<code>Banned       :  {banned}</code>\n\n"
        "<b>Active</b>\n"
        f"<code>Open polls   :  {activePolls}</code>\n"
        f"<code>Trending     :  {trending} items</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /cancel
# ─────────────────────────────────────────────

async def cmdCancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "<b>Cancelled</b>\n\nThe current operation has been stopped.",
        parse_mode="HTML",
        reply_markup=kbHome() if isAdmin(update.effective_user.id) else kbUser(),
    )


# ─────────────────────────────────────────────
#  /search
# ─────────────────────────────────────────────

async def cmdSearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Search Folders</b>\n\nUsage: <code>/search keyword</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    keyword = " ".join(context.args).strip()
    try:
        results = cursor.execute("""
            SELECT f.id, f.name, COUNT(fi.id), f.created_at,
                   (SELECT COUNT(*) FROM links WHERE folder_id=f.id
                    AND revoked=0 AND datetime(expiry) > datetime('now')) as active_links
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            WHERE f.name LIKE ?
            GROUP BY f.id ORDER BY f.created_at DESC
        """, (f"%{keyword}%",)).fetchall()
    except sqlite3.Error:
        await update.message.reply_text("Database error during search.")
        return
    if not results:
        await update.message.reply_text(
            f"<b>No Results</b>\n\nNo folders matched <code>{keyword}</code>.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    lines = [f"<b>Search Results</b>  |  \"{keyword}\"  |  {len(results)} found\n"]
    for fid, name, count, createdAt, activeLinks in results:
        lines.append(
            f"\n<code>{name}</code>\n"
            f"Files  :  {count}  |  Links  :  {activeLinks}  |  Created  :  {fmtDt(createdAt)}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=kbHome())


# ─────────────────────────────────────────────
#  /quota
# ─────────────────────────────────────────────

async def cmdQuota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    try:
        rows  = cursor.execute("""
            SELECT f.name, COUNT(fi.id), COALESCE(SUM(fi.file_size), 0)
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            GROUP BY f.id ORDER BY SUM(fi.file_size) DESC LIMIT 20
        """).fetchall()
        total = cursor.execute("SELECT COALESCE(SUM(file_size), 0) FROM files").fetchone()[0]
    except sqlite3.Error:
        await update.message.reply_text("Failed to load quota data.")
        return
    if not rows:
        await update.message.reply_text("<b>Storage Quota</b>\n\nNo data available.", parse_mode="HTML", reply_markup=kbHome())
        return
    lines = [f"<b>Storage Quota</b>  |  Total: {fmtSize(total)}\n"]
    for name, count, size in rows:
        lines.append(f"\n<code>{name}</code>\nFiles  :  {count}   |   Size  :  {fmtSize(size)}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=kbHome())


# ─────────────────────────────────────────────
#  /purge
# ─────────────────────────────────────────────

async def cmdPurge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    try:
        cursor.execute("DELETE FROM links WHERE datetime(expiry) <= datetime('now') AND revoked=0")
        expired = cursor.rowcount
        cursor.execute("DELETE FROM links WHERE revoked=1")
        revoked = cursor.rowcount
        conn.commit()
    except sqlite3.Error:
        await update.message.reply_text("Failed to purge links.")
        return
    await update.message.reply_text(
        "<b>Purge Complete</b>\n\n"
        f"<code>Expired removed  :  {expired}</code>\n"
        f"<code>Revoked removed  :  {revoked}</code>\n\n"
        "Folders and files are untouched.",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /export
# ─────────────────────────────────────────────

async def cmdExport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    export_type = context.args[0].lower() if context.args else "subscribers"
    if export_type == "subscribers":
        try:
            rows = cursor.execute(
                "SELECT user_id, username, first_name, subscribed_at, last_active, banned FROM subscribers"
            ).fetchall()
        except sqlite3.Error:
            await update.message.reply_text("Failed to export subscriber data.")
            return
        output          = io.StringIO()
        writer          = csv.writer(output)
        writer.writerow(["user_id", "username", "first_name", "subscribed_at", "last_active", "banned"])
        writer.writerows(rows)
        file_bytes      = io.BytesIO(output.getvalue().encode())
        file_bytes.name = f"subscribers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        await update.message.reply_document(
            file_bytes,
            caption=f"<b>Subscriber Export</b>\n\n{len(rows)} records exported.",
            parse_mode="HTML",
        )
    elif export_type == "logs":
        try:
            rows = cursor.execute(
                "SELECT user_id, username, folder_id, accessed_at FROM logs ORDER BY accessed_at DESC LIMIT 1000"
            ).fetchall()
        except sqlite3.Error:
            await update.message.reply_text("Failed to export logs.")
            return
        output          = io.StringIO()
        writer          = csv.writer(output)
        writer.writerow(["user_id", "username", "folder_id", "accessed_at"])
        writer.writerows(rows)
        file_bytes      = io.BytesIO(output.getvalue().encode())
        file_bytes.name = f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        await update.message.reply_document(file_bytes, caption=f"<b>Log Export</b>\n\n{len(rows)} records.", parse_mode="HTML")
    else:
        await update.message.reply_text(
            "<b>Export</b>\n\nUsage:\n<code>/export subscribers</code>\n<code>/export logs</code>",
            parse_mode="HTML",
        )


# ─────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────

async def cmdStatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    uptime = fmtUptime(START_TIME)
    try:
        db_folders = cursor.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
        db_files   = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        db_subs    = cursor.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    except sqlite3.Error:
        db_folders = db_files = db_subs = "?"
    await update.message.reply_text(
        "<b>Bot Status</b>\n\n"
        f"<code>Name     :  Drazeforce</code>\n"
        f"<code>Version  :  {BOT_VERSION}</code>\n"
        f"<code>Creator  :  @drazeforce</code>\n"
        f"<code>Uptime   :  {uptime}</code>\n"
        f"<code>Status   :  Online</code>\n\n"
        "<b>Database</b>\n"
        f"<code>Folders  :  {db_folders}</code>\n"
        f"<code>Files    :  {db_files}</code>\n"
        f"<code>Users    :  {db_subs}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /pin
# ─────────────────────────────────────────────

async def cmdPin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        await update.message.reply_text(
            "<b>Access Denied</b>\n\nOnly the Super Admin can send announcements.",
            parse_mode="HTML",
        )
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Pin Announcement</b>\n\nUsage: <code>/pin message text</code>\n\nSent immediately to all subscribers.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    text    = " ".join(context.args)
    senders = cursor.execute("SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL").fetchall()
    sent = failed = 0
    for (uid,) in senders:
        if isAdmin(uid):
            continue
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"<b>Announcement</b>\n\n{text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"<b>Announcement Sent</b>\n\n<code>Delivered  :  {sent}</code>\n<code>Failed     :  {failed}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /note
# ─────────────────────────────────────────────

async def cmdNote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "<b>Set Folder Note</b>\n\n"
            "Usage: <code>/note FolderName note text here</code>\n"
            "To clear: <code>/note FolderName CLEAR</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    folderName = context.args[0]
    noteText   = " ".join(context.args[1:])
    folder     = cursor.execute("SELECT id, name FROM folders WHERE name=?", (folderName,)).fetchone()
    if not folder:
        folder = cursor.execute(
            "SELECT id, name FROM folders WHERE LOWER(name)=LOWER(?)", (folderName,)
        ).fetchone()
    if not folder:
        await update.message.reply_text(
            f"<b>Folder Not Found</b>\n\n<code>{folderName}</code> does not exist.\n\nUse /search to find the exact name.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    folderId, exactName = folder
    if noteText.upper() == "CLEAR":
        cursor.execute("UPDATE folders SET note=NULL WHERE id=?", (folderId,))
        conn.commit()
        await update.message.reply_text(
            f"<b>Note Cleared</b>\n\n<code>{exactName}</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
    else:
        cursor.execute("UPDATE folders SET note=? WHERE id=?", (noteText, folderId))
        conn.commit()
        await update.message.reply_text(
            f"<b>Note Saved</b>\n\n"
            f"<code>Folder  :  {exactName}</code>\n"
            f"<code>Note    :  {noteText}</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )


# ─────────────────────────────────────────────
#  /welcome
# ─────────────────────────────────────────────

async def cmdWelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        current = cursor.execute("SELECT value FROM bot_settings WHERE key='welcome_message'").fetchone()
        current_text = current[0] if current else "<i>Using default welcome message</i>"
        await update.message.reply_text(
            f"<b>Welcome Message</b>\n\n<b>Current:</b>\n{current_text}\n\n"
            "<b>Usage:</b>\n<code>/welcome new message text</code>\n<code>/welcome RESET</code>  — restore default",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    text = " ".join(context.args)
    if text.upper() == "RESET":
        cursor.execute("DELETE FROM bot_settings WHERE key='welcome_message'")
        conn.commit()
        await update.message.reply_text(
            "<b>Welcome Message Reset</b>\n\nDefault greeting restored.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('welcome_message', ?)", (text,)
        )
        conn.commit()
        await update.message.reply_text(
            f"<b>Welcome Message Updated</b>\n\nPreview:\n\n{text}",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )


# ─────────────────────────────────────────────
#  /linkinfo
# ─────────────────────────────────────────────

async def cmdLinkinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Link Inspector</b>\n\nUsage: <code>/linkinfo TOKEN</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    token = context.args[0].strip()
    try:
        link = cursor.execute("""
            SELECT l.id, l.folder_id, f.name, l.expiry, l.revoked, l.single_use,
                   l.used_by, l.used_at, l.created_at, l.access_count
            FROM links l JOIN folders f ON l.folder_id = f.id
            WHERE l.token=?
        """, (token,)).fetchone()
    except sqlite3.Error as e:
        await update.message.reply_text(f"Database error: {e}")
        return
    if not link:
        await update.message.reply_text(
            "<b>Link Not Found</b>\n\nNo link matches that token.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    lid, folderId, folderName, expiry, revoked, singleUse, usedBy, usedAt, createdAt, accessCount = link
    now = datetime.now()
    if revoked:
        status = "Revoked"
    elif datetime.fromisoformat(expiry) < now:
        status = "Expired"
    else:
        status = "Active"
    if singleUse and usedBy:
        status = "Used (single-use redeemed)"
        usedByRow = cursor.execute(
            "SELECT username, first_name FROM subscribers WHERE user_id=?", (usedBy,)
        ).fetchone()
        usedByLabel = f"@{usedByRow[0]}" if usedByRow and usedByRow[0] else (usedByRow[1] if usedByRow else str(usedBy))
    else:
        usedByLabel = "N/A"
    unique = cursor.execute(
        "SELECT COUNT(DISTINCT user_id) FROM link_access_log WHERE link_id=?", (lid,)
    ).fetchone()[0]
    await update.message.reply_text(
        f"<b>Link Inspector</b>\n\n"
        f"<code>Token      :  {token[:16]}...</code>\n"
        f"<code>Folder     :  {folderName}</code>\n"
        f"<code>Status     :  {status}</code>\n"
        f"<code>Type       :  {'Single-use' if singleUse else 'Multi-use'}</code>\n"
        f"<code>Created    :  {fmtDt(createdAt)}</code>\n"
        f"<code>Expires    :  {fmtDt(expiry)}</code>\n"
        f"<code>Opens      :  {accessCount}</code>\n"
        f"<code>Unique     :  {unique} users</code>\n"
        f"<code>Used by    :  {usedByLabel}</code>\n"
        f"<code>Used at    :  {fmtDt(usedAt) if usedAt else 'N/A'}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /block
# ─────────────────────────────────────────────

async def cmdBlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    try:
        users = cursor.execute("""
            SELECT s.user_id, s.username, s.first_name,
                   CASE WHEN b.user_id IS NOT NULL THEN 1 ELSE 0 END as is_banned
            FROM subscribers s
            LEFT JOIN banned_users b ON s.user_id = b.user_id
            ORDER BY is_banned DESC, s.subscribed_at DESC
            LIMIT 30
        """).fetchall()
    except sqlite3.Error as e:
        await update.message.reply_text(f"Database error: {e}")
        return
    if not users:
        await update.message.reply_text(
            "<b>No Users</b>\n\nNo subscribers found.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    buttons = []
    for uid, username, firstName, isBannedFlag in users:
        label = username or firstName or str(uid)
        if isBannedFlag:
            btn_label = f"[BANNED] UNBAN — {label}"
            cb        = f"quickunban_{uid}"
        else:
            btn_label = f"BAN — {label}"
            cb        = f"quickban_{uid}"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=cb)])
    buttons.append([InlineKeyboardButton("Done", callback_data="back_main")])
    await update.message.reply_text(
        f"<b>User Ban Manager</b>\n\n<code>Showing  :  {len(users)} user(s)</code>\n\nTap a name to toggle their ban status.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def quickBanCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        return
    userId = int(query.data.replace("quickban_", ""))
    if userId == ADMIN_ID or isSuperAdmin(userId):
        await query.answer("Cannot ban a super admin.", show_alert=True)
        return
    row      = cursor.execute("SELECT username, first_name FROM subscribers WHERE user_id=?", (userId,)).fetchone()
    username = (row[0] if row else None)
    name     = username or (row[1] if row else None) or str(userId)
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO banned_users (user_id, username, reason, banned_at, banned_by)
            VALUES (?, ?, 'Banned via /block', ?, ?)
        """, (userId, username, datetime.now().isoformat(), query.from_user.id))
        cursor.execute(
            "UPDATE subscribers SET banned=1, ban_reason='Banned via /block' WHERE user_id=?", (userId,)
        )
        conn.commit()
    except sqlite3.Error as e:
        await query.answer(f"Failed: {e}", show_alert=True)
        return
    try:
        await context.bot.send_message(
            chat_id=userId,
            text="<b>Account Restricted</b>\n\n"
                 "Your access to this service has been restricted by an administrator.\n\n"
                 "If you believe this is a mistake, please contact the administrator directly.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await query.edit_message_reply_markup(
        reply_markup=_rebuildBlockKeyboard(query.message.reply_markup, userId, banned=True)
    )
    await query.answer(f"{name} has been banned.", show_alert=True)


async def quickUnbanCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        return
    userId = int(query.data.replace("quickunban_", ""))
    row  = cursor.execute("SELECT username, first_name FROM subscribers WHERE user_id=?", (userId,)).fetchone()
    name = (row[0] if row else None) or (row[1] if row else None) or str(userId)
    try:
        cursor.execute("DELETE FROM banned_users WHERE user_id=?", (userId,))
        cursor.execute("UPDATE subscribers SET banned=0, ban_reason=NULL WHERE user_id=?", (userId,))
        conn.commit()
    except sqlite3.Error as e:
        await query.answer(f"Failed: {e}", show_alert=True)
        return
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
    await query.edit_message_reply_markup(
        reply_markup=_rebuildBlockKeyboard(query.message.reply_markup, userId, banned=False)
    )
    await query.answer(f"{name} has been unbanned.", show_alert=True)


def _rebuildBlockKeyboard(old_markup, changedUserId: int, banned: bool):
    new_keyboard = []
    for row in old_markup.inline_keyboard:
        new_row = []
        for btn in row:
            cb = btn.callback_data or ""
            uid_str = cb.replace("quickban_", "").replace("quickunban_", "")
            try:
                uid = int(uid_str)
            except ValueError:
                new_row.append(btn)
                continue
            if uid == changedUserId:
                parts = btn.text.split(" — ", 1)
                label = parts[1] if len(parts) > 1 else str(uid)
                if banned:
                    new_row.append(InlineKeyboardButton(f"[BANNED] UNBAN — {label}", callback_data=f"quickunban_{uid}"))
                else:
                    new_row.append(InlineKeyboardButton(f"BAN — {label}", callback_data=f"quickban_{uid}"))
            else:
                new_row.append(btn)
        new_keyboard.append(new_row)
    return InlineKeyboardMarkup(new_keyboard)


# ─────────────────────────────────────────────
#  /broadcast (quick text)
# ─────────────────────────────────────────────

async def cmdBroadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Quick Broadcast</b>\n\nUsage: <code>/broadcast message text here</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return
    text    = " ".join(context.args)
    targets = cursor.execute("SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL").fetchall()
    sent = failed = 0
    for (uid,) in targets:
        if isAdmin(uid):
            continue
        try:
            await context.bot.send_message(uid, f"<b>Broadcast</b>\n\n{text}", parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"<b>Broadcast Complete</b>\n\n<code>Sent    :  {sent}</code>\n<code>Failed  :  {failed}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /ban
# ─────────────────────────────────────────────

async def cmdBan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Ban User</b>\n\nUsage: <code>/ban user_id reason</code>",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(context.args[0])
        reason    = " ".join(context.args[1:]) if len(context.args) > 1 else None
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be a number.")
        return

    if target_id == ADMIN_ID or isSuperAdmin(target_id):
        await update.message.reply_text("You cannot ban a super admin.", parse_mode="HTML")
        return

    try:
        row      = cursor.execute("SELECT username FROM subscribers WHERE user_id=?", (target_id,)).fetchone()
        username = row[0] if row else None
        cursor.execute("""
            INSERT OR REPLACE INTO banned_users (user_id, username, reason, banned_at, banned_by)
            VALUES (?, ?, ?, ?, ?)
        """, (target_id, username, reason, datetime.now().isoformat(), update.effective_user.id))
        cursor.execute(
            "UPDATE subscribers SET banned=1, ban_reason=? WHERE user_id=?",
            (reason, target_id)
        )
        conn.commit()
        await update.message.reply_text(
            f"<b>User Banned</b>\n\n"
            f"<code>User ID  :  {target_id}</code>\n"
            f"<code>Reason   :  {reason or 'Not specified'}</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        try:
            reason_text = f"\n<code>Reason  :  {reason}</code>" if reason else ""
            await context.bot.send_message(
                chat_id=target_id,
                text=f"<b>Account Restricted</b>\n\n"
                     f"Your access to this service has been restricted by an administrator.{reason_text}\n\n"
                     "If you believe this is a mistake, please contact the administrator directly.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except sqlite3.Error as e:
        await update.message.reply_text(f"Failed to ban user. Error: {e}")


# ─────────────────────────────────────────────
#  /unban
# ─────────────────────────────────────────────

async def cmdUnban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Unban User</b>\n\nUsage: <code>/unban user_id</code>",
            parse_mode="HTML",
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be a number.")
        return
    cursor.execute("DELETE FROM banned_users WHERE user_id=?", (target_id,))
    cursor.execute("UPDATE subscribers SET banned=0, ban_reason=NULL WHERE user_id=?", (target_id,))
    conn.commit()
    await update.message.reply_text(
        f"<b>User Unbanned</b>\n\n<code>{target_id}</code> removed from ban list.",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="<b>Access Restored</b>\n\n"
                 "Your access to this service has been reinstated by an administrator.\n\n"
                 "You can now use the bot normally again.",
            parse_mode="HTML",
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
#  /myid
# ─────────────────────────────────────────────

async def cmdMyId(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    userId = user.id
    sub              = cursor.execute("SELECT subscribed_at, last_active FROM subscribers WHERE user_id=?", (userId,)).fetchone()
    banned           = cursor.execute("SELECT reason FROM banned_users WHERE user_id=?", (userId,)).fetchone()
    folders_accessed = cursor.execute("SELECT COUNT(*) FROM logs WHERE user_id=?", (userId,)).fetchone()[0]
    admin_row        = cursor.execute("SELECT is_super_admin, added_at FROM admins WHERE user_id=?", (userId,)).fetchone()
    lines = [
        "<b>Your Account</b>\n",
        f"<code>User ID     :  {userId}</code>",
        f"<code>Name        :  {user.first_name or 'N/A'}</code>",
        f"<code>Username    :  {'@' + user.username if user.username else 'N/A'}</code>",
    ]
    if sub:
        lines.append(f"<code>Joined      :  {fmtDt(sub[0])}</code>")
        lines.append(f"<code>Last active :  {fmtDt(sub[1])}</code>")
    lines.append(f"<code>Folders opened  :  {folders_accessed}</code>")
    if admin_row:
        role = "Super Admin" if admin_row[0] else "Admin"
        lines.append(f"<code>Role        :  {role}</code>")
        lines.append(f"<code>Admin since :  {fmtDt(admin_row[1])}</code>")
    if banned:
        lines.append(f"\n<code>Status  :  BANNED</code>")
        lines.append(f"<code>Reason  :  {banned[0] or 'Not specified'}</code>")
    else:
        lines.append(f"<code>Status  :  Active</code>")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kbHome() if isAdmin(userId) else kbUser(),
    )