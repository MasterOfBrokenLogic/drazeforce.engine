import asyncio
import logging
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, fmtDt, fmtSize, deleteAll, validateMinutes
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  ADD MEDIA
# ─────────────────────────────────────────────

async def addMediaCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("addmedia_", ""))
    folder   = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
    if not folder:
        await safeEdit(query, "Folder not found.", markup=kbHome())
        return
    context.user_data["add_media_mode"]      = folder[0]
    context.user_data["add_media_folder_id"] = folderId
    context.user_data["file_count"]          = 0
    await safeEdit(
        query,
        f"<b>Add Files</b>  |  <code>{folder[0]}</code>\n\n"
        "Send any files, photos, videos, or text messages.\n\n"
        "Type <code>END</code> when you have finished uploading.",
        markup=kbBack(f"foldermenu_{folderId}"),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  DELETE MEDIA (selection UI)
# ─────────────────────────────────────────────

async def deleteMediaCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("deletemedia_", ""))
    try:
        files  = cursor.execute(
            "SELECT id, file_type, text_content, uploaded_at FROM files "
            "WHERE folder_id=? ORDER BY uploaded_at DESC",
            (folderId,)
        ).fetchall()
        folder = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"deleteMedia: {e}")
        await safeEdit(query, "Database error.", markup=kbHome())
        return

    if not files:
        await safeEdit(
            query,
            "<b>No Files</b>\n\nThis folder does not contain any files to delete.",
            markup=kbBack(f"foldermenu_{folderId}"),
            parse_mode="HTML",
        )
        return

    context.user_data["delete_media_folder_id"]  = folderId
    context.user_data["delete_media_selection"]  = []
    buttons = _buildFileDeleteButtons(files, [])
    buttons.append([
        InlineKeyboardButton("Delete Selected", callback_data=f"confirmdelete_{folderId}"),
        InlineKeyboardButton("Delete All",      callback_data=f"deleteall_{folderId}"),
    ])
    buttons.append([InlineKeyboardButton("Back", callback_data=f"foldermenu_{folderId}")])
    await safeEdit(
        query,
        f"<b>Delete Files</b>  |  <code>{folder[0]}</code>\n\n"
        "Tap a file to select it, then press <b>Delete Selected</b>.\n"
        f"Total: {len(files)} file(s)",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


def _buildFileDeleteButtons(files, selected):
    buttons = []
    for fid, fileType, textContent, uploadedAt in files:
        if fileType == "text":
            preview = (textContent[:30] + "...") if len(textContent) > 30 else textContent
            label   = preview
        else:
            label = fileType.upper()
        label += f"  |  {fmtDt(uploadedAt)}"
        if fid in selected:
            label = "[x]  " + label
        buttons.append([InlineKeyboardButton(label, callback_data=f"togglefile_{fid}")])
    return buttons


async def toggleFileCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    fileId = int(query.data.replace("togglefile_", ""))
    sel    = context.user_data.setdefault("delete_media_selection", [])

    if fileId in sel:
        sel.remove(fileId)
        await query.answer("Deselected")
    else:
        sel.append(fileId)
        await query.answer("Selected")

    folderId = context.user_data.get("delete_media_folder_id")
    try:
        files  = cursor.execute(
            "SELECT id, file_type, text_content, uploaded_at FROM files "
            "WHERE folder_id=? ORDER BY uploaded_at DESC",
            (folderId,)
        ).fetchall()
        folder = cursor.execute("SELECT name FROM folders WHERE id=?", (folderId,)).fetchone()
    except sqlite3.Error as e:
        logging.error(f"toggleFile: {e}")
        return

    buttons = _buildFileDeleteButtons(files, sel)
    buttons.append([
        InlineKeyboardButton(f"Delete Selected ({len(sel)})", callback_data=f"confirmdelete_{folderId}"),
        InlineKeyboardButton("Delete All",                    callback_data=f"deleteall_{folderId}"),
    ])
    buttons.append([InlineKeyboardButton("Back", callback_data=f"foldermenu_{folderId}")])
    await safeEdit(
        query,
        f"<b>Delete Files</b>  |  <code>{folder[0]}</code>\n\n"
        f"Selected: {len(sel)} / {len(files)}",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def confirmDeleteCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("confirmdelete_", ""))
    selected = context.user_data.get("delete_media_selection", [])
    if not selected:
        await query.answer("No files selected.", show_alert=True)
        return
    try:
        placeholders = ",".join("?" * len(selected))
        cursor.execute(f"DELETE FROM files WHERE id IN ({placeholders})", selected)
        conn.commit()
        context.user_data.clear()
        await safeEdit(
            query,
            f"<b>Files Deleted</b>\n\n{len(selected)} file(s) have been removed.",
            markup=kbBack(f"foldermenu_{folderId}"),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"confirmDelete: {e}")
        await safeEdit(query, "Failed to delete files.", markup=kbBack(f"foldermenu_{folderId}"))


async def deleteAllCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("deleteall_", ""))
    await safeEdit(
        query,
        "<b>Delete All Files</b>\n\n"
        "This will permanently remove every file in this folder.\n"
        "This cannot be undone. Are you sure?",
        markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Confirm", callback_data=f"confirmdeleteall_{folderId}"),
                InlineKeyboardButton("Cancel",  callback_data=f"deletemedia_{folderId}"),
            ]
        ]),
        parse_mode="HTML",
    )


async def confirmDeleteAllCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("confirmdeleteall_", ""))
    try:
        cursor.execute("DELETE FROM files WHERE folder_id=?", (folderId,))
        conn.commit()
        context.user_data.clear()
        await safeEdit(
            query,
            "<b>All Files Deleted</b>\n\nThe folder is now empty.",
            markup=kbBack(f"foldermenu_{folderId}"),
            parse_mode="HTML",
        )
    except sqlite3.Error as e:
        logging.error(f"confirmDeleteAll: {e}")
        await safeEdit(query, "Failed to delete files.", markup=kbBack(f"foldermenu_{folderId}"))


# ─────────────────────────────────────────────
#  PREVIEW
# ─────────────────────────────────────────────

async def previewFilesCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    folderId = int(query.data.replace("preview_", ""))
    context.user_data["preview_folder_id"]    = folderId
    context.user_data["awaiting_preview_time"] = True
    await safeEdit(
        query,
        "<b>Preview Duration</b>\n\n"
        "How many minutes should the preview remain visible?\n\n"
        "Enter a number between 1 and 10080:",
        markup=kbBack(f"foldermenu_{folderId}"),
        parse_mode="HTML",
    )