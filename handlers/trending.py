import logging
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, isSuperAdmin, fmtDt
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  TRENDING — Admin Management
# ─────────────────────────────────────────────

async def trendingMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        await query.answer("Super admins only.", show_alert=True)
        return

    try:
        items = cursor.execute("""
            SELECT t.id, f.name, t.label, t.expires_at
            FROM trending t JOIN folders f ON t.folder_id = f.id
            WHERE t.expires_at IS NULL OR datetime(t.expires_at) > datetime('now')
            ORDER BY t.sort_order ASC, t.added_at DESC
        """).fetchall()
    except sqlite3.Error as e:
        logging.error(f"trendingMenu: {e}")
        await safeEdit(query, "Failed to load trending.", markup=kbHome())
        return

    lines = ["<b>Trending Manager</b>\n"]
    for i, (tid, fname, label, expires) in enumerate(items, 1):
        exp_str = fmtDt(expires) if expires else "Never"
        lines.append(f"\n<code>{i}.  {label or fname}  |  Expires: {exp_str}</code>")

    if not items:
        lines.append("\n<i>No trending items set.</i>")

    await safeEdit(
        query,
        "\n".join(lines),
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Add to Trending",   callback_data="trending_add")],
            [InlineKeyboardButton("Remove Item",       callback_data="trending_remove")],
            [InlineKeyboardButton("Auto Mode (Top 5)", callback_data="trending_auto")],
            [InlineKeyboardButton("Clear All",         callback_data="trending_clear")],
            [InlineKeyboardButton("Main Menu",         callback_data="back_main")],
        ]),
        parse_mode="HTML",
    )


async def trendingAddCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        folders = cursor.execute(
            "SELECT id, name FROM folders WHERE is_secret=0 ORDER BY pinned DESC, created_at DESC"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"trendingAdd folders: {e}")
        await safeEdit(query, "Failed to load folders.", markup=kbBack("trending_menu"))
        return

    if not folders:
        await safeEdit(
            query,
            "<b>No Folders</b>\n\nCreate a folder first.",
            markup=kbBack("trending_menu"),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(name, callback_data=f"trending_pick_{fid}")]
        for fid, name in folders
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="trending_menu")])

    await safeEdit(
        query,
        "<b>Add to Trending</b>\n\nSelect a folder to feature:",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def trendingPickCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("trending_pick_", ""))
    context.user_data["trending_folder_id"] = folderId
    context.user_data["awaiting_trending_label"] = True
    await safeEdit(
        query,
        "<b>Trending Label</b>\n\n"
        "Enter a short label for this trending item.\n"
        "This is what users will see in the trending list.\n\n"
        "Type <code>SKIP</code> to use the folder name.",
        markup=kbBack("trending_add"),
        parse_mode="HTML",
    )


async def trendingRemoveCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        items = cursor.execute("""
            SELECT t.id, f.name, t.label
            FROM trending t JOIN folders f ON t.folder_id = f.id
            ORDER BY t.sort_order ASC, t.added_at DESC
        """).fetchall()
    except sqlite3.Error as e:
        logging.error(f"trendingRemove: {e}")
        await safeEdit(query, "Failed to load items.", markup=kbBack("trending_menu"))
        return

    if not items:
        await safeEdit(
            query,
            "<b>Nothing to Remove</b>\n\nTrending list is already empty.",
            markup=kbBack("trending_menu"),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(label or fname, callback_data=f"trending_del_{tid}")]
        for tid, fname, label in items
    ]
    buttons.append([InlineKeyboardButton("Back", callback_data="trending_menu")])

    await safeEdit(
        query,
        "<b>Remove Trending Item</b>\n\nSelect an item to remove:",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def trendingDelCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tid   = int(query.data.replace("trending_del_", ""))
    try:
        cursor.execute("DELETE FROM trending WHERE id=?", (tid,))
        conn.commit()
        await safeEdit(
            query,
            "<b>Removed</b>\n\nItem removed from trending.",
            markup=kbBack("trending_menu"),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"trendingDel: {e}")
        await safeEdit(query, "Failed to remove item.", markup=kbBack("trending_menu"))


async def trendingAutoCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        # Pull top 5 most-accessed folders in last 48h
        top = cursor.execute("""
            SELECT f.id, f.name, COUNT(l.id) as views
            FROM folders f
            JOIN logs l ON f.id = l.folder_id
            WHERE datetime(l.accessed_at) > datetime('now', '-2 days')
            AND f.is_secret = 0
            GROUP BY f.id
            ORDER BY views DESC
            LIMIT 5
        """).fetchall()
    except sqlite3.Error as e:
        logging.error(f"trendingAuto: {e}")
        await safeEdit(query, "Failed to run auto trending.", markup=kbBack("trending_menu"))
        return

    if not top:
        await safeEdit(
            query,
            "<b>Auto Trending</b>\n\nNot enough activity in the last 48 hours to generate trending.",
            markup=kbBack("trending_menu"),
            parse_mode="HTML",
        )
        return

    # Clear current trending and replace
    cursor.execute("DELETE FROM trending")
    expires = (datetime.now() + timedelta(hours=24)).isoformat()
    for i, (fid, fname, views) in enumerate(top):
        cursor.execute("""
            INSERT INTO trending (folder_id, label, added_by, added_at, expires_at, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fid, fname, query.from_user.id, datetime.now().isoformat(), expires, i))
    conn.commit()

    lines = [f"<b>Auto Trending Updated</b>\n\nTop {len(top)} folders from last 48h:\n"]
    for i, (fid, fname, views) in enumerate(top, 1):
        lines.append(f"<code>{i}.  {fname}  |  {views} views</code>")

    await safeEdit(
        query,
        "\n".join(lines),
        markup=kbBack("trending_menu"),
        parse_mode="HTML",
    )


async def trendingClearCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safeEdit(
        query,
        "<b>Clear Trending</b>\n\nRemove all items from the trending list?",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Confirm", callback_data="trending_clear_confirm"),
                InlineKeyboardButton("Cancel",  callback_data="trending_menu"),
            ]
        ]),
        parse_mode="HTML",
    )


async def trendingClearConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        cursor.execute("DELETE FROM trending")
        conn.commit()
        await safeEdit(
            query,
            "<b>Trending Cleared</b>\n\nAll trending items have been removed.",
            markup=kbBack("trending_menu"),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"trendingClearConfirm: {e}")
        await safeEdit(query, "Failed to clear trending.", markup=kbBack("trending_menu"))


# ─────────────────────────────────────────────
#  USER — VIEW TRENDING
# ─────────────────────────────────────────────

async def viewTrendingCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        items = cursor.execute("""
            SELECT t.id, f.id, f.name, t.label, t.expires_at
            FROM trending t JOIN folders f ON t.folder_id = f.id
            WHERE (t.expires_at IS NULL OR datetime(t.expires_at) > datetime('now'))
            AND f.is_secret = 0
            ORDER BY t.sort_order ASC, t.added_at DESC
        """).fetchall()
    except sqlite3.Error as e:
        logging.error(f"viewTrending: {e}")
        await safeEdit(query, "Failed to load trending.", markup=kbBack("user_menu"))
        return

    if not items:
        await safeEdit(
            query,
            "<b>Trending Now</b>\n\nNothing is trending right now.\nCheck back soon.",
            markup=kbBack("user_menu"),
            parse_mode="HTML",
        )
        return

    lines = ["<b>Trending Now</b>\n"]
    for i, (tid, fid, fname, label, expires) in enumerate(items, 1):
        display = label or fname
        lines.append(f"\n<code>{i}.  {display}</code>")

    # Offer access buttons for each trending folder that has an active link
    buttons = []
    for tid, fid, fname, label, expires in items:
        link = cursor.execute("""
            SELECT token FROM links
            WHERE folder_id=? AND revoked=0 AND datetime(expiry) > datetime('now')
            ORDER BY created_at DESC LIMIT 1
        """, (fid,)).fetchone()
        display = label or fname
        if link:
            buttons.append([InlineKeyboardButton(
                f"Access  —  {display}",
                url=f"https://t.me/{context.bot.username}?start={link[0]}"
            )])

    buttons.append([InlineKeyboardButton("Back", callback_data="user_menu")])

    await safeEdit(
        query,
        "\n".join(lines),
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )