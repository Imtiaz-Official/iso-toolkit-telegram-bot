"""
Telegram bot to keep Render site alive with auto-ping and manual controls.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Final

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import aiohttp

# Configuration from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_URL = os.getenv("TARGET_URL", "https://iso-toolkit.onrender.com/")
PING_INTERVAL = 600  # 10 minutes in seconds

# Validate required environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN environment variable is required! "
        "Set it in your deployment platform or run: "
        "export TELEGRAM_BOT_TOKEN=your_token_here"
    )

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def ping_site() -> tuple[bool, str, int]:
    """
    Ping the target site and return status.
    Returns: (success, message, status_code)
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                TARGET_URL,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                return (
                    True,
                    "Site is online",
                    response.status
                )
    except asyncio.TimeoutError:
        return False, "Request timed out", 0
    except aiohttp.ClientError as e:
        return False, f"Connection error: {e}", 0
    except Exception as e:
        return False, f"Unexpected error: {e}", 0


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    welcome_message = f"""
👋 Hi {user.first_name}!

I'm your ISO Toolkit keep-alive bot.

🤖 Commands:
/check - Check if site is online
/wake - Wake up the site
/status - Show bot status
/stats - Show ping statistics
/help - Show this help message

⏰ I'll automatically ping the site every 10 minutes to keep it alive.
    """
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    help_text = """
🤖 Available Commands:

/check - Check if site is online
/wake - Wake up the site
/status - Show current bot and site status
/stats - Show ping statistics
/help - Show this help message

The bot automatically pings the site every 10 minutes to prevent Render from spinning it down.
    """
    await update.message.reply_text(help_text)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if the site is online."""
    msg = await update.message.reply_text("🔍 Checking site status...")

    success, message, status_code = await ping_site()

    if success:
        await msg.edit_text(
            f"✅ {TARGET_URL}\n"
            f"Status: {message}\n"
            f"HTTP Code: {status_code}\n"
            f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        await msg.edit_text(
            f"❌ {TARGET_URL}\n"
            f"Error: {message}\n"
            f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"💡 The site may be spinning up. Try again in 30 seconds."
        )


async def wake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Wake up the site by pinging it."""
    msg = await update.message.reply_text("⏰ Waking up the site...")

    # First ping to wake it up
    success1, message1, code1 = await ping_site()

    if success1:
        await msg.edit_text(
            f"✅ Site is awake!\n"
            f"{TARGET_URL}\n"
            f"HTTP: {code1}\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        # Wait a bit and try again
        await asyncio.sleep(5)
        success2, message2, code2 = await ping_site()

        if success2:
            await msg.edit_text(
                f"✅ Site is now awake!\n"
                f"{TARGET_URL}\n"
                f"HTTP: {code2}\n"
                f"Time: {datetime.now().strftime('%H:%M:%S')}"
            )
        else:
            await msg.edit_text(
                f"❌ Failed to wake site\n"
                f"Error: {message2}\n"
                f"💡 Site may be down. Check Render dashboard."
            )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot status."""
    success, message, status_code = await ping_site()

    status_text = f"""
🤖 Bot Status:
━━━━━━━━━━━━━━━━
Target: {TARGET_URL}
Auto-ping: Every 10 minutes
━━━━━━━━━━━━━━━━
Current Status: {'🟢 Online' if success else '🔴 Offline'}
HTTP Code: {status_code if status_code else 'N/A'}
Last Check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    await update.message.reply_text(status_text)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show ping statistics."""
    # Get stats from context
    stats = context.bot_data.get('stats', {'total': 0, 'success': 0, 'failed': 0})

    success_rate = (stats['success']/stats['total']*100) if stats['total'] > 0 else 0

    stats_text = f"""
📊 Ping Statistics:
━━━━━━━━━━━━━━━━
Total Pings: {stats['total']}
Successful: {stats['success']} ✅
Failed: {stats['failed']} ❌
Success Rate: {success_rate:.1f}%
Uptime: {'🟢 Good' if stats['failed'] < stats['total'] * 0.1 else '🟡 Check dashboard'}
    """
    await update.message.reply_text(stats_text)


async def auto_ping_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Background job that pings the site every 10 minutes.
    """
    logger.info("Running auto-ping...")
    success, message, status_code = await ping_site()

    # Update stats
    stats = context.bot_data.get('stats', {'total': 0, 'success': 0, 'failed': 0})
    stats['total'] += 1
    if success:
        stats['success'] += 1
        logger.info(f"✅ Auto-ping successful: HTTP {status_code}")
    else:
        stats['failed'] += 1
        logger.warning(f"❌ Auto-ping failed: {message}")

    context.bot_data['stats'] = stats

    # Send notification to owner if failed
    if not success:
        try:
            owner_chat_id = os.getenv('OWNER_CHAT_ID')
            if owner_chat_id:
                await context.bot.send_message(
                    chat_id=owner_chat_id,
                    text=f"⚠️ Auto-ping failed!\n\nError: {message}\n\nSite may be down. Check Render dashboard."
                )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Initialize stats
    application.bot_data['stats'] = {'total': 0, 'success': 0, 'failed': 0}

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("wake", wake_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", stats_command))

    # Register auto-ping job (every 10 minutes)
    application.job_queue.run_repeating(
        auto_ping_job,
        interval=PING_INTERVAL,
        first=10,
    )

    # Start the bot
    logger.info("Bot started. Auto-pinging every 10 minutes.")
    logger.info(f"Target URL: {TARGET_URL}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
