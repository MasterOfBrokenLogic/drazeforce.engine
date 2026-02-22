import logging
from datetime import datetime

from config import cursor, conn
from handlers.settings import _sendQotd
from handlers.polls import _broadcastPollResults


# ─────────────────────────────────────────────
#  DAILY QUOTE OF THE DAY
# ─────────────────────────────────────────────

async def jobQotd(context):
    """Runs daily — sends a random quote to all subscribers."""
    try:
        cursor.execute("SELECT COUNT(*) FROM quotes")
        count = cursor.fetchone()
        count = count[0] if count else None
        if count == 0:
            return
        await _sendQotd(context)
        logging.info("QOTD sent successfully")
    except Exception as e:
        logging.error(f"jobQotd: {e}")


# ─────────────────────────────────────────────
#  AUTO-CLOSE EXPIRED POLLS
# ─────────────────────────────────────────────

async def jobClosePols(context):
    """Runs every 5 minutes — closes expired polls and broadcasts results."""
    try:
        expired = cursor.execute("""
            SELECT id FROM polls
            WHERE status='open'
            AND result_sent=0
            AND closes_at <= NOW()
        """)
        expired = cursor.fetchall()

        for (pollId,) in expired:
            cursor.execute("UPDATE polls SET status='closed' WHERE id=%s", (pollId,))
            conn.commit()
            await _broadcastPollResults(pollId, context)
            logging.info(f"Poll {pollId} auto-closed and results sent")
    except Exception as e:
        logging.error(f"jobClosePolls: {e}")


# ─────────────────────────────────────────────
#  AUTO-PURGE EXPIRED TRENDING
# ─────────────────────────────────────────────

async def jobPurgeTrending(context):
    """Runs hourly — removes expired trending items."""
    try:
        cursor.execute(
            "DELETE FROM trending WHERE expires_at IS NOT NULL AND expires_at <= NOW()"
        )
        removed = cursor.rowcount
        conn.commit()
        if removed > 0:
            logging.info(f"Purged {removed} expired trending item(s)")
    except Exception as e:
        logging.error(f"jobPurgeTrending: {e}")


# ─────────────────────────────────────────────
#  AUTO-PURGE EXPIRED LINKS
# ─────────────────────────────────────────────

async def jobPurgeLinks(context):
    """Runs daily — removes expired and revoked link records."""
    try:
        cursor.execute("DELETE FROM links WHERE expiry <= NOW()")
        exp = cursor.rowcount
        cursor.execute("DELETE FROM links WHERE revoked=1")
        rev = cursor.rowcount
        conn.commit()
        if exp + rev > 0:
            logging.info(f"Auto-purged {exp} expired + {rev} revoked links")
    except Exception as e:
        logging.error(f"jobPurgeLinks: {e}")
