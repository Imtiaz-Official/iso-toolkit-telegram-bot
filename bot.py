"""
Telegram bot to keep Render site alive with auto-ping and manual controls.
Plus ISO file hosting functionality.
"""

import asyncio
import logging
import os
import json
from datetime import datetime
from typing import Final, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import aiohttp

# Configuration from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_URL = os.getenv("TARGET_URL", "https://iso-toolkit.onrender.com/")
API_URL = os.getenv("API_URL", "https://iso-toolkit.onrender.com/api")
API_KEY = os.getenv("API_KEY", "")  # API key for authentication
PING_INTERVAL = 600  # 10 minutes in seconds

# URLs to keep alive
PING_TARGETS = [
    TARGET_URL,
    "https://modringsbot.onrender.com/"
]

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

# Admin user IDs (comma-separated in env)
ADMIN_IDS = set()
if admin_ids_str := os.getenv("ADMIN_CHAT_IDS", ""):
    ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip())


async def ping_site(url: str) -> tuple[bool, str, int]:
    """
    Ping the target site and return status.
    Returns: (success, message, status_code)
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
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
    is_admin = update.effective_user.id in ADMIN_IDS if ADMIN_IDS else False

    welcome_message = f"""
👋 Hi {user.first_name}!

I'm your ISO Toolkit bot.

{'🔐 **Admin Mode Enabled**' if is_admin else ''}

🤖 Commands:
/check - Check if site is online
/wake - Wake up the site
/status - Show bot status
/stats - Show ping statistics
{'/upload - Upload an ISO file (reply to file)' if is_admin else ''}
{'/list - List hosted ISOs' if is_admin else ''}
{'/info - Get ISO file info (reply to file)' if is_admin else ''}
/help - Show this help message

⏰ I'll automatically ping {len(PING_TARGETS)} sites every 10 minutes to keep them alive.
    """
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    help_text = f"""
🤖 Available Commands:

/check - Check if sites are online
/wake - Wake up the sites
/status - Show current bot and site status
/stats - Show ping statistics
/help - Show this help message

The bot automatically pings {len(PING_TARGETS)} sites every 10 minutes to prevent Render from spinning them down.
    """
    await update.message.reply_text(help_text)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if the sites are online."""
    msg = await update.message.reply_text("🔍 Checking site status...")

    results = []
    for url in PING_TARGETS:
        success, message, status_code = await ping_site(url)
        if success:
            results.append(f"✅ {url}\nStatus: {message}\nHTTP Code: {status_code}")
        else:
            results.append(f"❌ {url}\nError: {message}")

    await msg.edit_text(
        "\n\n".join(results) + 
        f"\n\nChecked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def wake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Wake up the sites by pinging them."""
    msg = await update.message.reply_text("⏰ Waking up sites...")

    results = []
    for url in PING_TARGETS:
        success1, message1, code1 = await ping_site(url)
        if success1:
            results.append(f"✅ {url} is awake (HTTP {code1})")
        else:
            # Wait a bit and try again
            await asyncio.sleep(2)
            success2, message2, code2 = await ping_site(url)
            if success2:
                results.append(f"✅ {url} is now awake (HTTP {code2})")
            else:
                results.append(f"❌ Failed to wake {url}: {message2}")

    await msg.edit_text(
        "Wake result:\n\n" + 
        "\n".join(results) + 
        f"\n\nTime: {datetime.now().strftime('%H:%M:%S')}"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot status."""
    status_text = f"""
🤖 Bot Status:
━━━━━━━━━━━━━━━━
Targets ({len(PING_TARGETS)}):
"""
    for url in PING_TARGETS:
        success, _, _ = await ping_site(url)
        status_text += f"{'🟢' if success else '🔴'} {url}\n"

    status_text += f"""
Auto-ping: Every 10 minutes
━━━━━━━━━━━━━━━━
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
Uptime: {'🟢 Good' if stats['failed'] < stats['total'] * 0.1 else '🟡 Check targets'}
    """
    await update.message.reply_text(stats_text)


async def auto_ping_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Background job that pings the sites every 10 minutes.
    """
    logger.info(f"Running auto-ping for {len(PING_TARGETS)} targets...")
    
    stats = context.bot_data.get('stats', {'total': 0, 'success': 0, 'failed': 0})
    
    for url in PING_TARGETS:
        success, message, status_code = await ping_site(url)
        stats['total'] += 1
        if success:
            stats['success'] += 1
            logger.info(f"✅ Auto-ping successful for {url}: HTTP {status_code}")
        else:
            stats['failed'] += 1
            logger.warning(f"❌ Auto-ping failed for {url}: {message}")

            # Send notification to owner if failed
            try:
                owner_chat_id = os.getenv('OWNER_CHAT_ID')
                if owner_chat_id:
                    await context.bot.send_message(
                        chat_id=owner_chat_id,
                        text=f"⚠️ Auto-ping failed for {url}!\n\nError: {message}\n\nSite may be down."
                    )
            except Exception as e:
                logger.error(f"Failed to send alert for {url}: {e}")

    context.bot_data['stats'] = stats


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
