import asyncio
import logging
import re
import secrets
import string
from datetime import datetime

from telegram.error import BadRequest  # type: ignore

from config import conn, cursor


def isAdmin(userId: int) -> bool:
    cursor.execute("SELECT 1 FROM admins WHERE user_id=%s", (userId,))
    return cursor.fetchone() is not None


def isSuperAdmin(userId: int) -> bool:
    cursor.execute("SELECT is_super_admin FROM admins WHERE user_id=%s", (userId,))
    row = cursor.fetchone()
    return bool(row and row[0])


def isBanned(userId: int) -> bool:
    cursor.execute("SELECT 1 FROM banned_users WHERE user_id=%s", (userId,))
    if cursor.fetchone() is not None:
        return True
    cursor.execute("SELECT banned FROM subscribers WHERE user_id=%s", (userId,))
    row = cursor.fetchone()
    return bool(row and row[0])


def generateToken() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def generateBroadcastCode() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(12))


def generateMessageId() -> str:
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))


def validateFolderName(name: str) -> tuple:
    if not name or len(name) > 100:
        return False, "Folder name must be between 1 and 100 characters."
    if not re.match(r"^[\w\s\-]+$", name):
        return False, "Only letters, numbers, spaces, dashes and underscores are allowed."
    return True, ""


def validateMinutes(value):
    try:
        mins = int(value)
        if mins < 1 or mins > 10080:
            return False, "Enter a value between 1 and 10080 (1 week)."
        return True, mins
    except (ValueError, TypeError):
        return False, "That is not a valid number."


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


def fmtBool(val) -> str:
    return "Yes" if val else "No"


def trackUser(user) -> None:
    try:
        cursor.execute("""
            INSERT INTO subscribers (user_id, username, first_name, subscribed_at, last_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username    = EXCLUDED.username,
                first_name  = EXCLUDED.first_name,
                last_active = EXCLUDED.last_active
        """, (
            user.id, user.username, user.first_name,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ))
        conn.commit()
    except Exception as e:
        logging.error(f"trackUser: {e}")
        conn.rollback()


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
