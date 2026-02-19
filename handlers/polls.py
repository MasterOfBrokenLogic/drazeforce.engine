import logging
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore
from telegram.ext import ContextTypes  # type: ignore

from config import conn, cursor
from helpers import safeEdit, isSuperAdmin, fmtDt, validateMinutes
from keyboards import kbHome, kbBack, kbMain


# ─────────────────────────────────────────────
#  POLL MENU (SA only)
# ─────────────────────────────────────────────

async def pollMenuCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not isSuperAdmin(query.from_user.id):
        await query.answer("Super admins only.", show_alert=True)
        return

    try:
        active = cursor.execute(
            "SELECT COUNT(*) FROM polls WHERE status='open'"
        ).fetchone()[0]
        total  = cursor.execute("SELECT COUNT(*) FROM polls").fetchone()[0]
    except sqlite3.Error as e:
        logging.error(f"pollMenu: {e}")
        await safeEdit(query, "Failed to load poll data.", markup=kbHome())
        return

    await safeEdit(
        query,
        "<b>Poll System</b>\n\n"
        f"<code>Active polls  :  {active}</code>\n"
        f"<code>Total polls   :  {total}</code>\n\n"
        "Create a poll to send to all subscribers.\n"
        "Results are shown in real time and announced when the poll closes.",
        markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Create Poll",   callback_data="poll_create")],
            [InlineKeyboardButton("Active Polls",  callback_data="poll_list_open")],
            [InlineKeyboardButton("Past Polls",    callback_data="poll_list_closed")],
            [InlineKeyboardButton("Main Menu",     callback_data="back_main")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
#  CREATE POLL
# ─────────────────────────────────────────────

async def pollCreateCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["poll_create_step"] = "question"
    context.user_data["poll_data"]        = {}
    await safeEdit(
        query,
        "<b>Create Poll  —  Step 1 of 6</b>\n\n"
        "Enter the poll question.\n\n"
        "<i>Example: What type of content do you want more of?</i>",
        markup=kbBack("poll_menu"),
        parse_mode="HTML",
    )


async def pollListCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    status = "open" if "open" in query.data else "closed"
    label  = "Active" if status == "open" else "Past"

    try:
        polls = cursor.execute(
            "SELECT id, question, created_at, closes_at FROM polls WHERE status=? ORDER BY created_at DESC LIMIT 10",
            (status,)
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"pollList: {e}")
        await safeEdit(query, "Failed to load polls.", markup=kbBack("poll_menu"))
        return

    if not polls:
        await safeEdit(
            query,
            f"<b>{label} Polls</b>\n\nNo {label.lower()} polls found.",
            markup=kbBack("poll_menu"),
            parse_mode="HTML",
        )
        return

    buttons = []
    for pid, question, created_at, closes_at in polls:
        short = question[:40] + "..." if len(question) > 40 else question
        buttons.append([InlineKeyboardButton(short, callback_data=f"poll_view_{pid}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="poll_menu")])

    await safeEdit(
        query,
        f"<b>{label} Polls</b>  |  {len(polls)} found\n\nTap a poll to view results.",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def pollViewCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    pollId = int(query.data.replace("poll_view_", ""))

    try:
        poll = cursor.execute(
            "SELECT id, question, option_a, option_b, option_c, option_d, status, closes_at, created_at "
            "FROM polls WHERE id=?", (pollId,)
        ).fetchone()
        if not poll:
            await safeEdit(query, "Poll not found.", markup=kbBack("poll_menu"))
            return
        votes = cursor.execute(
            "SELECT choice, COUNT(*) FROM poll_votes WHERE poll_id=? GROUP BY choice", (pollId,)
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"pollView: {e}")
        await safeEdit(query, "Failed to load poll.", markup=kbBack("poll_menu"))
        return

    pid, question, a, b, c, d, status, closes_at, created_at = poll
    vote_map   = {v[0]: v[1] for v in votes}
    total_votes = sum(vote_map.values())

    def bar(choice, label):
        if not label:
            return ""
        count = vote_map.get(choice, 0)
        pct   = int((count / total_votes) * 100) if total_votes else 0
        filled = int(pct / 10)
        bar_str = "█" * filled + "░" * (10 - filled)
        return f"\n<code>{label[:20]:<20}  {bar_str}  {pct}%  ({count})</code>"

    results = ""
    results += bar("A", a)
    results += bar("B", b)
    results += bar("C", c)
    results += bar("D", d)

    buttons = []
    if status == "open":
        buttons.append([InlineKeyboardButton("Close Poll Now", callback_data=f"poll_close_{pollId}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="poll_menu")])

    await safeEdit(
        query,
        f"<b>Poll Results</b>\n\n"
        f"<b>{question}</b>\n\n"
        f"{results}\n\n"
        f"<code>Total votes  :  {total_votes}</code>\n"
        f"<code>Status       :  {status.upper()}</code>\n"
        f"<code>Closes       :  {fmtDt(closes_at)}</code>",
        markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def pollCloseCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    pollId = int(query.data.replace("poll_close_", ""))
    try:
        cursor.execute("UPDATE polls SET status='closed' WHERE id=?", (pollId,))
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"pollClose: {e}")
        await safeEdit(query, "Failed to close poll.", markup=kbBack("poll_menu"))
        return

    await _broadcastPollResults(pollId, context)
    await safeEdit(
        query,
        "<b>Poll Closed</b>\n\nResults have been broadcast to all subscribers.",
        markup=kbBack("poll_menu"),
        parse_mode="HTML",
    )


async def _broadcastPollResults(pollId: int, context):
    try:
        poll = cursor.execute(
            "SELECT question, option_a, option_b, option_c, option_d FROM polls WHERE id=?", (pollId,)
        ).fetchone()
        votes = cursor.execute(
            "SELECT choice, COUNT(*) FROM poll_votes WHERE poll_id=? GROUP BY choice", (pollId,)
        ).fetchall()
        subs  = cursor.execute(
            "SELECT user_id FROM subscribers WHERE banned=0 OR banned IS NULL"
        ).fetchall()
    except sqlite3.Error as e:
        logging.error(f"broadcastPollResults: {e}")
        return

    if not poll:
        return

    question, a, b, c, d = poll
    vote_map    = {v[0]: v[1] for v in votes}
    total_votes = sum(vote_map.values())

    def line(choice, label):
        if not label:
            return ""
        count  = vote_map.get(choice, 0)
        pct    = int((count / total_votes) * 100) if total_votes else 0
        filled = int(pct / 10)
        return f"\n<code>{label[:20]:<20}  {'█'*filled}{'░'*(10-filled)}  {pct}%</code>"

    msg = (
        f"<b>Poll Results</b>\n\n"
        f"<b>{question}</b>\n"
        f"{line('A', a)}{line('B', b)}{line('C', c)}{line('D', d)}\n\n"
        f"<code>Total votes  :  {total_votes}</code>"
    )

    for (uid,) in subs:
        try:
            await context.bot.send_message(uid, msg, parse_mode="HTML")
        except Exception:
            pass

    try:
        cursor.execute("UPDATE polls SET result_sent=1 WHERE id=?", (pollId,))
        conn.commit()
    except sqlite3.Error:
        pass


# ─────────────────────────────────────────────
#  USER VOTING
# ─────────────────────────────────────────────

async def pollVoteCallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    userId  = query.from_user.id
    parts   = query.data.split("_")   # vote_POLLID_CHOICE
    pollId  = int(parts[1])
    choice  = parts[2]

    try:
        poll = cursor.execute(
            "SELECT question, option_a, option_b, option_c, option_d, status FROM polls WHERE id=?",
            (pollId,)
        ).fetchone()
        if not poll or poll[5] != "open":
            await query.answer("This poll is no longer active.", show_alert=True)
            return

        existing = cursor.execute(
            "SELECT 1 FROM poll_votes WHERE poll_id=? AND user_id=?", (pollId, userId)
        ).fetchone()
        if existing:
            await query.answer("You have already voted in this poll.", show_alert=True)
            return

        cursor.execute(
            "INSERT INTO poll_votes (poll_id, user_id, choice, voted_at) VALUES (?, ?, ?, ?)",
            (pollId, userId, choice, datetime.now().isoformat())
        )
        conn.commit()
        await query.answer("Vote recorded!", show_alert=False)

        # Update the vote count display for this user
        votes = cursor.execute(
            "SELECT choice, COUNT(*) FROM poll_votes WHERE poll_id=? GROUP BY choice", (pollId,)
        ).fetchall()
        vote_map    = {v[0]: v[1] for v in votes}
        total_votes = sum(vote_map.values())
        question, a, b, c, d, _ = poll

        def line(ch, label):
            if not label:
                return ""
            count  = vote_map.get(ch, 0)
            pct    = int((count / total_votes) * 100) if total_votes else 0
            filled = int(pct / 10)
            marker = "  <  YOU" if ch == choice else ""
            return f"\n<code>{label[:18]:<18}  {'█'*filled}{'░'*(10-filled)}  {pct}%{marker}</code>"

        await query.edit_message_text(
            f"<b>Poll  —  Results so far</b>\n\n"
            f"<b>{question}</b>\n"
            f"{line('A',a)}{line('B',b)}{line('C',c)}{line('D',d)}\n\n"
            f"<code>Total votes  :  {total_votes}</code>\n\n"
            "Thank you for voting!",
            parse_mode="HTML",
        )
    except sqlite3.IntegrityError:
        await query.answer("You have already voted.", show_alert=True)
    except sqlite3.Error as e:
        logging.error(f"pollVote: {e}")
        await query.answer("Failed to record vote.", show_alert=True)