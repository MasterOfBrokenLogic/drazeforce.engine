import sqlite3
import io
import csv
from datetime import datetime

from telegram import Update  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import cursor, conn, START_TIME, BOT_VERSION, BOT_CODENAME
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
            "<code>/start</code>   Open the main control panel\n"
            "<code>/help</code>    Show this message\n"
            "<code>/stats</code>   Quick analytics summary\n"
            "<code>/search</code>  Search folders by name\n"
            "<code>/quota</code>   Storage usage per folder\n"
            "<code>/purge</code>   Remove expired and revoked links\n"
            "<code>/export</code>  Export subscriber list as CSV\n"
            "<code>/status</code>  Bot health and uptime\n"
            "<code>/pin</code>     Pin an announcement to all users\n"
            "<code>/cancel</code>  Cancel the current operation",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
    else:
        await update.message.reply_text(
            "<b>Commands</b>\n\n"
            "<code>/start</code>   Open the menu\n"
            "<code>/help</code>    Show this message\n"
            "<code>/cancel</code>  Cancel current action",
            parse_mode="HTML",
            reply_markup=kbUser(),
        )


# ─────────────────────────────────────────────
#  /stats
# ─────────────────────────────────────────────

async def cmdStats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    fc  = cursor.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
    fil = cursor.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    sub = cursor.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]
    lnk = cursor.execute(
        "SELECT COUNT(*) FROM links WHERE revoked=0 AND datetime(expiry) > datetime('now')"
    ).fetchone()[0]
    await update.message.reply_text(
        "<b>Quick Stats</b>\n\n"
        f"<code>Folders      :  {fc}</code>\n"
        f"<code>Files        :  {fil}</code>\n"
        f"<code>Active links :  {lnk}</code>\n"
        f"<code>Subscribers  :  {sub}</code>",
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
            "<b>Search Folders</b>\n\n"
            "Usage: <code>/search &lt;keyword&gt;</code>\n\n"
            "Example: <code>/search project</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    keyword = " ".join(context.args).strip()
    try:
        results = cursor.execute("""
            SELECT f.id, f.name, COUNT(fi.id), f.created_at
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            WHERE f.name LIKE ?
            GROUP BY f.id
            ORDER BY f.created_at DESC
        """, (f"%{keyword}%",)).fetchall()
    except sqlite3.Error as e:
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
    for fid, name, count, createdAt in results:
        lines.append(
            f"\n<code>{name}</code>\n"
            f"Files    :  {count}   |   Created  :  {fmtDt(createdAt)}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /quota
# ─────────────────────────────────────────────

async def cmdQuota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    try:
        rows = cursor.execute("""
            SELECT f.name, COUNT(fi.id), SUM(fi.file_size)
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            GROUP BY f.id
            ORDER BY SUM(fi.file_size) DESC NULLS LAST
            LIMIT 20
        """).fetchall()
        total = cursor.execute("SELECT SUM(file_size) FROM files").fetchone()[0] or 0
    except sqlite3.Error:
        await update.message.reply_text("Failed to load quota data.")
        return

    if not rows:
        await update.message.reply_text(
            "<b>Storage Quota</b>\n\nNo data available.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    lines = [f"<b>Storage Quota</b>  |  Total: {fmtSize(total)}\n"]
    for name, count, size in rows:
        lines.append(
            f"\n<code>{name}</code>\n"
            f"Files  :  {count}   |   Size  :  {fmtSize(size)}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /purge
# ─────────────────────────────────────────────

async def cmdPurge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    try:
        cursor.execute("DELETE FROM links WHERE datetime(expiry) <= datetime('now')")
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
        f"<code>Revoked removed  :  {revoked}</code>",
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

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["user_id", "username", "first_name", "subscribed_at", "last_active", "banned"])
        writer.writerows(rows)

        file_bytes = io.BytesIO(output.getvalue().encode())
        file_bytes.name = f"subscribers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        await update.message.reply_document(
            file_bytes,
            caption=f"<b>Subscriber Export</b>\n\n{len(rows)} records exported.",
            parse_mode="HTML",
        )

    elif export_type == "logs":
        try:
            rows = cursor.execute("""
                SELECT l.user_id, l.username, f.name, l.accessed_at
                FROM logs l JOIN folders f ON l.folder_id = f.id
                ORDER BY l.accessed_at DESC LIMIT 1000
            """).fetchall()
        except sqlite3.Error:
            await update.message.reply_text("Failed to export activity logs.")
            return

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["user_id", "username", "folder_name", "accessed_at"])
        writer.writerows(rows)

        file_bytes = io.BytesIO(output.getvalue().encode())
        file_bytes.name = f"activity_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        await update.message.reply_document(
            file_bytes,
            caption=f"<b>Activity Log Export</b>\n\n{len(rows)} records (last 1000).",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "<b>Export</b>\n\n"
            "Usage:\n"
            "<code>/export subscribers</code>  — Export all subscribers\n"
            "<code>/export logs</code>          — Export activity log",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )


# ─────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────

async def cmdStatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isAdmin(update.effective_user.id):
        return
    uptime = fmtUptime(START_TIME)
    await update.message.reply_text(
        "<b>Bot Status</b>\n\n"
        f"<code>Name     :  Drazeforce</code>\n"
        f"<code>Version  :  {BOT_VERSION}</code>\n"
        f"<code>Creator  :  @drazeforce</code>\n"
        f"<code>Uptime   :  {uptime}</code>\n"
        f"<code>Status   :  Online</code>\n"
        f"<code>Polling  :  Active</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /pin
# ─────────────────────────────────────────────

async def cmdPin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        await update.message.reply_text(
            "<b>Access Denied</b>\n\nOnly super admins can pin announcements.",
            parse_mode="HTML",
        )
        return

    if not context.args:
        await update.message.reply_text(
            "<b>Pin Announcement</b>\n\n"
            "Usage: <code>/pin &lt;message text&gt;</code>\n\n"
            "The message will be sent to all subscribers immediately.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    text    = " ".join(context.args)
    senders = cursor.execute(
        "SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL"
    ).fetchall()

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
        f"<b>Announcement Sent</b>\n\n"
        f"<code>Delivered  :  {sent}</code>\n"
        f"<code>Failed     :  {failed}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /broadcast (text shortcut)
# ─────────────────────────────────────────────

async def cmdBroadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick text-only broadcast via command."""
    if not isSuperAdmin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "<b>Quick Broadcast</b>\n\n"
            "Usage: <code>/broadcast &lt;message&gt;</code>\n\n"
            "For rich broadcasts with files, use the Broadcast button in the main panel.",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        return

    text    = " ".join(context.args)
    targets = cursor.execute(
        "SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL"
    ).fetchall()

    sent = failed = 0
    for (uid,) in targets:
        if isAdmin(uid):
            continue
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"<b>Broadcast</b>\n\n{text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"<b>Broadcast Complete</b>\n\n"
        f"<code>Sent    :  {sent}</code>\n"
        f"<code>Failed  :  {failed}</code>",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )


# ─────────────────────────────────────────────
#  /ban (command shortcut)
# ─────────────────────────────────────────────

async def cmdBan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Ban User</b>\n\n"
            "Usage: <code>/ban &lt;user_id&gt; [reason]</code>",
            parse_mode="HTML",
        )
        return

    try:
        target_id = int(context.args[0])
        reason    = " ".join(context.args[1:]) if len(context.args) > 1 else None
    except ValueError:
        await update.message.reply_text("Invalid user ID. Must be a number.")
        return

    try:
        row = cursor.execute(
            "SELECT username FROM subscribers WHERE user_id=?", (target_id,)
        ).fetchone()
        username = row[0] if row else None

        cursor.execute("""
            INSERT OR REPLACE INTO banned_users (user_id, username, reason, banned_at, banned_by)
            VALUES (?, ?, ?, ?, ?)
        """, (target_id, username, reason, datetime.now().isoformat(), update.effective_user.id))
        conn.commit()

        await update.message.reply_text(
            f"<b>User Banned</b>\n\n"
            f"<code>User ID  :  {target_id}</code>\n"
            f"<code>Reason   :  {reason or 'Not specified'}</code>",
            parse_mode="HTML",
            reply_markup=kbHome(),
        )
        # Notify the banned user
        try:
            reason_text = f"\n<code>Reason  :  {reason}</code>" if reason else ""
            await context.bot.send_message(
                chat_id=target_id,
                text="<b>Account Restricted</b>\n\n"
                     f"Your access to this service has been restricted by an administrator.{reason_text}\n\n"
                     "If you believe this is an error, contact the administrator directly.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except sqlite3.Error as e:
        await update.message.reply_text(f"Failed to ban user. Error: {e}")


# ─────────────────────────────────────────────
#  /unban (command shortcut)
# ─────────────────────────────────────────────

async def cmdUnban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not isSuperAdmin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text(
            "<b>Unban User</b>\n\n"
            "Usage: <code>/unban &lt;user_id&gt;</code>",
            parse_mode="HTML",
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID.")
        return

    cursor.execute("DELETE FROM banned_users WHERE user_id=?", (target_id,))
    conn.commit()

    await update.message.reply_text(
        f"<b>User Unbanned</b>\n\n"
        f"<code>{target_id}</code> has been removed from the ban list.",
        parse_mode="HTML",
        reply_markup=kbHome(),
    )
    # Notify the unbanned user
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
#  /myid — account details
# ─────────────────────────────────────────────

async def cmdMyId(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    userId = user.id

    sub = cursor.execute(
        "SELECT subscribed_at, last_active FROM subscribers WHERE user_id=?", (userId,)
    ).fetchone()
    banned = cursor.execute(
        "SELECT reason FROM banned_users WHERE user_id=?", (userId,)
    ).fetchone()
    folders_accessed = cursor.execute(
        "SELECT COUNT(*) FROM logs WHERE user_id=?", (userId,)
    ).fetchone()[0]
    admin_row = cursor.execute(
        "SELECT is_super_admin, added_at FROM admins WHERE user_id=?", (userId,)
    ).fetchone()

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