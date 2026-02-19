# Titan Bot  v2.0.0

A production-grade Telegram content management and distribution bot.

---

## Setup

1. Clone or copy the `bot/` folder to your server.
2. Create a `.env` file in the same directory as `main.py`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_ID=your_telegram_user_id_here
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run the bot:

```bash
python main.py
```

---

## Project Structure

```
bot/
  main.py              Entry point, handler registration
  config.py            Environment, DB, schema, migrations
  helpers.py           Utilities, formatters, auth helpers
  keyboards.py         InlineKeyboard builders
  requirements.txt
  handlers/
    start.py           /start, token delivery, password verify
    admin.py           Admin panel, add/remove, ban/unban
    folders.py         Create, view, pin, note, delete folders
    files.py           Upload, delete, toggle, preview files
    links.py           Generate, revoke, purge links
    broadcast.py       Broadcast flow (multi-step)
    inbox.py           Inbox, contact admin, view/delete messages
    analytics.py       Stats, activity log, bot status
    subscribers.py     Subscriber list and details
    commands.py        All slash commands
    messages.py        Unified message handler (all text input flows)
```

---

## Commands

| Command | Access | Description |
|---|---|---|
| `/start` | All | Open the main panel or redeem an access link |
| `/help` | All | Show available commands |
| `/cancel` | All | Cancel the current operation |
| `/stats` | Admin | Quick analytics snapshot |
| `/search <keyword>` | Admin | Search folders by name |
| `/quota` | Admin | Storage usage per folder |
| `/purge` | Admin | Remove expired and revoked links |
| `/export subscribers` | Admin | Download subscriber list as CSV |
| `/export logs` | Admin | Download activity log as CSV |
| `/status` | Admin | Bot uptime and version info |
| `/pin <message>` | Super Admin | Send a pinned announcement to all subscribers |
| `/broadcast <text>` | Super Admin | Quick text-only broadcast |
| `/ban <user_id> [reason]` | Super Admin | Ban a user |
| `/unban <user_id>` | Super Admin | Remove a ban |

---

## Features

- **Folder management** — Create, pin, annotate and delete folders
- **File distribution** — Upload any file type, deliver via secure expiring links
- **Link control** — Set forwardable, auto-delete, expiry; revoke anytime
- **Password protection** — Per-folder passwords for access control
- **Broadcast system** — Rich broadcasts with password, auto-delete and forward controls
- **Inbox** — Users can contact specific admins; messages route to inbox
- **Analytics** — Full stats dashboard and activity log
- **User banning** — Ban/unban users from all access
- **CSV export** — Export subscriber and activity data
- **Bot status** — Real-time uptime and version display
- **Admin hierarchy** — Super admin and regular admin roles