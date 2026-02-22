import io
import csv
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import cursor, conn, START_TIME, BOT_VERSION, BOT_CODENAME, ADMIN_ID
from helpers import isAdmin, isSuperAdmin, isBanned, fmtSize, fmtDt, fmtUptime
from keyboards import kbHome, kbUser, kbMain


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
            "<code>/stats</code>        Upgraded analytics dashboard\n"
            "<code>/search</code>       Search folders by name\n"
            "<code>/quota</code>        Storage usage per folder\n"
            "<code>/purge</code>        Remove expired and revoked links\n"
            "<code>/export</code>       Export subscriber list as CSV\n"
            "<code>/status</code>       Bot health and uptime\n"
            "<code>/pin</code>          Send announcement to all subscribers\n"
            "<code>/note</code>         Set folder note  —  /note FolderName text\n"
            "<code>/welcome</code>      Set welcome message  —  /welcome text\n"
            "<code>/linkinfo</code>     Inspect a link  —  /linkinfo TOKEN\n"
            "<code>/block</code>        List users and ban/unban interactively\n"
            "<code>/broadcast</code>    Quick text broadcast\n"
            "<code>/ban</code>          Ban by ID  —  /ban user_id reason\n"
            "<code>/unban</code>        Unban by ID  —  /unban user_id\n"
            "<code>/myid</code>         Your account details\n"
            "<code>/cancel</code>       Cancel the current operation",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
    else:
        await update.message.reply_text(
            "<b>Commands</b>\n\n"
            "<code>/start</code>   Open the menu\n"
            "<code>/help</code>    Show this message\n"
            "<code>/myid</code>    Your account info\n"
            "<code>/cancel</code>  Cancel current action",
            parse_mode="HTML",
            reply_markup=kbUser(),
        )


# ─────────────────────────────────────────────
#  /stats — upgraded
# ─────────────────────────────────────────────

async def cmdStats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    try:
        cursor.execute("SELECT COUNT(*) FROM folders")
        fc = cursor.fetchone()
        fc = fc[0] if fc else None
        cursor.execute("SELECT COUNT(*) FROM files")
        fil = cursor.fetchone()
        fil = fil[0] if fil else None
        cursor.execute("SELECT SUM(file_size) FROM files")
        totalSize = cursor.fetchone()
        totalSize = (totalSize[0] if totalSize else None) or 0
        cursor.execute("SELECT COUNT(*) FROM subscribers")
        sub = cursor.fetchone()
        sub = sub[0] if sub else None
        newSubs   = cursor.execute(
            "SELECT COUNT(*) FROM subscribers WHERE subscribed_at > NOW() - INTERVAL '1 day'"
        )
        newSubs = cursor.fetchone()
        newSubs = newSubs[0] if newSubs else None
        lnk       = cursor.execute(
            "SELECT COUNT(*) FROM links WHERE revoked=0 AND expiry > NOW()"
        )
        lnk = cursor.fetchone()
        lnk = lnk[0] if lnk else None
        cursor.execute("SELECT COUNT(*) FROM logs")
        opens = cursor.fetchone()
        opens = opens[0] if opens else None
        opens24h  = cursor.execute(
            "SELECT COUNT(*) FROM logs WHERE accessed_at > NOW() - INTERVAL '1 day'"
        )
        opens24h = cursor.fetchone()
        opens24h = opens24h[0] if opens24h else None
        cursor.execute("SELECT COUNT(*) FROM banned_users")
        banned = cursor.fetchone()
        banned = banned[0] if banned else None
        topFolder = cursor.execute("""
            SELECT f.name, COUNT(l.id) as cnt
            FROM folders f JOIN logs l ON f.id = l.folder_id
            WHERE l.accessed_at > NOW() - INTERVAL '1 day'
            GROUP BY f.id ORDER BY cnt DESC LIMIT 1
        """)
        topFolder = cursor.fetchone()
        topAllTime = cursor.execute("""
            SELECT f.name, COUNT(l.id) as cnt
            FROM folders f JOIN logs l ON f.id = l.folder_id
            GROUP BY f.id ORDER BY cnt DESC LIMIT 1
        """)
        topAllTime = cursor.fetchone()
        activePolls = cursor.execute(
            "SELECT COUNT(*) FROM polls WHERE status='open'"
        )
        activePolls = cursor.fetchone()
        activePolls = activePolls[0] if activePolls else None
        trending  = cursor.execute(
            "SELECT COUNT(*) FROM trending WHERE expires_at > NOW()"
        )
        trending = cursor.fetchone()
        trending = trending[0] if trending else None
    except Exception as e:
        await update.message.reply_text(f"Database error: {e}")
        return

    top_today  = f"\n<code>Top today    :  {topFolder[0]}  ({topFolder[1]} opens)</code>" if topFolder else ""
    top_all    = f"\n<code>Top all-time :  {topAllTime[0]}  ({topAllTime[1]} opens)</code>" if topAllTime else ""

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
        f"<code>Last 24h     :  {opens24h} opens</code>"
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
            "<b>Search Folders</b>\n\nUsage: <code>/search &lt;keyword&gt;</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    keyword = " ".join(context.args).strip()
    try:
        results = cursor.execute("""
            SELECT f.id, f.name, COUNT(fi.id), f.created_at,
                   (SELECT COUNT(*) FROM links WHERE folder_id=f.id AND revoked=0 AND expiry > NOW()) as active_links
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            WHERE f.name LIKE %s
            GROUP BY f.id ORDER BY f.created_at DESC
        """, (f"%{keyword}%",))
        results = cursor.fetchall()
    except Exception as e:
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
            SELECT f.name, COUNT(fi.id), SUM(fi.file_size)
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            GROUP BY f.id ORDER BY SUM(fi.file_size) DESC NULLS LAST LIMIT 20
        """)
        rows = cursor.fetchall()
        cursor.execute("SELECT SUM(file_size) FROM files")
        total = cursor.fetchone()
        total = (total[0] if total else 0) or 0
    except Exception:
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
        cursor.execute("DELETE FROM links WHERE expiry <= NOW() AND revoked=0")
        expired = cursor.rowcount
        cursor.execute("DELETE FROM links WHERE revoked=1")
        revoked = cursor.rowcount
        conn.commit()
    except Exception:
        await update.message.reply_text("Failed to purge links.")
        return

    await update.message.reply_text(
        "<b>Purge Complete</b>\n\n"
        f"<code>Expired removed  :  {expired}</code>\n"
        f"<code>Revoked removed  :  {revoked}</code>\n\n"
        "Folders and files untouched.",
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
            )
            rows = cursor.fetchall()
        except Exception:
            await update.message.reply_text("Failed to export subscriber data.")
            return

        output     = io.StringIO()
        writer     = csv.writer(output)
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
            )
            rows = cursor.fetchall()
        except Exception:
            await update.message.reply_text("Failed to export logs.")
            return

        output     = io.StringIO()
        writer     = csv.writer(output)
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
        cursor.execute("SELECT COUNT(*) FROM folders")
        db_folders = cursor.fetchone()
        db_folders = db_folders[0] if db_folders else None
        cursor.execute("SELECT COUNT(*) FROM files")
        db_files = cursor.fetchone()
        db_files = db_files[0] if db_files else None
        cursor.execute("SELECT COUNT(*) FROM subscribers")
        db_subs = cursor.fetchone()
        db_subs = db_subs[0] if db_subs else None
    except Exception:
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
#  /pin — announcement to all subscribers
# ─────────────────────────────────────────────

async def cmdPin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        await update.message.reply_text("<b>Access Denied</b>\n\nOnly super admins can send announcements.", parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text(
            "<b>Pin Announcement</b>\n\n"
            "Usage: <code>/pin &lt;message text&gt;</code>\n\n"
            "Sends to all active subscribers immediately.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    text    = " ".join(context.args)
    cursor.execute("SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL")
    senders = cursor.fetchall()

    sent = failed = 0
    for (uid,) in senders:
        if isAdmin(uid):
            continue
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 <b>Announcement</b>\n\n{text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"<b>Announcement Sent</b>\n\n"
        f"<code>Delivered  :  {sent}</code>\n"
        f"<code>Failed     :  {failed}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /note — set folder note quickly
# ─────────────────────────────────────────────

async def cmdNote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "<b>Set Folder Note</b>\n\n"
            "Usage: <code>/note &lt;FolderName&gt; &lt;note text&gt;</code>\n\n"
            "Example: <code>/note MyFolder This folder contains promo content</code>\n\n"
            "To clear a note: <code>/note &lt;FolderName&gt; CLEAR</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    folderName = context.args[0]
    noteText   = " ".join(context.args[1:])

    cursor.execute("SELECT id, name FROM folders WHERE name=%s", (folderName,))
    folder = cursor.fetchone()
    if not folder:
        # Try case-insensitive search
        folder = cursor.execute(
            "SELECT id, name FROM folders WHERE LOWER(name)=LOWER(?)", (folderName,)
        )
        folder = cursor.fetchone()

    if not folder:
        await update.message.reply_text(
            f"<b>Folder Not Found</b>\n\n<code>{folderName}</code> does not exist.\n\n"
            "Use /search to find the exact folder name.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    folderId, exactName = folder

    if noteText.upper() == "CLEAR":
        cursor.execute("UPDATE folders SET note=NULL WHERE id=%s", (folderId,))
        conn.commit()
        await update.message.reply_text(
            f"<b>Note Cleared</b>\n\n<code>{exactName}</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
    else:
        cursor.execute("UPDATE folders SET note=%s WHERE id=%s", (noteText, folderId))
        conn.commit()
        await update.message.reply_text(
            f"<b>Note Saved</b>\n\n"
            f"<code>Folder  :  {exactName}</code>\n"
            f"<code>Note    :  {noteText}</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )


# ─────────────────────────────────────────────
#  /welcome — set welcome message quickly
# ─────────────────────────────────────────────

async def cmdWelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return

    if not context.args:
        current = cursor.execute(
            "SELECT value FROM bot_settings WHERE key='welcome_message'"
        )
        current = cursor.fetchone()
        current_text = current[0] if current else "<i>Using default welcome message</i>"
        await update.message.reply_text(
            "<b>Welcome Message</b>\n\n"
            f"<b>Current:</b>\n{current_text}\n\n"
            "<b>Usage:</b>\n"
            "<code>/welcome &lt;new message text&gt;</code>\n"
            "<code>/welcome RESET</code>  — restore default",
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
            "INSERT INTO bot_settings (key, value) VALUES ('welcome_message', ?)", (text,)
        )
        conn.commit()
        await update.message.reply_text(
            f"<b>Welcome Message Updated</b>\n\nPreview:\n\n{text}",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )


# ─────────────────────────────────────────────
#  /linkinfo TOKEN — inspect a link
# ─────────────────────────────────────────────

async def cmdLinkinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "<b>Link Inspector</b>\n\n"
            "Usage: <code>/linkinfo &lt;TOKEN&gt;</code>\n\n"
            "The TOKEN is the last part of the link:\n"
            "<code>https://t.me/YourBot?start=TOKEN</code>",
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
            WHERE l.token=%s
        """, (token,))
        link = cursor.fetchone()
    except Exception as e:
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

    # Determine status
    from datetime import datetime as dt
    now = dt.now()
    if revoked:
        status = "Revoked"
    elif dt.fromisoformat(expiry) < now:
        status = "Expired"
    else:
        status = "Active"

    if singleUse and usedBy:
        status = "Used (Single-use redeemed)"
        usedByRow = cursor.execute(
            "SELECT username, first_name FROM subscribers WHERE user_id=?", (usedBy,)
        )
        usedByRow = cursor.fetchone()
        usedByLabel = f"@{usedByRow[0]}" if usedByRow and usedByRow[0] else (usedByRow[1] if usedByRow else str(usedBy))
    else:
        usedByLabel = "N/A"

    # Unique users from access log
    unique = cursor.execute(
        "SELECT COUNT(DISTINCT user_id) FROM link_access_log WHERE link_id=?", (lid,)
    )
    unique = cursor.fetchone()
    unique = unique[0] if unique else None

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
#  /block — interactive user ban/unban list
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
        """)
        users = cursor.fetchall()
    except Exception as e:
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
        label  = username or firstName or str(uid)
        if isBannedFlag:
            btn_label = f"✅ UNBAN  —  {label}"
            cb        = f"quickunban_{uid}"
        else:
            btn_label = f"🚫 BAN  —  {label}"
            cb        = f"quickban_{uid}"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=cb)])

    buttons.append([InlineKeyboardButton("Done", callback_data="back_main")])

    await update.message.reply_text(
        f"<b>User Ban Manager</b>\n\n"
        f"<code>Total shown  :  {len(users)}</code>\n\n"
        "Tap to ban or unban instantly.\n"
        "🚫 = active user   ✅ = currently banned",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def quickBanCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        return
    userId = int(query.data.replace("quickban_", ""))

    cursor.execute("SELECT username, first_name FROM subscribers WHERE user_id=%s", (userId,))
    row = cursor.fetchone()
    username = (row[0] if row else None)
    name     = username or (row[1] if row else None) or str(userId)

    try:
        cursor.execute("""
            INSERT INTO banned_users (user_id, username, reason, banned_at, banned_by)
            VALUES (%s, %s, 'Banned via /block', %s, %s)
        """, (userId, username, datetime.now().isoformat(), query.from_user.id))
        conn.commit()
    except Exception as e:
        await query.answer(f"Failed: {e}", show_alert=True)
        return

    # Notify banned user immediately
    try:
        await context.bot.send_message(
            chat_id=userId,
            text="<b>Account Restricted</b>\n\n"
                 "Your access to this service has been restricted by an administrator.\n\n"
                 "If you believe this is an error, contact the administrator directly.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Update the button in place
    await query.edit_message_reply_markup(
        reply_markup=_rebuildBlockKeyboard(query.message.reply_markup, userId, banned=True)
    )
    await query.answer(f"✅ {name} banned and notified.", show_alert=True)


async def quickUnbanCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        return
    userId = int(query.data.replace("quickunban_", ""))

    cursor.execute("SELECT username, first_name FROM subscribers WHERE user_id=%s", (userId,))
    row = cursor.fetchone()
    name = (row[0] if row else None) or (row[1] if row else None) or str(userId)

    try:
        cursor.execute("DELETE FROM banned_users WHERE user_id=%s", (userId,))
        conn.commit()
    except Exception as e:
        await query.answer(f"Failed: {e}", show_alert=True)
        return

    # Notify unbanned user immediately
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
    await query.answer(f"✅ {name} unbanned and notified.", show_alert=True)


def _rebuildBlockKeyboard(old_markup, changedUserId: int, banned: bool):
    """Flip the button label for the user that was just banned/unbanned."""
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
                # Extract name from old label
                parts = btn.text.split("  —  ", 1)
                label = parts[1] if len(parts) > 1 else str(uid)
                if banned:
                    new_row.append(InlineKeyboardButton(f"✅ UNBAN  —  {label}", callback_data=f"quickunban_{uid}"))
                else:
                    new_row.append(InlineKeyboardButton(f"🚫 BAN  —  {label}", callback_data=f"quickban_{uid}"))
            else:
                new_row.append(btn)
        new_keyboard.append(new_row)
    return InlineKeyboardMarkup(new_keyboard)


# ─────────────────────────────────────────────
#  /broadcast (text shortcut)
# ─────────────────────────────────────────────

async def cmdBroadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Quick Broadcast</b>\n\nUsage: <code>/broadcast &lt;message&gt;</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    text    = " ".join(context.args)
    cursor.execute("SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL")
    targets = cursor.fetchall()

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
        await update.message.reply_text("<b>Ban User</b>\n\nUsage: <code>/ban &lt;user_id&gt; [reason]</code>", parse_mode="HTML")
        return

    try:
        target_id = int(context.args[0])
        reason    = " ".join(context.args[1:]) if len(context.args) > 1 else None
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be a number.")
        return

    try:
        cursor.execute("SELECT username FROM subscribers WHERE user_id=%s", (target_id,))
        row = cursor.fetchone()
        username = row[0] if row else None
        cursor.execute("""
            INSERT INTO banned_users (user_id, username, reason, banned_at, banned_by)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username, reason=EXCLUDED.reason, banned_at=EXCLUDED.banned_at, banned_by=EXCLUDED.banned_by
        """, (target_id, username, reason, datetime.now().isoformat(), update.effective_user.id))
        conn.commit()
        await update.message.reply_text(
            f"<b>User Banned</b>\n\n<code>User ID  :  {target_id}</code>\n<code>Reason   :  {reason or 'Not specified'}</code>",
            parse_mode="HTML", reply_markup=kbHome(),
        )
        try:
            reason_text = f"\n<code>Reason  :  {reason}</code>" if reason else ""
            await context.bot.send_message(
                chat_id=target_id,
                text=f"<b>Account Restricted</b>\n\nYour access to this service has been restricted by an administrator.{reason_text}\n\nIf you believe this is an error, contact the administrator directly.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"Failed to ban user. Error: {e}")


# ─────────────────────────────────────────────
#  /unban
# ─────────────────────────────────────────────

async def cmdUnban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("<b>Unban User</b>\n\nUsage: <code>/unban &lt;user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID.")
        return

    cursor.execute("DELETE FROM banned_users WHERE user_id=%s", (target_id,))
    conn.commit()
    await update.message.reply_text(
        f"<b>User Unbanned</b>\n\n<code>{target_id}</code> removed from ban list.",
        parse_mode="HTML", reply_markup=kbHome(),
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="<b>Access Restored</b>\n\nYour access to this service has been reinstated by an administrator.\n\nYou can now use the bot normally again.",
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

    cursor.execute("SELECT subscribed_at, last_active FROM subscribers WHERE user_id=%s", (userId,))
    sub = cursor.fetchone()
    cursor.execute("SELECT reason FROM banned_users WHERE user_id=%s", (userId,))
    banned = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM logs WHERE user_id=%s", (userId,))
    folders_accessed = cursor.fetchone()
    folders_accessed = folders_accessed[0] if folders_accessed else None
    cursor.execute("SELECT is_super_admin, added_at FROM admins WHERE user_id=%s", (userId,))
    admin_row = cursor.fetchone()

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
