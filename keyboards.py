from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore


# ─────────────────────────────────────────────
#  NAVIGATION
# ─────────────────────────────────────────────

def kbMain() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Folders",       callback_data="view_folders"),
            InlineKeyboardButton("New Folder",    callback_data="create_folder"),
        ],
        [
            InlineKeyboardButton("Generate Link", callback_data="generate_link"),
            InlineKeyboardButton("Revoke Link",   callback_data="revoke_link"),
        ],
        [
            InlineKeyboardButton("Broadcast",     callback_data="broadcast"),
            InlineKeyboardButton("Subscribers",   callback_data="subscribers"),
        ],
        [
            InlineKeyboardButton("Inbox",         callback_data="user_messages"),
            InlineKeyboardButton("Analytics",     callback_data="stats"),
        ],
        [
            InlineKeyboardButton("Activity Log",  callback_data="activity"),
            InlineKeyboardButton("Admin Panel",   callback_data="admin_menu"),
        ],
        [
            InlineKeyboardButton("Polls",         callback_data="poll_menu"),
            InlineKeyboardButton("Trending",      callback_data="trending_menu"),
        ],
        [
            InlineKeyboardButton("OTP Access",    callback_data="otp_menu"),
            InlineKeyboardButton("Customize",     callback_data="customize_menu"),
        ],
        [
            InlineKeyboardButton("Bot Settings",  callback_data="settings_menu"),
            InlineKeyboardButton("Bot Status",    callback_data="bot_status"),
        ],
        [
            InlineKeyboardButton("Purge Links",   callback_data="purge_links"),
        ],
    ])


def kbUser() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Trending Now",      callback_data="view_trending")],
        [InlineKeyboardButton("Quote of the Day",  callback_data="get_quote")],
        [InlineKeyboardButton("My Inbox",          callback_data="user_inbox"),
         InlineKeyboardButton("Contact Admin",     callback_data="contact_admin")],
        [InlineKeyboardButton("Help",              callback_data="help_support")],
    ])


def kbBack(cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=cb)]])


def kbHome() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="back_main")]])


def kbCancel(cb: str = "back_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=cb)]])


# ─────────────────────────────────────────────
#  ADMIN PANEL
# ─────────────────────────────────────────────

def kbAdminPanel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Add Admin",    callback_data="add_admin"),
            InlineKeyboardButton("List Admins",  callback_data="list_admins"),
        ],
        [
            InlineKeyboardButton("Remove Admin", callback_data="remove_admin"),
        ],
        [
            InlineKeyboardButton("Ban User",     callback_data="ban_user"),
            InlineKeyboardButton("Banned List",  callback_data="banned_list"),
        ],
        [InlineKeyboardButton("Main Menu",       callback_data="back_main")],
    ])


# ─────────────────────────────────────────────
#  CONFIRM / YES-NO
# ─────────────────────────────────────────────

def kbConfirm(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Confirm", callback_data=yes_cb),
            InlineKeyboardButton("Cancel",  callback_data=no_cb),
        ]
    ])


def kbYesNo(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes", callback_data=yes_cb),
            InlineKeyboardButton("No",  callback_data=no_cb),
        ]
    ])