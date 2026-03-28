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

# Known member user IDs — additions by these users are considered trusted
KNOWN_MEMBER_IDS = {
    1166772148,
    1870644348,
    5651721135,
    5662585948,
    6526824979,
    6659288294,
    6864194951,
    7001100331,
    7090417167,
    7279906688,
    7338429782,
    7422906767,
    7707071842,
    7715451354,
}


def _get_username_display(user) -> str:
    """Return @username if available, otherwise the user's full name."""
    if user.username:
        return f"@{user.username}"
    return user.full_name


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
    timestamp = result.date or datetime.now(timezone.utc)
    formatted_time = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")

    added_by_display = _get_username_display(added_by)
    new_member_display = _get_username_display(new_member)

    if added_by.id in KNOWN_MEMBER_IDS:
        # Known member added someone — friendly log
        log_message = (
            f"~ {new_member_display} has been added by "
            f"{added_by_display} in the CryptoIndia Group ‼️"
        )
    else:
        # Unknown person added someone — alert
        log_message = (
            f"🚨 <b>MEMBER ADDED BY A UNKNOWN PERSON</b> ‼️\n"
            f"\n"
            f"Username - {new_member_display} {new_member.id}\n"
            f"Added by - {added_by_display} {added_by.id}\n"
            f"Date - {formatted_time}\n"
            f"\n"
            f"If it is not done by any of the group members "
            f"please kick both of them asap to avoid deal disruption."
        )

    try:
        await context.bot.send_message(
            chat_id=int(LOG_CHANNEL_ID),
            text=log_message,
            parse_mode="HTML",
        )
        logger.info(
            "Logged new member %s (added by %s, known=%s)",
            new_member.id,
            added_by.id,
            added_by.id in KNOWN_MEMBER_IDS,
        )
    except Exception as e:
        logger.error("Failed to send log message: %s", e)


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

    logger.info("Bot started — monitoring group activity...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
