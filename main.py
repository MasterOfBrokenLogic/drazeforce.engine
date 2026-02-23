import logging
from datetime import time as dtime

from telegram import Update  # type: ignore
from telegram.error import BadRequest  # type: ignore
from telegram.ext import (  # type: ignore
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
    MessageHandler,
)

from config import TOKEN

from handlers.start import start, backMainCallback, userMenuCallback, cancelDeliveryCallback
from handlers.admin import (
    adminMenuCallback, addAdminCallback, listAdminsCallback, adminInfoCallback,
    removeAdminCallback, removeAdminConfirmCallback,
    banUserCallback, bannedListCallback, banInfoCallback, unbanCallback,
)
from handlers.folders import (
    createFolderCallback, viewFoldersCallback, folderMenuCallback,
    pinFolderCallback, noteFolderCallback,
    passwordCallback, removePasswordCallback,
    deleteSelectCallback, deleteConfirmCallback,
)
from handlers.files import (
    addMediaCallback, deleteMediaCallback, toggleFileCallback,
    confirmDeleteCallback, deleteAllCallback, confirmDeleteAllCallback,
    previewFilesCallback,
)
from handlers.links import (
    generateLinkCallback, linkCallback, linkSingleUseCallback, linkSettingsCallback,
    revokeLinkCallback, revokeSelectCallback, revokeConfirmCallback,
    purgeLinksCallback, purgeConfirmCallback,
)
from handlers.broadcast import (
    broadcastCallback, broadcastPasswordCallback, broadcastExpiryCallback,
    broadcastForwardCallback, broadcastPublishCallback, broadcastCancelCallback,
)
from handlers.inbox import (
    userMessagesCallback, viewMessageCallback, deleteMsgFromChatCallback,
    keepMsgCallback, markAllReadCallback, clearAllMessagesCallback,
    confirmClearMessagesCallback, contactAdminCallback, selectAdminToContactCallback,
    replyToUserCallback, userInboxCallback, viewReplyCallback,
    deleteReplyCallback, userReplyBackCallback,
)
from handlers.analytics import statsCallback, activityCallback, botStatusCallback
from handlers.subscribers import subscribersCallback, subInfoCallback
from handlers.commands import (
    cmdHelp, cmdStats, cmdCancel, cmdSearch, cmdQuota,
    cmdPurge, cmdExport, cmdStatus, cmdPin, cmdBroadcast,
    cmdBan, cmdUnban, cmdMyId,
    cmdNote, cmdWelcome, cmdLinkinfo, cmdBlock,
    quickBanCallback, quickUnbanCallback,
)
from handlers.messages import messageHandler
from handlers.polls import (
    pollMenuCallback, pollCreateCallback, pollListCallback,
    pollViewCallback, pollCloseCallback, pollVoteCallback,
)
from handlers.trending import (
    trendingMenuCallback, trendingAddCallback, trendingPickCallback,
    trendingRemoveCallback, trendingDelCallback, trendingAutoCallback,
    trendingClearCallback, trendingClearConfirmCallback, viewTrendingCallback,
)
from handlers.settings import (
    settingsMenuCallback, settingsWelcomeCallback,
    settingsQuotesCallback, quoteAddCallback, quoteDeleteCallback,
    quoteDelConfirmCallback, qotdSendNowCallback,
    settingsSecretsCallback, secretMakeCallback, secretPickCallback,
    secretUnmarkCallback, secretUnmarkConfirmCallback,
    settingsLinkstatsCallback, linkstatsViewCallback,
    getQuoteCallback,
)
from handlers.otp import (
    otpMenuCallback, otpToggleCallback, otpGenerateCallback, otpSendCallback,
)
from handlers.customize import (
    customizeMenuCallback,
    custMessagesCallback, custLinksCallback, custFoldersCallback,
    custUxCallback, custBroadcastCallback, custIdentityCallback,
    custNotifsCallback, custSetCallback, custToggleCallback,
)
from handlers.jobs import jobQotd, jobClosePols, jobPurgeTrending, jobPurgeLinks


async def errorHandler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, BadRequest):
        if "Message is not modified" in str(context.error):
            return
    logging.error("Unhandled error", exc_info=context.error)


async def helpSupportCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from helpers import safeEdit
    from keyboards import kbBack
    query = update.callback_query
    await query.answer()
    await safeEdit(
        query,
        "<b>Help</b>\n\n"
        "Open a link from the administrator to receive content.\n\n"
        "If you know a secret codeword, type it directly in the chat.\n\n"
        "Tap <b>Trending Now</b> to see featured content.\n\n"
        "Tap <b>Contact Admin</b> to send a message to the team.",
        markup=kbBack("user_menu"),
        parse_mode="HTML",
    )


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      cmdHelp))
    app.add_handler(CommandHandler("stats",     cmdStats))
    app.add_handler(CommandHandler("cancel",    cmdCancel))
    app.add_handler(CommandHandler("search",    cmdSearch))
    app.add_handler(CommandHandler("quota",     cmdQuota))
    app.add_handler(CommandHandler("purge",     cmdPurge))
    app.add_handler(CommandHandler("export",    cmdExport))
    app.add_handler(CommandHandler("status",    cmdStatus))
    app.add_handler(CommandHandler("pin",       cmdPin))
    app.add_handler(CommandHandler("note",      cmdNote))
    app.add_handler(CommandHandler("welcome",   cmdWelcome))
    app.add_handler(CommandHandler("linkinfo",  cmdLinkinfo))
    app.add_handler(CommandHandler("block",     cmdBlock))
    app.add_handler(CommandHandler("broadcast", cmdBroadcast))
    app.add_handler(CommandHandler("ban",       cmdBan))
    app.add_handler(CommandHandler("unban",     cmdUnban))
    app.add_handler(CommandHandler("myid",      cmdMyId))

    # /block inline ban/unban buttons
    app.add_handler(CallbackQueryHandler(quickBanCallback,   pattern="^quickban_\\d+$"))
    app.add_handler(CallbackQueryHandler(quickUnbanCallback, pattern="^quickunban_\\d+$"))

    # Navigation
    app.add_handler(CallbackQueryHandler(backMainCallback,       pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(userMenuCallback,       pattern="^user_menu$"))
    app.add_handler(CallbackQueryHandler(cancelDeliveryCallback, pattern="^cancel_delivery_\\d+$"))

    # User
    app.add_handler(CallbackQueryHandler(helpSupportCallback,          pattern="^help_support$"))
    app.add_handler(CallbackQueryHandler(contactAdminCallback,         pattern="^contact_admin$"))
    app.add_handler(CallbackQueryHandler(selectAdminToContactCallback, pattern="^contact_select_\\d+$"))
    app.add_handler(CallbackQueryHandler(viewTrendingCallback,         pattern="^view_trending$"))

    # Admin panel
    app.add_handler(CallbackQueryHandler(adminMenuCallback,          pattern="^admin_menu$"))
    app.add_handler(CallbackQueryHandler(addAdminCallback,           pattern="^add_admin$"))
    app.add_handler(CallbackQueryHandler(listAdminsCallback,         pattern="^list_admins$"))
    app.add_handler(CallbackQueryHandler(adminInfoCallback,          pattern="^admin_info_\\d+$"))
    app.add_handler(CallbackQueryHandler(removeAdminCallback,        pattern="^remove_admin$"))
    app.add_handler(CallbackQueryHandler(removeAdminConfirmCallback, pattern="^remove_admin_\\d+$"))
    app.add_handler(CallbackQueryHandler(banUserCallback,            pattern="^ban_user$"))
    app.add_handler(CallbackQueryHandler(bannedListCallback,         pattern="^banned_list$"))
    app.add_handler(CallbackQueryHandler(banInfoCallback,            pattern="^ban_info_\\d+$"))
    app.add_handler(CallbackQueryHandler(unbanCallback,              pattern="^unban_\\d+$"))

    # Folders
    app.add_handler(CallbackQueryHandler(createFolderCallback, pattern="^create_folder$"))
    app.add_handler(CallbackQueryHandler(viewFoldersCallback,  pattern="^view_folders$"))
    app.add_handler(CallbackQueryHandler(folderMenuCallback,   pattern="^foldermenu_\\d+$"))
    app.add_handler(CallbackQueryHandler(pinFolderCallback,    pattern="^pin_\\d+$"))
    app.add_handler(CallbackQueryHandler(noteFolderCallback,   pattern="^note_\\d+$"))

    # Password
    app.add_handler(CallbackQueryHandler(passwordCallback,       pattern="^password_\\d+$"))
    app.add_handler(CallbackQueryHandler(removePasswordCallback, pattern="^removepass_\\d+$"))

    # Files
    app.add_handler(CallbackQueryHandler(addMediaCallback,         pattern="^addmedia_\\d+$"))
    app.add_handler(CallbackQueryHandler(deleteMediaCallback,      pattern="^deletemedia_\\d+$"))
    app.add_handler(CallbackQueryHandler(toggleFileCallback,       pattern="^togglefile_\\d+$"))
    app.add_handler(CallbackQueryHandler(confirmDeleteCallback,    pattern="^confirmdelete_\\d+$"))
    app.add_handler(CallbackQueryHandler(deleteAllCallback,        pattern="^deleteall_\\d+$"))
    app.add_handler(CallbackQueryHandler(confirmDeleteAllCallback, pattern="^confirmdeleteall_\\d+$"))
    app.add_handler(CallbackQueryHandler(previewFilesCallback,     pattern="^preview_\\d+$"))

    # Links
    app.add_handler(CallbackQueryHandler(generateLinkCallback,  pattern="^generate_link$"))
    app.add_handler(CallbackQueryHandler(linkCallback,          pattern="^link_\\d+$"))
    app.add_handler(CallbackQueryHandler(linkSingleUseCallback, pattern="^link_single_(yes|no)$"))
    app.add_handler(CallbackQueryHandler(linkSettingsCallback,  pattern="^(forward_yes|forward_no)$"))
    app.add_handler(CallbackQueryHandler(revokeLinkCallback,    pattern="^revoke_link$"))
    app.add_handler(CallbackQueryHandler(revokeSelectCallback,  pattern="^revoke_select_\\d+$"))
    app.add_handler(CallbackQueryHandler(revokeConfirmCallback, pattern="^revoke_confirm_\\d+$"))
    app.add_handler(CallbackQueryHandler(purgeLinksCallback,    pattern="^purge_links$"))
    app.add_handler(CallbackQueryHandler(purgeConfirmCallback,  pattern="^purge_confirm$"))

    # Folder delete
    app.add_handler(CallbackQueryHandler(deleteSelectCallback,  pattern="^delete_select_\\d+$"))
    app.add_handler(CallbackQueryHandler(deleteConfirmCallback, pattern="^delete_confirm_\\d+$"))

    # Analytics
    app.add_handler(CallbackQueryHandler(statsCallback,     pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(activityCallback,  pattern="^activity$"))
    app.add_handler(CallbackQueryHandler(botStatusCallback, pattern="^bot_status$"))

    # Subscribers
    app.add_handler(CallbackQueryHandler(subscribersCallback, pattern="^subscribers$"))
    app.add_handler(CallbackQueryHandler(subInfoCallback,     pattern="^sub_info_\\d+$"))

    # Inbox
    app.add_handler(CallbackQueryHandler(userMessagesCallback,         pattern="^user_messages$"))
    app.add_handler(CallbackQueryHandler(viewMessageCallback,          pattern="^viewmsg_.+$"))
    app.add_handler(CallbackQueryHandler(deleteMsgFromChatCallback,    pattern="^delmsg_.+$"))
    app.add_handler(CallbackQueryHandler(keepMsgCallback,              pattern="^keepmsg_.+$"))
    app.add_handler(CallbackQueryHandler(replyToUserCallback,          pattern="^replyto_.+$"))
    app.add_handler(CallbackQueryHandler(userInboxCallback,            pattern="^user_inbox$"))
    app.add_handler(CallbackQueryHandler(viewReplyCallback,            pattern="^viewreply_.+$"))
    app.add_handler(CallbackQueryHandler(deleteReplyCallback,          pattern="^delreply_.+$"))
    app.add_handler(CallbackQueryHandler(userReplyBackCallback,        pattern="^userreply_.+$"))
    app.add_handler(CallbackQueryHandler(markAllReadCallback,          pattern="^mark_all_read$"))
    app.add_handler(CallbackQueryHandler(clearAllMessagesCallback,     pattern="^clear_all_messages$"))
    app.add_handler(CallbackQueryHandler(confirmClearMessagesCallback, pattern="^confirm_clear_messages$"))

    # Broadcast
    app.add_handler(CallbackQueryHandler(broadcastCallback,         pattern="^broadcast$"))
    app.add_handler(CallbackQueryHandler(broadcastPasswordCallback, pattern="^broadcast_pass_(yes|no)$"))
    app.add_handler(CallbackQueryHandler(broadcastExpiryCallback,   pattern="^broadcast_exp_(yes|no)$"))
    app.add_handler(CallbackQueryHandler(broadcastForwardCallback,  pattern="^broadcast_fwd_(yes|no)$"))
    app.add_handler(CallbackQueryHandler(broadcastPublishCallback,  pattern="^broadcast_publish$"))
    app.add_handler(CallbackQueryHandler(broadcastCancelCallback,   pattern="^broadcast_cancel$"))

    # Polls
    app.add_handler(CallbackQueryHandler(pollMenuCallback,   pattern="^poll_menu$"))
    app.add_handler(CallbackQueryHandler(pollCreateCallback, pattern="^poll_create$"))
    app.add_handler(CallbackQueryHandler(pollListCallback,   pattern="^poll_list_(open|closed)$"))
    app.add_handler(CallbackQueryHandler(pollViewCallback,   pattern="^poll_view_\\d+$"))
    app.add_handler(CallbackQueryHandler(pollCloseCallback,  pattern="^poll_close_\\d+$"))
    app.add_handler(CallbackQueryHandler(pollVoteCallback,   pattern="^vote_\\d+_[ABCD]$"))

    # Trending
    app.add_handler(CallbackQueryHandler(trendingMenuCallback,         pattern="^trending_menu$"))
    app.add_handler(CallbackQueryHandler(trendingAddCallback,          pattern="^trending_add$"))
    app.add_handler(CallbackQueryHandler(trendingPickCallback,         pattern="^trending_pick_\\d+$"))
    app.add_handler(CallbackQueryHandler(trendingRemoveCallback,       pattern="^trending_remove$"))
    app.add_handler(CallbackQueryHandler(trendingDelCallback,          pattern="^trending_del_\\d+$"))
    app.add_handler(CallbackQueryHandler(trendingAutoCallback,         pattern="^trending_auto$"))
    app.add_handler(CallbackQueryHandler(trendingClearCallback,        pattern="^trending_clear$"))
    app.add_handler(CallbackQueryHandler(trendingClearConfirmCallback, pattern="^trending_clear_confirm$"))

    # OTP Access
    app.add_handler(CallbackQueryHandler(otpMenuCallback,     pattern="^otp_menu$"))
    app.add_handler(CallbackQueryHandler(otpToggleCallback,   pattern="^otp_toggle_\\d+$"))
    app.add_handler(CallbackQueryHandler(otpGenerateCallback, pattern="^otp_gen_\\d+_\\d+$"))
    app.add_handler(CallbackQueryHandler(otpSendCallback,     pattern="^otp_send_\\d+_\\d+$"))

    # Customize
    app.add_handler(CallbackQueryHandler(customizeMenuCallback,   pattern="^customize_menu$"))
    app.add_handler(CallbackQueryHandler(custMessagesCallback,    pattern="^cust_messages$"))
    app.add_handler(CallbackQueryHandler(custLinksCallback,       pattern="^cust_links$"))
    app.add_handler(CallbackQueryHandler(custFoldersCallback,     pattern="^cust_folders$"))
    app.add_handler(CallbackQueryHandler(custUxCallback,          pattern="^cust_ux$"))
    app.add_handler(CallbackQueryHandler(custBroadcastCallback,   pattern="^cust_broadcast$"))
    app.add_handler(CallbackQueryHandler(custIdentityCallback,    pattern="^cust_identity$"))
    app.add_handler(CallbackQueryHandler(custNotifsCallback,      pattern="^cust_notifs$"))
    app.add_handler(CallbackQueryHandler(custSetCallback,         pattern="^cust_set_.+$"))
    app.add_handler(CallbackQueryHandler(custToggleCallback,      pattern="^cust_toggle_.+$"))

    # Settings
    app.add_handler(CallbackQueryHandler(settingsMenuCallback,        pattern="^settings_menu$"))
    app.add_handler(CallbackQueryHandler(settingsWelcomeCallback,     pattern="^settings_welcome$"))
    app.add_handler(CallbackQueryHandler(settingsQuotesCallback,      pattern="^settings_quotes$"))
    app.add_handler(CallbackQueryHandler(quoteAddCallback,            pattern="^quote_add$"))
    app.add_handler(CallbackQueryHandler(quoteDeleteCallback,         pattern="^quote_delete$"))
    app.add_handler(CallbackQueryHandler(quoteDelConfirmCallback,     pattern="^quote_del_\\d+$"))
    app.add_handler(CallbackQueryHandler(qotdSendNowCallback,         pattern="^qotd_send_now$"))
    app.add_handler(CallbackQueryHandler(getQuoteCallback,            pattern="^get_quote$"))
    app.add_handler(CallbackQueryHandler(settingsSecretsCallback,     pattern="^settings_secrets$"))
    app.add_handler(CallbackQueryHandler(secretMakeCallback,          pattern="^secret_make$"))
    app.add_handler(CallbackQueryHandler(secretPickCallback,          pattern="^secret_pick_\\d+$"))
    app.add_handler(CallbackQueryHandler(secretUnmarkCallback,        pattern="^secret_unmark$"))
    app.add_handler(CallbackQueryHandler(secretUnmarkConfirmCallback, pattern="^secret_unmark_\\d+$"))
    app.add_handler(CallbackQueryHandler(settingsLinkstatsCallback,   pattern="^settings_linkstats$"))
    app.add_handler(CallbackQueryHandler(linkstatsViewCallback,       pattern="^linkstats_\\d+$"))

    # Message handler
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
        messageHandler,
    ))

    app.add_error_handler(errorHandler)

    # Background jobs
    jq = app.job_queue
    jq.run_daily(jobQotd,               time=dtime(hour=12, minute=0))
    jq.run_repeating(jobClosePols,      interval=300,  first=30)
    jq.run_repeating(jobPurgeTrending,  interval=3600, first=60)
    jq.run_daily(jobPurgeLinks,         time=dtime(hour=3, minute=0))

    logging.info("Drazeforce Bot v3.0 started — polling active")
    app.run_polling()


if __name__ == "__main__":
    main()