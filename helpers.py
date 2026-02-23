import asyncio
import logging
import re
import secrets
import string
from datetime import datetime

from telegram.error import BadRequest  # type: ignore

from config import conn, cursor

# ─────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────

def isAdmin(userId: int) -> bool:
    return cursor.execute(
        "SELECT 1 FROM admins WHERE user_id=?", (userId,)
    ).fetchone() is not None


def isSuperAdmin(userId: int) -> bool:
    row = cursor.execute(
        "SELECT is_super_admin FROM admins WHERE user_id=?", (userId,)
    ).fetchone()
    return bool(row and row[0])


def isBanned(userId: int) -> bool:
    # Check both the banned_users table AND the subscribers.banned flag
    in_ban_table = cursor.execute(
        "SELECT 1 FROM banned_users WHERE user_id=?", (userId,)
    ).fetchone() is not None
    if in_ban_table:
        return True
    sub_banned = cursor.execute(
        "SELECT banned FROM subscribers WHERE user_id=?", (userId,)
    ).fetchone()
    return bool(sub_banned and sub_banned[0])


def isVerified(userId: int) -> bool:
    row = cursor.execute(
        "SELECT phone_verified FROM subscribers WHERE user_id=?", (userId,)
    ).fetchone()
    return bool(row and row[0])


# ─────────────────────────────────────────────
#  GENERATORS
# ─────────────────────────────────────────────

def generateToken() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def generateBroadcastCode() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(12))


def generateMessageId() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))


def randomFolderName() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))


# ─────────────────────────────────────────────
#  VALIDATORS
# ─────────────────────────────────────────────

def validateFolderName(name: str) -> tuple[bool, str]:
    if not name or len(name) > 100:
        return False, "Folder name must be between 1 and 100 characters."
    if not re.match(r"^[\w\s\-]+$", name):
        return False, "Only letters, numbers, spaces, dashes and underscores are allowed."
    return True, ""


def validateMinutes(value) -> tuple[bool, int | str]:
    try:
        mins = int(value)
        if mins < 1 or mins > 10080:
            return False, "Enter a value between 1 and 10080 (1 week)."
        return True, mins
    except (ValueError, TypeError):
        return False, "That is not a valid number."


# ─────────────────────────────────────────────
#  FORMATTERS
# ─────────────────────────────────────────────

def fmtSize(size) -> str:
    if size is None:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fmtDt(dtStr: str) -> str:
    try:
        return datetime.fromisoformat(dtStr).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return dtStr or "N/A"


def fmtUptime(start: datetime) -> str:
    delta = datetime.now() - start
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    days   = delta.days
    if days:
        return f"{days}d {h % 24}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def fmtBool(val: int | bool) -> str:
    return "Yes" if val else "No"


# ─────────────────────────────────────────────
#  USER TRACKING
# ─────────────────────────────────────────────

def trackUser(user) -> None:
    try:
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO subscribers
                (user_id, username, first_name, subscribed_at, last_active)
            VALUES (?, ?, ?, ?, ?)
        """, (user.id, user.username, user.first_name, now, now))
        cursor.execute("""
            UPDATE subscribers
               SET username = ?, first_name = ?, last_active = ?
             WHERE user_id = ?
        """, (user.username, user.first_name, now, user.id))
        conn.commit()
    except Exception as e:
        logging.error(f"trackUser: {e}")


# ─────────────────────────────────────────────
#  ASYNC HELPERS
# ─────────────────────────────────────────────

async def deleteLater(message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception:
        pass


async def deleteAll(messages: list, delay: int) -> None:
    await asyncio.sleep(delay)
    for m in messages:
        try:
            await m.delete()
        except Exception:
            pass


async def safeEdit(query, text: str, markup=None, parse_mode: str = None) -> None:
    try:
        kwargs = {"text": text, "reply_markup": markup}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        await query.edit_message_text(**kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


# ─────────────────────────────────────────────
#  DECORATORS / WRAPPERS
# ─────────────────────────────────────────────

def adminOnly(func):
    """Decorator: blocks non-admins from callback handlers."""
    async def wrapper(update, context, *args, **kwargs):
        userId = update.effective_user.id
        if not isAdmin(userId):
            try:
                await update.callback_query.answer(
                    "Access denied. Admins only.", show_alert=True
                )
            except Exception:
                pass
            return
        return await func(update, context, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


def superAdminOnly(func):
    """Decorator: blocks non-super-admins from callback handlers."""
    async def wrapper(update, context, *args, **kwargs):
        userId = update.effective_user.id
        if not isSuperAdmin(userId):
            try:
                await update.callback_query.answer(
                    "Only super admins can do this.", show_alert=True
                )
            except Exception:
                pass
            return
        return await func(update, context, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper