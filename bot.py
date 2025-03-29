import os
import time
import asyncio
import subprocess
import re
import logging
from datetime import timedelta
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
import tempfile
import threading
import http.server
import socketserver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration from environment variables with fallback to hardcoded values
API_ID = int(os.environ.get("API_ID", "28271744"))
API_HASH = os.environ.get("API_HASH", "1df4d2b4dc77dc5fd65622f9d8f6814d")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7466186150:AAH3OyHD5MUYW6YzPfQHFtL-uZUHNNDZKBM")
PORT = int(os.environ.get("PORT", 8080))  # Get port from environment or default to 8080
# Initialize the Pyrogram client
app = Client("screenshot_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Store user states (waiting for screenshot count input)
user_states = {}

# Maximum file size for direct download (10MB)
MAX_DIRECT_DOWNLOAD_SIZE = 10 * 1024 * 1024

# Maximum number of screenshots
MAX_SCREENSHOTS = 15

# Theme colors (using Telegram markdown)
COLORS = {
    "primary": "**",       # Bold
    "secondary": "__",     # Italic
    "accent": "`",         # Monospace
    "error": "**",         # Bold
    "success": "**",       # Bold
    "warning": "__",       # Italic
}

# Helper function to apply color
def color(text, color_type):
    return f"{COLORS[color_type]}{text}{COLORS[color_type]}"

# Helper function to create section
def create_section(title, content):
    return f"{color(title, 'primary')}\n{content}\n"

# Check if FFmpeg is installed
def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.error("FFmpeg is not installed or not in PATH")
        return False

@app.on_message(filters.command("start"))
async def start_command(client, message):
    """Handle the /start command."""
    user_name = message.from_user.first_name
    
    # Create welcome message
    welcome_text = (
        f"{color(f'Welcome, {user_name}!', 'primary')}\n\n"
        f"I'm your {color('Screenshot Generator Bot', 'accent')}. I can create screenshots from any video you send me.\n\n"
        f"{color('How to use me:', 'secondary')}\n"
        f"1. Send me a video file\n"
        f"2. Tell me how many screenshots you want (1-15)\n"
        f"3. I'll generate high-quality screenshots for you!\n\n"
        f"Type /help to see all available commands."
    )
    
    # Create keyboard with buttons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Help", callback_data="help"),
            InlineKeyboardButton("Examples", callback_data="examples")
        ]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_callback_query()
async def handle_callback(client, callback_query):
    """Handle callback queries from inline buttons."""
    try:
        # Answer the callback query immediately to prevent expiration
        await callback_query.answer()
        
        data = callback_query.data
        
        if data == "help":
            help_text = (
                f"{color('Available Commands', 'primary')}\n\n"
                f"/start - Start the bot\n"
                f"/help - Show this help message\n"
                f"/about - Information about the bot\n\n"
                f"{color('Tips & Tricks:', 'secondary')}\n"
                f"• For best results, send high-quality videos\n"
                f"• You can request up to {MAX_SCREENSHOTS} screenshots per video\n"
                f"• Large videos may take longer to process\n"
                f"• Screenshots are taken at equal intervals throughout the video"
            )
            await callback_query.message.edit_text(help_text)
            
        elif data == "examples":
            examples_text = (
                f"{color('How Screenshots Work', 'primary')}\n\n"
                f"When you send a video and request 5 screenshots, I'll:\n"
                f"1. Analyze your video's duration\n"
                f"2. Take 5 screenshots at equal intervals\n"
                f"3. Send them back with timestamps\n\n"
                f"{color('Example:', 'secondary')}\n"
                f"For a 10-minute video with 5 screenshots:\n"
                f"• Screenshot 1: at 1:00\n"
                f"• Screenshot 2: at 3:00\n"
                f"• Screenshot 3: at 5:00\n"
                f"• Screenshot 4: at 7:00\n"
                f"• Screenshot 5: at 9:00"
            )
            await callback_query.message.edit_text(examples_text)
        
        elif data.startswith("count_"):
            await handle_count_callback(client, callback_query)
        
        elif data == "process_another":
            await callback_query.message.reply_text(
                f"{color('Ready For Another Video', 'primary')}\n\n"
                f"Send me another video file to generate screenshots!"
            )
        
        elif data.startswith("feedback_"):
            feedback_type = data.split("_")[1]
            if feedback_type == "positive":
                await callback_query.message.edit_text(
                    f"{color('Thank You!', 'success')}\n\n"
                    f"I'm glad you liked the screenshots! Feel free to send another video anytime."
                )
            else:
                await callback_query.message.edit_text(
                    f"{color('Feedback Received', 'warning')}\n\n"
                    f"I'm sorry you experienced issues. Your feedback helps me improve.\n\n"
                    f"Please try again with a different video or contact my developer."
                )
    except Exception as e:
        logger.error(f"Error handling callback: {e}")
        # Don't try to answer the callback query again if there's an error

@app.on_message(filters.command("help"))
async def help_command(client, message):
    """Handle the /help command."""
    help_text = (
        f"{color('Available Commands', 'primary')}\n\n"
        f"/start - Start the bot\n"
        f"/help - Show this help message\n"
        f"/about - Information about the bot\n\n"
        f"{color('How to use:', 'secondary')}\n"
        f"1. Send me a video file\n"
        f"2. I'll show you the file details\n"
        f"3. Tell me how many screenshots you want (1-{MAX_SCREENSHOTS})\n"
        f"4. I'll generate and send the screenshots\n\n"
        f"{color('Note:', 'accent')} For large files, the download may take some time. Please be patient."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Examples", callback_data="examples")]
    ])
    
    await message.reply_text(help_text, reply_markup=keyboard)

@app.on_message(filters.command("about"))
async def about_command(client, message):
    """Handle the /about command."""
    about_text = (
        f"{color('Screenshot Generator Bot', 'primary')}\n\n"
        f"A bot that generates high-quality screenshots from your videos.\n\n"
        f"{color('Features:', 'secondary')}\n"
        f"• Extract screenshots from any video\n"
        f"• Choose how many screenshots you want (up to {MAX_SCREENSHOTS})\n"
        f"• Get timestamps for each screenshot\n"
        f"• Support for large video files\n\n"
        f"{color('Version:', 'accent')} 2.2"
    )
    
    await message.reply_text(about_text)

async def animated_progress(status_message, action, total_steps):
    """Display a box-style progress indicator."""
    frames = ["⬜⬜⬜⬜", "⬛⬜⬜⬜", "⬛⬛⬜⬜", "⬛⬛⬛⬜", "⬛⬛⬛⬛"]
    frame_count = len(frames)
    
    for i in range(total_steps):
        frame = frames[min(i % frame_count, frame_count - 1)]
        try:
            await status_message.edit_text(f"{color(action, 'primary')}\n\n{frame} ({i+1}/{total_steps})")
            await asyncio.sleep(0.3)
        except MessageNotModified:
            # Message content was not modified, skip this update
            pass
        except Exception as e:
            logger.error(f"Error updating animation: {e}")
            break

def create_progress_bar(current, total, bar_length=20):
    """Create a box-style progress bar."""
    progress = min(1.0, current / total) if total > 0 else 0
    filled_length = int(bar_length * progress)
    
    # Use box-drawing characters for progress bar
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    percent = int(progress * 100)
    return f"[{bar}] {percent}%"

@app.on_message(filters.video | filters.document)
async def handle_file(client, message):
    """Handle incoming video or document files."""
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    
    # Send a processing message
    status_message = await message.reply_text(f"{color('Analyzing file...', 'primary')}")
    
    # Show box-style progress while analyzing
    analysis_task = asyncio.create_task(
        animated_progress(status_message, "Analyzing file", 5)
    )
    
    try:
        # Check if it's a video
        if message.video:
            # Cancel the animation task
            analysis_task.cancel()
            
            file_id = message.video.file_id
            file_name = message.video.file_name or "video.mp4"
            file_size = message.video.file_size
            duration = message.video.duration
            file_type = "Video"
            
            # Format duration as HH:MM:SS
            duration_formatted = str(timedelta(seconds=duration))
            
            # Format file size in MB
            file_size_mb = file_size / (1024 * 1024)
            
            # Warn if file is large
            size_warning = ""
            if file_size > MAX_DIRECT_DOWNLOAD_SIZE:
                size_warning = f"\n\n{color('This is a large file. Download may take some time.', 'warning')}"
            
            # Create file details message
            file_details = (
                f"{color('File Details', 'primary')}\n\n"
                f"Name: {file_name}\n"
                f"Size: {file_size_mb:.2f} MB\n"
                f"Duration: {duration_formatted}\n"
                f"Type: {file_type}{size_warning}\n\n"
                f"{color('How many screenshots would you like?', 'accent')} (Enter a number between 1-{MAX_SCREENSHOTS})"
            )
            
            # Create keyboard with quick number selection
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("1", callback_data="count_1"),
                    InlineKeyboardButton("3", callback_data="count_3"),
                    InlineKeyboardButton("5", callback_data="count_5")
                ],
                [
                    InlineKeyboardButton("10", callback_data="count_10"),
                    InlineKeyboardButton("15", callback_data="count_15")
                ]
            ])
            
            await status_message.edit_text(file_details, reply_markup=keyboard)
            
            # Store the file info for later use
            user_states[chat_id] = {
                "waiting_for_count": True,
                "file_id": file_id,
                "file_name": file_name,
                "duration": duration,
                "file_size": file_size,
                "is_video": True,
                "message_id": message.id  # Store original message ID for alternative download
            }
            
        # Check if it's a document
        elif message.document:
            # Cancel the animation task
            analysis_task.cancel()
            
            file_id = message.document.file_id
            file_name = message.document.file_name or "document"
            file_size = message.document.file_size
            file_type = "Document"
            
            # Format file size in MB
            file_size_mb = file_size / (1024 * 1024)
            
            # Check if document is a video by mime type
            mime_type = message.document.mime_type
            is_video = mime_type and mime_type.startswith("video/")
            
            # Warn if file is large
            size_warning = ""
            if file_size > MAX_DIRECT_DOWNLOAD_SIZE:
                size_warning = f"\n\n{color('This is a large file. Download may take some time.', 'warning')}"
            
            if is_video:
                # Create file details message
                file_details = (
                    f"{color('File Details', 'primary')}\n\n"
                    f"Name: {file_name}\n"
                    f"Size: {file_size_mb:.2f} MB\n"
                    f"Type: {file_type} (Video){size_warning}\n\n"
                    f"{color('How many screenshots would you like?', 'accent')} (Enter a number between 1-{MAX_SCREENSHOTS})"
                )
                
                # Create keyboard with quick number selection
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("1", callback_data="count_1"),
                        InlineKeyboardButton("3", callback_data="count_3"),
                        InlineKeyboardButton("5", callback_data="count_5")
                    ],
                    [
                        InlineKeyboardButton("10", callback_data="count_10"),
                        InlineKeyboardButton("15", callback_data="count_15")
                    ]
                ])
                
                await status_message.edit_text(file_details, reply_markup=keyboard)
                
                # Store the file info for later use
                user_states[chat_id] = {
                    "waiting_for_count": True,
                    "file_id": file_id,
                    "file_name": file_name,
                    "file_size": file_size,
                    "is_video": True,
                    "is_document": True,
                    "message_id": message.id  # Store original message ID for alternative download
                }
            else:
                error_message = (
                    f"{color('Unsupported File', 'error')}\n\n"
                    f"Name: {file_name}\n"
                    f"Size: {file_size_mb:.2f} MB\n"
                    f"Type: {file_type}\n\n"
                    #f"{color(\"This doesn't appear to be a video file.\", 'warning')} I can only generate screenshots from videos."
                )
                
                await status_message.edit_text(error_message)
    except Exception as e:
        # Cancel the animation task if it's still running
        if not analysis_task.done():
            analysis_task.cancel()
            
        logger.error(f"Error handling file: {e}")
        error_message = (
            f"{color('Error', 'error')}\n\n"
            f"I couldn't process this file: {str(e)}\n\n"
            f"Please try again with a different file."
        )
        await status_message.edit_text(error_message)

async def handle_count_callback(client, callback_query):
    """Handle screenshot count selection from inline keyboard."""
    chat_id = callback_query.message.chat.id
    count_match = re.match(r"count_(\d+)", callback_query.data)
    
    if count_match and chat_id in user_states and user_states[chat_id].get("waiting_for_count"):
        count = int(count_match.group(1))
        
        # Update user state
        user_states[chat_id]["waiting_for_count"] = False
        user_states[chat_id]["screenshot_count"] = count
        
        # Don't answer the callback query again, it's already answered in handle_callback
        
        # Update the message to show processing
        await callback_query.message.edit_text(
            f"{color('Processing', 'primary')}\n\n"
            f"Preparing to generate {count} screenshots...\n"
            f"This may take a moment."
        )
        
        # Process the video and generate screenshots
        await generate_screenshots(client, callback_query.message, chat_id)
    else:
        logger.warning("Invalid selection or timed out callback query")

@app.on_message(filters.text & filters.private)
async def handle_text(client, message):
    """Handle text messages (for screenshot count input)."""
    chat_id = message.chat.id
    
    # Check if we're waiting for screenshot count from this user
    if chat_id in user_states and user_states[chat_id].get("waiting_for_count"):
        try:
            count = int(message.text.strip())
            
            # Validate the count
            if count < 1 or count > MAX_SCREENSHOTS:
                await message.reply_text(
                    f"{color('Invalid Number', 'warning')}\n\n"
                    f"Please enter a number between 1 and {MAX_SCREENSHOTS}."
                )
                return
            
            # Update user state
            user_states[chat_id]["waiting_for_count"] = False
            user_states[chat_id]["screenshot_count"] = count
            
            # Send processing message
            processing_msg = await message.reply_text(
                f"{color('Processing', 'primary')}\n\n"
                f"Preparing to generate {count} screenshots...\n"
                f"This may take a moment."
            )
            
            # Process the video and generate screenshots
            await generate_screenshots(client, processing_msg, chat_id)
            
        except ValueError:
            await message.reply_text(
                f"{color('Invalid Input', 'warning')}\n\n"
                f"Please enter a valid number between 1 and {MAX_SCREENSHOTS}."
            )
        except Exception as e:
            logger.error(f"Error handling text input: {e}")
            await message.reply_text(
                f"{color('Error', 'error')}\n\n"
                f"An unexpected error occurred: {str(e)}\n"
                f"Please try again."
            )

async def progress_callback(current, total, status_message, action_text):
    """Update progress bar in status message."""
    try:
        # Only update every 5% to avoid API rate limits
        if total > 0:
            progress = current / total
            # Update on 5% increments or when complete
            if progress == 1.0 or int(progress * 20) > int((current - 1024) / total * 20):
                progress_bar = create_progress_bar(current, total)
                
                # Create a progress message
                progress_message = (
                    f"{color(action_text, 'primary')}\n\n"
                    f"{progress_bar}\n"
                    f"{current / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB"
                )
                
                await status_message.edit_text(progress_message)
    except MessageNotModified:
        # Message content was not modified, skip this update
        pass
    except Exception as e:
        logger.error(f"Error updating progress: {e}")

async def download_with_retry(client, file_id, file_path, status_message, max_retries=3):
    """Download file with retry logic."""
    retries = 0
    
    while retries < max_retries:
        try:
            # Update status message
            retry_text = f" (Attempt {retries+1}/{max_retries})" if retries > 0 else ""
            
            # Create download message
            download_message = (
                f"{color(f'Downloading video{retry_text}', 'primary')}\n\n"
                f"{create_progress_bar(0, 100)}\n"
                f"0.0 MB / ? MB"
            )
            
            await status_message.edit_text(download_message)
            
            # Define progress callback for download
            async def download_progress(current, total):
                await progress_callback(
                    current, total, status_message, f"Downloading video{retry_text}"
                )
            
            # Try to download with progress tracking
            await client.download_media(
                message=file_id,
                file_name=file_path,
                progress=download_progress
            )
            
            # Check if file exists and has content
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return True
            
            retries += 1
            
        except Exception as e:
            retries += 1
            logger.warning(f"Download error: {e}, retrying ({retries}/{max_retries})...")
            
            # Check if it's a timeout-related error
            if "timed out" in str(e).lower():
                timeout_message = (
                    f"{color('Download Timed Out', 'warning')}\n\n"
                    f"Retrying ({retries}/{max_retries})...\n"
                    f"This may happen with large files or slow connections."
                )
                await status_message.edit_text(timeout_message)
            elif isinstance(e, FloodWait):
                # Handle Telegram's flood wait
                wait_time = e.value
                logger.warning(f"FloodWait: Waiting for {wait_time} seconds")
                
                flood_message = (
                    f"{color('Rate Limit Reached', 'warning')}\n\n"
                    f"Telegram is asking us to wait for {wait_time} seconds before retrying.\n"
                    f"Please be patient..."
                )
                await status_message.edit_text(flood_message)
                await asyncio.sleep(wait_time)
            else:
                error_message = (
                    f"{color('Download Error', 'warning')}\n\n"
                    f"Error: {str(e)}\n"
                    f"Retrying ({retries}/{max_retries})..."
                )
                await status_message.edit_text(error_message)
            
            await asyncio.sleep(2)  # Wait before retrying
    
    return False

async def alternative_download(client, chat_id, message_id, file_path, status_message):
    """Alternative download method for large files."""
    try:
        alt_download_message = (
            f"{color('Alternative Download Method', 'primary')}\n\n"
            f"Using a different method for large file download.\n"
            f"This may take some time. Please be patient."
        )
        await status_message.edit_text(alt_download_message)
        
        # Show box-style progress while downloading
        download_task = asyncio.create_task(
            animated_progress(status_message, "Downloading large file", 10)
        )
        
        try:
            # Get the message with the file
            message = await client.get_messages(chat_id, message_id)
            
            # Download without progress tracking (more reliable for large files)
            await client.download_media(message, file_path)
            
            # Cancel the animation task
            download_task.cancel()
            
            # Check if file exists and has content
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                success_message = (
                    f"{color('Download Complete', 'success')}\n\n"
                    f"Successfully downloaded the file.\n"
                    f"Proceeding to generate screenshots..."
                )
                await status_message.edit_text(success_message)
                return True
            else:
                error_message = (
                    f"{color('Download Failed', 'error')}\n\n"
                    f"The file is empty or could not be downloaded.\n"
                    f"Please try again with a different video."
                )
                await status_message.edit_text(error_message)
                return False
        except Exception as e:
            # Cancel the animation task if it's still running
            if not download_task.done():
                download_task.cancel()
            raise e
            
    except Exception as e:
        logger.error(f"Alternative download error: {e}")
        
        error_message = (
            f"{color('Download Failed', 'error')}\n\n"
            f"Error: {str(e)}\n"
            f"Please try again with a different video."
        )
        await status_message.edit_text(error_message)
        return False

async def generate_screenshots(client, message, chat_id):
    """Generate and send screenshots from the video using FFmpeg."""
    # Check if FFmpeg is installed
    if not check_ffmpeg():
        await message.edit_text(
            f"{color('FFmpeg Not Found', 'error')}\n\n"
            f"FFmpeg is required to generate screenshots but it's not installed on the server.\n"
            f"Please contact the bot administrator."
        )
        return
    
    # Get user state
    state = user_states[chat_id]
    file_id = state["file_id"]
    screenshot_count = state["screenshot_count"]
    file_size = state.get("file_size", 0)
    original_message_id = state.get("message_id")
    
    # Send initial status message
    status_message = message
    if not isinstance(message, Message):
        status_message = await client.send_message(
            chat_id,
            f"{color('Preparing', 'primary')}\n\n"
            f"Getting ready to process your video..."
        )
    
    start_time = time.time()
    
    try:
        # Create a temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Prepare file path
            video_path = os.path.join(temp_dir, "video.mp4")
            
            # Try standard download with retry
            download_success = await download_with_retry(
                client, file_id, video_path, status_message
            )
            
            # If standard download fails and file is large, try alternative method
            if not download_success and file_size > MAX_DIRECT_DOWNLOAD_SIZE and original_message_id:
                download_success = await alternative_download(
                    client, chat_id, original_message_id, video_path, status_message
                )
            
            # Check if download was successful
            if not download_success or not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
                error_message = (
                    f"{color('Download Failed', 'error')}\n\n"
                    f"I couldn't download the video after multiple attempts.\n\n"
                    f"{color('Possible reasons:', 'secondary')}\n"
                    f"• File is too large\n"
                    f"• Network issues\n"
                    f"• Telegram server limitations\n\n"
                    f"Please try with a smaller video or try again later."
                )
                await status_message.edit_text(error_message)
                return
            
            # Update status for screenshot generation
            screenshot_message = (
                f"{color('Generating Screenshots', 'primary')}\n\n"
                f"{create_progress_bar(0, screenshot_count)}\n"
                f"0/{screenshot_count} screenshots"
            )
            await status_message.edit_text(screenshot_message)
            
            # Get video duration if not already available
            if "duration" not in state:
                try:
                    # Use FFprobe to get video duration
                    cmd = [
                        "ffprobe", 
                        "-v", "error", 
                        "-show_entries", "format=duration", 
                        "-of", "default=noprint_wrappers=1:nokey=1", 
                        video_path
                    ]
                    duration = float(subprocess.check_output(cmd).decode('utf-8').strip())
                    state["duration"] = duration
                except Exception as e:
                    logger.error(f"Error getting video duration: {e}")
                    duration = 0
            else:
                duration = state["duration"]
            
            if duration <= 0:
                error_message = (
                    f"{color('Error', 'error')}\n\n"
                    f"Could not determine video duration.\n"
                    f"The file might be corrupted or in an unsupported format."
                )
                await status_message.edit_text(error_message)
                return
            
            # Generate screenshots using FFmpeg
            screenshot_paths = []
            for i in range(screenshot_count):
                # Calculate timestamp for this screenshot (distribute evenly)
                timestamp = duration * (i + 0.5) / screenshot_count  # Add 0.5 to avoid very beginning/end
                
                # Format timestamp for FFmpeg (HH:MM:SS.mmm)
                timestamp_str = str(timedelta(seconds=timestamp))
                
                # Output path for this screenshot
                screenshot_path = os.path.join(temp_dir, f"screenshot_{i+1}.jpg")
                
                # FFmpeg command to extract the frame at the timestamp
                cmd = [
                    "ffmpeg",
                    "-ss", timestamp_str,
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "2",
                    screenshot_path
                ]
                
                # Run FFmpeg
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Check if screenshot was created
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                    screenshot_paths.append(screenshot_path)
                
                # Update progress bar
                progress_bar = create_progress_bar(i + 1, screenshot_count)
                
                # Create a progress message
                progress_message = (
                    f"{color('Generating Screenshots', 'primary')}\n\n"
                    f"{progress_bar}\n"
                    f"{i + 1}/{screenshot_count} screenshots"
                )
                
                await status_message.edit_text(progress_message)
                
                # Small delay to avoid API rate limits
                await asyncio.sleep(0.2)
            
            # Check if any screenshots were generated
            if not screenshot_paths:
                error_message = (
                    f"{color('Generation Failed', 'error')}\n\n"
                    f"Failed to generate any screenshots.\n"
                    f"The video file might be corrupted or in an unsupported format."
                )
                await status_message.edit_text(error_message)
                return
            
            # Update status for sending phase
            sending_message = (
                f"{color('Sending Screenshots', 'primary')}\n\n"
                f"{create_progress_bar(0, len(screenshot_paths))}\n"
                f"0/{len(screenshot_paths)} sent"
            )
            await status_message.edit_text(sending_message)
            
            # Send screenshots with progress updates
            for i, path in enumerate(screenshot_paths):
                # Calculate timestamp for this screenshot
                timestamp = timedelta(seconds=int(duration * (i + 0.5) / screenshot_count))
                
                try:
                    # Create a simple caption
                    caption = f"Screenshot {i+1}/{screenshot_count}\nTimestamp: {timestamp}"
                    
                    # Send the screenshot with timestamp caption
                    await client.send_photo(
                        chat_id=chat_id,
                        photo=path,
                        caption=caption
                    )
                    
                    # Update progress bar
                    progress_bar = create_progress_bar(i + 1, len(screenshot_paths))
                    
                    # Create a progress message
                    progress_message = (
                        f"{color('Sending Screenshots', 'primary')}\n\n"
                        f"{progress_bar}\n"
                        f"{i + 1}/{len(screenshot_paths)} sent"
                    )
                    
                    await status_message.edit_text(progress_message)
                except Exception as e:
                    logger.error(f"Error sending screenshot {i+1}: {e}")
                    
                    error_message = (
                        f"{color('Sending Error', 'warning')}\n\n"
                        f"Error sending screenshot {i+1}: {str(e)}\n"
                        f"Continuing with remaining screenshots..."
                    )
                    await status_message.edit_text(error_message)
                
                # Add a small delay to avoid flooding
                await asyncio.sleep(0.5)
            
            # Calculate total processing time
            total_time = time.time() - start_time
            
            # Final message with success
            success_message = (
                f"{color('Success!', 'success')}\n\n"
                f"Successfully generated and sent {len(screenshot_paths)} screenshots!\n\n"
                f"Processing Time: {total_time:.1f} seconds\n\n"
                f"Thank you for using the Screenshot Generator Bot."
            )
            
            # Create keyboard with feedback buttons
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👍 Great!", callback_data="feedback_positive"),
                    InlineKeyboardButton("👎 Issues", callback_data="feedback_negative")
                ],
                [
                    InlineKeyboardButton("Process Another Video", callback_data="process_another")
                ]
            ])
            
            await status_message.edit_text(success_message, reply_markup=keyboard)
            
            # Clean up user state
            if chat_id in user_states:
                del user_states[chat_id]
                
    except Exception as e:
        logger.error(f"Error generating screenshots: {e}")
        
        error_message = (
            f"{color('Error', 'error')}\n\n"
            f"An unexpected error occurred: {str(e)}\n\n"
            f"Please try again with a different video or contact the bot administrator."
        )
        await status_message.edit_text(error_message)
        
        # Clean up user state
        if chat_id in user_states:
            del user_states[chat_id]

# Create a simple HTTP server for Render
class SimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Screenshot Bot is running!')
        
    def log_message(self, format, *args):
        # Suppress log messages to avoid cluttering the console
        return

def run_server():
    """Run a simple HTTP server to keep Render happy."""
    handler = SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", PORT), handler)
    logger.info(f"Starting HTTP server on port {PORT}")
    httpd.serve_forever()

# Run the bot and HTTP server
if __name__ == "__main__":
    print(f"Starting Screenshot Bot with HTTP server on port {PORT}...")
    
    # Start HTTP server in a separate thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Run the bot
    app.run()
