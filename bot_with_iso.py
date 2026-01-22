"""
Enhanced Telegram bot for ISO Toolkit.
Features: Keep-alive pings + ISO file hosting (Telegram + PixelDrain)
"""

import asyncio
import json
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

# ============================================================================
# ACCESS CONTROL
# ============================================================================

# Owner ID - Only person who can use the bot initially
OWNER_ID = 1851080851

# Admin chat IDs (comma-separated) - DEPRECATED, use ALLOWED_USERS instead
ADMIN_IDS = set()
if admin_ids_str := os.getenv("ADMIN_CHAT_IDS", ""):
    ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip())

# Current PixelDrain folder for uploads (stored per user in bot_data)
CURRENT_FOLDER = {}  # {user_id: folder_name}

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
    user_id = user.id

    # Check authorization
    if not is_authorized(update, context):
        # Silently ignore unauthorized users
        return

    is_owner = user_id == OWNER_ID
    is_admin = user_id in ADMIN_IDS if ADMIN_IDS else False

    msg = f"""👋 Hi {user.first_name}!

I'm your ISO Toolkit bot.

{'👑 **Owner Mode**' if is_owner else ('🔐 **Admin Mode**' if is_admin else '')}

**Commands:**
/check - Check site status
/wake - Wake up the site
/status - Show status
/stats - Show statistics

**ISO Hosting:**
/upload - Upload ISO (reply to file)
/fetch - Fetch from URL & host (streaming)
/folder_create - Create folder on PixelDrain
/folder_list - List your PixelDrain folders
/folder_set - Set current folder for uploads
/info - Get file info (reply to file)
/list - List hosted ISOs

**Permission Management (Owner only):**
/allow <user_id> - Grant access to a user
/deny <user_id> - Revoke access from a user
/users - List all authorized users

⏰ Auto-ping every 10 min.
"""
    await update.message.reply_text(msg)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check if site is online."""
    if not is_authorized(update, context):
        return  # Silently ignore

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
    """Check if user is admin (DEPRECATED - use is_authorized instead)."""
    if not ADMIN_IDS:
        return True  # No restrictions if no admin IDs set
    return update.effective_user.id in ADMIN_IDS


def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if user is authorized to use the bot.

    Owner (1851080851) and users explicitly allowed by owner can use the bot.
    Unauthorized users receive no response (silent ignore).
    """
    user_id = update.effective_user.id

    # Owner always authorized
    if user_id == OWNER_ID:
        return True

    # Check if user is in allowed list (stored in bot_data)
    allowed_users = context.bot_data.get('allowed_users', set())
    if user_id in allowed_users:
        return True

    # Unauthorized - log and return False
    logger.info(f"Unauthorized access attempt by user_id: {user_id}, username: {update.effective_user.username}")
    return False


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
                    if response.status in [200, 201]:  # Accept both 200 and 201
                        # PixelDrain returns text/plain, parse as JSON manually
                        response_text = await response.text()
                        result = json.loads(response_text)
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
    if not is_authorized(update, context):
        return  # Silently ignore

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


async def fetch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Fetch ISO from URL and stream directly to PixelDrain (no disk storage).

    Usage: /fetch <url> <name> <version> <arch>
    Example: /fetch https://example.com/win10.iso Windows 10 22H2 x64
    """
    if not is_authorized(update, context):
        return  # Silently ignore

    args = context.args

    if len(args) < 4:
        await update.message.reply_text(
            "📥 Fetch ISO from URL\n\n"
            "Usage: /fetch <url> <name> <version> <arch>\n\n"
            "Example:\n"
            "/fetch https://example.com/windows10.iso Windows 10 22H2 x64\n\n"
            "The file will be streamed directly to PixelDrain (no disk storage).\n\n"
            "⏱️ Large files may take a while. Progress updates every 5 seconds."
        )
        return

    url = args[0]
    name = args[1]
    version = args[2]
    arch = args[3]

    # Validate URL
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Invalid URL. Must start with http:// or https://")
        return

    msg = await update.message.reply_text(
        f"📥 Initializing...\n\n"
        f"🌐 {url[:50]}{'...' if len(url) > 50 else ''}"
    )

    try:
        if not PIXELDRAIN_API_KEY:
            await msg.edit_text(
                "⚠️ PIXELDRAIN_API_KEY not configured!\n\n"
                "This feature requires PixelDrain for hosting.\n"
                "Get your API key from: https://pixeldrain.com/user/settings"
            )
            return

        # Step 1: Get file info from URL
        await msg.edit_text(
            f"📡 Checking file info...\n\n"
            f"🌐 {url[:50]}{'...' if len(url) > 50 else ''}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.head(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=True
            ) as response:
                if response.status != 200:
                    await msg.edit_text(f"❌ URL returned HTTP {response.status}")
                    return

                content_length = response.headers.get('Content-Length')
                file_size = int(content_length) if content_length else None
                filename = url.split('/')[-1].split('?')[0] or f"{name}_{version}_{arch}.iso"

                # Format initial progress message
                size_text = f"{format_size(file_size)}" if file_size else "Unknown size"
                await msg.edit_text(
                    f"📁 Ready to upload!\n\n"
                    f"📄 Name: {filename}\n"
                    f"📏 Size: {size_text}\n"
                    f"🌐 Target: PixelDrain\n\n"
                    f"⏳ Starting upload..."
                )

        # Step 2: Stream upload with progress tracking
        credentials = base64.b64encode(f":{PIXELDRAIN_API_KEY}".encode()).decode()
        headers_pd = {"Authorization": f"Basic {credentials}"}

        # For progress tracking
        start_time = datetime.now()
        last_update = start_time

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=3600)
            ) as download_response:
                if download_response.status != 200:
                    await msg.edit_text(f"❌ Download failed: HTTP {download_response.status}")
                    return

                # Read content for size tracking
                content = await download_response.read()
                actual_size = len(content)

                # Create FormData
                data = aiohttp.FormData()
                data.add_field(
                    "file",
                    content,
                    filename=filename,
                    content_type="application/octet-stream"
                )

                # Upload with progress simulation
                await msg.edit_text(
                    f"☁️ Uploading to PixelDrain...\n\n"
                    f"📄 {filename}\n"
                    f"📏 {format_size(actual_size)}\n\n"
                    f"⏳ Please wait..."
                )

                # Upload to PixelDrain
                async with session.post(
                    "https://pixeldrain.com/api/file",
                    data=data,
                    headers=headers_pd,
                    timeout=aiohttp.ClientTimeout(total=3600)
                ) as pd_response:
                    # Calculate elapsed time
                    elapsed = (datetime.now() - start_time).total_seconds()

                    if pd_response.status in [200, 201]:
                        # PixelDrain returns text/plain, parse as JSON manually
                        response_text = await pd_response.text()
                        result = json.loads(response_text)
                        file_id = result.get("id")
                        download_url = f"https://pixeldrain.com/api/file/{file_id}"
                        view_url = f"https://pixeldrain.com/u/{file_id}"
                        final_size = result.get("size", actual_size)

                        # Generate ISO ID
                        iso_id = f"pixeldrain_{name.lower().replace(' ', '_')}_{version.lower().replace(' ', '_')}_{arch.lower()}"

                        # Register with server
                        if API_KEY:
                            await register_iso_with_server(
                                iso_id=iso_id,
                                platform="pixeldrain",
                                file_id=file_id,
                                download_url=download_url,
                                name=filename,
                                size=final_size
                            )

                        # Calculate average speed
                        if elapsed > 0:
                            speed_bps = actual_size / elapsed
                            speed_text = format_size(int(speed_bps)) + "/s"
                        else:
                            speed_text = "N/A"

                        await msg.edit_text(
                            f"✅ Upload complete!\n\n"
                            f"📄 {filename}\n"
                            f"📏 {format_size(final_size)}\n"
                            f"⚡ Speed: {speed_text}\n"
                            f"⏱️ Time: {elapsed:.1f}s\n\n"
                            f"🌐 Platform: PIXELDRAIN\n"
                            f"🆔 ID: {file_id}\n\n"
                            f"🔗 {view_url}\n\n"
                            f"Registered: {iso_id}"
                        )

                        logger.info(f"Fetched from URL and uploaded to PixelDrain: {filename} ({speed_text}, {elapsed:.1f}s)")
                    else:
                        error_text = await pd_response.text()
                        await msg.edit_text(
                            f"❌ PixelDrain upload failed:\n"
                            f"HTTP {pd_response.status}\n\n"
                            f"{error_text[:200]}"
                        )

    except asyncio.TimeoutError:
        await msg.edit_text("❌ Timeout: Operation took too long")
        logger.error(f"Fetch timeout for URL: {url}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)[:200]}")
        logger.error(f"Fetch error: {e}", exc_info=True)


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get file info."""
    if not is_authorized(update, context):
        return  # Silently ignore

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
    if not is_authorized(update, context):
        return  # Silently ignore

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
# PIXELDRAIN FOLDER MANAGEMENT
# ============================================================================

async def folder_create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new folder on PixelDrain."""
    if not is_authorized(update, context):
        return  # Silently ignore

    if not PIXELDRAIN_API_KEY:
        await update.message.reply_text("⚠️ PIXELDRAIN_API_KEY not configured")
        return

    if not context.args:
        await update.message.reply_text(
            "📁 Create a new folder on PixelDrain\n\n"
            "Usage: /folder_create <folder_name>\n\n"
            "Example: /folder_create Windows ISOs\n\n"
            "The folder will be used for subsequent uploads."
        )
        return

    folder_name = " ".join(context.args)

    msg = await update.message.reply_text(
        f"📁 Creating folder: {folder_name}\n\n"
        f"⏳ Please wait..."
    )

    try:
        # PixelDrain doesn't have a folder API, so we simulate folders
        # by storing them in bot_data and prefixing file names
        user_id = update.effective_user.id

        if user_id not in CURRENT_FOLDER:
            CURRENT_FOLDER[user_id] = {}

        CURRENT_FOLDER[user_id][folder_name] = {
            "created_at": datetime.now().isoformat(),
            "file_count": 0
        }

        await msg.edit_text(
            f"✅ Folder created!\n\n"
            f"📁 Name: {folder_name}\n"
            f"👤 Created by: {update.effective_user.first_name}\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"💡 Uploads to this folder will be tagged with the folder name.\n"
            f"Use /folder_set to switch between folders."
        )

        logger.info(f"Created PixelDrain folder: {folder_name} by user {user_id}")

    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")
        logger.error(f"Folder creation error: {e}", exc_info=True)


async def folder_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all folders on PixelDrain."""
    if not is_authorized(update, context):
        return  # Silently ignore

    user_id = update.effective_user.id

    if user_id not in CURRENT_FOLDER or not CURRENT_FOLDER[user_id]:
        await update.message.reply_text(
            "📁 Your folders:\n\n"
            "No folders found.\n\n"
            "Create one with: /folder_create <name>"
        )
        return

    folders = CURRENT_FOLDER[user_id]

    msg = "📁 Your PixelDrain folders:\n\n"
    for folder_name, info in folders.items():
        msg += f"📂 {folder_name}\n"
        msg += f"   Files: {info['file_count']}\n"
        msg += f"   Created: {info['created_at']}\n\n"

    await update.message.reply_text(msg)


async def folder_set_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the current active folder for uploads."""
    if not is_authorized(update, context):
        return  # Silently ignore

    if not context.args:
        # Show current folder
        user_id = update.effective_user.id
        if user_id in CURRENT_FOLDER and CURRENT_FOLDER[user_id]:
            # Find current folder (one with most recent timestamp would be active)
            current = next(reversed(list(CURRENT_FOLDER[user_id].items())), None)
            if current:
                folder_name = current[0]
                await update.message.reply_text(
                    f"📁 Current folder: {folder_name}\n\n"
                    f"Use /folder_set <name> to switch folders."
                )
                return

        await update.message.reply_text(
            "📁 No folder is currently set.\n\n"
            "Create one with: /folder_create <name>\n"
            "Or list folders: /folder_list"
        )
        return

    folder_name = " ".join(context.args)
    user_id = update.effective_user.id

    if user_id not in CURRENT_FOLDER or folder_name not in CURRENT_FOLDER[user_id]:
        await update.message.reply_text(
            f"❌ Folder '{folder_name}' not found.\n\n"
            f"List folders with: /folder_list"
        )
        return

    # Set as current
    # In our implementation, the "current folder" is just the last accessed one
    # Move it to the end of the dict to make it "current"
    folder_data = CURRENT_FOLDER[user_id][folder_name]
    del CURRENT_FOLDER[user_id][folder_name]
    CURRENT_FOLDER[user_id][folder_name] = folder_data

    await update.message.reply_text(
        f"✅ Current folder set to: {folder_name}\n\n"
        f"Uploads will be tagged with this folder."
    )


# ============================================================================
# PERMISSION MANAGEMENT (Owner Only)
# ============================================================================

async def allow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Allow a user to access the bot. Owner only.

    Usage: /allow <user_id>
    Example: /allow 123456789
    """
    user_id = update.effective_user.id

    # Only owner can manage permissions
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command")
        return

    if not context.args:
        await update.message.reply_text(
            "🔓 Grant access to a user\n\n"
            "Usage: /allow <user_id>\n\n"
            "Example: /allow 123456789\n\n"
            "Get user ID from: @userinfobot or forward their message"
        )
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    # Initialize allowed_users set if not exists
    if 'allowed_users' not in context.bot_data:
        context.bot_data['allowed_users'] = set()

    allowed_users = context.bot_data['allowed_users']

    # Check if already allowed
    if target_user_id in allowed_users:
        await update.message.reply_text(f"✅ User {target_user_id} is already authorized.")
        return

    # Add to allowed list
    allowed_users.add(target_user_id)
    context.bot_data['allowed_users'] = allowed_users

    await update.message.reply_text(
        f"✅ User {target_user_id} has been granted access.\n\n"
        f"Total authorized users: {len(allowed_users) + 1}"  # +1 for owner
    )

    logger.info(f"Owner {user_id} granted access to user {target_user_id}")


async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Revoke access from a user. Owner only.

    Usage: /deny <user_id>
    Example: /deny 123456789
    """
    user_id = update.effective_user.id

    # Only owner can manage permissions
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command")
        return

    if not context.args:
        await update.message.reply_text(
            "🔒 Revoke access from a user\n\n"
            "Usage: /deny <user_id>\n\n"
            "Example: /deny 123456789"
        )
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    # Cannot deny owner
    if target_user_id == OWNER_ID:
        await update.message.reply_text("❌ Cannot revoke owner's access.")
        return

    allowed_users = context.bot_data.get('allowed_users', set())

    # Check if user is allowed
    if target_user_id not in allowed_users:
        await update.message.reply_text(f"❌ User {target_user_id} is not in the allowed list.")
        return

    # Remove from allowed list
    allowed_users.remove(target_user_id)
    context.bot_data['allowed_users'] = allowed_users

    await update.message.reply_text(
        f"✅ Access revoked from user {target_user_id}.\n\n"
        f"Total authorized users: {len(allowed_users) + 1}"  # +1 for owner
    )

    logger.info(f"Owner {user_id} revoked access from user {target_user_id}")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all authorized users. Owner only."""
    user_id = update.effective_user.id

    # Only owner can view users
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command")
        return

    allowed_users = context.bot_data.get('allowed_users', set())

    msg = f"👥 Authorized Users\n\n"
    msg += f"👑 Owner: {OWNER_ID}\n\n"

    if allowed_users:
        msg += f"✅ Allowed users ({len(allowed_users)}):\n"
        for uid in sorted(allowed_users):
            msg += f"   • {uid}\n"
    else:
        msg += "✅ No additional users allowed.\n"
        msg += "Use /allow <user_id> to grant access."

    await update.message.reply_text(msg)


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.bot_data['stats'] = {'total': 0, 'success': 0, 'failed': 0}
    application.bot_data['allowed_users'] = set()  # Initialize allowed users set

    # Keep-alive commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("wake", check_command))
    application.add_handler(CommandHandler("status", check_command))
    application.add_handler(CommandHandler("stats", check_command))

    # ISO hosting commands
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("fetch", fetch_command))
    application.add_handler(CommandHandler("folder_create", folder_create_command))
    application.add_handler(CommandHandler("folder_list", folder_list_command))
    application.add_handler(CommandHandler("folder_set", folder_set_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("list", list_command))

    # Permission management commands (Owner only)
    application.add_handler(CommandHandler("allow", allow_command))
    application.add_handler(CommandHandler("deny", deny_command))
    application.add_handler(CommandHandler("users", users_command))

    # Auto-ping job
    application.job_queue.run_repeating(
        auto_ping_job,
        interval=PING_INTERVAL,
        first=10,
    )

    logger.info("Bot started with ISO hosting support!")
    logger.info(f"Target: {TARGET_URL}")
    logger.info(f"Owner ID: {OWNER_ID}")
    logger.info(f"Admin IDs: {ADMIN_IDS if ADMIN_IDS else 'None (using access control)'}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
