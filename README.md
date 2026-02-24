# Drazeforce Bot

A feature-rich private content delivery Telegram bot built with Python and `python-telegram-bot`. Designed for admins who need to securely distribute files, videos, photos, and documents to verified users through access-controlled folder links.

---

## Features

### Content Management
- **Folders** — Create named folders to group content. Pin important folders to the top.
- **File Uploads** — Upload videos, photos, documents, and text into folders. Type `END` when done.
- **Add Media** — Add more files to existing folders at any time.
- **Delete Files** — Selectively toggle and delete individual files from a folder.
- **Preview** — Preview all files in a folder before sharing.
- **Folder Notes** — Attach internal admin-only notes to any folder.
- **Folder Search** — Search folders by name via `/search`.
- **Storage Quota** — View per-folder storage usage via `/quota`.

### Access Links
- **Generate Links** — Create shareable deep links for any folder with custom expiry times.
- **Single-Use Links** — Links that self-revoke after the first redemption.
- **Forwardable / Protected** — Toggle whether delivered content can be forwarded.
- **Auto-Delete** — Content automatically deletes after a configurable number of minutes.
- **Password Protection** — Lock any folder behind a password. Users get 3 attempts.
- **Revoke Links** — Instantly revoke any active link.
- **Purge Links** — Bulk-remove expired and revoked links via `/purge`.
- **Link Info** — View full details about any link via `/linkinfo <token>`.

### OTP Access
- Folders can be configured to require a One-Time Password instead of a standard link.
- Only the Super Admin can enable OTP on a folder and set the expiry duration (1–60 minutes).
- When a user opens the folder link, they see an OTP request screen.
- Tapping **Request OTP** pings the SA in-bot with a **Generate & Send OTP** button.
- SA taps the button — a 6-digit OTP is instantly generated and sent to the user.
- Users have 3 attempts to enter the correct code before it is revoked.
- OTPs are single-use and expire after the configured time.

### Phone Verification
- New users are prompted to share their phone number via Telegram's native contact button on first `/start`.
- Verified phone number is stored securely and forwarded to the Super Admin instantly.
- Unverified users are blocked from opening folder links, requesting OTPs, and voting on polls.
- Super Admin can view verified and unverified user lists and revoke any user's verification.
- Verification is persistent — users are never asked to re-verify unless explicitly revoked.

### Broadcasts
- **Rich Broadcasts** — Send mixed content (videos, photos, documents, text) to all subscribers at once.
- **Password-Protected Broadcasts** — Require users to enter a password to access broadcast content.
- **Expiry** — Broadcast content auto-expires after a set number of minutes.
- **Forward Control** — Choose whether broadcast content can be forwarded by recipients.
- **Cancel Delivery** — Users can cancel their own content delivery mid-stream.
- Broadcast via command: `/broadcast`

### Polls
- Create multiple-choice polls (up to 4 options A–D).
- Polls auto-close after a set time or can be closed manually.
- Results are sent automatically when a poll closes.
- Unverified users cannot vote.

### Trending
- Pin up to a configurable number of trending folders visible to all users.
- Set expiry on trending items — they auto-remove when expired.
- Users can browse trending content from their menu without needing a link.

### Inbox & Messaging
- Users can send messages and files directly to admins through the bot.
- Admins can view, reply to, keep, or delete messages from their inbox.
- Replies are delivered back to users inside the bot.
- Users can view admin replies in their own inbox.
- Admins can contact specific users directly from the admin panel.

### Subscriber Management
- View all subscribers with name, username, join date, last active time.
- See counts for total, active (last 24h), banned, verified, and unverified users.
- Browse **Verified** and **Unverified** user lists separately with per-user detail buttons.
- Export full subscriber list as a CSV file via `/export`.
- View per-user details: name, username, user ID, status, verified status, phone number, join date.

### Admin Panel
- Add and remove admins.
- Super Admin role with elevated permissions (OTP, verification revoke, settings).
- Ban and unban users with optional reasons.
- View banned user list with details.
- Quick-ban inline button available from `/block` command.
- `/ban` and `/unban` commands for fast action.

### Settings (Super Admin only)
- **Welcome Message** — Set a custom welcome message for new users. Reset to default anytime.
- **Quote of the Day** — Add, delete, and schedule daily quotes sent to all subscribers.
- **Secret Codewords** — Mark folders as secret and assign a codeword. Users who type the codeword in chat receive the folder contents automatically.
- **Link Stats** — View access logs per link.

### Customize (Super Admin only)
Granular control over bot behaviour across 7 categories:
- **Messages** — Customize delivery messages, access granted text, expiry notices.
- **Links** — Default expiry, single-use defaults, forward defaults.
- **Folders** — Auto-delete defaults, protect defaults.
- **UX** — Cancel button visibility, spoiler tags on media.
- **Broadcast** — Default forward and expiry settings for broadcasts.
- **Identity** — Bot name and tagline shown in messages.
- **Notifications** — Toggle single-use link redemption alerts to SA.

### Analytics
- **Stats Dashboard** — Total users, folders, files, links, broadcasts, polls, and storage.
- **Activity Log** — Recent folder access events with user and timestamp.
- **Bot Status** — Uptime, version, Python and library versions, DB size.
- `/stats` — Extended analytics dashboard via command.
- `/status` — Quick bot health check.

### Slash Commands

| Command | Access | Description |
|---|---|---|
| `/start` | All | Open main menu or redeem a folder link |
| `/help` | All | Show available commands |
| `/stats` | Admin | Full analytics dashboard |
| `/search` | Admin | Search folders by name |
| `/quota` | Admin | Storage usage per folder |
| `/purge` | Admin | Remove expired and revoked links |
| `/export` | Admin | Export subscriber list as CSV |
| `/status` | Admin | Bot health and uptime |
| `/pin` | Admin | Pin a message by message ID |
| `/note` | Admin | Add a note to a folder |
| `/welcome` | Super Admin | Set or reset the user welcome message |
| `/linkinfo` | Admin | View full details for a link token |
| `/block` | Admin | Block a user by ID with quick ban button |
| `/broadcast` | Admin | Start a broadcast session |
| `/ban` | Admin | Ban a user by ID |
| `/unban` | Admin | Unban a user by ID |
| `/myid` | All | Get your own Telegram user ID |
| `/cancel` | Admin | Cancel any active input session |

---

## Project Structure

```
.
├── main.py                  # Entry point, all handler registration
├── config.py                # DB connection, schema creation, migrations
├── helpers.py               # Shared utilities (auth, formatting, generators)
├── keyboards.py             # Reusable inline keyboard layouts
├── handlers/
│   ├── start.py             # /start, deep link handling, folder delivery
│   ├── admin.py             # Admin panel, ban/unban
│   ├── folders.py           # Folder CRUD, password, pin, note
│   ├── files.py             # File upload, delete, preview
│   ├── links.py             # Link generation, revoke, purge
│   ├── broadcast.py         # Broadcast creation and delivery
│   ├── messages.py          # Central message handler (all text/media input)
│   ├── inbox.py             # Admin inbox, user messaging
│   ├── polls.py             # Poll creation, voting, results
│   ├── trending.py          # Trending folder management
│   ├── analytics.py         # Stats, activity log, bot status
│   ├── subscribers.py       # Subscriber list, verification management
│   ├── commands.py          # All slash command handlers
│   ├── settings.py          # Quotes, secrets, link stats (Super Admin)
│   ├── customize.py         # Bot behaviour customisation (Super Admin)
│   ├── otp.py               # OTP access system
│   └── jobs.py              # Background jobs (QOTD, poll close, link purge)
```

---

## Setup

### Requirements

- Python 3.11+
- `python-telegram-bot[job-queue]`
- `python-dotenv`

Install dependencies:

```bash
pip install python-telegram-bot[job-queue] python-dotenv
```

### Environment Variables

Create a `.env` file in the root directory:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_ID=your_telegram_user_id_here
DB_PATH=/data/bot.db
```

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | Your Telegram user ID — this account becomes the Super Admin |
| `DB_PATH` | Path to the SQLite database file (use `/data/bot.db` on Railway) |

### Run Locally

```bash
python main.py
```

### Deploy on Railway

1. Push this repo to GitHub.
2. Create a new Railway project and connect the repo.
3. Add the environment variables in the **Variables** tab.
4. In the **Settings** tab, go to **Volumes** and add a volume mounted at `/data` — this keeps your database persistent across restarts.
5. Railway will deploy automatically on every push.

---

## Database

The bot uses **SQLite** with WAL mode enabled for safe concurrent writes. The schema is created automatically on first run. All migrations for new columns are handled automatically — no manual SQL required when updating.

On Railway, the database lives at `/data/bot.db` on a persistent volume. Since the bot only stores Telegram file IDs (not actual file bytes), the database stays small even with thousands of files — typically under 5 MB.

---

## User Roles

| Role | How to get it | Permissions |
|---|---|---|
| User | Anyone who starts the bot | Browse trending, contact admin, open links (if verified) |
| Admin | Added by Super Admin | Manage folders, files, links, broadcasts, subscribers, inbox |
| Super Admin | Set via `ADMIN_ID` env var | All admin permissions + OTP, verification, settings, customize |

---

## Security Notes

- All folder content delivery uses Telegram's `protect_content` flag when forwardable is disabled.
- Single-use links are revoked atomically before delivery to prevent race conditions.
- OTP codes are 6-digit numeric, single-use, and expire after a configurable time.
- Banned users are blocked at the entry point before any processing occurs.
- Phone numbers are stored in the bot's own database only — never shared externally.

---

## License

MIT
