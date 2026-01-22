"""
Enhanced Telegram bot for ISO Toolkit.
Features: Keep-alive pings + ISO file hosting (Telegram + PixelDrain)
"""

import asyncio
import logging
import os
import base64
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update, Document
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import aiohttp

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_URL = os.getenv("TARGET_URL", "https://iso-toolkit.onrender.com/")
API_URL = os.getenv("API_URL", "https://iso-toolkit.onrender.com/api")
API_KEY = os.getenv("API_KEY", "")
PIXELDRAIN_API_KEY = os.getenv("PIXELDRAIN_API_KEY", "")
PING_INTERVAL = 600  # 10 minutes

# Admin chat IDs (comma-separated)
ADMIN_IDS = set()
if admin_ids_str := os.getenv("ADMIN_CHAT_IDS", ""):
    ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip())

# Validate
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN required!")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ============================================================================
# KEEP-ALIVE FUNCTIONS (Original)
# ============================================================================

async def ping_site() -> tuple[bool, str, int]:
    """Ping target site. Returns (success, message, status_code)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                TARGET_URL,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                return True, "Site is online", response.status
    except asyncio.TimeoutError:
        return False, "Request timed out", 0
    except Exception as e:
        return False, str(e), 0


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show welcome message."""
    user = update.effective_user
    is_admin = update.effective_user.id in ADMIN_IDS if ADMIN_IDS else False

    msg = f"""
👋 Hi {user.first_name}!

I'm your ISO Toolkit bot.

{'🔐 **Admin Mode**' if is_admin else ''}

**Commands:**
/check - Check site status
/wake - Wake up the site
/status - Show status
/stats - Show statistics

**ISO Hosting (Admin only):**
/upload - Upload ISO to host (reply to file)
/info - Get file info (reply to file)
/list - List hosted ISOs
/help - Show help

⏰ Auto-ping every 10 min.
    """
    await update.message.reply_text(msg)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if site is online."""
    msg = await update.message.reply_text("🔍 Checking...")

    success, message, status_code = await ping_site()

    if success:
        await msg.edit_text(
            f"✅ {TARGET_URL}\n"
            f"Status: {message}\n"
            f"HTTP: {status_code}\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        await msg.edit_text(
            f"❌ {TARGET_URL}\n"
            f"Error: {message}\n"
            f"Time: {datetime.now().strftime('%H:%M:%S')}"
        )


# ============================================================================
# ISO HOSTING FUNCTIONS
# ============================================================================

def is_admin(update: Update) -> bool:
    """Check if user is admin."""
    if not ADMIN_IDS:
        return True  # No restrictions if no admin IDs set
    return update.effective_user.id in ADMIN_IDS


def format_size(bytes: int) -> str:
    """Format bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} PB"


async def upload_to_pixeldrain(
    file_path: str,
    filename: str
) -> Dict[str, Any]:
    """Upload file to PixelDrain."""
    if not PIXELDRAIN_API_KEY:
        return {"success": False, "error": "No API key"}

    credentials = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}

    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("file", f, filename=filename)

                async with session.post(
                    "https://pixeldrain.com/api/file",
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=3600)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        file_id = result.get("id")
                        return {
                            "success": True,
                            "file_id": file_id,
                            "download_url": f"https://pixeldrain.com/api/file/{file_id}",
                            "view_url": f"https://pixeldrain.com/u/{file_id}",
                            "size": result.get("size", 0)
                        }
                    else:
                        error = await response.text()
                        return {"success": False, "error": f"HTTP {response.status}: {error}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def register_iso_with_server(
    iso_id: str,
    platform: str,
    file_id: str,
    download_url: str,
    name: str,
    size: int
) -> bool:
    """Register hosted ISO with main server."""
    if not API_KEY:
        logger.warning("No API_KEY - skipping server registration")
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_URL}/admin/hosted-iso",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "iso_id": iso_id,
                    "platform": platform,
                    "file_id": file_id,
                    "download_url": download_url,
                    "file_name": name,
                    "file_size": size,
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                return response.status == 200
    except Exception as e:
        logger.error(f"Failed to register with server: {e}")
        return False


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ISO upload - reply to a document."""
    if not is_admin(update):
        await update.message.reply_text("❌ Admin only command")
        return

    # Check if replying to a document
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "📎 Reply to an ISO file with /upload to host it.\n\n"
            "Usage: Send an ISO file, then reply to it with:\n"
            "/upload <name> <version> <arch>\n"
            "Example: /upload Windows 10 22H2 x64"
        )
        return

    replied_msg = update.message.reply_to_message
    document = replied_msg.document

    if not document:
        await update.message.reply_text("❌ Not a file. Reply to a document/ISO file.")
        return

    # Parse ISO info from args
    args = context.args or []
    if len(args) >= 3:
        name = args[0]
        version = args[1]
        arch = args[2]
    else:
        # Try to extract from filename
        filename = document.file_name
        name = "Windows"
        version = "Unknown"
        arch = "x64"
        await update.message.reply_text(
            f"📝 Using defaults:\n"
            f"Name: {name}\n"
            f"Version: {version}\n"
            f"Arch: {arch}\n\n"
            f"Specify custom: /upload <name> <version> <arch>"
        )

    file_size = document.file_size
    size_gb = file_size / (1024**3)

    msg = await update.message.reply_text(
        f"📦 Processing: {document.file_name}\n"
        f"📏 Size: {format_size(file_size)}\n\n"
        f"⏳ Starting upload..."
    )

    # Choose platform based on size
    # Telegram Premium: 8GB limit
    # PixelDrain: No limit
    use_pixeldrain = file_size > 7 * 1024**3  # > 7GB

    if use_pixeldrain and not PIXELDRAIN_API_KEY:
        await msg.edit_text(
            f"⚠️ File is {size_gb:.1f}GB (>7GB)\n"
            f"Requires PixelDrain, but no API key configured.\n\n"
            f"Set PIXELDRAIN_API_KEY environment variable."
        )
        return

    try:
        # Download file from Telegram
        await msg.edit_text(f"⬇️ Downloading from Telegram...")

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".iso")
        temp_path = temp_file.name
        temp_file.close()

        file = await document.get_file()
        await file.download_to_drive(temp_path)

        # Upload to chosen platform
        if use_pixeldrain:
            await msg.edit_text(f"☁️ Uploading to PixelDrain...\n\n"
                               f"This may take a while for large files.")
            result = await upload_to_pixeldrain(temp_path, document.file_name)
            platform = "pixeldrain"
        else:
            await msg.edit_text(f"☁️ Using Telegram hosting...")
            # For Telegram, the file_id is already available
            result = {
                "success": True,
                "file_id": document.file_id,
                "download_url": f"tg://{document.file_id}",
                "size": file_size
            }
            platform = "telegram"

        # Clean up temp file
        os.unlink(temp_path)

        if not result.get("success"):
            await msg.edit_text(f"❌ Upload failed:\n{result.get('error', 'Unknown error')}")
            return

        # Generate ISO ID
        iso_id = f"{platform}_{name.lower().replace(' ', '_')}_{version.lower().replace(' ', '_')}_{arch.lower()}"

        # Register with server
        await register_iso_with_server(
            iso_id=iso_id,
            platform=platform,
            file_id=result["file_id"],
            download_url=result.get("download_url", ""),
            name=document.file_name,
            size=file_size
        )

        await msg.edit_text(
            f"✅ Upload successful!\n\n"
            f"📁 File: {document.file_name}\n"
            f"📏 Size: {format_size(file_size)}\n"
            f"🌐 Platform: {platform.upper()}\n"
            f"🆔 ID: {result.get('file_id', 'N/A')[:30]}...\n\n"
            f"Registered with server as: {iso_id}"
        )

    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Upload error: {e}", exc_info=True)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get file info."""
    if not is_admin(update):
        await update.message.reply_text("❌ Admin only")
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("📎 Reply to a file to get info.")
        return

    doc = update.message.reply_to_message.document

    # Truncate file ID for display to avoid Markdown parsing issues
    file_id_short = doc.file_id[:30] + "..." if len(doc.file_id) > 30 else doc.file_id

    info = f"""
📄 File Information

📁 Name: {doc.file_name}
📏 Size: {format_size(doc.file_size)}
🆔 File ID: {file_id_short}
📊 MIME Type: {doc.mime_type}

📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    await update.message.reply_text(info)  # Removed parse_mode to avoid Markdown errors


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List hosted ISOs."""
    if not is_admin(update):
        await update.message.reply_text("❌ Admin only")
        return

    if not API_KEY:
        await update.message.reply_text("⚠️ No API_KEY configured")
        return

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_URL}/admin/hosted-iso",
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    isos = data.get("isos", [])

                    if not isos:
                        await update.message.reply_text("📭 No hosted ISOs found.")
                        return

                    msg = "📦 Hosted ISOs:\n\n"
                    for iso in isos[:10]:  # Limit to 10
                        msg += f"• {iso.get('name', 'Unknown')} ({iso.get('platform', 'unknown')})\n"
                        msg += f"  {format_size(iso.get('file_size', 0))}\n"

                    if len(isos) > 10:
                        msg += f"\n... and {len(isos) - 10} more"

                    await update.message.reply_text(msg)  # Removed parse_mode to avoid Markdown errors
                else:
                    await update.message.reply_text(f"❌ Server error: HTTP {response.status}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def auto_ping_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Background auto-ping job."""
    logger.info("Running auto-ping...")
    success, message, status_code = await ping_site()

    stats = context.bot_data.get('stats', {'total': 0, 'success': 0, 'failed': 0})
    stats['total'] += 1
    if success:
        stats['success'] += 1
        logger.info(f"✅ Auto-ping successful: HTTP {status_code}")
    else:
        stats['failed'] += 1
        logger.warning(f"❌ Auto-ping failed: {message}")

    context.bot_data['stats'] = stats


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data['stats'] = {'total': 0, 'success': 0, 'failed': 0}

    # Keep-alive commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("wake", check_command))
    application.add_handler(CommandHandler("status", check_command))
    application.add_handler(CommandHandler("stats", check_command))

    # ISO hosting commands
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("list", list_command))

    # Auto-ping job
    application.job_queue.run_repeating(
        auto_ping_job,
        interval=PING_INTERVAL,
        first=10,
    )

    logger.info("Bot started with ISO hosting support!")
    logger.info(f"Target: {TARGET_URL}")
    logger.info(f"Admin IDs: {ADMIN_IDS if ADMIN_IDS else 'None (open)'}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
