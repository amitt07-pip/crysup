import json
import os
import logging
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ChatMember
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
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
SECURITY_CHANNEL_ID = "-1002215462357"
MONITORED_GROUP_ID = -1003446573761

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

# Auto-kick timeout in seconds (30 minutes)
AUTO_KICK_TIMEOUT = 30 * 60
# Security check interval in seconds (1 hour)
SECURITY_CHECK_INTERVAL = 60 * 60

# In-memory store for member display info (keyed by "member_id:group_id")
# Used to keep callback data under Telegram's 64-byte limit
_member_info: dict[str, dict[str, str | int]] = {}


def _get_username_display(user) -> str:
    """Return @username if available, otherwise the user's full name."""
    if user.username:
        return f"@{user.username}"
    return user.full_name


def _build_security_message(
    new_member_display: str,
    added_by_display: str,
    hours: int,
) -> str:
    """Build the security protocol message."""
    hour_text = f"{hours} hour" if hours == 1 else f"{hours} hours"
    return (
        f"‼️ <b>SECURITY PROTOCOL</b> ‼️\n"
        f"\n"
        f"{new_member_display} (added by {added_by_display}) "
        f"is still in the group for more than {hour_text}, "
        f'if the deal is still running then click on '
        f'"<b>✅ I am still doing deal</b>" '
        f'if not then click on "<b>❌ Kick Member</b>" '
        f"please respond to the message within 30 minutes "
        f"or the member will be auto kicked."
    )


def _store_member_info(
    new_member_id: int,
    group_chat_id: int,
    hours: int,
    new_member_display: str,
    added_by_display: str,
    adder_id: int = 0,
) -> None:
    """Store member display info in memory for callback lookups."""
    key = f"{new_member_id}:{group_chat_id}"
    _member_info[key] = {
        "member_disp": new_member_display,
        "adder_disp": added_by_display,
        "hours": hours,
        "adder_id": adder_id,
    }


def _build_security_keyboard(
    new_member_id: int,
    group_chat_id: int,
    hours: int,
    new_member_display: str,
    added_by_display: str,
    adder_id: int = 0,
) -> InlineKeyboardMarkup:
    """Build inline keyboard for the security protocol message."""
    # Store display info in memory so callback data stays under 64 bytes
    _store_member_info(
        new_member_id, group_chat_id, hours, new_member_display, added_by_display,
        adder_id=adder_id,
    )
    # Compact callback data: "d:member_id:group_id" for deal, "k:member_id:group_id" for kick
    callback_data_deal = f"d:{new_member_id}:{group_chat_id}"
    callback_data_kick = f"k:{new_member_id}:{group_chat_id}"
    keyboard = [
        [InlineKeyboardButton("✅ I am still doing deal", callback_data=callback_data_deal)],
        [InlineKeyboardButton("❌ Kick Member", callback_data=callback_data_kick)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_security_check(
    context: ContextTypes.DEFAULT_TYPE,
    new_member_id: int,
    group_chat_id: int,
    hours: int,
    new_member_display: str,
    added_by_display: str,
    target_chat_id: int | None = None,
    adder_id: int = 0,
) -> None:
    """Send security protocol message and schedule auto-kick."""
    send_to = target_chat_id or int(SECURITY_CHANNEL_ID)
    message_text = _build_security_message(new_member_display, added_by_display, hours)
    keyboard = _build_security_keyboard(
        new_member_id, group_chat_id, hours, new_member_display, added_by_display,
        adder_id=adder_id,
    )

    try:
        sent_msg = await context.bot.send_message(
            chat_id=send_to,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        logger.info(
            "Sent security check for member %s in group %s (hour %s)",
            new_member_id,
            group_chat_id,
            hours,
        )

        # Schedule auto-kick after 30 minutes if no response
        job_name = f"autokick_{new_member_id}_{group_chat_id}"
        # Remove any existing auto-kick job for this member
        existing_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in existing_jobs:
            job.schedule_removal()

        context.job_queue.run_once(
            auto_kick_member,
            when=AUTO_KICK_TIMEOUT,
            name=job_name,
            data={
                "member_id": new_member_id,
                "group_id": group_chat_id,
                "message_id": sent_msg.message_id,
                "sent_chat_id": send_to,
            },
        )
    except Exception as e:
        logger.error("Failed to send security check: %s", e)


async def schedule_security_check(
    context: ContextTypes.DEFAULT_TYPE,
    new_member_id: int,
    group_chat_id: int,
    hours: int,
    new_member_display: str,
    added_by_display: str,
    adder_id: int = 0,
) -> None:
    """Schedule the first (or next) security check after SECURITY_CHECK_INTERVAL."""
    job_name = f"security_{new_member_id}_{group_chat_id}"
    # Remove any existing security check job for this member
    existing_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in existing_jobs:
        job.schedule_removal()

    context.job_queue.run_once(
        _security_check_job,
        when=SECURITY_CHECK_INTERVAL,
        name=job_name,
        data={
            "member_id": new_member_id,
            "group_id": group_chat_id,
            "hours": hours,
            "member_disp": new_member_display,
            "adder_disp": added_by_display,
            "adder_id": adder_id,
        },
    )
    logger.info(
        "Scheduled security check for member %s in %s seconds (hour %s)",
        new_member_id,
        SECURITY_CHECK_INTERVAL,
        hours,
    )


async def _security_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback that sends the security check message."""
    data = context.job.data
    await send_security_check(
        context,
        new_member_id=data["member_id"],
        group_chat_id=data["group_id"],
        hours=data["hours"],
        new_member_display=data["member_disp"],
        added_by_display=data["adder_disp"],
        adder_id=data.get("adder_id", 0),
    )


async def auto_kick_member(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-kick member after 30 minutes of no response."""
    data = context.job.data
    member_id = data["member_id"]
    group_id = data["group_id"]
    message_id = data["message_id"]

    try:
        await context.bot.ban_chat_member(chat_id=group_id, user_id=member_id)
        await context.bot.unban_chat_member(chat_id=group_id, user_id=member_id)
        logger.info("Auto-kicked member %s from group %s", member_id, group_id)

        # Edit the security message to indicate auto-kick
        sent_chat_id = data.get("sent_chat_id", int(SECURITY_CHANNEL_ID))
        try:
            await context.bot.edit_message_text(
                chat_id=sent_chat_id,
                message_id=message_id,
                text="⚠️ Member was auto-kicked due to no response within 30 minutes.",
            )
        except Exception as e:
            logger.error("Failed to edit security message after auto-kick: %s", e)

    except Exception as e:
        logger.error("Failed to auto-kick member %s from group %s: %s", member_id, group_id, e)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses on security protocol messages."""
    query = update.callback_query
    await query.answer()

    raw = query.data or ""
    parts = raw.split(":")
    if len(parts) < 3:
        return

    action = parts[0]  # "d" for deal, "k" for kick
    member_id = int(parts[1])
    group_id = int(parts[2])
    info_key = f"{member_id}:{group_id}"

    # Only the known member who added this person can use the buttons
    info = _member_info.get(info_key, {})
    adder_id = int(info.get("adder_id", 0))
    if adder_id and query.from_user.id != adder_id:
        await query.answer("Only the person who added this member can use this button.", show_alert=True)
        return

    if action == "k":
        # Cancel the auto-kick job
        job_name = f"autokick_{member_id}_{group_id}"
        existing_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in existing_jobs:
            job.schedule_removal()

        # Cancel any pending security check job
        sec_job_name = f"security_{member_id}_{group_id}"
        sec_jobs = context.job_queue.get_jobs_by_name(sec_job_name)
        for job in sec_jobs:
            job.schedule_removal()

        # Clean up stored info
        _member_info.pop(info_key, None)

        try:
            await context.bot.ban_chat_member(chat_id=group_id, user_id=member_id)
            await context.bot.unban_chat_member(chat_id=group_id, user_id=member_id)
            await query.edit_message_text("❌ Member has been kicked from the group.")
            logger.info("Kicked member %s from group %s via button", member_id, group_id)
        except Exception as e:
            await query.edit_message_text(f"Failed to kick member: {e}")
            logger.error("Failed to kick member %s: %s", member_id, e)

    elif action == "d":
        info = _member_info.get(info_key, {})
        hours = int(info.get("hours", 1))
        new_member_display = str(info.get("member_disp", "Unknown"))
        added_by_display = str(info.get("adder_disp", "Unknown"))
        stored_adder_id = int(info.get("adder_id", 0))

        # Cancel the auto-kick job
        job_name = f"autokick_{member_id}_{group_id}"
        existing_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in existing_jobs:
            job.schedule_removal()

        # Update the message to confirm
        await query.edit_message_text("✅ Deal confirmed. Will check again in 1 hour.")

        # Schedule another check in 1 hour with incremented hours
        await schedule_security_check(
            context,
            new_member_id=member_id,
            group_chat_id=group_id,
            hours=hours + 1,
            new_member_display=new_member_display,
            added_by_display=added_by_display,
            adder_id=stored_adder_id,
        )


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
    group_chat_id = result.chat.id
    IST = timezone(timedelta(hours=5, minutes=30))
    timestamp = result.date or datetime.now(timezone.utc)
    ist_time = timestamp.astimezone(IST)
    formatted_time = ist_time.strftime("%Y-%m-%d %H:%M:%S IST")

    added_by_display = _get_username_display(added_by)
    new_member_display = _get_username_display(new_member)

    if added_by.id in KNOWN_MEMBER_IDS:
        # Known member added someone — friendly log
        log_message = (
            f"~ {new_member_display} (<code>{new_member.id}</code>) has been added by "
            f"{added_by_display} (<code>{added_by.id}</code>) in the CryptoIndia Group ‼️"
        )

        # Schedule security check after 1 hour
        await schedule_security_check(
            context,
            new_member_id=new_member.id,
            group_chat_id=group_chat_id,
            hours=1,
            new_member_display=new_member_display,
            added_by_display=added_by_display,
            adder_id=added_by.id,
        )
    else:
        # Unknown person added someone — alert
        log_message = (
            f"🚨 <b>MEMBER ADDED BY A UNKNOWN PERSON</b> ‼️\n"
            f"\n"
            f"Username - {new_member_display} (<code>{new_member.id}</code>)\n"
            f"Added by - {added_by_display} (<code>{added_by.id}</code>)\n"
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


async def unklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List unknown members still in the monitored group and send to security channel."""
    try:
        tracked_keys = list(_member_info.keys())
        if not tracked_keys:
            await context.bot.send_message(
                chat_id=int(SECURITY_CHANNEL_ID),
                text="📋 <b>Unknown Members List</b>\n\nNo tracked unknown members currently in the group.",
                parse_mode="HTML",
            )
            return

        lines = []
        for key in tracked_keys:
            info = _member_info[key]
            member_disp = info.get("member_disp", "Unknown")
            adder_disp = info.get("adder_disp", "Unknown")
            parts = key.split(":")
            member_id = parts[0]
            lines.append(
                f"• {member_disp} (<code>{member_id}</code>) — added by {adder_disp}"
            )

        member_list = "\n".join(lines)
        message_text = (
            f"📋 <b>Tracked Members List</b>\n\n"
            f"{member_list}\n\n"
            f"Total: {len(lines)} member(s) with active security checks."
        )

        await context.bot.send_message(
            chat_id=int(SECURITY_CHANNEL_ID),
            text=message_text,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("Failed to send unknown members list: %s", e)


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a test security protocol message to the chat where /test is used."""
    test_member_display = "@test_member"
    test_adder_display = "@test_adder"
    test_member_id = 123456789
    test_group_id = update.effective_chat.id

    await send_security_check(
        context,
        new_member_id=test_member_id,
        group_chat_id=test_group_id,
        hours=1,
        new_member_display=test_member_display,
        added_by_display=test_adder_display,
        target_chat_id=update.effective_chat.id,
    )


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

    # Handle inline button callbacks
    application.add_handler(CallbackQueryHandler(handle_callback))

    # /test command for testing security protocol
    application.add_handler(CommandHandler("test", test_command))

    # /unklist command to list unknown members in the monitored group
    application.add_handler(CommandHandler("unklist", unklist_command))

    logger.info("Bot started — monitoring group activity...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
