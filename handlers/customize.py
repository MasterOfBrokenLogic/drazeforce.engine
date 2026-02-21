import logging
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, isSuperAdmin
from keyboards import kbHome, kbBack


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def _get(key: str, default: str = "Not set") -> str:
    row = cursor.execute("SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set(key: str, value: str):
    cursor.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()


def _del(key: str):
    cursor.execute("DELETE FROM bot_settings WHERE key=?", (key,))
    conn.commit()


def _yn(key: str, default: str = "1") -> str:
    val = _get(key, default)
    return "✅ ON" if val == "1" else "❌ OFF"


def _toggle(key: str, default: str = "1") -> str:
    cur = _get(key, default)
    new = "0" if cur == "1" else "1"
    _set(key, new)
    return new


# ─────────────────────────────────────────────
#  MAIN CUSTOMIZE MENU
# ─────────────────────────────────────────────

async def customizeMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        await query.answer("Super admins only.", show_alert=True)
        return

    await safeEdit(
        query,
        "<b>Customize</b>\n\n"
        "Every setting in one place.\n"
        "Pick a category:",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Messages & Text",    callback_data="cust_messages")],
            [InlineKeyboardButton("🔗 Links & Access",     callback_data="cust_links")],
            [InlineKeyboardButton("📁 Folders",            callback_data="cust_folders")],
            [InlineKeyboardButton("👤 User Experience",    callback_data="cust_ux")],
            [InlineKeyboardButton("📢 Broadcasts",         callback_data="cust_broadcast")],
            [InlineKeyboardButton("🤖 Bot Identity",       callback_data="cust_identity")],
            [InlineKeyboardButton("🔔 Notifications",      callback_data="cust_notifs")],
            [InlineKeyboardButton("Main Menu",             callback_data="back_main")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  MESSAGES & TEXT
# ─────────────────────────────────────────────

async def custMessagesCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    welcome   = _get("welcome_message", "Default")
    banned    = _get("banned_message",  "Default")
    expired   = _get("expired_message", "Default")
    revoked   = _get("revoked_message", "Default")
    empty     = _get("empty_folder_message", "Default")
    granted   = _get("access_granted_text", "Default")

    preview = lambda v: (v[:30] + "...") if len(v) > 30 else v

    await safeEdit(
        query,
        "<b>Messages &amp; Text</b>\n\n"
        f"<code>Welcome     :  {preview(welcome)}</code>\n"
        f"<code>Banned      :  {preview(banned)}</code>\n"
        f"<code>Expired     :  {preview(expired)}</code>\n"
        f"<code>Revoked     :  {preview(revoked)}</code>\n"
        f"<code>Empty folder:  {preview(empty)}</code>\n"
        f"<code>Access text :  {preview(granted)}</code>\n\n"
        "Tap to edit. Type <code>RESET</code> to restore default.",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Welcome Message",     callback_data="cust_set_welcome_message")],
            [InlineKeyboardButton("Banned Message",      callback_data="cust_set_banned_message")],
            [InlineKeyboardButton("Link Expired Text",   callback_data="cust_set_expired_message")],
            [InlineKeyboardButton("Link Revoked Text",   callback_data="cust_set_revoked_message")],
            [InlineKeyboardButton("Empty Folder Text",   callback_data="cust_set_empty_folder_message")],
            [InlineKeyboardButton("Access Granted Text", callback_data="cust_set_access_granted_text")],
            [InlineKeyboardButton("Back",                callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  LINKS & ACCESS
# ─────────────────────────────────────────────

async def custLinksCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    def_expiry   = _get("default_link_expiry_minutes", "1440")
    max_attempts = _get("max_password_attempts", "3")
    spoiler      = _yn("spoiler_on_media", "1")
    forward      = _yn("default_forwardable", "1")
    single_notif = _yn("notify_single_use", "1")

    await safeEdit(
        query,
        "<b>Links &amp; Access</b>\n\n"
        f"<code>Default expiry      :  {def_expiry} min</code>\n"
        f"<code>Max pw attempts     :  {max_attempts}</code>\n"
        f"<code>Spoiler on media    :  {spoiler}</code>\n"
        f"<code>Forwardable default :  {forward}</code>\n"
        f"<code>Notify on single-use:  {single_notif}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Default Expiry (minutes)",    callback_data="cust_set_default_link_expiry_minutes")],
            [InlineKeyboardButton("Max Password Attempts",       callback_data="cust_set_max_password_attempts")],
            [InlineKeyboardButton(f"Spoiler on Media  {spoiler}",   callback_data="cust_toggle_spoiler_on_media")],
            [InlineKeyboardButton(f"Forwardable by Default  {forward}", callback_data="cust_toggle_default_forwardable")],
            [InlineKeyboardButton(f"Single-Use Notification  {single_notif}", callback_data="cust_toggle_notify_single_use")],
            [InlineKeyboardButton("Back",                        callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  FOLDERS
# ─────────────────────────────────────────────

async def custFoldersCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    auto_del   = _get("default_auto_delete_minutes", "Off")
    max_files  = _get("max_files_per_folder", "Unlimited")
    show_count = _yn("show_file_count_in_link", "1")

    await safeEdit(
        query,
        "<b>Folders</b>\n\n"
        f"<code>Default auto-delete  :  {auto_del} min</code>\n"
        f"<code>Max files per folder :  {max_files}</code>\n"
        f"<code>Show file count      :  {show_count}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Default Auto-Delete (min)",  callback_data="cust_set_default_auto_delete_minutes")],
            [InlineKeyboardButton("Max Files Per Folder",       callback_data="cust_set_max_files_per_folder")],
            [InlineKeyboardButton(f"Show File Count  {show_count}", callback_data="cust_toggle_show_file_count_in_link")],
            [InlineKeyboardButton("Back",                       callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  USER EXPERIENCE
# ─────────────────────────────────────────────

async def custUxCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    qotd       = _yn("qotd_enabled", "1")
    qotd_time  = _get("qotd_time", "12:00 UTC")
    trending   = _yn("trending_enabled", "1")
    contact    = _yn("contact_admin_enabled", "1")
    inbox_notif= _yn("user_inbox_notify", "1")

    await safeEdit(
        query,
        "<b>User Experience</b>\n\n"
        f"<code>Quote of the Day    :  {qotd}</code>\n"
        f"<code>QOTD time           :  {qotd_time}</code>\n"
        f"<code>Trending section    :  {trending}</code>\n"
        f"<code>Contact Admin btn   :  {contact}</code>\n"
        f"<code>Inbox notifications :  {inbox_notif}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"Quote of the Day  {qotd}",       callback_data="cust_toggle_qotd_enabled")],
            [InlineKeyboardButton("QOTD Time",                        callback_data="cust_set_qotd_time")],
            [InlineKeyboardButton(f"Trending Section  {trending}",    callback_data="cust_toggle_trending_enabled")],
            [InlineKeyboardButton(f"Contact Admin Button  {contact}", callback_data="cust_toggle_contact_admin_enabled")],
            [InlineKeyboardButton(f"Inbox Notifications  {inbox_notif}", callback_data="cust_toggle_user_inbox_notify")],
            [InlineKeyboardButton("Back",                             callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  BROADCASTS
# ─────────────────────────────────────────────

async def custBroadcastCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    delay      = _get("broadcast_delay_ms", "50")
    fwd        = _yn("broadcast_forwardable_default", "1")
    pin_header = _get("pin_header_text", "📢 Announcement")
    bcast_hdr  = _get("broadcast_header_text", "📣 Broadcast")

    await safeEdit(
        query,
        "<b>Broadcasts</b>\n\n"
        f"<code>Send delay (ms)     :  {delay}</code>\n"
        f"<code>Forwardable default :  {fwd}</code>\n"
        f"<code>Pin header text     :  {pin_header}</code>\n"
        f"<code>Broadcast header    :  {bcast_hdr}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Send Delay (ms)",          callback_data="cust_set_broadcast_delay_ms")],
            [InlineKeyboardButton(f"Forwardable Default  {fwd}", callback_data="cust_toggle_broadcast_forwardable_default")],
            [InlineKeyboardButton("Pin Header Text",          callback_data="cust_set_pin_header_text")],
            [InlineKeyboardButton("Broadcast Header Text",    callback_data="cust_set_broadcast_header_text")],
            [InlineKeyboardButton("Back",                     callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  BOT IDENTITY
# ─────────────────────────────────────────────

async def custIdentityCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    name     = _get("bot_display_name", "Drazeforce")
    tagline  = _get("bot_tagline",      "Not set")
    footer   = _get("bot_footer_text",  "Not set")
    version  = _get("bot_version_label","Not set")

    await safeEdit(
        query,
        "<b>Bot Identity</b>\n\n"
        f"<code>Display name  :  {name}</code>\n"
        f"<code>Tagline       :  {tagline[:35]}</code>\n"
        f"<code>Footer text   :  {footer[:35]}</code>\n"
        f"<code>Version label :  {version}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Display Name",    callback_data="cust_set_bot_display_name")],
            [InlineKeyboardButton("Tagline",         callback_data="cust_set_bot_tagline")],
            [InlineKeyboardButton("Footer Text",     callback_data="cust_set_bot_footer_text")],
            [InlineKeyboardButton("Version Label",   callback_data="cust_set_bot_version_label")],
            [InlineKeyboardButton("Back",            callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  NOTIFICATIONS
# ─────────────────────────────────────────────

async def custNotifsCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    new_sub   = _yn("notify_new_subscriber", "1")
    link_open = _yn("notify_link_opened",    "0")
    msg_recv  = _yn("notify_message_received","1")
    ban_notif = _yn("notify_user_on_ban",    "1")
    daily_rep = _yn("daily_report_enabled",  "0")

    await safeEdit(
        query,
        "<b>Notifications  (sent to SA)</b>\n\n"
        f"<code>New subscriber      :  {new_sub}</code>\n"
        f"<code>Link opened         :  {link_open}</code>\n"
        f"<code>Message received    :  {msg_recv}</code>\n"
        f"<code>Notify user on ban  :  {ban_notif}</code>\n"
        f"<code>Daily report        :  {daily_rep}</code>",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"New Subscriber Alert  {new_sub}",    callback_data="cust_toggle_notify_new_subscriber")],
            [InlineKeyboardButton(f"Link Opened Alert  {link_open}",     callback_data="cust_toggle_notify_link_opened")],
            [InlineKeyboardButton(f"Message Received Alert  {msg_recv}", callback_data="cust_toggle_notify_message_received")],
            [InlineKeyboardButton(f"Notify User on Ban  {ban_notif}",    callback_data="cust_toggle_notify_user_on_ban")],
            [InlineKeyboardButton(f"Daily Report  {daily_rep}",          callback_data="cust_toggle_daily_report_enabled")],
            [InlineKeyboardButton("Back",                                callback_data="customize_menu")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  GENERIC SET (text input)
# ─────────────────────────────────────────────

# Maps setting key → human label for the prompt
_SET_LABELS = {
    "welcome_message":              "Welcome Message",
    "banned_message":               "Banned User Message",
    "expired_message":              "Link Expired Message",
    "revoked_message":              "Link Revoked Message",
    "empty_folder_message":         "Empty Folder Message",
    "access_granted_text":          "Access Granted Header Text",
    "default_link_expiry_minutes":  "Default Link Expiry (minutes, 1–10080)",
    "max_password_attempts":        "Max Password Attempts (1–10)",
    "default_auto_delete_minutes":  "Default Auto-Delete (minutes, or NONE)",
    "max_files_per_folder":         "Max Files Per Folder (number, or NONE)",
    "qotd_time":                    "QOTD Time (e.g. 09:00 UTC)",
    "broadcast_delay_ms":           "Broadcast Send Delay (milliseconds, e.g. 50)",
    "pin_header_text":              "Pin / Announcement Header Text",
    "broadcast_header_text":        "Broadcast Header Text",
    "bot_display_name":             "Bot Display Name",
    "bot_tagline":                  "Bot Tagline",
    "bot_footer_text":              "Bot Footer Text",
    "bot_version_label":            "Version Label",
}

# Which menu to return to after saving
_SET_BACK = {
    "welcome_message":              "cust_messages",
    "banned_message":               "cust_messages",
    "expired_message":              "cust_messages",
    "revoked_message":              "cust_messages",
    "empty_folder_message":         "cust_messages",
    "access_granted_text":          "cust_messages",
    "default_link_expiry_minutes":  "cust_links",
    "max_password_attempts":        "cust_links",
    "default_auto_delete_minutes":  "cust_folders",
    "max_files_per_folder":         "cust_folders",
    "qotd_time":                    "cust_ux",
    "broadcast_delay_ms":           "cust_broadcast",
    "pin_header_text":              "cust_broadcast",
    "broadcast_header_text":        "cust_broadcast",
    "bot_display_name":             "cust_identity",
    "bot_tagline":                  "cust_identity",
    "bot_footer_text":              "cust_identity",
    "bot_version_label":            "cust_identity",
}


async def custSetCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic handler: cust_set_<key>"""
    query  = update.callback_query
    await query.answer()
    key    = query.data.replace("cust_set_", "")
    label  = _SET_LABELS.get(key, key)
    current = _get(key, "Not set")

    context.user_data["cust_set_key"]  = key
    context.user_data["cust_awaiting"] = True

    await safeEdit(
        query,
        f"<b>Set  —  {label}</b>\n\n"
        f"<code>Current  :  {current[:60]}</code>\n\n"
        "Type the new value.\n"
        "Type <code>RESET</code> to restore default.\n"
        "Type <code>CANCEL</code> to go back.",
        markup=kbBack(_SET_BACK.get(key, "customize_menu")),
        parse_mode="HTML",
    )


async def custToggleCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generic handler: cust_toggle_<key>"""
    query = update.callback_query
    await query.answer()
    key   = query.data.replace("cust_toggle_", "")
    new   = _toggle(key)
    label = "ON ✅" if new == "1" else "OFF ❌"
    await query.answer(f"Turned {label}", show_alert=False)

    # Re-render parent menu
    parent_map = {
        "spoiler_on_media":               custLinksCallback,
        "default_forwardable":            custLinksCallback,
        "notify_single_use":              custLinksCallback,
        "show_file_count_in_link":        custFoldersCallback,
        "qotd_enabled":                   custUxCallback,
        "trending_enabled":               custUxCallback,
        "contact_admin_enabled":          custUxCallback,
        "user_inbox_notify":              custUxCallback,
        "broadcast_forwardable_default":  custBroadcastCallback,
        "notify_new_subscriber":          custNotifsCallback,
        "notify_link_opened":             custNotifsCallback,
        "notify_message_received":        custNotifsCallback,
        "notify_user_on_ban":             custNotifsCallback,
        "daily_report_enabled":           custNotifsCallback,
    }
    handler = parent_map.get(key)
    if handler:
        await handler(update, context)


# ─────────────────────────────────────────────
#  SAVE VALUE (called from messages.py)
# ─────────────────────────────────────────────

async def saveCustSetting(update, context, text: str):
    """Save whatever the admin typed for the current cust_set_key."""
    key  = context.user_data.get("cust_set_key")
    back = _SET_BACK.get(key, "customize_menu")
    context.user_data.clear()

    if not key:
        await update.message.reply_text("Session expired.", reply_markup=kbHome())
        return

    if text.upper() == "RESET":
        _del(key)
        await update.message.reply_text(
            f"<b>Reset</b>  —  <code>{_SET_LABELS.get(key, key)}</code> restored to default.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data=back)]
            ]),
        )
    elif text.upper() == "CANCEL":
        await update.message.reply_text(
            "Cancelled.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data=back)]
            ]),
        )
    else:
        _set(key, text)
        await update.message.reply_text(
            f"<b>Saved ✅</b>\n\n"
            f"<code>{_SET_LABELS.get(key, key)}</code>\n"
            f"<code>{text[:80]}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data=back)]
            ]),
        )