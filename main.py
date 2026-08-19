# (DPX_ARMY_FF_01) Thank you from me to the haters
import os
import json
import aiohttp
import asyncio
import time
import logging
import traceback
import base64
import re
import shutil
import random
from datetime import datetime, timedelta, timezone
from html import escape
from collections import defaultdict

# Telegram Bot Library Imports
from telegram import Update, InputFile, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, Forbidden, BadRequest

# Environment Variable Loading
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()

# Essential: Get Bot Token
TOKEN = os.getenv('8738964867:AAF6uwcmXRImrVI91CEs_A4gCYxt36hhyi8')
if not TOKEN or TOKEN == "8738964867:AAF6uwcmXRImrVI91CEs_A4gCYxt36hhyi8":
    TOKEN = "8738964867:AAF6uwcmXRImrVI91CEs_A4gCYxt36hhyi8"

# API Configuration
API_BASE_URL = os.getenv('JWT_API_URL', 'https://frexy-jwt-gen.vercel.app/token')
API_KEY = os.getenv('JWT_API_KEY', '')

# --- UPDATED: Performance Settings ---
MAX_CONCURRENT_REQUESTS = 7           # 7 concurrent threads
MAX_RETRY_ATTEMPTS = 10               # 10 retry attempts per account
RETRY_TIMEOUT = 120                   # 120 seconds timeout per attempt (increased)

# --- NEW: Auto-Processing Settings ---
AUTO_PROCESS_INTERVAL_HOURS = 7       # 7 hours interval for auto-processing
AUTO_PROCESS_CHECK_INTERVAL = 300     # Check every 5 minutes (in seconds)

# Optional: Bot Settings
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 5 * 1024 * 1024))
ADMIN_ID = int(os.getenv('ADMIN_ID', 6417430059))
if ADMIN_ID == 6417430059:
    print("WARNING: ADMIN_ID environment variable is not set, invalid, or 0. Admin commands (/vip, /broadcast) and error forwarding will be disabled.")
ADMIN_CONTACT_LINK = os.getenv('ADMIN_CONTACT_LINK', 'https://t.me/Frexy1only')

# --- File Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'bot_data')
TEMP_DIR = os.path.join(DATA_DIR, 'temp_files')
SCHEDULED_FILES_DATA_DIR = os.path.join(DATA_DIR, 'scheduled_files_data')

VIP_FILE = os.path.join(DATA_DIR, 'vip_users.json')
GITHUB_CONFIG_FILE = os.path.join(DATA_DIR, 'githubconfigs.json')
KNOWN_USERS_FILE = os.path.join(DATA_DIR, 'knownusers.json')
SCHEDULED_FILES_CONFIG = os.path.join(DATA_DIR, 'scheduledfiles.json')

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.vendor.ptb_urllib3.urllib3").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def format_time(seconds: float) -> str:
    """Formats seconds into a human-readable string."""
    if seconds is None or seconds < 0: return "N/A"
    try:
        seconds_int = int(seconds)
        if seconds_int < 60:
            return f"{seconds_int}s" if seconds_int >= 0 else "0s"
        delta = timedelta(seconds=seconds_int)
        total_seconds = delta.total_seconds()
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if hours > 0: parts.append(f"{int(hours)}h")
        if minutes > 0 or (hours > 0 and seconds > 0): parts.append(f"{int(minutes)}m")
        if seconds > 0 or (not parts and total_seconds >=0): parts.append(f"{int(seconds)}s")

        if not parts: return "0s"
        return " ".join(parts).strip()

    except (OverflowError, ValueError):
        return "Infinity"
    except Exception as e:
        logger.warning(f"Error formatting time {seconds}: {e}")
        return "Format Error"

def sanitize_filename(name: str) -> str:
    """Sanitizes a string to be used as part of a filename, ensuring it ends with .json."""
    if not name: return 'Unknown.json'
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
    sanitized = sanitized.strip(' _.-')
    if not sanitized.lower().endswith('.json'):
        base, _ = os.path.splitext(sanitized)
        sanitized = base + ".json"
    if not sanitized or sanitized == '.json':
        return 'Unknown.json'
    return sanitized

def parse_interval(interval_str: str) -> int | None:
    """Parses interval strings like '1h', '30m', '2d' into seconds."""
    match = re.match(r'^(\d+)\s*(m|h|d)$', interval_str.lower().strip())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    return None

def load_json_data(filepath: str, default_value=None) -> dict | list:
    """Loads JSON data from a file, returning default_value on error or if file not found."""
    if default_value is None:
        default_value = {}
    try:
        dir_name = os.path.dirname(filepath)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info(f"File {filepath} not found, creating with default value.")
        save_json_data(filepath, default_value)
        return default_value
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {filepath}: {e}. Backing up corrupted file and returning default.")
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupted_backup_path = f"{filepath}.corrupted_{timestamp}"
            os.rename(filepath, corrupted_backup_path)
            logger.info(f"Backed up corrupted file to {corrupted_backup_path}")
        except OSError as ren_err:
             logger.error(f"Could not backup corrupted file {filepath}: {ren_err}")
        save_json_data(filepath, default_value)
        return default_value
    except Exception as e:
        logger.error(f"Unexpected error loading {filepath}: {e}. Returning default value.", exc_info=True)
        return default_value

def save_json_data(filepath: str, data: dict | list) -> bool:
    """Saves data to a JSON file using atomic write. Returns True on success, False on error."""
    temp_filepath = filepath + ".tmp"
    try:
        dir_name = os.path.dirname(filepath)
        if dir_name:
             os.makedirs(dir_name, exist_ok=True)
        with open(temp_filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(temp_filepath, filepath)
        logger.debug(f"Successfully saved data to {filepath}")
        return True
    except OSError as e:
        logger.error(f"OS Error saving data to {filepath}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving data to {filepath}: {e}", exc_info=True)
        return False
    finally:
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError as e:
                logger.warning(f"Could not remove temporary save file {temp_filepath}: {e}")

# --- VIP User Management ---

def load_vip_data() -> dict:
    return load_json_data(VIP_FILE, {})

def save_vip_data(data: dict) -> bool:
    return save_json_data(VIP_FILE, data)

def is_user_vip(user_id: int) -> bool:
    vip_data = load_vip_data()
    user_id_str = str(user_id)
    if user_id_str in vip_data and isinstance(vip_data.get(user_id_str), dict):
        try:
            expiry_iso = vip_data[user_id_str].get('expiry')
            if expiry_iso:
                expiry_dt = datetime.fromisoformat(expiry_iso.replace('Z', '+00:00'))
                return expiry_dt > datetime.now(timezone.utc)
            else:
                return False
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Invalid or missing VIP data format for user {user_id_str}: {e}. Assuming not VIP.")
            return False
    return False

def get_vip_expiry(user_id: int) -> str | None:
    vip_data = load_vip_data()
    user_id_str = str(user_id)
    if user_id_str in vip_data and isinstance(vip_data.get(user_id_str), dict):
        try:
            expiry_iso = vip_data[user_id_str].get('expiry')
            if expiry_iso:
                expiry_dt = datetime.fromisoformat(expiry_iso.replace('Z', '+00:00'))
                if expiry_dt > datetime.now(timezone.utc):
                    return expiry_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                else:
                    return None
            else:
                return None
        except (ValueError, KeyError, TypeError):
            return "Invalid Date Stored"
    return None

# --- GitHub Config Management ---

def load_github_configs() -> dict:
    return load_json_data(GITHUB_CONFIG_FILE, {})

def save_github_configs(data: dict) -> bool:
    return save_json_data(GITHUB_CONFIG_FILE, data)

# --- Known User Management ---

def load_known_users() -> set:
    user_list = load_json_data(KNOWN_USERS_FILE, [])
    valid_users = set()
    if isinstance(user_list, list):
        for item in user_list:
            if isinstance(item, int) and item != 0:
                valid_users.add(item)
            elif isinstance(item, str) and item.isdigit() and int(item) != 0:
                 valid_users.add(int(item))
    else:
        logger.error(f"Loaded known users data from {KNOWN_USERS_FILE} is not a list. Resetting to empty list.")
        save_known_users(set())
        return set()
    return valid_users

def save_known_users(user_set: set) -> bool:
    int_user_list = sorted([int(uid) for uid in user_set if isinstance(uid, (int, str)) and str(uid).isdigit() and int(str(uid)) != 0])
    return save_json_data(KNOWN_USERS_FILE, int_user_list)

def add_known_user(user_id: int) -> None:
    if not isinstance(user_id, int) or user_id == 0:
        logger.debug(f"Attempted to add invalid user ID: {user_id}. Skipping.")
        return
    known_users = load_known_users()
    if user_id not in known_users:
        known_users.add(user_id)
        if save_known_users(known_users):
             logger.info(f"Added new user {user_id} to known users list ({len(known_users)} total).")
        else:
             logger.error(f"Failed attempt to save known users file after adding {user_id}.")

# --- Scheduled File Management ---

def load_scheduled_files() -> dict:
    return load_json_data(SCHEDULED_FILES_CONFIG, {})

def save_scheduled_files(data: dict) -> bool:
    return save_json_data(SCHEDULED_FILES_CONFIG, data)

# --- Command Buttons ---
COMMAND_BUTTONS_LAYOUT = [
    ["Process File 📤", "Vip Status 📇"],
    ["Vip Shop 🛒", "GitHub Status 📊"],
    ["Scheduled Files ⚙️", "Help 🆘"],
    ["Cancel ❌"]
]
main_reply_markup = ReplyKeyboardMarkup(COMMAND_BUTTONS_LAYOUT, resize_keyboard=True, one_time_keyboard=False)

# --- Bot Command Handlers (ALL ORIGINAL - UNCHANGED) ---

async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user: return
    add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    username = escape(user.first_name) or "there"

    start_msg = f"👋 Hello {username}!\n\n"
    start_msg += "🚀 Welcome to the JWT Token Generator Bot!\n\n"
    start_msg += "📁 Send me a JSON file containing account credentials like this:\n"
    start_msg += "```json\n"
    start_msg += '[\n'
    start_msg += '    {"uid": "user1", "password": "pass1"},\n'
    start_msg += '    {"uid": "user2", "password": "pass2"}\n'
    start_msg += '    // ... more entries ...\n'
    start_msg += ']\n'
    start_msg += "```\n"
    start_msg += "✅ Successful tokens (Region summary included in message) will be saved to `jwt_token.json` AND `accounts{Region}.json` files.\n"
    start_msg += "✔️ Working accounts (UID/Pass) will be saved to `working_account.json`\n"
    start_msg += "❌ Failed/invalid entries (UID/Pass) will be saved to `lost_account.json`\n\n"
    start_msg += f"⚠️ Max file size: {MAX_FILE_SIZE / 1024 / 1024:.1f}MB\n\n"
    start_msg += "⚡ *Performance Settings:*\n"
    start_msg += f"  - {MAX_CONCURRENT_REQUESTS} concurrent requests\n"
    start_msg += f"  - {MAX_RETRY_ATTEMPTS} retry attempts per account\n"
    start_msg += f"  - {RETRY_TIMEOUT}s timeout per attempt\n"
    start_msg += f"  - Auto-processing every {AUTO_PROCESS_INTERVAL_HOURS} hours\n\n"
    start_msg += "✨ *VIP Features:*\n"
    start_msg += "  - Auto-upload tokens to GitHub.\n"
    start_msg += "  - Schedule files for automatic periodic processing and GitHub upload (`/setfile`).\n\n"
    start_msg += "Use /help or the Help button (🆘) to see all available commands."

    await update.message.reply_text(
        start_msg,
        reply_markup=main_reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if user: add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    help_text = (
        "🆘 *Help Center*\n\n"
        "📌 *Available Commands:*\n"
        "  `/start` - Show the main welcome message\n"
        "  `/help` - Show this help message\n"
        "  `/vipstatus` - Check your current VIP status\n"
        "  `/vipshop` - View available VIP plans\n"
        "  `/cancel` - Cancel the current operation\n\n"
        "🔧 *VIP Commands:*\n"
        "  `/setgithub <TOKEN> <owner/repo> <branch> <filename.json>` - Configure GitHub auto-upload.\n"
        "  `/mygithub` - Show your current GitHub configuration.\n"
        "  `/setfile <Interval> <ScheduleName.json>` - Schedule a file for auto-processing.\n"
        "  `/removefile <ScheduleName.json>` - Remove a scheduled file.\n"
        "  `/scheduledfiles` - List your scheduled files.\n\n"
        "⚡ *Processing Settings:*\n"
        f"  - {MAX_CONCURRENT_REQUESTS} concurrent requests\n"
        f"  - {MAX_RETRY_ATTEMPTS} retry attempts per account\n"
        f"  - {RETRY_TIMEOUT}s timeout per attempt\n"
        f"  - Auto-processing every {AUTO_PROCESS_INTERVAL_HOURS} hours\n\n"
        "👑 *Admin Commands:*\n"
        "  `/vip add <user_id> <days>` - Add VIP\n"
        "  `/vip remove <user_id>` - Remove VIP\n"
        "  `/vip list` - List VIP users\n"
        "  `/broadcast <message>` - Broadcast message\n\n"
        "📤 *Manual Processing:*\n"
        "  1. Send a JSON file with UID-password pairs.\n"
        "  2. Bot processes and returns result files.\n"
        "  3. VIPs with GitHub config get auto-upload.\n\n"
        "⚙️ *Auto-Processing (VIP):*\n"
        f"  1. Bot auto-processes every {AUTO_PROCESS_INTERVAL_HOURS} hours\n"
        "  2. Generates tokens and uploads to GitHub automatically\n"
        "  3. Shows progress during processing"
    )
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_markup,
        disable_web_page_preview=True
    )

async def vip_shop_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if user: add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    vip_shop_text = (
        "✨ Unlock **Automatic GitHub Uploads** & **Scheduled File Processing** ✨\n"
        "& Other Premium Features Instantly!\n\n"
        "💼 *Available Plans & Prices:*\n\n"
        "🗓️   `7 Days`       —   `₹ 10`\n"
        "🗓️  `15 Days`     —   `₹ 49`\n"
        "📅  `1 Month`      —   `₹ 69`\n"
        "📅  `2 Months`     —   `₹ 89`\n"
        "📅  `3 Months`     —   `₹ 99`\n"
        "🎯  `1 Year`       —   `₹ 159`\n\n"
        "📩 *To Purchase VIP Membership:*\n"
        f"Contact Admin 👉 [Admin Contact]({ADMIN_CONTACT_LINK})"
    )

    await update.message.reply_text(
        vip_shop_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_markup,
        disable_web_page_preview=True
    )

async def vip_status_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user: return
    user_id = user.id
    add_known_user(user_id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    expiry_date_str = get_vip_expiry(user_id)

    if expiry_date_str and "Invalid" not in expiry_date_str:
        status_msg = f"🌟 *VIP Status:* Active\n*Expires:* `{expiry_date_str}`"
    elif expiry_date_str == "Invalid Date Stored":
        status_msg = "⚠️ *VIP Status:* Error reading expiry date. Please contact admin."
    else:
        status_msg = "ℹ️ *Status:* Regular User\nUse /vipshop to upgrade and unlock premium features!"

    await update.message.reply_text(
        status_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_markup
    )

async def cancel(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    user_id = user.id if user else "Unknown"
    cleared_action = False
    if context.user_data.pop('pending_schedule', None):
        cleared_action = True
        logger.info(f"User {user_id} cancelled pending file schedule setup.")
        await update.message.reply_text(
            "Scheduled file setup cancelled. Returning to main menu.",
            reply_markup=main_reply_markup
        )
    elif context.user_data.pop('waiting_for_json', None):
         cleared_action = True
         logger.info(f"User {user_id} cancelled waiting for manual JSON process.")
         await update.message.reply_text(
            "Waiting for manual process file cancelled. Returning to main menu.",
            reply_markup=main_reply_markup
         )

    if not cleared_action:
        logger.info(f"User {user_id} used /cancel, but no active operation found.")
        await update.message.reply_text(
            "No active operation to cancel. Returning to main menu.",
            reply_markup=main_reply_markup
        )

# --- UPDATED: Process Account with 120s timeout ---

async def process_account_with_retry(session: aiohttp.ClientSession, account: dict, semaphore: asyncio.Semaphore, max_retries: int = 10, timeout_seconds: int = 120) -> tuple[str | None, str | None, dict | None, dict | None, str | None]:
    """
    Processes a single account via the API to get a JWT token with retry logic.
    - 7 concurrent requests
    - 120 second timeout per attempt
    - Up to 10 retry attempts
    """
    uid = account.get("uid")
    password = account.get("password")
    error_reason = None
    original_account_info = account.copy()

    if not uid: error_reason = "Missing 'uid'"
    elif not password: error_reason = "Missing 'password'"

    if error_reason:
        logger.debug(f"Skipping account due to validation error: {error_reason} - Account: {account}")
        lost_info = {**original_account_info, "error_reason": error_reason}
        return None, None, None, lost_info, error_reason

    uid_str = str(uid)
    attempt = 0
    last_error = None
    all_errors = []

    async with semaphore:
        while attempt < max_retries:
            attempt += 1
            try:
                params = {'uid': uid_str, 'password': password}
                if API_KEY:
                    params['key'] = API_KEY

                async with session.get(
                    API_BASE_URL, 
                    params=params, 
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                ) as response:
                    response_text = await response.text()

                    if 200 <= response.status < 300:
                        try:
                            result = json.loads(response_text)
                            token = result.get('token') or result.get('access_token') or result.get('jwt')
                            if token:
                                region = result.get('region') or result.get('server') or "Unknown"
                                logger.info(f"✅ Success: Token received for UID: {uid_str} (Attempt {attempt}/{max_retries}, Region: {region})")
                                return token, region, original_account_info, None, None
                            else:
                                err_msg = f"API returned no token (Attempt {attempt}/{max_retries})"
                                logger.warning(f"{err_msg} for UID: {uid_str}. Response: {response_text[:200]}")
                                last_error = err_msg
                                all_errors.append(err_msg)
                        except json.JSONDecodeError:
                            err_msg = f"API returned non-JSON response (Attempt {attempt}/{max_retries})"
                            logger.error(f"{err_msg} for UID: {uid_str}. Response: {response_text[:200]}")
                            last_error = err_msg
                            all_errors.append(err_msg)
                    else:
                        error_detail = f"API Error ({response.status})"
                        try:
                            error_json = json.loads(response_text)
                            if isinstance(error_json, dict):
                                msg = error_json.get('message') or error_json.get('error') or error_json.get('detail')
                                if msg and isinstance(msg, str):
                                    error_detail += f": {msg[:100]}"
                        except (json.JSONDecodeError, TypeError):
                            pass
                        logger.warning(f"API Error for UID: {uid_str} (Attempt {attempt}/{max_retries}). Status: {response.status}. Detail: {error_detail}")
                        last_error = error_detail
                        all_errors.append(error_detail)

            except asyncio.TimeoutError:
                last_error = f"Timeout (120s) (Attempt {attempt}/{max_retries})"
                logger.warning(f"Timeout processing API request for UID: {uid_str} (Attempt {attempt}/{max_retries})")
                all_errors.append(last_error)
            except aiohttp.ClientConnectorError as e:
                last_error = f"Network Error: {e} (Attempt {attempt}/{max_retries})"
                logger.error(f"Network Connection Error processing UID {uid_str} (Attempt {attempt}/{max_retries}): {e}")
                all_errors.append(last_error)
            except aiohttp.ClientError as e:
                last_error = f"HTTP Client Error: {e} (Attempt {attempt}/{max_retries})"
                logger.error(f"AIOHTTP Client Error processing UID {uid_str} (Attempt {attempt}/{max_retries}): {e}")
                all_errors.append(last_error)
            except Exception as e:
                last_error = f"Unexpected Error: {e} (Attempt {attempt}/{max_retries})"
                logger.error(f"Unexpected error processing UID {uid_str} (Attempt {attempt}/{max_retries}): {e}", exc_info=True)
                all_errors.append(last_error)

            if attempt < max_retries:
                wait_time = 0.5 * (attempt ** 1.2) + random.uniform(0, 0.3)
                await asyncio.sleep(wait_time)

        error_summary = "; ".join(all_errors[-3:])
        final_error = f"❌ Failed after {max_retries} attempts. Last errors: {error_summary}"
        logger.warning(f"All retries exhausted for UID: {uid_str}. Total attempts: {max_retries}. Last error: {last_error}")
        lost_info = {**original_account_info, "error_reason": final_error}
        return None, None, None, lost_info, final_error

async def process_account(session: aiohttp.ClientSession, account: dict, semaphore: asyncio.Semaphore) -> tuple[str | None, str | None, dict | None, dict | None, str | None]:
    """
    Process account with automatic retry (wrapper for process_account_with_retry)
    - 10 retry attempts
    - 120 second timeout per attempt
    - 7 concurrent requests
    """
    return await process_account_with_retry(
        session, 
        account, 
        semaphore, 
        max_retries=MAX_RETRY_ATTEMPTS,
        timeout_seconds=RETRY_TIMEOUT
    )

# --- handle_document function (ORIGINAL - UNCHANGED except timeout display) ---

async def handle_document(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    chat_id = message.chat_id
    add_known_user(user.id)

    if context.user_data.get('pending_schedule'):
        await handle_scheduled_file_upload(update, context)
        return

    process_button_text = COMMAND_BUTTONS_LAYOUT[0][0]
    if message.text == process_button_text and not message.document:
        await message.reply_text(
            "Okay, please send the JSON file now for manual processing.\n\n"
            "Make sure it's a `.json` file containing a list like:\n"
            "```json\n"
            '[\n  {"uid": "user1", "password": "pass1"},\n  {"uid": "user2", "password": "pass2"}\n]\n'
            "```",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data['waiting_for_json'] = True
        return

    was_waiting_manual = context.user_data.pop('waiting_for_json', False)
    if was_waiting_manual and not message.document:
         await message.reply_text("Looks like you sent text instead of a file for manual processing. Please send the JSON file or use /cancel.", reply_markup=main_reply_markup)
         return
    elif not was_waiting_manual and not message.document:
        known_button_texts = {btn for row in COMMAND_BUTTONS_LAYOUT for btn in row}
        if message.text not in known_button_texts:
            logger.debug(f"Ignoring unhandled text message from user {user_id} in private chat.")
        return

    document = message.document
    if not document: return

    is_json_mime = document.mime_type and document.mime_type.lower() == 'application/json'
    has_json_extension = document.file_name and document.file_name.lower().endswith('.json')

    if not is_json_mime and not has_json_extension:
        await message.reply_text("❌ File does not appear to be a JSON file. Please ensure it has a `.json` extension or the correct `application/json` type.", reply_markup=main_reply_markup)
        return

    file_id = document.file_id
    file_name = document.file_name or f"file_{file_id}.json"

    if document.file_size and document.file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"⚠️ File is too large ({document.file_size / 1024 / 1024:.2f} MB). Max: {MAX_FILE_SIZE / 1024 / 1024:.1f} MB.",
            reply_markup=main_reply_markup
        )
        return

    temp_file_path = os.path.join(TEMP_DIR, f'input_manual_{user_id}_{int(time.time())}.json')
    progress_message = None
    accounts_data = []

    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        progress_message = await message.reply_text(f"⏳ Downloading `{escape(file_name)}` for manual processing...", parse_mode=ParseMode.MARKDOWN)

        bot_file = await context.bot.get_file(file_id)
        await bot_file.download_to_drive(temp_file_path)
        logger.info(f"User {user_id} uploaded file '{file_name}' for manual processing, downloaded to {temp_file_path}")

        await context.bot.edit_message_text(
            chat_id=progress_message.chat_id, message_id=progress_message.message_id,
            text=f"⏳ Downloaded `{escape(file_name)}`. Parsing JSON...", parse_mode=ParseMode.MARKDOWN
        )

        actual_size = os.path.getsize(temp_file_path)
        if actual_size > MAX_FILE_SIZE:
             raise ValueError(f"Downloaded file size ({actual_size / 1024 / 1024:.2f} MB) exceeds limit ({MAX_FILE_SIZE / 1024 / 1024:.1f} MB).")

        with open(temp_file_path, 'r', encoding='utf-8') as f:
            try:
                accounts_data = json.load(f)
            except json.JSONDecodeError as e:
                error_line_info = ""
                if hasattr(e, 'lineno') and hasattr(e, 'colno'):
                    error_line_info = f" near line {e.lineno}, column {e.colno}"
                error_msg = f"❌ Invalid JSON format in `{escape(file_name)}`{error_line_info}.\nError: `{escape(e.msg)}`.\nPlease check the file structure and syntax."
                await context.bot.edit_message_text(
                    chat_id=progress_message.chat_id, message_id=progress_message.message_id,
                    text=error_msg, parse_mode=ParseMode.MARKDOWN
                )
                if ADMIN_ID and ADMIN_ID != 0:
                    try:
                        await context.bot.send_message(ADMIN_ID, f"⚠️ User {user.id} uploaded invalid JSON for manual processing: `{escape(file_name)}`. Error: {escape(e.msg)}{error_line_info}")
                    except Exception as forward_e:
                        logger.error(f"Failed to forward invalid JSON notice to admin {ADMIN_ID}: {forward_e}")
                return

        if not isinstance(accounts_data, list):
            raise ValueError("Input JSON structure is invalid. It must be an array (a list `[...]`) of objects.")
        if accounts_data and not all(isinstance(item, dict) for item in accounts_data):
             first_bad_item = next((item for item in accounts_data if not isinstance(item, dict)), None)
             raise ValueError(f"All items inside the JSON array must be objects (`{{...}}`). Found an item that is not an object: `{escape(str(first_bad_item)[:50])}`...")

    except ValueError as e:
        logger.warning(f"Input file validation failed for user {user_id} ('{file_name}'): {e}")
        error_text = f"❌ Validation Error: {escape(str(e))}"
        if progress_message:
             await context.bot.edit_message_text(chat_id=progress_message.chat_id, message_id=progress_message.message_id, text=error_text, parse_mode=ParseMode.MARKDOWN)
        else:
             await message.reply_text(error_text, reply_markup=main_reply_markup, parse_mode=ParseMode.MARKDOWN)
        return
    except TelegramError as e:
        logger.error(f"Telegram API error during file handling for user {user_id}: {e}")
        try:
            error_text = f"⚠️ A Telegram error occurred: `{escape(str(e))}`. Please try again later."
            if progress_message:
                await context.bot.edit_message_text(chat_id=progress_message.chat_id, message_id=progress_message.message_id, text=error_text, parse_mode=ParseMode.MARKDOWN)
            else:
                 await message.reply_text(error_text, reply_markup=main_reply_markup, parse_mode=ParseMode.MARKDOWN)
        except TelegramError:
            logger.error(f"Could not inform user {user_id} about Telegram error: {e}")
        return
    except Exception as e:
        logger.error(f"Error downloading or parsing file from user {user_id}: {e}", exc_info=True)
        error_text = f"⚠️ An unexpected error occurred while handling the file. Please try again or contact admin if it persists."
        if progress_message:
            try:
                await context.bot.edit_message_text(chat_id=progress_message.chat_id, message_id=progress_message.message_id, text=error_text)
            except TelegramError:
                await message.reply_text(error_text, reply_markup=main_reply_markup)
        else:
            await message.reply_text(error_text, reply_markup=main_reply_markup)
        return
    finally:
        if os.path.exists(temp_file_path):
             try:
                 os.remove(temp_file_path)
             except OSError as e:
                 logger.warning(f"Could not remove temp input file {temp_file_path}: {e}")

    total_count = len(accounts_data)
    if total_count == 0:
        await context.bot.edit_message_text(
            chat_id=progress_message.chat_id, message_id=progress_message.message_id,
            text="ℹ️ The provided JSON file is empty or contains no valid account objects."
        )
        return

    await context.bot.edit_message_text(
        chat_id=progress_message.chat_id, message_id=progress_message.message_id,
        text=f"🔄 *Processing {total_count} Accounts (Manual)*\n"
             f"⚡ {MAX_CONCURRENT_REQUESTS} concurrent requests\n"
             f"🔄 {MAX_RETRY_ATTEMPTS} retry attempts per account\n"
             f"⏱️ {RETRY_TIMEOUT}s timeout per attempt\n"
             f"Initializing API calls...",
        parse_mode=ParseMode.MARKDOWN
    )

    start_time = time.time()
    processed_count = 0
    successful_tokens = []
    working_accounts = []
    lost_accounts = []
    errors_summary = defaultdict(int)
    retry_count_stats = defaultdict(int)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    async with aiohttp.ClientSession() as session:
        tasks = [process_account(session, account, semaphore) for account in accounts_data]
        last_update_time = time.time()
        last_progress_text_sent = ""

        for future in asyncio.as_completed(tasks):
            try:
                token, region, working_acc, lost_acc, error_reason = await future
            except Exception as task_err:
                logger.error(f"Error retrieving result from processing task: {task_err}", exc_info=True)
                error_msg = f"Internal task error: {task_err}"
                lost_account_info = {"uid": "unknown", "password": "unknown", "error_reason": error_msg}
                lost_accounts.append(lost_account_info)
                errors_summary[error_msg] += 1
                processed_count += 1
                continue

            processed_count += 1

            if token and working_acc:
                successful_tokens.append({"token": token, "region": region})
                working_accounts.append(working_acc)
            elif lost_acc:
                lost_accounts.append(lost_acc)
                reason = lost_acc.get("error_reason", "Unknown Failure")
                simple_error = reason.split(':')[0].strip()
                errors_summary[simple_error] += 1
                if "Failed after" in reason or "attempts" in reason:
                    retry_count_stats["failed_after_retries"] += 1
            else:
                logger.error(f"Task completed unexpectedly. Token:{token}, Region:{region}, Work:{working_acc}, Lost:{lost_acc}, Err:{error_reason}")
                generic_lost_info = {"account_info": lost_acc or working_acc or "unknown", "error_reason": "Processing function returned unexpected state"}
                lost_accounts.append(generic_lost_info)
                errors_summary["Processing function error"] += 1

            current_time = time.time()
            update_frequency_items = max(5, min(50, total_count // 20))
            time_elapsed_since_last_update = current_time - last_update_time

            if time_elapsed_since_last_update > 1.5 or \
               (update_frequency_items > 0 and processed_count % update_frequency_items == 0) or \
               processed_count == total_count:

                elapsed_time = current_time - start_time
                percentage = (processed_count / total_count) * 100 if total_count > 0 else 0

                estimated_remaining_time = -1
                if processed_count > 3 and elapsed_time > 1:
                    try:
                        time_per_item = elapsed_time / processed_count
                        remaining_items = total_count - processed_count
                        estimated_remaining_time = time_per_item * remaining_items
                    except ZeroDivisionError:
                        pass

                progress_text = (
                    f"🔄 *Processing Accounts (Manual)...*\n\n"
                    f"Progress: {processed_count}/{total_count} ({percentage:.1f}%)\n"
                    f"✅ Success: {len(successful_tokens)} | ❌ Failed: {len(lost_accounts)}\n"
                    f"🔄 Failed after {MAX_RETRY_ATTEMPTS} retries: {retry_count_stats.get('failed_after_retries', 0)}\n"
                    f"⚡ Concurrent: {MAX_CONCURRENT_REQUESTS} threads\n"
                    f"⏱️ Elapsed: {format_time(elapsed_time)}\n"
                    f"⏳ Est. Remaining: {format_time(estimated_remaining_time)}"
                )

                if last_progress_text_sent != progress_text:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=progress_message.chat_id, message_id=progress_message.message_id,
                            text=progress_text, parse_mode=ParseMode.MARKDOWN
                        )
                        last_progress_text_sent = progress_text
                        last_update_time = current_time
                    except TelegramError as edit_err:
                        if "Message is not modified" not in str(edit_err):
                             logger.warning(f"Could not edit progress message: {edit_err}")
                        last_update_time = current_time

    final_elapsed_time = time.time() - start_time
    escaped_file_name = escape(file_name)
    final_summary_parts = [
        f"🏁 *Manual Processing Complete for `{escaped_file_name}`*\n",
        f"📊 Total Accounts Processed: {total_count}",
        f"✅ Successful Tokens: {len(successful_tokens)}",
        f"❌ Failed/Invalid Accounts: {len(lost_accounts)}",
        f"🔄 Failed after {MAX_RETRY_ATTEMPTS} retries: {retry_count_stats.get('failed_after_retries', 0)}",
        f"⚡ Concurrent threads: {MAX_CONCURRENT_REQUESTS}",
        f"⏱️ Total Time Taken: {format_time(final_elapsed_time)}"
    ]

    successful_by_region = defaultdict(list)
    if successful_tokens:
        for token_entry in successful_tokens:
            region = token_entry.get('region')
            region_name = region if region else "Unknown Region"
            successful_by_region[region_name].append(token_entry)

        if successful_by_region:
            final_summary_parts.append("\n*Successful by Region:*")
            sorted_regions = sorted(successful_by_region.keys())
            for region in sorted_regions:
                count = len(successful_by_region[region])
                final_summary_parts.append(f"- {escape(region)}: {count} tokens")
    else:
        final_summary_parts.append("\n*Successful by Region:* 0 tokens found.")

    if errors_summary:
        final_summary_parts.append("\n*Error Summary (Top 5 Types):*")
        sorted_errors = sorted(errors_summary.items(), key=lambda item: item[1], reverse=True)
        for msg, count in sorted_errors[:5]:
            final_summary_parts.append(f"- `{escape(msg)}`: {count} times")
        if len(sorted_errors) > 5:
            final_summary_parts.append(f"... and {len(sorted_errors) - 5} more error types.")

    final_summary = "\n".join(final_summary_parts)

    try:
        if progress_message:
            await context.bot.delete_message(chat_id=progress_message.chat_id, message_id=progress_message.message_id)
        await message.reply_text(
            final_summary,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
    except TelegramError as final_msg_err:
        logger.error(f"Could not delete progress message or send final summary: {final_msg_err}")
        try:
            await message.reply_text(
                final_summary,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_reply_markup
            )
        except Exception as fallback_err:
            logger.critical(f"Failed even fallback sending final summary for manual process: {fallback_err}")

    file_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_files_to_send = []
    cleanup_paths = []
    jwt_token_path_for_upload = None

    try:
        os.makedirs(TEMP_DIR, exist_ok=True)

        if successful_tokens:
            jwt_token_path = os.path.join(TEMP_DIR, f'jwt_only_{user_id}_{file_timestamp}.json')
            tokens_only_list_for_file = [{"token": entry.get("token")} for entry in successful_tokens if entry.get("token")]

            if tokens_only_list_for_file:
                if save_json_data(jwt_token_path, tokens_only_list_for_file):
                    output_files_to_send.append((jwt_token_path, 'jwt_token.json'))
                    cleanup_paths.append(jwt_token_path)
                    jwt_token_path_for_upload = jwt_token_path
                else:
                    await message.reply_text("⚠️ Error saving main `jwt_token.json` to temporary storage.")

        if successful_by_region:
            logger.info(f"Creating region-specific files for user {user_id}")
            for region_name, entries in successful_by_region.items():
                 if not entries: continue

                 region_tokens_only = [{"token": entry.get("token")} for entry in entries if entry.get("token")]

                 if region_tokens_only:
                     sanitized_region_name = sanitize_filename(region_name)
                     base_region_name = os.path.splitext(sanitized_region_name)[0]
                     region_file_name = f'accounts{base_region_name}.json'

                     region_file_path = os.path.join(TEMP_DIR, f'{base_region_name}_{user_id}_{file_timestamp}.json')

                     if save_json_data(region_file_path, region_tokens_only):
                         output_files_to_send.append((region_file_path, region_file_name))
                         cleanup_paths.append(region_file_path)
                         logger.debug(f"Created region file: {region_file_name} with {len(region_tokens_only)} tokens.")
                     else:
                         await message.reply_text(f"⚠️ Error saving region file `{escape(region_file_name)}` to temporary storage.", parse_mode=ParseMode.MARKDOWN)
                         logger.error(f"Failed to save region file {region_file_name} for user {user_id}")

        if working_accounts:
            working_account_path = os.path.join(TEMP_DIR, f'working_{user_id}_{file_timestamp}.json')
            if save_json_data(working_account_path, working_accounts):
                output_files_to_send.append((working_account_path, 'working_account.json'))
                cleanup_paths.append(working_account_path)
            else:
                await message.reply_text("⚠️ Error saving `working_account.json` to temporary storage.")

        if lost_accounts:
            lost_account_path = os.path.join(TEMP_DIR, f'lost_{user_id}_{file_timestamp}.json')
            if save_json_data(lost_account_path, lost_accounts):
                output_files_to_send.append((lost_account_path, 'lost_account.json'))
                cleanup_paths.append(lost_account_path)
            else:
                await message.reply_text("⚠️ Error saving `lost_account.json` to temporary storage.")

        if output_files_to_send:
            await message.reply_text(f"⬇️ Sending {len(output_files_to_send)} result file(s)...")
            output_files_to_send.sort(key=lambda x: x[1])
            for temp_path, desired_filename in output_files_to_send:
                 if not os.path.exists(temp_path):
                     logger.error(f"Output file {temp_path} (for {desired_filename}) not found before sending.")
                     await message.reply_text(f"⚠️ Internal Error: Could not find `{escape(desired_filename)}` for sending.", parse_mode=ParseMode.MARKDOWN)
                     continue
                 try:
                     with open(temp_path, 'rb') as f:
                         await message.reply_document(
                             document=InputFile(f, filename=desired_filename),
                             caption=f"`{escape(desired_filename)}`\nFrom manual processing of: `{escaped_file_name}`\nTotal Processed: {total_count}",
                             parse_mode=ParseMode.MARKDOWN
                         )
                     logger.info(f"Sent '{desired_filename}' to user {user_id} (manual process)")
                     await asyncio.sleep(0.5)
                 except TelegramError as send_err:
                     logger.error(f"Failed to send '{desired_filename}' to user {user_id}: {send_err}")
                     await message.reply_text(f"⚠️ Failed to send `{escape(desired_filename)}`: {escape(str(send_err))}", parse_mode=ParseMode.MARKDOWN)
                 except Exception as general_err:
                     logger.error(f"Unexpected error sending '{desired_filename}' to {user_id}: {general_err}", exc_info=True)
                     await message.reply_text(f"⚠️ Unexpected error sending `{escape(desired_filename)}`.", parse_mode=ParseMode.MARKDOWN)
        elif total_count > 0:
             await message.reply_text("ℹ️ No output files were generated (e.g., 0 successful tokens found or error saving files).", reply_markup=main_reply_markup)

        if is_user_vip(user_id) and jwt_token_path_for_upload:
            github_configs = load_github_configs()
            user_id_str = str(user_id)
            config = github_configs.get(user_id_str)

            if config and isinstance(config, dict):
                logger.info(f"User {user_id} is VIP with GitHub config. Attempting auto-upload (manual process).")
                if os.path.exists(jwt_token_path_for_upload):
                    await upload_to_github_background(
                        context.bot,
                        user_id,
                        jwt_token_path_for_upload,
                        config
                        )
                else:
                     logger.error(f"JWT file {jwt_token_path_for_upload} missing for GitHub upload (user {user_id}). Logic error?")
                     await message.reply_text("⚠️ Internal Error: Token file for GitHub upload not found.", disable_notification=True)
            elif user_id_str in github_configs:
                 logger.error(f"GitHub config for user {user_id} is invalid (not a dict). Skipping upload.")
                 await message.reply_text("⚠️ GitHub upload skipped: Invalid config stored. Use /setgithub again.", disable_notification=True)
            else:
                 logger.info(f"User {user_id} is VIP but has no GitHub config.")
                 await message.reply_text("ℹ️ GitHub auto-upload skipped: No GitHub configuration found. Use `/setgithub` command to enable.", disable_notification=True, parse_mode=ParseMode.MARKDOWN)
        elif is_user_vip(user_id) and not jwt_token_path_for_upload and successful_tokens:
             await message.reply_text("⚠️ GitHub upload skipped: Error occurred while saving the main token file locally.", disable_notification=True)
        elif is_user_vip(user_id) and not successful_tokens and total_count > 0:
            await message.reply_text("ℹ️ GitHub auto-upload skipped: No successful tokens were generated in this batch.", disable_notification=True)

    except Exception as final_err:
        logger.error(f"Error during file generation/sending stage for user {user_id}: {final_err}", exc_info=True)
        await message.reply_text(f"⚠️ An error occurred while generating/sending result files: {escape(str(final_err))}", reply_markup=main_reply_markup)
    finally:
        for path in cleanup_paths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    logger.warning(f"Could not remove temp output file {path}: {e}")

        if ADMIN_ID and ADMIN_ID != 0:
            try:
                temp_forward_path = os.path.join(TEMP_DIR, f'forward_{user_id}_{message.message_id}.json')
                try:
                    bot_file = await context.bot.get_file(file_id)
                    await bot_file.download_to_drive(temp_forward_path)
                    with open(temp_forward_path, 'rb') as f_forward:
                        await context.bot.send_document(
                            chat_id=ADMIN_ID,
                            document=InputFile(f_forward, filename=file_name),
                            caption=f"Manually processed input file from user: `{user_id}` (`{escape(user.first_name or '')}` @{escape(user.username or 'NoUsername')})\nFilename: `{escape(file_name)}`",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    logger.info(f"Forwarded original input file '{file_name}' from user {user_id} to admin {ADMIN_ID}")
                except Exception as download_err:
                    logger.error(f"Could not re-download file for forwarding to admin: {download_err}")
                    await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=message.chat_id, message_id=message.message_id)
                    await context.bot.send_message(ADMIN_ID, f"(Forwarded original message as file re-download failed for admin log)")
                finally:
                     if os.path.exists(temp_forward_path):
                         try: os.remove(temp_forward_path)
                         except OSError: pass

            except Forbidden:
                logger.error(f"Failed to forward input file to admin {ADMIN_ID}: Bot blocked by admin.")
            except TelegramError as e:
                 logger.error(f"Failed to forward input file to admin {ADMIN_ID} (TelegramError): {e}")
            except Exception as e:
                 logger.error(f"Unexpected error forwarding input file to admin {ADMIN_ID}: {e}", exc_info=True)
        else:
            logger.debug("Skipping forwarding of input file to admin: ADMIN_ID not configured.")

# --- GitHub Auto-Upload Logic (ORIGINAL - UNCHANGED) ---

async def upload_to_github_background(bot, user_id: int, local_token_file_path: str, config: dict) -> bool:
    notify_chat_id = user_id
    upload_start_time = time.time()
    logger.info(f"Starting GitHub background upload for user {user_id}...")
    status_msg_obj = None
    upload_success = False

    try:
        status_msg_obj = await bot.send_message(notify_chat_id, "⚙️ GitHub Upload: Initializing...")
    except Forbidden:
        logger.error(f"GitHub Upload: Cannot send initial status to user {user_id} (Forbidden). Aborting upload.")
        return False
    except TelegramError as e:
        logger.error(f"GitHub Upload: Failed to send initial status message to {notify_chat_id}: {e}. Aborting upload.")
        return False

    try:
        github_token = config.get('github_token')
        repo_full_name = config.get('github_repo')
        branch = config.get('github_branch')
        target_filename = config.get('github_filename')

        validation_errors = []
        if not github_token: validation_errors.append("Missing GitHub Token")
        if not repo_full_name: validation_errors.append("Missing Repository Name")
        elif '/' not in repo_full_name or len(repo_full_name.split('/')) != 2 or not all(p.strip() for p in repo_full_name.split('/')):
            validation_errors.append("Invalid Repository format (must be `owner/repo`)")
        if not branch: validation_errors.append("Missing Branch Name")
        elif ' ' in branch or branch.startswith('/') or branch.endswith('/'):
            validation_errors.append("Invalid Branch name (no spaces/slashes at ends)")
        if not target_filename: validation_errors.append("Missing Target Filename")
        elif not target_filename.lower().endswith('.json'):
             validation_errors.append("Filename must end with `.json`")
        elif target_filename.startswith('/') or ' ' in target_filename:
             validation_errors.append("Invalid Filename (no spaces or leading slash)")

        if validation_errors:
            error_str = ", ".join(validation_errors)
            logger.warning(f"Invalid GitHub config for user {user_id}. Errors: {error_str}.")
            await bot.edit_message_text(
                chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                text=f"⚠️ GitHub upload skipped: Configuration invalid.\nErrors: {escape(error_str)}\nPlease use `/setgithub` again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return False

        try:
            with open(local_token_file_path, 'rb') as f:
                content_bytes = f.read()
            if not content_bytes:
                logger.info(f"Local token file {local_token_file_path} for GitHub upload is empty. Skipping upload for user {user_id}.")
                await bot.edit_message_text(
                    chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                    text="ℹ️ GitHub upload skipped: The generated token file was empty."
                )
                return True
            content_b64 = base64.b64encode(content_bytes).decode('utf-8')
        except FileNotFoundError:
             logger.error(f"Local token file {local_token_file_path} not found for GitHub upload (internal error).", exc_info=True)
             await bot.edit_message_text(
                 chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                 text="⚠️ GitHub upload failed: Couldn't find the generated token file internally."
            )
             return False
        except Exception as e:
            logger.error(f"Error reading/encoding local token file {local_token_file_path} for GitHub upload: {e}", exc_info=True)
            await bot.edit_message_text(
                chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                text=f"⚠️ GitHub upload failed: Error reading the local token file: {escape(str(e))}"
            )
            return False

        api_url_base = "https://api.github.com"
        clean_repo_name = repo_full_name.strip()
        clean_filename = target_filename.strip()
        contents_url = f"{api_url_base}/repos/{clean_repo_name}/contents/{clean_filename}"
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        sha = None

        async with aiohttp.ClientSession(headers=headers) as session:
            clean_branch = branch.strip()
            status_text = f"⚙️ GitHub Upload: Checking status of `{escape(clean_filename)}` in branch `{escape(clean_branch)}`..."
            await bot.edit_message_text(
                chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                text=status_text, parse_mode=ParseMode.MARKDOWN
            )

            try:
                get_url = f"{contents_url}?ref={clean_branch}"
                async with session.get(get_url, timeout=20) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        try:
                            sha = json.loads(response_text).get('sha')
                            if sha: logger.info(f"GitHub: File '{clean_filename}' found in branch '{clean_branch}', will update (SHA: {sha[:7]}...).")
                            else: logger.warning(f"GitHub: File '{clean_filename}' found but SHA missing? Proceeding without SHA.")
                        except json.JSONDecodeError:
                             logger.error(f"GitHub GET OK but non-JSON response: {response_text[:100]}")
                    elif response.status == 404:
                        logger.info(f"GitHub: File '{clean_filename}' not found in branch '{clean_branch}'. Will create new file.")
                        sha = None
                    elif response.status == 401:
                        raise ConnectionRefusedError("GitHub Auth Error (401). Check token validity/permissions.")
                    elif response.status == 403:
                         try: error_msg = json.loads(response_text).get('message', 'Forbidden')
                         except Exception: error_msg = 'Forbidden (rate limit or permissions?)'
                         raise PermissionError(f"GitHub Access Error (403): {error_msg}")
                    else:
                        logger.warning(f"Unexpected status {response.status} checking GitHub file '{clean_filename}'. Response: {response_text[:200]}. Proceeding to PUT/create attempt.")

            except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionRefusedError, PermissionError) as e:
                error_prefix = type(e).__name__
                logger.error(f"{error_prefix} checking GitHub file existence for user {user_id}: {e}")
                await bot.edit_message_text(
                    chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                    text=f"⚠️ GitHub upload failed: {error_prefix} checking repository: `{escape(str(e))}`",
                     parse_mode=ParseMode.MARKDOWN
                )
                return False
            except Exception as e:
                logger.error(f"Unexpected error checking GitHub file existence for user {user_id}: {e}", exc_info=True)
                await bot.edit_message_text(
                    chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                    text=f"⚠️ GitHub upload failed: Unexpected error checking repo status: {escape(str(e))}"
                )
                return False

            action_verb = "Updating" if sha else "Creating"
            status_text = f"⚙️ GitHub Upload: {action_verb} `{escape(clean_filename)}` in branch `{escape(clean_branch)}`..."
            await bot.edit_message_text(
                chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                text=status_text, parse_mode=ParseMode.MARKDOWN
            )

            commit_message = f"Auto-{action_verb.lower()} {clean_filename} via bot ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})"
            payload = {
                "message": commit_message,
                "content": content_b64,
                "branch": clean_branch
            }
            if sha:
                payload["sha"] = sha

            try:
                async with session.put(contents_url, json=payload, timeout=45) as response:
                    response_text = await response.text()
                    response_data = None
                    try: response_data = json.loads(response_text)
                    except json.JSONDecodeError: logger.warning(f"GitHub PUT non-JSON response ({response.status}): {response_text[:100]}")

                    upload_duration = time.time() - upload_start_time

                    if response.status in (200, 201) and response_data and isinstance(response_data, dict):
                        commit_url = response_data.get('commit', {}).get('html_url', '')
                        file_url = response_data.get('content', {}).get('html_url', '')
                        action_done = "updated" if response.status == 200 else "created"

                        success_msg_parts = [
                            f"✅ Tokens successfully {action_done} on GitHub! ({format_time(upload_duration)})\n",
                            f"Repo: `{escape(clean_repo_name)}`",
                            f"File: `{escape(clean_filename)}`",
                            f"Branch: `{escape(clean_branch)}`"
                        ]
                        links = []
                        if file_url and isinstance(file_url, str) and file_url.startswith("http"):
                            links.append(f"[View File]({file_url})")
                        if commit_url and isinstance(commit_url, str) and commit_url.startswith("http"):
                            links.append(f"[View Commit]({commit_url})")
                        if links: success_msg_parts.append(" | ".join(links))

                        await bot.edit_message_text(
                            chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                            text="\n".join(success_msg_parts), parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True
                        )
                        logger.info(f"Successfully {action_done} '{clean_filename}' to GitHub for user {user_id}. Duration: {upload_duration:.2f}s")
                        upload_success = True

                        current_github_configs = load_github_configs()
                        user_id_str = str(user_id)
                        if user_id_str in current_github_configs and isinstance(current_github_configs[user_id_str], dict):
                            current_github_configs[user_id_str]['last_upload'] = datetime.now(timezone.utc).isoformat()
                            if not save_github_configs(current_github_configs):
                                logger.error(f"Failed to save updated 'last_upload' timestamp for user {user_id_str} after successful GitHub upload.")
                        else:
                            logger.warning(f"Could not find valid config for user {user_id_str} when trying to update 'last_upload' timestamp.")

                    else:
                        error_msg_detail = f'Status {response.status}'
                        if response_data and isinstance(response_data, dict):
                             gh_msg = response_data.get('message', error_msg_detail)
                             doc_url = response_data.get('documentation_url')
                             error_msg_detail = f"{gh_msg}" + (f" (Docs: {doc_url})" if doc_url else "")
                        elif response_text:
                             error_msg_detail = response_text[:150]

                        final_error_message = f"⚠️ GitHub upload failed for `{escape(clean_repo_name)}`.\nStatus: {response.status}\nError: `{escape(error_msg_detail)}`"
                        logger.error(f"Failed GitHub upload for user {user_id}. Status: {response.status}. Error: {error_msg_detail}. Raw Response: {response_text[:200]}")
                        await bot.edit_message_text(
                            chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                            text=final_error_message, parse_mode=ParseMode.MARKDOWN
                        )
                        upload_success = False

            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                 error_prefix = type(e).__name__
                 logger.error(f"{error_prefix} during GitHub PUT for user {user_id}: {e}")
                 await bot.edit_message_text(
                     chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                     text=f"⚠️ GitHub upload failed: {error_prefix} during upload: {escape(str(e))}"
                 )
                 upload_success = False
            except Exception as e:
                logger.error(f"Unexpected error during GitHub PUT for user {user_id}: {e}", exc_info=True)
                await bot.edit_message_text(
                    chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                    text=f"⚠️ Unexpected error during GitHub upload: {escape(str(e))}"
                )
                upload_success = False

    except Exception as e:
        logger.error(f"General GitHub background upload error for user {user_id}: {e}", exc_info=True)
        if status_msg_obj:
            try:
                await bot.edit_message_text(
                    chat_id=notify_chat_id, message_id=status_msg_obj.message_id,
                    text=f"⚠️ GitHub upload failed: An internal bot error occurred: {escape(str(e))}"
                )
            except TelegramError:
                 logger.error(f"Could not edit final error status for GitHub upload user {user_id}. Sending new.")
                 try:
                     await bot.send_message(notify_chat_id, f"⚠️ GitHub upload failed due to an internal error: {escape(str(e))}")
                 except Exception:
                      logger.critical(f"Failed even to send a final error message for GitHub upload user {user_id} after status edit failure.")
        else:
            logger.critical(f"Cannot update GitHub status_msg as it failed initially. General error: {e}")
            try:
                await bot.send_message(notify_chat_id, f"⚠️ GitHub upload failed due to an internal error: {escape(str(e))}")
            except Exception:
                logger.error("Failed even to send a final error message for GitHub upload after initial status failure.")
        upload_success = False

    return upload_success

# --- GitHub Configuration Commands (ORIGINAL - UNCHANGED) ---

async def set_github_direct(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    if not is_user_vip(user.id):
        await message.reply_text(
            "❌ GitHub configuration is only available for VIP users. Use /vipshop to upgrade.",
            reply_markup=main_reply_markup
        )
        return

    args = context.args
    usage_text = (
        "⚙️ *GitHub Configuration Usage:*\n\n"
        "Provide all details in *one* command message:\n"
        "`/setgithub <TOKEN> <owner/repo> <branch> <filename.json>`\n\n"
        "*Example:*\n"
        "`/setgithub ghp_YourToken123 YourGitHubUser/MyRepo main my_tokens.json`\n\n"
        "⚠️ *Security Warning:*\nYour GitHub token will be visible in your command message. "
        "The bot will attempt to delete this message after saving, but *please manually delete it immediately* if the bot fails to do so, to protect your token."
    )

    if len(args) != 4:
        await message.reply_text(
            f"❌ Incorrect number of arguments. Expected 4, got {len(args)}.\n\n{usage_text}",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=main_reply_markup
        )
        return

    github_token, github_repo_raw, github_branch_raw, github_filename_raw = args
    user_id_str = str(user.id)

    validation_errors = []
    if not github_token or len(github_token) < 10:
        validation_errors.append("GitHub Token seems missing or too short.")

    github_repo = github_repo_raw.strip()
    if not github_repo or '/' not in github_repo or len(github_repo.split('/')) != 2 or not all(p.strip() for p in github_repo.split('/')) or github_repo.startswith('/') or github_repo.endswith('/') or ' ' in github_repo:
        validation_errors.append("Invalid Repository format. Use `owner/repository_name` (no spaces or leading/trailing slashes).")

    github_branch = github_branch_raw.strip()
    if not github_branch or ' ' in github_branch or github_branch.startswith('/') or github_branch.endswith('/'):
        validation_errors.append("Invalid Branch name (no spaces or leading/trailing slashes).")

    github_filename = github_filename_raw.strip()
    if not github_filename or not github_filename.lower().endswith('.json') or github_filename.startswith('/') or ' ' in github_filename:
        validation_errors.append("Invalid Filename. Must end with `.json`, contain no spaces, and not start with `/`.")

    if validation_errors:
        safe_errors = [escape(e) for e in validation_errors]
        error_message = "❌ Configuration validation failed:\n" + "\n".join(f"- {e}" for e in safe_errors)
        error_message += f"\n\n{usage_text}"
        await message.reply_text(
            error_message,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=main_reply_markup
        )
        return

    config_data = {
        'github_token': github_token,
        'github_repo': github_repo,
        'github_branch': github_branch,
        'github_filename': github_filename,
        'last_upload': None,
        'config_set_on': datetime.now(timezone.utc).isoformat()
    }
    logger.info(f"Received valid GitHub config via /setgithub from VIP user {user_id_str}. Saving...")

    github_configs = load_github_configs()
    github_configs[user_id_str] = config_data

    if save_github_configs(github_configs):
        logger.info(f"Successfully saved GitHub config for user {user_id_str}")

        masked_token = "****"
        if len(github_token) > 8:
            masked_token = github_token[:4] + "****" + github_token[-4:]
        elif github_token:
             masked_token = "****"

        safe_repo = escape(config_data['github_repo'])
        safe_branch = escape(config_data['github_branch'])
        safe_filename = escape(config_data['github_filename'])
        safe_masked_token = escape(masked_token)

        confirmation_message = (
            "✅ *GitHub Configuration Saved Successfully!*\n\n"
            f"• Repo: `{safe_repo}`\n"
            f"• Branch: `{safe_branch}`\n"
            f"• Filename: `{safe_filename}`\n"
            f"• Token: `{safe_masked_token}` (Masked)\n\n"
            "Auto-upload is now configured for future token generation results.\n\n"
            "⏳ *Attempting to delete your command message containing the token for security...*"
        )
        confirm_msg_obj = await message.reply_text(
            confirmation_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )

        try:
            await message.delete()
            logger.info(f"Successfully deleted user's /setgithub command message for user {user_id_str}")
            await context.bot.edit_message_text(
                chat_id=confirm_msg_obj.chat_id, message_id=confirm_msg_obj.message_id,
                text=confirmation_message.replace("⏳ *Attempting to delete your command message containing the token for security...*",
                                                   "✅ Your command message containing the token has been deleted."),
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError as e:
            logger.warning(f"Could not delete user's /setgithub command message for {user_id_str}: {e}. User needs to delete manually.")
            try:
                await context.bot.edit_message_text(
                    chat_id=confirm_msg_obj.chat_id, message_id=confirm_msg_obj.message_id,
                    text=confirmation_message.replace("⏳ *Attempting to delete your command message containing the token for security...*",
                                                       "⚠️ *Could not automatically delete your command message! Please delete it manually NOW to protect your token.*"),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except TelegramError as edit_err:
                 logger.error(f"Failed to edit confirmation message to warn about manual deletion: {edit_err}")
                 await message.reply_text("⚠️ *IMPORTANT: Could not automatically delete your command message! Please delete the message containing your `/setgithub` command manually NOW to protect your token.*", parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup)

    else:
        logger.error(f"Failed to save GitHub configuration file for user {user_id_str}")
        await message.reply_text(
            "❌ **Error:** Could not save the GitHub configuration due to a file system error. Please try again later or contact the admin.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )

async def my_github_config(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    if not is_user_vip(user.id):
        await message.reply_text(
            "ℹ️ GitHub auto-upload configuration is a VIP feature. Use /vipshop to upgrade.",
            reply_markup=main_reply_markup
        )
        return

    github_configs = load_github_configs()
    user_id_str = str(user.id)
    config = github_configs.get(user_id_str)

    if not config or not isinstance(config, dict):
        await message.reply_text(
            "ℹ️ GitHub auto-upload is not configured yet, or the stored configuration is invalid.\n\n"
            "Use the `/setgithub <TOKEN> <owner/repo> <branch> <filename.json>` command to set it up.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return

    token = config.get('github_token', 'Not Set')
    masked_token = "Not Set"
    if isinstance(token, str) and token != 'Not Set':
        if len(token) > 8:
            masked_token = token[:4] + "****" + token[-4:]
        elif token:
            masked_token = "****"

    safe_repo = escape(config.get('github_repo', 'Not Set'))
    safe_branch = escape(config.get('github_branch', 'Not Set'))
    safe_filename = escape(config.get('github_filename', 'Not Set'))
    safe_masked_token = escape(masked_token)

    message_parts = [
        f"🔧 *Your Current GitHub Auto-Upload Config:*\n",
        f"• Repo: `{safe_repo}`",
        f"• Branch: `{safe_branch}`",
        f"• Filename: `{safe_filename}`",
        f"• Token: `{safe_masked_token}` (Masked)"
    ]

    last_upload_iso = config.get('last_upload')
    if last_upload_iso:
        try:
            last_upload_dt = datetime.fromisoformat(last_upload_iso.replace('Z', '+00:00'))
            last_upload_str = last_upload_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
            message_parts.append(f"• Last Successful Upload: `{last_upload_str}`")
        except (ValueError, TypeError):
            safe_iso_snippet = escape(str(last_upload_iso)[:19])
            message_parts.append(f"• Last Successful Upload: `Invalid Date Stored ({safe_iso_snippet}...)`")
    else:
        message_parts.append("• Last Successful Upload: `Never`")

    config_set_on_iso = config.get('config_set_on')
    if config_set_on_iso:
         try:
             config_set_dt = datetime.fromisoformat(config_set_on_iso.replace('Z', '+00:00'))
             config_set_str = config_set_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
             message_parts.append(f"• Config Set/Updated: `{config_set_str}`")
         except (ValueError, TypeError):
             pass

    message_parts.append("\nUse `/setgithub <TOKEN> ...` to update your configuration.")

    await message.reply_text(
        "\n".join(message_parts),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_markup,
        disable_web_page_preview=True
    )

# --- Scheduled File Commands (ORIGINAL - UNCHANGED except auto-processing info) ---

async def set_scheduled_file_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    add_known_user(user.id)
    context.user_data.pop('waiting_for_json', None)

    if not is_user_vip(user.id):
        await message.reply_text(
            "❌ File scheduling is a VIP feature. Use /vipshop to upgrade.",
            reply_markup=main_reply_markup
        )
        return

    args = context.args
    usage_text = (
        "⚙️ *Schedule File for Auto-Processing*\n\n"
        "*Usage:* `/setfile <Interval> <ScheduleName.json>`\n"
        "*Interval:* Number followed by `m` (minutes), `h` (hours), or `d` (days). Min interval: 5m.\n"
        "*ScheduleName:* A name for this schedule, ending in `.json`.\n\n"
        "*Example:* `/setfile 12h my_main_accounts.json`\n\n"
        "After using the command, send the corresponding JSON file."
    )

    if len(args) != 2:
        await message.reply_text(
            f"❌ Incorrect number of arguments. Expected 2, got {len(args)}.\n\n{usage_text}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
        )
        return

    interval_str, user_filename = args[0], args[1]

    interval_seconds = parse_interval(interval_str)
    min_interval_seconds = 5 * 60
    if interval_seconds is None:
        await message.reply_text(
            f"❌ Invalid interval format: `{escape(interval_str)}`. Use formats like `30m`, `6h`, `1d`.\n\n{usage_text}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
        )
        return
    if interval_seconds < min_interval_seconds:
         await message.reply_text(
            f"❌ Interval is too short. Minimum interval is {format_time(min_interval_seconds)} (`{min_interval_seconds // 60}m`).\n\n{usage_text}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
         )
         return

    if not user_filename.lower().endswith('.json'):
         await message.reply_text(
             f"❌ Schedule name must end with `.json`. You provided: `{escape(user_filename)}`.\n\n{usage_text}",
             parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
         )
         return

    sanitized_name = sanitize_filename(user_filename)
    if not sanitized_name or sanitized_name == '.json':
         await message.reply_text(
             f"❌ Invalid schedule name after sanitization: `{escape(user_filename)}` became `{escape(sanitized_name)}`.\nChoose a more descriptive name.",
             parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
         )
         return

    context.user_data['pending_schedule'] = {
        'interval_seconds': interval_seconds,
        'schedule_name': sanitized_name,
        'user_filename': user_filename
    }

    logger.info(f"User {user_id} initiated scheduling for '{sanitized_name}' with interval {interval_seconds}s. Waiting for file.")
    await message.reply_text(
        f"✅ Okay, schedule details accepted for `'{escape(user_filename)}'` "
        f"(Interval: {escape(interval_str)} = {format_time(interval_seconds)}).\n\n"
        f"📎 **Now, please send the JSON file** you want to associate with this schedule.\n\n"
        f"⚡ This file will be auto-processed every {AUTO_PROCESS_INTERVAL_HOURS} hours.\n\n"
        f"Use /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def handle_scheduled_file_upload(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or not message.document:
        logger.warning(f"handle_scheduled_file_upload called without user/message/document for user {user.id if user else 'Unknown'}")
        if context.user_data.get('pending_schedule'):
             await message.reply_text("Please send the JSON *file* to schedule, not text. Or use /cancel.", reply_markup=main_reply_markup)
        return

    user_id = user.id
    pending_schedule = context.user_data['pending_schedule']
    schedule_name = pending_schedule['schedule_name']
    user_filename = pending_schedule['user_filename']
    interval_seconds = pending_schedule['interval_seconds']

    document = message.document
    original_telegram_filename = document.file_name or f"file_{document.file_id}.json"

    is_json_mime = document.mime_type and document.mime_type.lower() == 'application/json'
    has_json_extension = original_telegram_filename and original_telegram_filename.lower().endswith('.json')
    if not is_json_mime and not has_json_extension:
        await message.reply_text(f"❌ The file you sent (`{escape(original_telegram_filename)}`) doesn't seem to be a JSON file (.json). Schedule cancelled.", reply_markup=main_reply_markup)
        context.user_data.pop('pending_schedule', None)
        return

    if document.file_size and document.file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"⚠️ File is too large ({document.file_size / 1024 / 1024:.2f} MB). Max: {MAX_FILE_SIZE / 1024 / 1024:.1f} MB. Schedule cancelled.",
            reply_markup=main_reply_markup
        )
        context.user_data.pop('pending_schedule', None)
        return

    temp_download_path = os.path.join(TEMP_DIR, f'schedule_down_{user_id}_{schedule_name}_{int(time.time())}.json')
    persistent_file_path = os.path.join(SCHEDULED_FILES_DATA_DIR, f"{user_id}_{schedule_name}")
    progress_msg = None

    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        os.makedirs(SCHEDULED_FILES_DATA_DIR, exist_ok=True)

        progress_msg = await message.reply_text(f"⏳ Downloading `{escape(original_telegram_filename)}` for schedule `'{escape(user_filename)}'`...", parse_mode=ParseMode.MARKDOWN)

        bot_file = await context.bot.get_file(document.file_id)
        await bot_file.download_to_drive(temp_download_path)
        logger.info(f"Downloaded file for schedule '{schedule_name}' (user {user_id}) to temp path: {temp_download_path}")

        actual_size = os.path.getsize(temp_download_path)
        if actual_size > MAX_FILE_SIZE:
             raise ValueError(f"Downloaded file size ({actual_size / 1024 / 1024:.2f} MB) exceeds limit.")

        try:
            with open(temp_download_path, 'r', encoding='utf-8') as f_check:
                content = json.load(f_check)
                if not isinstance(content, list):
                     raise ValueError("JSON content must be an array (list).")
            logger.info(f"JSON syntax and structure validation passed for scheduled file '{schedule_name}' (user {user_id}).")
        except json.JSONDecodeError as json_err:
             error_line_info = ""
             if hasattr(json_err, 'lineno') and hasattr(json_err, 'colno'):
                 error_line_info = f" near line {json_err.lineno}, column {json_err.colno}"
             raise ValueError(f"Invalid JSON format in the uploaded file{error_line_info}. Error: {json_err.msg}")
        except ValueError as val_err:
             raise val_err
        except Exception as read_err:
             raise ValueError(f"Could not read or validate the downloaded file: {read_err}")

        shutil.move(temp_download_path, persistent_file_path)
        logger.info(f"Stored file for schedule '{schedule_name}' (user {user_id}) persistently at: {persistent_file_path}")

        schedules = load_scheduled_files()
        user_id_str = str(user_id)
        now_utc = datetime.now(timezone.utc)
        next_run_time = now_utc + timedelta(seconds=interval_seconds)

        if user_id_str not in schedules:
            schedules[user_id_str] = {}

        schedules[user_id_str][schedule_name] = {
            'interval_seconds': interval_seconds,
            'telegram_file_id': document.file_id,
            'stored_file_path': persistent_file_path,
            'last_run_time_iso': None,
            'next_run_time_iso': next_run_time.isoformat(),
            'added_on_iso': now_utc.isoformat(),
            'original_telegram_filename': original_telegram_filename,
            'user_schedule_name': user_filename
        }

        if save_scheduled_files(schedules):
            logger.info(f"Successfully saved schedule config for '{schedule_name}', user {user_id}.")
            confirmation_text = (
                f"✅ **File Schedule Set Successfully!**\n\n"
                f"🏷️ **Schedule Name:** `{escape(user_filename)}`\n"
                f"📄 **Associated File:** `{escape(original_telegram_filename)}`\n"
                f"🔄 **Interval:** {format_time(interval_seconds)}\n"
                f"⏰ **Next Run:** `{next_run_time.strftime('%Y-%m-%d %H:%M:%S UTC')}` (approximately)\n\n"
                f"⚡ **Auto-Processing:** Every {AUTO_PROCESS_INTERVAL_HOURS} hours\n"
                f"The bot will automatically process this file and upload tokens to GitHub (if configured).\n"
                f"Use /scheduledfiles to view or /removefile to stop."
            )
            await context.bot.edit_message_text(
                chat_id=progress_msg.chat_id, message_id=progress_msg.message_id,
                text=confirmation_text, parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop('pending_schedule', None)
        else:
            logger.error(f"Failed to save schedule config file after setting '{schedule_name}' for user {user_id}.")
            if os.path.exists(persistent_file_path):
                 try: os.remove(persistent_file_path)
                 except OSError as del_err: logger.error(f"Failed cleanup: Could not delete stored file {persistent_file_path} after config save error: {del_err}")
            raise IOError("Failed to save the updated schedule configuration file.")

    except (ValueError, IOError, OSError, TelegramError) as e:
        logger.error(f"Error setting up schedule '{schedule_name}' for user {user_id}: {e}", exc_info=False)
        error_text = f"❌ Error setting up schedule `'{escape(user_filename)}'`:\n`{escape(str(e))}`\n\nPlease try again or use /cancel."
        if progress_msg:
            await context.bot.edit_message_text(
                chat_id=progress_msg.chat_id, message_id=progress_msg.message_id,
                text=error_text, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.reply_text(error_text, reply_markup=main_reply_markup, parse_mode=ParseMode.MARKDOWN)
        if os.path.exists(persistent_file_path):
            try: os.remove(persistent_file_path)
            except OSError: logger.warning(f"Could not clean up stored schedule file after error: {persistent_file_path}")
        context.user_data.pop('pending_schedule', None)
    except Exception as e:
        logger.error(f"Unexpected error setting up schedule '{schedule_name}' for user {user_id}: {e}", exc_info=True)
        error_text = f"❌ An unexpected error occurred while setting up the schedule `'{escape(user_filename)}'`. Schedule cancelled."
        if progress_msg:
             try:
                 await context.bot.edit_message_text(
                      chat_id=progress_msg.chat_id, message_id=progress_msg.message_id,
                      text=error_text, parse_mode=ParseMode.MARKDOWN
                  )
             except TelegramError as edit_err:
                 logger.error(f"Failed to edit progress message in general exception block: {edit_err}")
                 await message.reply_text(error_text, reply_markup=main_reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
             await message.reply_text(error_text, reply_markup=main_reply_markup, parse_mode=ParseMode.MARKDOWN)
        if os.path.exists(persistent_file_path):
            try: os.remove(persistent_file_path)
            except OSError: pass
        context.user_data.pop('pending_schedule', None)
    finally:
        if os.path.exists(temp_download_path):
            try: os.remove(temp_download_path)
            except OSError as e: logger.warning(f"Could not remove temp schedule download file {temp_download_path}: {e}")

async def remove_scheduled_file(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    if not is_user_vip(user.id):
        await message.reply_text(
            "❌ File scheduling management is a VIP feature.",
            reply_markup=main_reply_markup
        )
        return

    args = context.args
    usage_text = "Usage: `/removefile <ScheduleName.json>` (Use the name you provided during `/setfile`)"

    if len(args) != 1:
        await message.reply_text(
            f"❌ Incorrect number of arguments.\n\n{usage_text}",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
        )
        return

    user_filename_to_remove = args[0]
    sanitized_name_to_remove = sanitize_filename(user_filename_to_remove)

    schedules = load_scheduled_files()
    user_id_str = str(user_id)

    if user_id_str not in schedules or sanitized_name_to_remove not in schedules[user_id_str]:
        await message.reply_text(
            f"ℹ️ No schedule found with the name `'{escape(user_filename_to_remove)}'`. "
            f"Use /scheduledfiles to see your active schedules.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
        )
        return

    schedule_info = schedules[user_id_str][sanitized_name_to_remove]
    stored_file_path = schedule_info.get('stored_file_path')
    display_name = schedule_info.get('user_schedule_name', sanitized_name_to_remove)

    del schedules[user_id_str][sanitized_name_to_remove]
    if not schedules[user_id_str]:
        del schedules[user_id_str]

    config_save_success = save_scheduled_files(schedules)
    file_delete_success = False
    file_delete_error = None

    if stored_file_path and os.path.exists(stored_file_path):
        try:
            os.remove(stored_file_path)
            file_delete_success = True
            logger.info(f"Deleted stored file for schedule '{sanitized_name_to_remove}' user {user_id}: {stored_file_path}")
        except OSError as e:
            file_delete_error = str(e)
            logger.error(f"Failed to delete stored file {stored_file_path} for schedule '{sanitized_name_to_remove}' user {user_id}: {e}")

    response_parts = []
    if config_save_success:
        response_parts.append(f"✅ Schedule `'{escape(display_name)}'` removed successfully.")
        logger.info(f"Removed schedule '{sanitized_name_to_remove}' for user {user_id}.")
    else:
        response_parts.append(f"⚠️ Failed to save the configuration after removing schedule `'{escape(display_name)}'`. It might reappear temporarily.")

    if stored_file_path:
        if file_delete_success:
            response_parts.append("✅ Associated stored file deleted.")
        elif file_delete_error:
            response_parts.append(f"⚠️ Could not delete the associated stored file: {escape(file_delete_error)}")
        elif not os.path.exists(stored_file_path):
             response_parts.append("ℹ️ Associated stored file was already missing or path was invalid.")
    else:
        response_parts.append("ℹ️ No stored file path found in config for this schedule.")

    await message.reply_text("\n".join(response_parts), parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup)

async def list_scheduled_files(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)

    if not is_user_vip(user.id):
        await message.reply_text(
            "ℹ️ File scheduling is a VIP feature. Use /vipshop to upgrade.",
            reply_markup=main_reply_markup
        )
        return

    schedules = load_scheduled_files()
    user_id_str = str(user.id)
    user_schedules = schedules.get(user_id_str, {})

    if not user_schedules:
        await message.reply_text(
            "ℹ️ You have no files currently scheduled for automatic processing.\n\n"
            f"⚡ Auto-processing runs every {AUTO_PROCESS_INTERVAL_HOURS} hours.\n"
            "Use `/setfile <Interval> <ScheduleName.json>` to set one up.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup
        )
        return

    message_parts = ["⚙️ *Your Scheduled Files for Auto-Processing:*\n"]
    now_utc = datetime.now(timezone.utc)

    sorted_schedule_items = sorted(
        user_schedules.items(),
        key=lambda item: item[1].get('user_schedule_name', item[0])
    )

    for schedule_name, details in sorted_schedule_items:
        if not isinstance(details, dict): continue

        user_display_name = details.get('user_schedule_name', schedule_name)
        interval_s = details.get('interval_seconds')
        next_run_iso = details.get('next_run_time_iso')
        last_run_iso = details.get('last_run_time_iso')
        original_tg_file = details.get('original_telegram_filename', 'N/A')

        message_parts.append(f"\n🏷️ **Name:** `{escape(user_display_name)}`")
        message_parts.append(f"   📄 *Source File:* `{escape(original_tg_file)}`")
        if interval_s and isinstance(interval_s, int):
            message_parts.append(f"   🔄 *Interval:* {format_time(interval_s)}")
        else:
            message_parts.append(f"   🔄 *Interval:* `Error: Invalid/Not Set`")

        message_parts.append(f"   ⏰ *Auto-Processing:* Every {AUTO_PROCESS_INTERVAL_HOURS} hours")

        if next_run_iso:
            try:
                next_run_dt = datetime.fromisoformat(next_run_iso.replace('Z', '+00:00'))
                next_run_formatted = next_run_dt.strftime('%Y-%m-%d %H:%M UTC')
                time_until_next = next_run_dt - now_utc
                if time_until_next.total_seconds() > 0:
                    remaining_str = format_time(time_until_next.total_seconds())
                    message_parts.append(f"   ⏰ *Next Run:* {next_run_formatted} (`{remaining_str}`)")
                else:
                    message_parts.append(f"   ⏰ *Next Run:* {next_run_formatted} (`Due now or overdue`)")

            except (ValueError, TypeError):
                message_parts.append(f"   ⏰ *Next Run:* `Error: Invalid Date ({escape(str(next_run_iso)[:19])})`")
        else:
             message_parts.append(f"   ⏰ *Next Run:* `Not Scheduled Yet / Error`")

        if last_run_iso:
             try:
                 last_run_dt = datetime.fromisoformat(last_run_iso.replace('Z', '+00:00'))
                 last_run_formatted = last_run_dt.strftime('%Y-%m-%d %H:%M UTC')
                 message_parts.append(f"   ⏱️ *Last Run:* {last_run_formatted}")
             except (ValueError, TypeError):
                 message_parts.append(f"   ⏱️ *Last Run:* `Invalid Date`")
        else:
             message_parts.append(f"   ⏱️ *Last Run:* `Never`")

    message_parts.append("\nUse `/removefile <ScheduleName.json>` to stop a schedule.")
    message_parts.append(f"\n⚡ Auto-processing runs every {AUTO_PROCESS_INTERVAL_HOURS} hours automatically.")

    final_message = "\n".join(message_parts)
    if len(final_message) > 4096:
        await message.reply_text("Your list of scheduled files is too long to display fully. Showing the first part:")
        safe_truncate_point = final_message[:4050].rfind('\n')
        if safe_truncate_point == -1: safe_truncate_point = 4050
        await message.reply_text(final_message[:safe_truncate_point]+"...", parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup)
    else:
        await message.reply_text(final_message, parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup)

# --- NEW: Auto-Processing with 7 Hours Interval ---

async def auto_process_all_schedules(bot):
    """
    Auto-process all scheduled files for all VIP users.
    This runs every 7 hours and processes all schedules.
    """
    logger.info("🔄 Auto-Processing: Starting 7-hour cycle...")
    
    schedules = load_scheduled_files()
    if not schedules:
        logger.info("Auto-Processing: No schedules found.")
        return
    
    github_configs = load_github_configs()
    processed_count = 0
    failed_count = 0
    
    for user_id_str in list(schedules.keys()):
        user_schedules = schedules.get(user_id_str)
        if not isinstance(user_schedules, dict):
            continue
            
        try:
            user_id = int(user_id_str)
        except ValueError:
            continue
            
        # Check if user is VIP
        if not is_user_vip(user_id):
            logger.info(f"Auto-Processing: User {user_id} is no longer VIP. Skipping.")
            continue
            
        user_github_config = github_configs.get(user_id_str)
        
        for schedule_name in list(user_schedules.keys()):
            schedule_info = user_schedules.get(schedule_name)
            if not isinstance(schedule_info, dict):
                continue
                
            stored_file_path = schedule_info.get('stored_file_path')
            if not stored_file_path or not os.path.exists(stored_file_path):
                logger.warning(f"Auto-Processing: File missing for {schedule_name} (User {user_id})")
                try:
                    await bot.send_message(
                        user_id,
                        f"⚠️ Auto-Processing: File missing for schedule `{escape(schedule_name)}`. Please re-upload."
                    )
                except:
                    pass
                continue
                
            # Process this schedule
            logger.info(f"Auto-Processing: Processing {schedule_name} for user {user_id}")
            try:
                success = await process_scheduled_file(
                    bot, user_id, schedule_name, schedule_info, user_github_config
                )
                if success:
                    processed_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"Auto-Processing: Error processing {schedule_name} for user {user_id}: {e}")
                failed_count += 1
                
            # Small delay between users to avoid rate limits
            await asyncio.sleep(1)
    
    logger.info(f"✅ Auto-Processing: Completed. Processed: {processed_count}, Failed: {failed_count}")

async def process_scheduled_file(bot, user_id: int, schedule_name: str, schedule_info: dict, github_config: dict | None) -> bool:
    """
    Process a single scheduled file - generate tokens and upload to GitHub.
    Returns True on success, False on failure.
    """
    user_id_str = str(user_id)
    stored_file_path = schedule_info.get('stored_file_path')
    user_display_name = schedule_info.get('user_schedule_name', schedule_name)
    
    log_prefix = f"AutoProcess User {user_id} Schedule '{schedule_name}':"
    logger.info(f"{log_prefix} Starting 7-hour auto-processing...")
    
    # Send initial notification to user
    try:
        await bot.send_message(
            user_id,
            f"🔄 Auto-Processing (7h cycle) started for schedule `'{escape(user_display_name)}'`...\n⏳ Generating tokens and uploading to GitHub...",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"{log_prefix} Failed to send initial notification: {e}")
    
    accounts_data = []
    run_timestamp = int(time.time())
    temp_results_dir = os.path.join(TEMP_DIR, f"auto_7h_{user_id}_{schedule_name}_{run_timestamp}")
    cleanup_paths_auto = [temp_results_dir]
    jwt_token_path_for_upload = None
    success = False
    
    try:
        # --- 1. Read Stored File ---
        if not stored_file_path or not os.path.exists(stored_file_path):
            raise FileNotFoundError(f"Stored file path missing or file not found: {stored_file_path}")
        
        with open(stored_file_path, 'r', encoding='utf-8') as f:
            try:
                accounts_data = json.load(f)
                if not isinstance(accounts_data, list):
                    raise ValueError("Scheduled file content must be a JSON list.")
                if accounts_data and not all(isinstance(item, dict) for item in accounts_data):
                    first_bad = next((x for x in accounts_data if not isinstance(x, dict)), None)
                    raise ValueError(f"All items must be JSON objects. Found: {type(first_bad)}")
                logger.info(f"{log_prefix} Read {len(accounts_data)} accounts from {stored_file_path}")
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON format in stored file: {e.msg}")
            except Exception as read_err:
                raise IOError(f"Could not read stored file: {read_err}")
        
        total_count = len(accounts_data)
        if total_count == 0:
            logger.info(f"{log_prefix} Stored file is empty. No processing needed.")
            try:
                await bot.send_message(user_id, f"ℹ️ Auto-Processing: Stored file for `{escape(user_display_name)}` is empty.")
            except:
                pass
            return True
        
        # --- 2. Process Accounts via API ---
        start_time = time.time()
        successful_tokens = []
        working_accounts = []
        lost_accounts = []
        errors_summary = defaultdict(int)
        retry_count_stats = defaultdict(int)
        processed_count = 0
        
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        async with aiohttp.ClientSession() as session:
            tasks = [process_account(session, account, semaphore) for account in accounts_data]
            
            # Progress update every 10% or every 20 items
            update_frequency = max(10, min(20, total_count // 10))
            
            for i, future in enumerate(asyncio.as_completed(tasks)):
                if (i + 1) % update_frequency == 0 or (i + 1) == total_count:
                    progress_pct = ((i + 1) / total_count) * 100
                    try:
                        await bot.send_message(
                            user_id,
                            f"🔄 Auto-Processing: {i+1}/{total_count} ({progress_pct:.0f}%) tokens generated...",
                            disable_notification=True
                        )
                    except:
                        pass
                
                try:
                    token, region, working_acc, lost_acc, error_reason = await future
                    processed_count += 1
                    if token and working_acc:
                        successful_tokens.append({"token": token, "region": region})
                        working_accounts.append(working_acc)
                    elif lost_acc:
                        lost_accounts.append(lost_acc)
                        reason = lost_acc.get("error_reason", "Unknown")
                        errors_summary[reason.split(':')[0].strip()] += 1
                        if "Failed after" in reason:
                            retry_count_stats["failed_after_retries"] += 1
                    else:
                        lost_accounts.append({"account_info": "unknown", "error_reason": "Unexpected result"})
                        errors_summary["Processing error"] += 1
                except Exception as task_err:
                    processed_count += 1
                    logger.error(f"{log_prefix} Error retrieving result: {task_err}")
                    lost_accounts.append({"account_info": "unknown", "error_reason": f"Task Error: {task_err}"})
                    errors_summary["Task error"] += 1
        
        processing_time = time.time() - start_time
        logger.info(f"{log_prefix} API processing finished in {processing_time:.2f}s. Success: {len(successful_tokens)}, Failed: {len(lost_accounts)}")
        
        # --- 3. Prepare Token File for Upload ---
        if successful_tokens:
            os.makedirs(temp_results_dir, exist_ok=True)
            jwt_token_path_for_upload = os.path.join(temp_results_dir, 'jwt_token_7h_auto.json')
            tokens_only_list = [{"token": entry["token"]} for entry in successful_tokens if entry.get("token")]
            
            if tokens_only_list:
                if not save_json_data(jwt_token_path_for_upload, tokens_only_list):
                    jwt_token_path_for_upload = None
                    raise IOError("Failed to save temporary token file for upload.")
                logger.info(f"{log_prefix} Saved {len(tokens_only_list)} tokens to {jwt_token_path_for_upload}")
            else:
                jwt_token_path_for_upload = None
                logger.info(f"{log_prefix} No valid tokens found for upload.")
        
        # --- 4. Upload to GitHub if configured ---
        github_upload_success = False
        if jwt_token_path_for_upload and github_config and isinstance(github_config, dict):
            logger.info(f"{log_prefix} Attempting GitHub upload...")
            github_upload_success = await upload_to_github_background(
                bot, user_id, jwt_token_path_for_upload, github_config
            )
            logger.info(f"{log_prefix} GitHub upload finished. Success: {github_upload_success}")
        
        # --- 5. Send Summary to User ---
        summary_parts = [
            f"✅ Auto-Processing (7h cycle) completed for `{escape(user_display_name)}`",
            f"📊 {len(successful_tokens)} tokens generated, {len(lost_accounts)} failed",
            f"⏱️ Time taken: {format_time(processing_time)}"
        ]
        
        if jwt_token_path_for_upload and github_config:
            if github_upload_success:
                summary_parts.append("✅ GitHub upload: Successful")
            else:
                summary_parts.append("❌ GitHub upload: Failed")
        else:
            summary_parts.append("ℹ️ GitHub upload: Not configured")
            
        if retry_count_stats.get('failed_after_retries', 0) > 0:
            summary_parts.append(f"🔄 Failed after {MAX_RETRY_ATTEMPTS} retries: {retry_count_stats.get('failed_after_retries', 0)}")
        
        try:
            await bot.send_message(
                user_id,
                "\n".join(summary_parts),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"{log_prefix} Failed to send summary: {e}")
        
        success = True
        
    except Exception as e:
        logger.error(f"{log_prefix} FAILED: {e}", exc_info=True)
        try:
            await bot.send_message(
                user_id,
                f"❌ Auto-Processing failed for `{escape(user_display_name)}`:\n`{escape(str(e))}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        success = False
    
    finally:
        # Cleanup
        for path in cleanup_paths_auto:
            if os.path.exists(path):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                except OSError as e:
                    logger.warning(f"{log_prefix} Could not clean up {path}: {e}")
    
    return success

# --- Background Task for 7-Hour Auto-Processing ---

async def run_7h_auto_processor(application: Application) -> None:
    """
    Background task that runs every 7 hours to auto-process all schedules.
    """
    bot = application.bot
    logger.info(f"🚀 7-Hour Auto-Processor started. Interval: {AUTO_PROCESS_INTERVAL_HOURS} hours")
    
    # Initial delay to let bot fully start
    await asyncio.sleep(30)
    
    # Store last run time in bot_data for persistence
    application.bot_data['last_auto_run'] = None
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            last_run = application.bot_data.get('last_auto_run')
            
            # Check if 7 hours have passed since last run
            should_run = False
            if last_run is None:
                should_run = True  # First run
            else:
                time_diff = (now - last_run).total_seconds()
                if time_diff >= (AUTO_PROCESS_INTERVAL_HOURS * 3600):
                    should_run = True
            
            if should_run:
                logger.info(f"🔄 Running 7-hour auto-processing cycle at {now.isoformat()}")
                await auto_process_all_schedules(bot)
                application.bot_data['last_auto_run'] = now
                logger.info(f"✅ 7-hour auto-processing cycle completed at {datetime.now(timezone.utc).isoformat()}")
            
            # Check every 5 minutes (300 seconds) to see if it's time to run
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"❌ Error in 7-hour auto-processor: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retrying on error

# --- Admin Commands (ORIGINAL - UNCHANGED) ---

async def vip_management(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or not ADMIN_ID or user.id != ADMIN_ID:
        logger.warning(f"Unauthorized access attempt to /vip by user {user.id if user else 'Unknown'}")
        if message: await message.reply_text("You are not authorized to use this command.", reply_markup=main_reply_markup)
        return
    if message.chat.type != 'private':
         await message.reply_text("Admin commands must be used in a private chat with the bot.")
         return

    args = context.args
    command_usage = (
        "👑 *Admin VIP Management*\n\n"
        "*Usage:*\n"
        "`/vip add <user_id> <days>` - Add/extend VIP\n"
        "`/vip remove <user_id>` - Remove VIP\n"
        "`/vip list` - List VIPs\n\n"
        "*Example:* `/vip add 123456789 30`"
    )

    if not args:
        await message.reply_text(command_usage, parse_mode=ParseMode.MARKDOWN)
        return

    action = args[0].lower()
    vip_data = load_vip_data()

    if action == 'add':
        if len(args) != 3:
            return await message.reply_text(f"⚠️ Incorrect arguments for 'add'.\n\n{command_usage}", parse_mode=ParseMode.MARKDOWN)

        try:
            target_user_id_str, days_str = args[1], args[2]
            if not target_user_id_str.isdigit() or not days_str.isdigit():
                return await message.reply_text("⚠️ Invalid User ID or Days. Both must be numbers.")

            target_user_id = int(target_user_id_str)
            days_to_add = int(days_str)

            if days_to_add <= 0:
                 return await message.reply_text("⚠️ Number of days must be positive.")

            now_utc = datetime.now(timezone.utc)
            start_date_for_calc = now_utc

            user_vip_info = vip_data.get(target_user_id_str, {})
            if not isinstance(user_vip_info, dict): user_vip_info = {}

            is_extending = False
            if target_user_id_str in vip_data:
                try:
                    current_expiry_iso = user_vip_info.get('expiry')
                    if current_expiry_iso:
                        current_expiry_dt = datetime.fromisoformat(current_expiry_iso.replace('Z', '+00:00'))
                        if current_expiry_dt > now_utc:
                            start_date_for_calc = current_expiry_dt
                            is_extending = True
                            logger.info(f"Extending existing VIP for {target_user_id} from {current_expiry_dt.isoformat()}")
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning(f"Invalid expiry format for user {target_user_id_str}: {e}. Starting new period from now.")
                    user_vip_info = {}

            new_expiry_date = start_date_for_calc + timedelta(days=days_to_add)

            user_vip_info.update({
                'expiry': new_expiry_date.isoformat(),
                'added_by': user.id,
                'added_on': user_vip_info.get('added_on', now_utc.isoformat()),
                'last_update': now_utc.isoformat()
            })
            vip_data[target_user_id_str] = user_vip_info

            if save_vip_data(vip_data):
                expiry_formatted_display = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')
                action_word = "Extended" if is_extending else "Added"
                response_msg = f"✅ VIP {action_word} for User ID `{target_user_id}`.\nDuration Added: {days_to_add} days\nNew Expiry: `{expiry_formatted_display}`"
                logger.info(f"Admin {user.id} {action_word.lower()} VIP for {target_user_id} to {expiry_formatted_display}")
                await message.reply_text(response_msg, parse_mode=ParseMode.MARKDOWN)

                try:
                    await context.bot.send_message(
                        target_user_id,
                        f"🎉 Your VIP status has been {'updated' if is_extending else 'activated'}!\nExpires: `{expiry_formatted_display}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await message.reply_text(f"✅ User `{target_user_id}` notified.", parse_mode=ParseMode.MARKDOWN, disable_notification=True)
                except:
                    await message.reply_text(f"⚠️ Could not notify user `{target_user_id}`.", parse_mode=ParseMode.MARKDOWN, disable_notification=True)

            else:
                logger.error(f"Failed to save VIP data for user {target_user_id_str}")
                await message.reply_text("❌ Error: Could not save VIP data.")

        except ValueError:
            await message.reply_text("⚠️ Invalid number format for User ID or Days.")
        except Exception as e:
            logger.error(f"Error processing '/vip add': {e}", exc_info=True)
            await message.reply_text(f"An unexpected error occurred: {escape(str(e))}")

    elif action == 'remove':
        if len(args) != 2:
            return await message.reply_text(f"⚠️ Incorrect arguments for 'remove'.\n\n{command_usage}", parse_mode=ParseMode.MARKDOWN)

        target_user_id_str = args[1]
        if not target_user_id_str.isdigit():
            return await message.reply_text("⚠️ Invalid User ID format. Must be a number.")

        target_user_id = int(target_user_id_str)
        
        if target_user_id_str in vip_data:
            del vip_data[target_user_id_str]
            if save_vip_data(vip_data):
                await message.reply_text(f"✅ Removed VIP status for `{target_user_id_str}`.", parse_mode=ParseMode.MARKDOWN)
                logger.info(f"Admin {user.id} removed VIP for {target_user_id_str}.")
                try:
                    await context.bot.send_message(target_user_id, "ℹ️ Your VIP status has been removed by an admin.")
                except:
                    pass
            else:
                await message.reply_text(f"❌ Error removing VIP for `{target_user_id_str}`.", parse_mode=ParseMode.MARKDOWN)
        else:
            await message.reply_text(f"ℹ️ User `{target_user_id_str}` is not a VIP.", parse_mode=ParseMode.MARKDOWN)

    elif action == 'list':
        active_vips, inactive_vips = [], []
        now_utc = datetime.now(timezone.utc)

        for uid_str, data in vip_data.items():
            if not isinstance(data, dict): continue
            try:
                expiry_iso = data.get('expiry')
                if not expiry_iso: continue
                expiry_dt = datetime.fromisoformat(expiry_iso.replace('Z', '+00:00'))
                expiry_fmt = expiry_dt.strftime('%Y-%m-%d %H:%M UTC')
                
                if expiry_dt > now_utc:
                    rem_delta = expiry_dt - now_utc
                    days = rem_delta.days
                    hours, remainder = divmod(rem_delta.seconds, 3600)
                    rem_str = f"{days}d {hours}h" if days > 0 else f"{hours}h"
                    active_vips.append(f"✅ `{uid_str}` | Expires: {expiry_fmt} | Rem: `{rem_str}`")
                else:
                    inactive_vips.append(f"❌ `{uid_str}` | Expired: {expiry_fmt}")
            except:
                inactive_vips.append(f"⚠️ `{uid_str}` | Invalid date format")

        message_parts = [f"🌟 *VIP Users* ({len(active_vips)} Active)\n"]
        if active_vips:
            message_parts.append("*Active:*")
            message_parts.extend(active_vips)
        if inactive_vips:
            message_parts.append(f"\n*Expired/Invalid ({len(inactive_vips)}):*")
            message_parts.extend(inactive_vips)
        message_parts.append(f"\nTotal: {len(vip_data)}")

        await message.reply_text("\n".join(message_parts), parse_mode=ParseMode.MARKDOWN)

    else:
        await message.reply_text(f"⚠️ Invalid action '{escape(action)}'.\n\n{command_usage}", parse_mode=ParseMode.MARKDOWN)

async def broadcast(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message

    if not user or not message or not ADMIN_ID or user.id != ADMIN_ID:
        logger.warning(f"Unauthorized access attempt to /broadcast by user {user.id if user else 'Unknown'}")
        if message: await message.reply_text("You are not authorized to use this command.")
        return
    if message.chat.type != 'private':
         await message.reply_text("Broadcast must be initiated from a private chat with the bot.")
         return

    message_to_send = ""
    parse_mode_to_use = None

    replied_message = message.reply_to_message
    if replied_message:
        message_to_send = replied_message.text or replied_message.caption or ""
        if replied_message.text_html or replied_message.caption_html:
            parse_mode_to_use = ParseMode.HTML
            message_to_send = replied_message.text_html or replied_message.caption_html
        elif replied_message.text_markdown_v2 or replied_message.caption_markdown_v2:
             parse_mode_to_use = ParseMode.MARKDOWN_V2
             message_to_send = replied_message.text_markdown_v2 or replied_message.caption_markdown_v2
    else:
        if message.text:
            text_content = message.text
            command_pattern = rf"^\s*/broadcast(?:@{context.bot.username})?\s+"
            message_to_send = re.sub(command_pattern, '', text_content, count=1, flags=re.IGNORECASE | re.DOTALL).strip()
            if message.entities:
                 if any(e.type in ['bold', 'italic', 'code', 'pre', 'text_link'] for e in message.entities):
                     parse_mode_to_use = ParseMode.MARKDOWN_V2
                     message_to_send = message.text_markdown_v2

    if not message_to_send:
         return await message.reply_text(
             "Usage: `/broadcast <Your message here>`\n"
             "Or reply to the message you want to broadcast.",
             parse_mode=ParseMode.MARKDOWN
         )

    known_users = load_known_users()
    if not known_users:
         return await message.reply_text("ℹ️ No known users found.")

    total_users = len(known_users)
    logger.info(f"Admin {user.id} initiated broadcast to {total_users} users.")
    
    status_message_obj = await message.reply_text(f"📣 Broadcasting to {total_users} users...")
    
    success, fail = 0, 0
    start_time = time.time()
    
    for user_id_to_send in known_users:
        if user_id_to_send == ADMIN_ID:
            continue
        try:
            await context.bot.send_message(
                chat_id=user_id_to_send,
                text=message_to_send,
                parse_mode=parse_mode_to_use,
                disable_web_page_preview=True
            )
            success += 1
        except:
            fail += 1
        await asyncio.sleep(0.05)
    
    duration = format_time(time.time() - start_time)
    await status_message_obj.edit_text(
        f"🏁 Broadcast Complete!\n✅ Sent: {success}\n❌ Failed: {fail}\n⏱️ Duration: {duration}"
    )

# --- Message Forwarding (ORIGINAL - UNCHANGED) ---

async def forward_to_admin(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message

    if not ADMIN_ID or ADMIN_ID == 0: return
    if not user or not message: return
    if message.chat.type != 'private': return
    if user.id == ADMIN_ID: return

    if context.user_data.get('pending_schedule'):
        await message.reply_text("I'm waiting for you to send the JSON file for your schedule. Please send the file or use /cancel.", reply_markup=main_reply_markup)
        return
    if context.user_data.get('waiting_for_json'):
        await message.reply_text("I'm waiting for you to send the JSON file for manual processing. Please send the file or use /cancel.", reply_markup=main_reply_markup)
        return

    add_known_user(user.id)

    try:
        user_info = f"Forwarded from: ID `{user.id}`"
        if user.username: user_info += f" @{escape(user.username)}"
        if user.first_name: user_info += f" ({escape(user.first_name)})"

        await context.bot.send_message(ADMIN_ID, user_info, parse_mode=ParseMode.MARKDOWN)
        await context.bot.forward_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )
        logger.info(f"Forwarded message from user {user.id} to admin {ADMIN_ID}")
    except Exception as e:
        logger.error(f"Failed to forward message: {e}")

# --- Global Error Handler (ORIGINAL - UNCHANGED) ---

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    if isinstance(update, Update) and update.effective_chat:
        chat_id_for_notify = update.effective_chat.id
        cleaned = False
        if context.user_data.pop('pending_schedule', None):
            cleaned = True
        if context.user_data.pop('waiting_for_json', None):
             cleaned = True

        if cleaned:
             try:
                 await context.bot.send_message(
                     chat_id=chat_id_for_notify,
                     text="⚠️ An internal error occurred. Any pending action has been cancelled. Please try again.",
                     reply_markup=main_reply_markup
                 )
             except:
                 pass

    if not ADMIN_ID or ADMIN_ID == 0:
        return

    try:
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)
        
        error_message = (
            f"⚠️ <b>Bot Error</b>\n\n"
            f"<b>Error:</b>\n<pre>{escape(str(context.error))}</pre>\n"
            f"<b>Traceback:</b>\n<pre>{escape(tb_string[-3000:])}</pre>"
        )
        
        await context.bot.send_message(ADMIN_ID, error_message[:4096], parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.critical(f"Failed to send error notification to admin: {e}")

# --- Main Application Setup ---

async def main() -> None:
    global ADMIN_ID, TOKEN

    print("\n--- Initializing Bot ---")

    if not TOKEN or TOKEN == "YOUR_FALLBACK_BOT_TOKEN":
        print("\n" + "="*60)
        print(" FATAL ERROR: TELEGRAM_BOT_TOKEN is missing or invalid.")
        print(" -> Exiting.")
        print("="*60 + "\n")
        exit(1)
    elif len(TOKEN.split(':')) != 2:
        print("\n" + "="*60)
        print(f" FATAL ERROR: TELEGRAM_BOT_TOKEN format looks incorrect.")
        print(" -> Exiting.")
        print("="*60 + "\n")
        exit(1)

    try:
        admin_id_env = os.getenv('ADMIN_ID')
        if admin_id_env and admin_id_env.isdigit():
            ADMIN_ID = int(admin_id_env)
            if ADMIN_ID == 0: print(" WARNING: ADMIN_ID is set to 0. Admin features disabled.")
            else: logger.info(f"Admin User ID configured: {ADMIN_ID}")
        else:
            ADMIN_ID = 0
            print(" WARNING: ADMIN_ID not set. Admin features disabled.")
    except Exception as e:
         ADMIN_ID = 0
         print(f" WARNING: Error processing ADMIN_ID: {e}")

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        os.makedirs(SCHEDULED_FILES_DATA_DIR, exist_ok=True)
        logger.info(f"Data Directory: {DATA_DIR}")
        logger.info(f"Temp Directory: {TEMP_DIR}")
        logger.info(f"Scheduled Files Storage: {SCHEDULED_FILES_DATA_DIR}")
    except OSError as e:
        print(f"\nFATAL ERROR: Cannot create required directories: {e}\n-> Exiting.")
        exit(1)

    app_builder = Application.builder().token(TOKEN)\
        .concurrent_updates(True) \
        .read_timeout(30) \
        .write_timeout(30) \
        .connect_timeout(30) \
        .pool_timeout(60)

    application = app_builder.build()
    private_chat_filter = filters.ChatType.PRIVATE

    # Command Handlers
    application.add_handler(CommandHandler("start", start, filters=private_chat_filter))
    application.add_handler(CommandHandler("help", help_command, filters=private_chat_filter))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(COMMAND_BUTTONS_LAYOUT[2][1])}$") & private_chat_filter, help_command))

    application.add_handler(CommandHandler("vipstatus", vip_status_command, filters=private_chat_filter))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(COMMAND_BUTTONS_LAYOUT[0][1])}$") & private_chat_filter, vip_status_command))
    application.add_handler(CommandHandler("vipshop", vip_shop_command, filters=private_chat_filter))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(COMMAND_BUTTONS_LAYOUT[1][0])}$") & private_chat_filter, vip_shop_command))

    application.add_handler(CommandHandler("setgithub", set_github_direct, filters=private_chat_filter))
    application.add_handler(CommandHandler("mygithub", my_github_config, filters=private_chat_filter))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(COMMAND_BUTTONS_LAYOUT[1][1])}$") & private_chat_filter, my_github_config))

    application.add_handler(CommandHandler("setfile", set_scheduled_file_start, filters=private_chat_filter))
    application.add_handler(CommandHandler("removefile", remove_scheduled_file, filters=private_chat_filter))
    application.add_handler(CommandHandler("scheduledfiles", list_scheduled_files, filters=private_chat_filter))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(COMMAND_BUTTONS_LAYOUT[2][0])}$") & private_chat_filter, list_scheduled_files))

    application.add_handler(MessageHandler(filters.Text(COMMAND_BUTTONS_LAYOUT[0][0]) & private_chat_filter, handle_document))
    application.add_handler(MessageHandler(
        (filters.Document.MimeType('application/json') | filters.Document.FileExtension('json')) & private_chat_filter,
        handle_document
    ))

    application.add_handler(CommandHandler("cancel", cancel, filters=private_chat_filter))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(COMMAND_BUTTONS_LAYOUT[3][0])}$") & private_chat_filter, cancel))

    # Admin Commands
    if ADMIN_ID and ADMIN_ID != 0:
        admin_filter = filters.User(user_id=ADMIN_ID) & private_chat_filter
        application.add_handler(CommandHandler("vip", vip_management, filters=admin_filter))
        application.add_handler(CommandHandler("broadcast", broadcast, filters=admin_filter))
        logger.info(f"Admin commands enabled for ADMIN_ID: {ADMIN_ID}.")

    # Message Forwarding
    if ADMIN_ID and ADMIN_ID != 0:
        known_button_texts_set = {btn for row in COMMAND_BUTTONS_LAYOUT for btn in row}
        forwarding_filters = (
            private_chat_filter &
            ~filters.User(user_id=ADMIN_ID) &
            ~filters.COMMAND &
            ~filters.Text(known_button_texts_set) &
            ~(filters.Document.MimeType('application/json') | filters.Document.FileExtension('json')) &
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) &
            ~filters.UpdateType.EDITED_MESSAGE
        )
        application.add_handler(MessageHandler(forwarding_filters, forward_to_admin))
        logger.info("Message forwarding to admin enabled.")

    application.add_error_handler(error_handler)

    logger.info("🤖 Bot is initializing...")
    print("\n" + "="*60)
    print(" 🚀 JWT Token Bot with Auto-Processing is starting...")
    print(f" ⚡ {MAX_CONCURRENT_REQUESTS} concurrent requests")
    print(f" 🔄 {MAX_RETRY_ATTEMPTS} retry attempts per account")
    print(f" ⏱️ {RETRY_TIMEOUT}s timeout per attempt")
    print(f" ⏰ Auto-processing every {AUTO_PROCESS_INTERVAL_HOURS} hours")
    print("="*60 + "\n")

    try:
        await application.initialize()
        bot_info = await application.bot.get_me()
        print(f" ✔️ Bot Username: @{bot_info.username}")

        # Start 7-hour auto-processor
        auto_task = asyncio.create_task(run_7h_auto_processor(application))
        logger.info("7-Hour Auto-Processor task created.")

        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        print("\n Bot is running. Press Ctrl+C to stop.\n")
        print("="*60 + "\n")

        await auto_task

    except (TelegramError, ConnectionError) as e:
         print(f"\n FATAL ERROR: Could not connect to Telegram: {e}")
         exit(1)
    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
    except Exception as e:
        print(f"\n FATAL ERROR: {e}")
        logger.critical(f"Unhandled exception: {e}", exc_info=True)
        exit(1)
    finally:
         if 'application' in locals() and application.running:
              logger.info("Shutting down...")
              await application.stop()
              await application.shutdown()
         if 'auto_task' in locals() and not auto_task.done():
              auto_task.cancel()
              try: await auto_task
              except: pass
         logger.info("Shutdown complete.")

if __name__ == '__main__':
    try:
        if not TOKEN or TOKEN == "YOUR_FALLBACK_BOT_TOKEN":
             print("FATAL: TELEGRAM_BOT_TOKEN is not set.")
        else:
             asyncio.run(main())
    except KeyboardInterrupt:
        print("\n-- Bot stopped by user --")
    except Exception as e:
        print(f"\n💥 Critical error: {e}")
