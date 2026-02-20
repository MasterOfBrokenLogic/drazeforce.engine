import logging
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, fmtDt, randomFolderName
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  CREATE FOLDER
# ─────────────────────────────────────────────

async def createFolderCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_folder_name"] = True
    await safeEdit(
        query,
        "<b>Create Folder</b>\n\n"
        "Enter a name for the new folder.\n\n"
        "Type <code>RANDOM</code> to generate a name automatically.\n\n"
        "<i>Allowed characters: letters, numbers, spaces, dashes, underscores</i>",
        markup=kbHome(),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  VIEW FOLDERS
# ─────────────────────────────────────────────

async def viewFoldersCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        folders = cursor.execute("""
            SELECT f.id, f.name, f.created_at, COUNT(fi.id), f.pinned
            FROM folders f
            LEFT JOIN files fi ON f.id = fi.folder_id
            GROUP BY f.id
            ORDER BY f.pinned DESC, f.created_at DESC
        """).fetchall()
    except sqlite3.Error as e:
        logging.error(f"viewFolders: {e}")
        await safeEdit(query, "Failed to load folders.", markup=kbHome())
        return

    if not folders:
        await safeEdit(
            query,
            "<b>No Folders Found</b>\n\n"
            "Create a folder first to start managing content.",
            markup=kbHome(),
            parse_mode="HTML",
        )
        return

    buttons = []
    for fid, name, _, count, pinned in folders:
        pin_label = "[P]  " if pinned else ""
        buttons.append([InlineKeyboardButton(
            f"{pin_label}{name}  |  {count} file(s)",
            callback_data=f"foldermenu_{fid}"
        )])
    buttons.append([InlineKeyboardButton("Main Menu", callback_data="back_main")])

    await safeEdit(
        query,
        f"<b>Folders</b>  |  {len(folders)} total\n\n"
        "Pinned folders appear at the top.\n"
        "Select a folder to manage it.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  FOLDER MENU
# ─────────────────────────────────────────────

async def folderMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("foldermenu_", ""))
    try:
        folder    = cursor.execute(
            "SELECT name, password, pinned, note FROM folders WHERE id=?", (folderId,)
        ).fetchone()
        fileCount = cursor.execute(
            "SELECT COUNT(*) FROM files WHERE folder_id=?", (folderId,)
        ).fetchone()[0]
        totalSize = cursor.execute(
            "SELECT SUM(file_size) FROM files WHERE folder_id=?", (folderId,)
        ).fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"folderMenu: {e}")
        await safeEdit(query, "Failed to load folder.", markup=kbHome())
        return

    if not folder:
        await safeEdit(query, "Folder not found.", markup=kbHome())
        return

    folderName, password, pinned, note = folder
    pwLabel  = "Remove Password" if password else "Set Password"
    pinLabel = "Unpin" if pinned else "Pin"

    from helpers import fmtSize
    buttons = [
        [
            InlineKeyboardButton("Preview",       callback_data=f"preview_{folderId}"),
            InlineKeyboardButton("Add Files",     callback_data=f"addmedia_{folderId}"),
        ],
        [
            InlineKeyboardButton("Delete Files",  callback_data=f"deletemedia_{folderId}"),
            InlineKeyboardButton("Generate Link", callback_data=f"link_{folderId}"),
        ],
        [
            InlineKeyboardButton(pwLabel,         callback_data=f"password_{folderId}"),
            InlineKeyboardButton(pinLabel,        callback_data=f"pin_{folderId}"),
        ],
        [
            InlineKeyboardButton("Add Note",      callback_data=f"note_{folderId}"),
            InlineKeyboardButton("Delete Folder", callback_data=f"delete_select_{folderId}"),
        ],
        [InlineKeyboardButton("Back", callback_data="view_folders")],
    ]

    note_line = f"\n<code>Note     :  {note}</code>" if note else ""

    await safeEdit(
        query,
        f"<b>{folderName}</b>\n\n"
        f"<code>Files    :  {fileCount}</code>\n"
        f"<code>Size     :  {fmtSize(totalSize)}</code>\n"
        f"<code>Password :  {'Set' if password else 'None'}</code>\n"
        f"<code>Pinned   :  {'Yes' if pinned else 'No'}</code>"
        f"{note_line}",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  PIN / UNPIN
# ─────────────────────────────────────────────

async def pinFolderCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("pin_", ""))
    try:
        row    = cursor.execute("SELECT pinned FROM folders WHERE id=?", (folderId,)).fetchone()
        newVal = 0 if row and row[0] else 1
        cursor.execute("UPDATE folders SET pinned=? WHERE id=?", (newVal, folderId))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"pinFolder: {e}")
        await safeEdit(query, "Failed to update pin status.", markup=kbHome())
        return
    await folderMenuCallback(update, context)


# ─────────────────────────────────────────────
#  FOLDER NOTE
# ─────────────────────────────────────────────

async def noteFolderCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("note_", ""))
    context.user_data["note_folder_id"]  = folderId
    context.user_data["awaiting_note"]   = True
    await safeEdit(
        query,
        "<b>Add Note</b>\n\n"
        "Type your internal note for this folder.\n"
        "This note is only visible to admins.\n\n"
        "Type <code>CLEAR</code> to remove the existing note.",
        markup=kbBack(f"foldermenu_{folderId}"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  SEARCH FOLDERS
# ─────────────────────────────────────────────

async def searchFolderCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_search"] = True
    await safeEdit(
        query,
        "<b>Search Folders</b>\n\n"
        "Type the folder name or part of it to search.",
        markup=kbBack("view_folders"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  PASSWORD
# ─────────────────────────────────────────────

async def passwordCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("password_", ""))
    try:
        folder = cursor.execute(
            "SELECT name, password FROM folders WHERE id=?", (folderId,)
        ).fetchone()
    except sqlite3.Error as e:
        logging.error(f"passwordCb: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())
        return

    if not folder:
        await safeEdit(query, "Folder not found.", markup=kbHome())
        return

    folderName, password = folder

    if password:
        await safeEdit(
            query,
            f"<b>Remove Password</b>\n\n"
            f"<code>Folder  :  {folderName}</code>\n\n"
            "Are you sure you want to remove password protection from this folder?",
            markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Confirm", callback_data=f"removepass_{folderId}"),
                    InlineKeyboardButton("Cancel",  callback_data=f"foldermenu_{folderId}"),
                ]
            ]),
            parse_mode="HTML",
        )
    else:
        context.user_data["set_password_folder_id"] = folderId
        context.user_data["awaiting_password"]       = True
        await safeEdit(
            query,
            f"<b>Set Password</b>\n\n"
            f"<code>Folder  :  {folderName}</code>\n\n"
            "Enter a password for this folder:",
            markup=kbBack(f"foldermenu_{folderId}"),
            parse_mode="HTML",
        )


async def removePasswordCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("removepass_", ""))
    try:
        cursor.execute("UPDATE folders SET password=NULL WHERE id=?", (folderId,))
        conn.commit()
        await safeEdit(
            query,
            "<b>Password Removed</b>\n\nThis folder is now accessible without a password.",
            markup=kbBack(f"foldermenu_{folderId}"),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"removePass: {e}")
        await safeEdit(query, "Failed to remove password.", markup=kbBack(f"foldermenu_{folderId}"))


# ─────────────────────────────────────────────
#  DELETE FOLDER
# ─────────────────────────────────────────────

async def deleteSelectCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("delete_select_", ""))
    folder    = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
    fileCount = cursor.execute("SELECT COUNT(*) FROM files WHERE folder_id=?", (folderId,)).fetchone()[0]
    if not folder:
        await safeEdit(query, "Folder not found.", markup=kbHome())
        return
    await safeEdit(
        query,
        f"<b>Delete Folder</b>\n\n"
        f"<code>Name   :  {folder[0]}</code>\n"
        f"<code>Files  :  {fileCount}</code>\n\n"
        "This will permanently delete the folder, all its files, links and logs.\n"
        "This action cannot be undone.",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Delete", callback_data=f"delete_confirm_{folderId}"),
                InlineKeyboardButton("Cancel", callback_data=f"foldermenu_{folderId}"),
            ]
        ]),
        parse_mode="HTML",
    )


async def deleteConfirmCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("delete_confirm_", ""))
    try:
        cursor.execute("DELETE FROM files   WHERE folder_id=?", (folderId,))
        cursor.execute("DELETE FROM links   WHERE folder_id=?", (folderId,))
        cursor.execute("DELETE FROM logs    WHERE folder_id=?", (folderId,))
        cursor.execute("DELETE FROM folders WHERE id=?",        (folderId,))
        conn.commit()
        await safeEdit(
            query,
            "<b>Folder Deleted</b>\n\nThe folder and all associated data have been removed.",
            markup=kbHome(),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"deleteConfirm: {e}")
        await safeEdit(query, "Failed to delete folder.", markup=kbHome())
