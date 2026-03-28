import os
import logging
from datetime import datetime, timezone

from telegram import Update, ChatMember
from telegram.ext import (
    Application,
    ChatMemberHandler,
    ContextTypes,
)

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "")


def _format_user(user) -> str:
    """Format user details into a readable string."""
    parts = []
    parts.append(f"<b>Name:</b> {user.full_name}")
    if user.username:
        parts.append(f"<b>Username:</b> @{user.username}")
    parts.append(f"<b>User ID:</b> <code>{user.id}</code>")
    parts.append(f"<b>Is Bot:</b> {'Yes' if user.is_bot else 'No'}")
    return "\n".join(parts)


async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle chat member updates — detect when someone is added to the group."""
    if not LOG_CHANNEL_ID:
        logger.warning("LOG_CHANNEL_ID is not set. Skipping log.")
        return

    result = update.chat_member
    if result is None:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    # Detect a new member being added (was not in the group, now is a member)
    was_member = old_status in (
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR,
        ChatMember.OWNER,
    )
    is_member = new_status in (
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR,
        ChatMember.OWNER,
    )

    if was_member or not is_member:
        # Not a new addition — ignore
        return

    new_member = result.new_chat_member.user
    added_by = result.from_user
    chat = result.chat
    timestamp = result.date or datetime.now(timezone.utc)
    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    message_lines = [
        "👤 <b>New Member Added</b>",
        "",
        f"<b>Group:</b> {chat.title} (<code>{chat.id}</code>)",
        "",
        "── <b>New Member</b> ──",
        _format_user(new_member),
        "",
        "── <b>Added By</b> ──",
        _format_user(added_by),
        "",
        f"<b>Time:</b> {formatted_time}",
    ]

    log_message = "\n".join(message_lines)

    try:
        await context.bot.send_message(
            chat_id=int(LOG_CHANNEL_ID),
            text=log_message,
            parse_mode="HTML",
        )
        logger.info(
            "Logged new member %s (added by %s) in group %s",
            new_member.id,
            added_by.id,
            chat.id,
        )
    except Exception as e:
        logger.error("Failed to send log message: %s", e)


async def track_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track when the bot itself is added to or removed from a group."""
    if not LOG_CHANNEL_ID:
        return

    result = update.my_chat_member
    if result is None:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    chat = result.chat
    added_by = result.from_user
    timestamp = result.date or datetime.now(timezone.utc)
    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    if old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status in (
        ChatMember.MEMBER,
        ChatMember.ADMINISTRATOR,
    ):
        log_message = "\n".join([
            "🤖 <b>Bot Added to Group</b>",
            "",
            f"<b>Group:</b> {chat.title} (<code>{chat.id}</code>)",
            "",
            "── <b>Added By</b> ──",
            _format_user(added_by),
            "",
            f"<b>Time:</b> {formatted_time}",
        ])

        try:
            await context.bot.send_message(
                chat_id=int(LOG_CHANNEL_ID),
                text=log_message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to send bot-added log: %s", e)

    elif old_status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR) and new_status in (
        ChatMember.LEFT,
        ChatMember.BANNED,
    ):
        log_message = "\n".join([
            "🚫 <b>Bot Removed from Group</b>",
            "",
            f"<b>Group:</b> {chat.title} (<code>{chat.id}</code>)",
            "",
            "── <b>Removed By</b> ──",
            _format_user(added_by),
            "",
            f"<b>Time:</b> {formatted_time}",
        ])

        try:
            await context.bot.send_message(
                chat_id=int(LOG_CHANNEL_ID),
                text=log_message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Failed to send bot-removed log: %s", e)


def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return

    if not LOG_CHANNEL_ID:
        logger.warning(
            "LOG_CHANNEL_ID is not set. The bot will run but won't send logs anywhere."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    # Monitor member changes in groups (other users being added/removed)
    application.add_handler(
        ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER)
    )

    # Monitor when the bot itself is added/removed from groups
    application.add_handler(
        ChatMemberHandler(track_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    logger.info("Bot started — monitoring group activity...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
