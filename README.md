# crysup

A Telegram bot that monitors group activity and logs member additions to a designated log channel.

## Features

- Detects when a new member is added to a group
- Logs the new member's details (name, username, user ID, bot status)
- Logs who added the member
- Logs the timestamp of the addition
- Tracks when the bot itself is added to or removed from groups

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```bash
   export BOT_TOKEN="your_bot_token_here"
   export LOG_CHANNEL_ID="your_log_channel_id_here"
   ```

3. Run the bot:
   ```bash
   python bot.py
   ```

## Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `LOG_CHANNEL_ID` | The Telegram channel/group ID where logs will be sent |

## Requirements

- The bot must be added as an **admin** in both the monitored group and the log channel
- Group privacy mode must be **disabled** in @BotFather (so the bot receives chat member updates)
