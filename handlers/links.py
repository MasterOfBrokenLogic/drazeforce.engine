import logging
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, generateToken, fmtDt
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  GENERATE LINK — Folder picker
# ─────────────────────────────────────────────

async def generateLinkCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        folders = cursor.execute(
            "SELECT id, name FROM folders ORDER BY pinned DESC, created_at DESC"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"generateLink: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())
        return
    if not folders:
        await safeEdit(
            query,
            "<b>No Folders</b>\n\nCreate a folder first before generating a link.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return
    buttons = [[InlineKeyboardButton(name, callback_data=f"link_{fid}")] for fid, name in folders]
    buttons.append([InlineKeyboardButton("Main Menu", callback_data="back_main")])
    await safeEdit(
        query,
        "<b>Generate Link</b>\n\n"
        "Select the folder you want to create an access link for.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  LINK — Forward settings
# ─────────────────────────────────────────────

async def linkCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.split("_")[1])
    folder   = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
    if not folder:
        await safeEdit(query, "Folder not found.", markup=kbHome())
        return
    context.user_data["link_folder_id"] = folderId
    context.user_data["link_step"]      = "single_use"
    await safeEdit(
        query,
        f"<b>Link Settings</b>  |  <code>{folder[0]}</code>\n\n"
        "Should this be a <b>single-use</b> link?\n\n"
        "<code>Single-use</code>  —  Automatically revokes after the first person opens it.\n"
        "<code>Multi-use</code>   —  Anyone with the link can open it until it expires.",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Single-Use", callback_data="link_single_yes"),
                InlineKeyboardButton("Multi-Use",  callback_data="link_single_no"),
            ],
            [InlineKeyboardButton("Back", callback_data="generate_link")],
        ]),
        parse_mode="HTML",
    )


async def linkSingleUseCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["link_single_use"] = 1 if query.data == "link_single_yes" else 0
    context.user_data["link_step"]       = "forwardable"
    folderId = context.user_data.get("link_folder_id")
    await safeEdit(
        query,
        "<b>Forward Permission</b>\n\n"
        "Should recipients be allowed to forward the content they receive?",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Allow", callback_data="forward_yes"),
                InlineKeyboardButton("Block", callback_data="forward_no"),
            ],
            [InlineKeyboardButton("Back", callback_data=f"link_{folderId}")],
        ]),
        parse_mode="HTML",
    )


async def linkSettingsCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if context.user_data.get("link_step") == "forwardable":
        context.user_data["forwardable"] = 1 if query.data == "forward_yes" else 0
        context.user_data["link_step"]   = "auto_delete"
        folderId = context.user_data.get("link_folder_id")
        await safeEdit(
            query,
            "<b>Auto-Delete</b>\n\n"
            "How many minutes after being opened should the content auto-delete?\n\n"
            "Enter a number, or type <code>0</code> to disable auto-delete:",
            markup=kbBack(f"link_{folderId}"),
            parse_mode="HTML",
        )


# ─────────────────────────────────────────────
#  REVOKE LINK
# ─────────────────────────────────────────────

async def revokeLinkCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        folders = cursor.execute("""
            SELECT f.id, f.name, COUNT(l.id)
            FROM folders f
            LEFT JOIN links l ON f.id = l.folder_id AND l.revoked = 0
            GROUP BY f.id
            HAVING COUNT(l.id) > 0
        """).fetchall()
    except sqlite3.Error as e:
        logging.error(f"revokeLink: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())
        return

    if not folders:
        await safeEdit(
            query,
            "<b>No Active Links</b>\n\nThere are no active links to revoke.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return

    buttons = [
        [InlineKeyboardButton(f"{name}  |  {cnt} link(s)", callback_data=f"revoke_select_{fid}")]
        for fid, name, cnt in folders
    ]
    buttons.append([InlineKeyboardButton("Main Menu", callback_data="back_main")])
    await safeEdit(
        query,
        "<b>Revoke Links</b>\n\n"
        "Select a folder to revoke all its active links.\n"
        "Revoked links stop working immediately.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def revokeSelectCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("revoke_select_", ""))
    folder   = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
    if not folder:
        await safeEdit(query, "Folder not found.", markup=kbHome())
        return
    linkCount = cursor.execute(
        "SELECT COUNT(*) FROM links WHERE folder_id=? AND revoked=0", (folderId,)
    ).fetchone()[0]
    await safeEdit(
        query,
        f"<b>Revoke Links</b>\n\n"
        f"<code>Folder   :  {folder[0]}</code>\n"
        f"<code>Links    :  {linkCount} active</code>\n\n"
        "All existing links will stop working immediately.",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Revoke All", callback_data=f"revoke_confirm_{folderId}"),
                InlineKeyboardButton("Cancel",     callback_data="revoke_link"),
            ]
        ]),
        parse_mode="HTML",
    )


async def revokeConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("revoke_confirm_", ""))
    try:
        cursor.execute("UPDATE links SET revoked=1 WHERE folder_id=? AND revoked=0", (folderId,))
        conn.commit()
        await safeEdit(
            query,
            f"<b>Links Revoked</b>\n\n"
            f"{cursor.rowcount} link(s) have been deactivated.",
            markup=kbHome(),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"revokeConfirm: {e}")
        await safeEdit(query, "Failed to revoke links.", markup=kbHome())


# ─────────────────────────────────────────────
#  PURGE EXPIRED LINKS
# ─────────────────────────────────────────────

async def purgeLinksCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        expired = cursor.execute(
            "SELECT COUNT(*) FROM links WHERE datetime(expiry) <= datetime('now') AND revoked=0"
        ).fetchone()[0]
        revoked = cursor.execute(
            "SELECT COUNT(*) FROM links WHERE revoked=1"
        ).fetchone()[0]
    except sqlite3.Error as e:
        logging.error(f"purgeLinks count: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())
        return

    total = expired + revoked
    if total == 0:
        await safeEdit(
            query,
            "<b>Nothing to Purge</b>\n\nNo expired or revoked links found.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return

    await safeEdit(
        query,
        f"<b>Purge Links</b>\n\n"
        f"<code>Expired  :  {expired}</code>\n"
        f"<code>Revoked  :  {revoked}</code>\n"
        f"<code>Total    :  {total}</code>\n\n"
        "<b>Note:</b> Only link records are deleted.\n"
        "Folders and files are NOT affected.",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Purge Now", callback_data="purge_confirm"),
                InlineKeyboardButton("Cancel",    callback_data="back_main"),
            ]
        ]),
        parse_mode="HTML",
    )


async def purgeConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        # Explicitly only delete from links — never touches folders or files
        cursor.execute(
            "DELETE FROM links WHERE datetime(expiry) <= datetime('now') AND revoked=0"
        )
        expired_count = cursor.rowcount
        cursor.execute("DELETE FROM links WHERE revoked=1")
        revoked_count = cursor.rowcount
        conn.commit()
        await safeEdit(
            query,
            f"<b>Purge Complete</b>\n\n"
            f"<code>Expired removed  :  {expired_count}</code>\n"
            f"<code>Revoked removed  :  {revoked_count}</code>\n\n"
            "Folders and files remain untouched.",
            markup=kbHome(),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"purgeConfirm: {e}")
        await safeEdit(query, "Failed to purge links.", markup=kbHome())