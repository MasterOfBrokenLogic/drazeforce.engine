import logging
from datetime import datetime

from telegram import Update  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import cursor, START_TIME, BOT_VERSION, BOT_CODENAME
from helpers import safeEdit, fmtSize, fmtDt, fmtUptime
from keyboards import kbHome


# ─────────────────────────────────────────────
#  ANALYTICS
# ─────────────────────────────────────────────

async def statsCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        cursor.execute("SELECT COUNT(*) FROM folders")
        folderCount = cursor.fetchone()
        folderCount = folderCount[0] if folderCount else None
        cursor.execute("SELECT COUNT(*) FROM files")
        fileCount = cursor.fetchone()
        fileCount = fileCount[0] if fileCount else None
        cursor.execute("SELECT SUM(file_size) FROM files")
        totalSize = cursor.fetchone()
        totalSize = (totalSize[0] if totalSize else None) or 0
        activeLinks  = cursor.execute(
            "SELECT COUNT(*) FROM links WHERE revoked=0 AND expiry > NOW()"
        )
        activeLinks = cursor.fetchone()
        activeLinks = activeLinks[0] if activeLinks else None
        expiredLinks = cursor.execute(
            "SELECT COUNT(*) FROM links WHERE revoked=0 AND expiry <= NOW()"
        )
        expiredLinks = cursor.fetchone()
        expiredLinks = expiredLinks[0] if expiredLinks else None
        cursor.execute("SELECT COUNT(*) FROM links WHERE revoked=1")
        revokedLinks = cursor.fetchone()
        revokedLinks = revokedLinks[0] if revokedLinks else None
        cursor.execute("SELECT COUNT(*) FROM logs")
        totalViews = cursor.fetchone()
        totalViews = totalViews[0] if totalViews else None
        views24h     = cursor.execute(
            "SELECT COUNT(*) FROM logs WHERE accessed_at > NOW() - INTERVAL '1 day'"
        )
        views24h = cursor.fetchone()
        views24h = views24h[0] if views24h else None
        topFolder    = cursor.execute("""
            SELECT f.name, COUNT(l.id)
            FROM folders f LEFT JOIN logs l ON f.id = l.folder_id
            GROUP BY f.id ORDER BY COUNT(l.id) DESC LIMIT 1
        """)
        topFolder = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM subscribers")
        totalSubs = cursor.fetchone()
        totalSubs = totalSubs[0] if totalSubs else None
        cursor.execute("SELECT COUNT(*) FROM banned_users")
        bannedCount = cursor.fetchone()
        bannedCount = bannedCount[0] if bannedCount else None
        cursor.execute("SELECT COUNT(*) FROM broadcasts")
        bcCount = cursor.fetchone()
        bcCount = bcCount[0] if bcCount else None
        cursor.execute("SELECT COUNT(*) FROM admins")
        adminCount = cursor.fetchone()
        adminCount = adminCount[0] if adminCount else None
    except Exception as e:
        logging.error(f"stats: {e}")
        await safeEdit(query, "Failed to load analytics.", markup=kbHome())
        return

    top_line = ""
    if topFolder and topFolder[1] > 0:
        top_line = (
            f"\n\n<b>Most Viewed</b>\n"
            f"<code>{topFolder[0]}  |  {topFolder[1]} views</code>"
        )

    await safeEdit(
        query,
        "<b>Analytics</b>\n\n"
        "<b>Content</b>\n"
        f"<code>Folders     :  {folderCount}</code>\n"
        f"<code>Files       :  {fileCount}</code>\n"
        f"<code>Storage     :  {fmtSize(totalSize)}</code>\n\n"
        "<b>Links</b>\n"
        f"<code>Active      :  {activeLinks}</code>\n"
        f"<code>Expired     :  {expiredLinks}</code>\n"
        f"<code>Revoked     :  {revokedLinks}</code>\n\n"
        "<b>Access</b>\n"
        f"<code>Total views :  {totalViews}</code>\n"
        f"<code>Last 24h    :  {views24h}</code>\n\n"
        "<b>Users</b>\n"
        f"<code>Subscribers :  {totalSubs}</code>\n"
        f"<code>Banned      :  {bannedCount}</code>\n"
        f"<code>Admins      :  {adminCount}</code>\n\n"
        "<b>Broadcasts</b>\n"
        f"<code>Total sent  :  {bcCount}</code>"
        f"{top_line}",
        markup=kbHome(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  ACTIVITY LOG
# ─────────────────────────────────────────────

async def activityCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        rows = cursor.execute("""
            SELECT l.username, l.user_id, f.name, l.accessed_at
            FROM logs l JOIN folders f ON l.folder_id = f.id
            ORDER BY l.accessed_at DESC LIMIT 15
        """)
        rows = cursor.fetchall()
    except Exception as e:
        logging.error(f"activity: {e}")
        await safeEdit(query, "Failed to load activity.", markup=kbHome())
        return

    if not rows:
        await safeEdit(
            query,
            "<b>Activity Log</b>\n\nNo activity has been recorded yet.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return

    lines = ["<b>Recent Activity</b>  |  Last 15 entries\n"]
    for username, userId, folderName, accessedAt in rows:
        lines.append(
            f"\n<code>{fmtDt(accessedAt)}</code>\n"
            f"User    :  {username or userId}\n"
            f"Folder  :  {folderName}"
        )

    await safeEdit(query, "\n".join(lines), markup=kbHome(), parse_mode="HTML")


# ─────────────────────────────────────────────
#  BOT STATUS
# ─────────────────────────────────────────────

async def botStatusCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uptime  = fmtUptime(START_TIME)
    started = fmtDt(START_TIME.isoformat())

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

    await safeEdit(
        query,
        "<b>Bot Status</b>\n\n"
        f"<code>Name      :  Drazeforce</code>\n"
        f"<code>Version   :  {BOT_VERSION}</code>\n"
        f"<code>Creator   :  @drazeforce</code>\n"
        f"<code>Uptime    :  {uptime}</code>\n"
        f"<code>Started   :  {started}</code>\n\n"
        "<b>Database</b>\n"
        f"<code>Folders   :  {db_folders}</code>\n"
        f"<code>Files     :  {db_files}</code>\n"
        f"<code>Users     :  {db_subs}</code>\n\n"
        "<b>System</b>\n"
        "<code>Status    :  Online</code>\n"
        "<code>Polling   :  Active</code>",
        markup=kbHome(),
        parse_mode="HTML",
    )
