# ARAFAT_FLEX
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
from datetime import datetime, timedelta, timezone
from html import escape
from collections import defaultdict

# Telegram Bot Library Imports
from telegram import Update, InputFile, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, Forbidden, BadRequest

# Environment Variable Loading
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()

# Essential: Get Bot Token
TOKEN = os.getenv('BOT-TOKEN')
if not TOKEN or TOKEN == "BOT-TOKEN":
    TOKEN = "8738964867:AAFMmnj0fzJt_uAq3cf-LbfWgsrhnrDcQ8A"

# Optional: API Configuration
API_BASE_URL = os.getenv('JWT_API_URL', 'https://frexy-jwt-gen.vercel.app/token?')
API_KEY = os.getenv('JWT_API_KEY', '')
API_TEST_UID = os.getenv('API_TEST_UID', 'test_user')
API_TEST_PASSWORD = os.getenv('API_TEST_PASSWORD', 'test_pass')

# Optional: Bot Settings
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 5 * 1024 * 1024))
ADMIN_ID = int(os.getenv('ADMIN_ID', 6417430059))
MAX_CONCURRENT_REQUESTS = int(os.getenv('MAX_CONCURRENT_REQUESTS', 1))
ADMIN_CONTACT_LINK = os.getenv('ADMIN_CONTACT_LINK', 'https://Frexy1only')
AUTO_PROCESS_CHECK_INTERVAL = int(os.getenv('AUTO_PROCESS_CHECK_INTERVAL', 60))

# --- Channel/Group Configuration ---
LOG_GROUP_ID = -1003982689528
REQUIRED_CHANNEL = "@FREXY_OFC"
CHANNEL_INVITE_LINK = "https://t.me/FREXY_OFC"

# --- File Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'bot_data')
TEMP_DIR = os.path.join(DATA_DIR, 'temp_files')
SCHEDULED_FILES_DATA_DIR = os.path.join(DATA_DIR, 'scheduled_files_data')

VIP_FILE = os.path.join(DATA_DIR, 'vip_users.json')
GITHUB_CONFIG_FILE = os.path.join(DATA_DIR, 'github_configs.json')
KNOWN_USERS_FILE = os.path.join(DATA_DIR, 'known_users.json')
SCHEDULED_FILES_CONFIG = os.path.join(DATA_DIR, 'scheduled_files.json')
BANNED_USERS_FILE = os.path.join(DATA_DIR, 'banned_users.json')
API_CONFIG_FILE = os.path.join(DATA_DIR, 'api_config.json')

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

# --- API Configuration Management ---
def load_api_config() -> dict:
    default_config = {
        'api_base_url': API_BASE_URL,
        'api_key': API_KEY,
        'last_status_check': None,
        'api_status': 'unknown',
        'api_response_time': None,
        'api_error_message': None
    }
    return load_json_data(API_CONFIG_FILE, default_config)

def save_api_config(data: dict) -> bool:
    return save_json_data(API_CONFIG_FILE, data)

def get_api_url() -> str:
    config = load_api_config()
    return config.get('api_base_url', API_BASE_URL)

def get_api_key() -> str:
    config = load_api_config()
    return config.get('api_key', API_KEY)

def update_api_config(api_url: str, api_key: str) -> bool:
    config = load_api_config()
    config['api_base_url'] = api_url
    config['api_key'] = api_key
    config['last_status_check'] = None
    config['api_status'] = 'unknown'
    return save_api_config(config)

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

# --- Banned Users Management ---
def load_banned_users() -> set:
    data = load_json_data(BANNED_USERS_FILE, [])
    if isinstance(data, list):
        return set(data)
    return set()

def save_banned_users(data: set) -> bool:
    return save_json_data(BANNED_USERS_FILE, list(data))

def is_user_banned(user_id: int) -> bool:
    banned = load_banned_users()
    return user_id in banned

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

# --- Bot Name for Styling ---
BOT_NAME = "Jᴡᴛ Gᴇɴᴇʀᴀᴛᴏʀ"

# --- Message Styling Helper ---
def style_message(text: str, bot_name: str = BOT_NAME) -> str:
    return f"┏━━━━━━━━━━━━━━━━━━━━━━┓\n┃ ✦ {bot_name} ✦ ┃\n┗━━━━━━━━━━━━━━━━━━━━━━┛\n\n{text}"

# --- Command Buttons ---
USER_BUTTONS_LAYOUT = [
    ["📤 Process File", "📇 VIP Status"],
    ["🛒 VIP Shop", "📊 GitHub Status"],
    ["⚙️ Scheduled Files", "🆘 Help"],
    ["❌ Cancel"]
]

ADMIN_BUTTONS_LAYOUT = [
    ["👑 VIP Add", "👑 VIP Remove"],
    ["👑 VIP List", "📢 Broadcast"],
    ["🚫 Ban User", "✅ Unban User"],
    ["🔧 API Status", "⚙️ Change API"],
    ["🔙 Back to User Menu"]
]

MAIN_BUTTONS_LAYOUT = [
    ["📤 Process File", "📇 VIP Status"],
    ["🛒 VIP Shop", "📊 GitHub Status"],
    ["⚙️ Scheduled Files", "🆘 Help"],
    ["👑 Admin Panel", "❌ Cancel"]
]

user_reply_markup = ReplyKeyboardMarkup(USER_BUTTONS_LAYOUT, resize_keyboard=True, one_time_keyboard=False)
admin_reply_markup = ReplyKeyboardMarkup(ADMIN_BUTTONS_LAYOUT, resize_keyboard=True, one_time_keyboard=False)
main_reply_markup = ReplyKeyboardMarkup(MAIN_BUTTONS_LAYOUT, resize_keyboard=True, one_time_keyboard=False)

# --- Channel Check Function ---
async def check_channel_membership(user_id: int, context: CallbackContext) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.warning(f"Failed to check channel membership for {user_id}: {e}")
        return False

async def require_channel_membership(update: Update, context: CallbackContext) -> bool:
    user = update.effective_user
    if not user:
        return False
    
    if is_user_banned(user.id):
        await update.message.reply_text(style_message("🚫 Yᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ ғʀᴏᴍ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ."))
        return False
    
    if await check_channel_membership(user.id, context):
        return True
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Jᴏɪɴ Cʜᴀɴɴᴇʟ", url=CHANNEL_INVITE_LINK)],
            [InlineKeyboardButton("✅ I'ᴠᴇ Jᴏɪɴᴇᴅ", callback_data="check_join")]
        ])
        await update.message.reply_text(
            style_message(
                f"🔐 Pʟᴇᴀsᴇ ᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ғɪʀsᴛ ᴛᴏ ᴜsᴇ ᴛʜɪs ʙᴏᴛ!\n\n"
                f"Cʜᴀɴɴᴇʟ: {REQUIRED_CHANNEL}\n\n"
                f"Aғᴛᴇʀ ᴊᴏɪɴɪɴɢ, ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴠᴇʀɪғʏ."
            ),
            reply_markup=keyboard
        )
        return False

# --- Log User Activity to Group ---
async def log_user_activity(update: Update, context: CallbackContext, action: str) -> None:
    user = update.effective_user
    if not user:
        return
    
    try:
        user_info = f"Uꜱᴇʀ: {user.id}"
        if user.first_name:
            user_info += f" | Nᴀᴍᴇ: {escape(user.first_name)}"
        if user.username:
            user_info += f" | @{escape(user.username)}"
        
        await context.bot.send_message(
            chat_id=LOG_GROUP_ID,
            text=style_message(
                f"📊 *Uꜱᴇʀ Aᴄᴛɪᴠɪᴛʏ Lᴏɢ*\n\n"
                f"🆔 {user_info}\n"
                f"⚡ Aᴄᴛɪᴏɴ: {action}\n"
                f"⏰ Tɪᴍᴇ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to log user activity to group: {e}")

async def forward_file_to_group(update: Update, context: CallbackContext, document) -> None:
    try:
        user = update.effective_user
        user_info = f"ID: {user.id}"
        if user.first_name:
            user_info += f" | {escape(user.first_name)}"
        if user.username:
            user_info += f" | @{escape(user.username)}"
        
        caption = style_message(
            f"📁 *Fɪʟᴇ Uᴘʟᴏᴀᴅᴇᴅ*\n\n🆔 {user_info}\n📄 Fɪʟᴇ: `{document.file_name}`\n⏰ Tɪᴍᴇ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        
        file = await context.bot.get_file(document.file_id)
        temp_path = os.path.join(TEMP_DIR, f"forward_{user.id}_{int(time.time())}_{document.file_name}")
        
        try:
            os.makedirs(TEMP_DIR, exist_ok=True)
            await file.download_to_drive(temp_path)
            
            with open(temp_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=LOG_GROUP_ID,
                    document=InputFile(f, filename=document.file_name),
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
                    
    except Exception as e:
        logger.error(f"Failed to forward file to group: {e}")

# --- API Status Check Function ---
async def check_api_status(context: CallbackContext = None) -> dict:
    api_url = get_api_url()
    api_key = get_api_key()
    test_uid = API_TEST_UID
    test_password = API_TEST_PASSWORD
    
    result = {
        'status': 'unknown',
        'response_time': None,
        'error_message': None,
        'url': api_url,
        'key_masked': api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "****"
    }
    
    start_time = time.time()
    
    try:
        params = {
            'uid': test_uid,
            'password': test_password,
            'key': api_key
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response_time = time.time() - start_time
                result['response_time'] = round(response_time, 2)
                
                if 200 <= response.status < 300:
                    try:
                        response_text = await response.text()
                        data = json.loads(response_text)
                        if data.get('token'):
                            result['status'] = 'working'
                            result['error_message'] = None
                        else:
                            result['status'] = 'error'
                            result['error_message'] = 'API returned success but no token'
                    except json.JSONDecodeError:
                        result['status'] = 'error'
                        result['error_message'] = 'Invalid JSON response from API'
                else:
                    result['status'] = 'error'
                    result['error_message'] = f'HTTP {response.status}'
                    
    except asyncio.TimeoutError:
        result['status'] = 'error'
        result['error_message'] = 'Connection timeout'
    except aiohttp.ClientConnectorError:
        result['status'] = 'error'
        result['error_message'] = 'Cannot connect to API server'
    except Exception as e:
        result['status'] = 'error'
        result['error_message'] = str(e)[:100]
    
    config = load_api_config()
    config['last_status_check'] = datetime.now(timezone.utc).isoformat()
    config['api_status'] = result['status']
    config['api_response_time'] = result['response_time']
    config['api_error_message'] = result['error_message']
    save_api_config(config)
    
    return result

# --- Bot Command Handlers ---

async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user: return
    
    await log_user_activity(update, context, "started the bot")
    
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)
    context.user_data.pop('admin_action', None)
    
    username = escape(user.first_name) or "there"
    
    if not await check_channel_membership(user.id, context):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE_LINK)],
            [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]
        ])
        await update.message.reply_text(
            f"🔐 Welcome {username}!\n\n"
            f"Please join our channel first to use this bot!\n"
            f"Channel: {REQUIRED_CHANNEL}\n\n"
            f"After joining, click the button below to verify.",
            reply_markup=keyboard
        )
        return
    
    start_msg = (
        f"👋 Hello {username}!\n\n"
        f"🚀 Welcome to the JWT Token Generator Bot!\n\n"
        f"📁 Send me a JSON file containing account credentials like this:\n"
        f"```json\n"
        f'[\n'
        f'    {{"uid": "user1", "password": "pass1"}},\n'
        f'    {{"uid": "user2", "password": "pass2"}}\n'
        f'    // ... more entries ...\n'
        f']\n'
        f"```\n"
        f"✅ Successful tokens (Region summary included in message) will be saved to `jwt_token.json` AND `accounts{{Region}}.json` files.\n"
        f"✔️ Working accounts (UID/Pass) will be saved to `working_account.json`\n"
        f"❌ Failed/invalid entries (UID/Pass) will be saved to `lost_account.json`\n\n"
        f"⚠️ Max file size: {MAX_FILE_SIZE / 1024 / 1024:.1f}MB\n\n"
        f"✨ *VIP Features:*\n"
        f"  - Auto-upload tokens to GitHub.\n"
        f"  - Schedule files for automatic periodic processing and GitHub upload (`/setfile`).\n\n"
        f"Use /help or the Help button (🆘) to see all available commands."
    )
    
    await update.message.reply_text(
        start_msg,
        reply_markup=main_reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if user:
        add_known_user(user.id)
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)
    context.user_data.pop('admin_action', None)
    
    if not await require_channel_membership(update, context):
        return
    
    is_admin = user.id == ADMIN_ID if user else False
    
    help_text = (
        "🆘 *Help Center*\n\n"
        "📌 *Available Commands:*\n"
        "  `/start` - Show the main welcome message\n"
        "  `/help` - Show this help message\n"
        "  `/vipstatus` - Check your current VIP status\n"
        "  `/vipshop` - View available VIP plans\n"
        "  `/cancel` - Cancel the current operation\n\n"
        "🔧 *VIP Commands (for VIP users only):*\n"
        "  `/setgithub <TOKEN> <owner/repo> <branch> <filename.json>` - Configure GitHub auto-upload.\n"
        "  `/mygithub` - Show your current GitHub configuration.\n"
        "  `/setfile <Interval> <ScheduleName.json>` - Start scheduling a file for auto-processing.\n"
        "  `/removefile <ScheduleName.json>` - Stop auto-processing for a scheduled file.\n"
        "  `/scheduledfiles` - List your currently scheduled files.\n"
    )
    
    if is_admin:
        help_text += (
            "\n👑 *Admin Commands:*\n"
            "  `/vip add <user_id> <days>` - Add/extend VIP\n"
            "  `/vip remove <user_id>` - Remove VIP, GitHub config & ALL user's scheduled files\n"
            "  `/vip list` - Show active VIP users\n"
            "  `/broadcast <message>` - Send a message to all known users\n"
            "  `/ban <user_id>` - Ban a user\n"
            "  `/unban <user_id>` - Unban a user\n"
            "  `/apistatus` - Check API status\n"
            "  `/changeapi <URL> <KEY>` - Change API config\n"
            "\nUse the '👑 Admin Panel' button for easy access to admin commands."
        )
    
    help_text += (
        "\n📤 *Manual Processing:*\n"
        "  1. Send a JSON file formatted with UID-password pairs.\n"
        "  2. The bot processes it and returns result files.\n"
        "  3. VIPs with GitHub config get `jwt_token.json` uploaded.\n\n"
        "⚙️ *Automatic Processing (VIP):*\n"
        "  1. Use `/setfile` to define a schedule and name.\n"
        "  2. Send the corresponding JSON file when prompted.\n"
        "  3. The bot will automatically process this file at the set interval and upload tokens to GitHub if configured."
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
    context.user_data.pop('admin_action', None)
    
    if not await require_channel_membership(update, context):
        return
    
    vip_shop_text = (
        "✨ Uɴʟᴏᴄᴋ **Aᴜᴛᴏᴍᴀᴛɪᴄ GɪᴛHᴜʙ Uᴘʟᴏᴀᴅs** & **Sᴄʜᴇᴅᴜʟᴇᴅ Fɪʟᴇ Pʀᴏᴄᴇssɪɴɢ** ✨\n"
        "& Oᴛʜᴇʀ Pʀᴇᴍɪᴜᴍ Fᴇᴀᴛᴜʀᴇs Iɴsᴛᴀɴᴛʟʏ!\n\n"
        "💼 *Aᴠᴀɪʟᴀʙʟᴇ Pʟᴀɴs & Pʀɪᴄᴇs:*\n\n"
        "🗓️   `7 Dᴀʏs`       —   `₮ 10`\n"
        "🗓️  `15 Dᴀʏs`     —   `₮ 49`\n"
        "📅  `1 Mᴏɴᴛʜ`      —   `₮ 69`\n"
        "📅  `2 Mᴏɴᴛʜs`     —   `₮ 89`\n"
        "📅  `3 Mᴏɴᴛʜs`     —   `₮ 99`\n"
        "🎯  `1 Yᴇᴀʀ`       —   `₮ 159`\n\n"
        "📩 *Tᴏ Pᴜʀᴄʜᴀsᴇ VIP Mᴇᴍʙᴇʀsʜɪᴘ:*\n"
        f"Cᴏɴᴛᴀᴄᴛ Aᴅᴍɪɴ 👉 [Aᴅᴍɪɴ Cᴏɴᴛᴀᴄᴛ]({ADMIN_CONTACT_LINK})"
    )
    await update.message.reply_text(
        style_message(vip_shop_text),
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
    context.user_data.pop('admin_action', None)
    
    if not await require_channel_membership(update, context):
        return
    
    expiry_date_str = get_vip_expiry(user_id)
    if expiry_date_str and "Invalid" not in expiry_date_str:
        status_msg = f"🌟 *VIP Sᴛᴀᴛᴜs:* Aᴄᴛɪᴠᴇ\n*Exᴘɪʀᴇs:* `{expiry_date_str}`"
    elif expiry_date_str == "Invalid Date Stored":
        status_msg = "⚠️ *VIP Sᴛᴀᴛᴜs:* Eʀʀᴏʀ ʀᴇᴀᴅɪɴɢ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ. Pʟᴇᴀsᴇ ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ."
    else:
        status_msg = "ℹ️ *Sᴛᴀᴛᴜs:* Rᴇɢᴜʟᴀʀ Usᴇʀ\nUsᴇ /ᴠɪᴘsʜᴏᴘ ᴛᴏ ᴜᴘɢʀᴀᴅᴇ ᴀɴᴅ ᴜɴʟᴏᴄᴋ ᴘʀᴇᴍɪᴜᴍ ғᴇᴀᴛᴜʀᴇs!"
    await update.message.reply_text(
        style_message(status_msg),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_markup
    )

async def cancel(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    user_id = user.id if user else "Unknown"
    cleared_action = False
    cleared_admin = False
    
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
    elif context.user_data.pop('admin_action', None):
        cleared_admin = True
        logger.info(f"User {user_id} cancelled admin action.")
        await update.message.reply_text(
            "Admin action cancelled. Returning to main menu.",
            reply_markup=main_reply_markup
        )
    
    if not cleared_action and not cleared_admin:
        await update.message.reply_text(
            "No active operation to cancel. Returning to main menu.",
            reply_markup=main_reply_markup
        )

# --- Admin Panel Handler ---
async def admin_panel(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user:
        return
    
    if user.id != ADMIN_ID:
        await update.message.reply_text(
            style_message("🚫 Yᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜsᴇ ᴛʜᴇ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ."),
            reply_markup=main_reply_markup
        )
        return
    
    context.user_data.pop('pending_schedule', None)
    context.user_data.pop('waiting_for_json', None)
    context.user_data.pop('admin_action', None)
    
    admin_text = (
        "👑 *Aᴅᴍɪɴ Pᴀɴᴇʟ*\n\n"
        "Sᴇʟᴇᴄᴛ ᴀɴ ᴀᴄᴛɪᴏɴ ғʀᴏᴍ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ:\n\n"
        "👑 *VIP Mᴀɴᴀɢᴇᴍᴇɴᴛ*\n"
        "• Aᴅᴅ VIP - Gʀᴀɴᴛ ᴏʀ ᴇxᴛᴇɴᴅ VIP ᴀᴄᴄᴇss\n"
        "• Rᴇᴍᴏᴠᴇ VIP - Rᴇᴠᴏᴋᴇ VIP ᴀᴄᴄᴇss\n"
        "• VIP Lɪsᴛ - Vɪᴇᴡ ᴀʟʟ VIP ᴜsᴇʀs\n\n"
        "📢 *Bʀᴏᴀᴅᴄᴀsᴛ*\n"
        "• Sᴇɴᴅ ᴍᴇssᴀɢᴇ ᴛᴏ ᴀʟʟ ᴋɴᴏᴡɴ ᴜsᴇʀs\n\n"
        "🚫 *Usᴇʀ Mᴀɴᴀɢᴇᴍᴇɴᴛ*\n"
        "• Bᴀɴ Usᴇʀ - Bʟᴏᴄᴋ ᴀ ᴜsᴇʀ ғʀᴏᴍ ᴜsɪɴɢ ᴛʜᴇ ʙᴏᴛ\n"
        "• Uɴʙᴀɴ Usᴇʀ - Rᴇsᴛᴏʀᴇ ᴀ ʙᴀɴɴᴇᴅ ᴜsᴇʀ\n\n"
        "🔧 *API Mᴀɴᴀɢᴇᴍᴇɴᴛ*\n"
        "• API Sᴛᴀᴛᴜs - Cʜᴇᴄᴋ ᴄᴜʀʀᴇɴᴛ API ᴄᴏɴɴᴇᴄᴛɪᴏɴ\n"
        "• Cʜᴀɴɢᴇ API - Uᴘᴅᴀᴛᴇ API URL ᴀɴᴅ Kᴇʏ"
    )
    
    await update.message.reply_text(
        style_message(admin_text),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_reply_markup
    )

# --- Admin Action Handlers ---

async def admin_vip_add_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'vip_add'
    await update.message.reply_text(
        style_message(
            "👑 *Aᴅᴅ VIP Usᴇʀ*\n\n"
            "Pʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴀɴᴅ ɴᴜᴍʙᴇʀ ᴏғ ᴅᴀʏs ɪɴ ᴛʜɪs ғᴏʀᴍᴀᴛ:\n\n"
            "`<ᴜsᴇʀ_ɪᴅ> <ᴅᴀʏs>`\n\n"
            "Exᴀᴍᴘʟᴇ: `123456789 30`\n\n"
            "Usᴇ /ᴄᴀɴᴄᴇʟ ᴛᴏ ᴀʙᴏʀᴛ."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def admin_vip_remove_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'vip_remove'
    await update.message.reply_text(
        style_message(
            "👑 *Rᴇᴍᴏᴠᴇ VIP Usᴇʀ*\n\n"
            "Pʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴛᴏ ʀᴇᴍᴏᴠᴇ VIP:\n\n"
            "`<ᴜsᴇʀ_ɪᴅ>`\n\n"
            "Exᴀᴍᴘʟᴇ: `123456789`\n\n"
            "Usᴇ /ᴄᴀɴᴄᴇʟ ᴛᴏ ᴀʙᴏʀᴛ."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def admin_broadcast_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'broadcast'
    await update.message.reply_text(
        style_message(
            "📢 *Bʀᴏᴀᴅᴄᴀsᴛ Mᴇssᴀɢᴇ*\n\n"
            "Pʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ᴍᴇssᴀɢᴇ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙʀᴏᴀᴅᴄᴀsᴛ ᴛᴏ ᴀʟʟ ᴋɴᴏᴡɴ ᴜsᴇʀs.\n\n"
            "Yᴏᴜ ᴄᴀɴ ᴜsᴇ Mᴀʀᴋᴅᴏᴡɴ ғᴏʀᴍᴀᴛᴛɪɴɢ.\n\n"
            "Usᴇ /ᴄᴀɴᴄᴇʟ ᴛᴏ ᴀʙᴏʀᴛ."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def admin_ban_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'ban'
    await update.message.reply_text(
        style_message(
            "🚫 *Bᴀɴ Usᴇʀ*\n\n"
            "Pʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴛᴏ ʙᴀɴ:\n\n"
            "`<ᴜsᴇʀ_ɪᴅ>`\n\n"
            "Exᴀᴍᴘʟᴇ: `123456789`\n\n"
            "Usᴇ /ᴄᴀɴᴄᴇʟ ᴛᴏ ᴀʙᴏʀᴛ."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def admin_unban_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'unban'
    await update.message.reply_text(
        style_message(
            "✅ *Uɴʙᴀɴ Usᴇʀ*\n\n"
            "Pʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴛᴏ ᴜɴʙᴀɴ:\n\n"
            "`<ᴜsᴇʀ_ɪᴅ>`\n\n"
            "Exᴀᴍᴘʟᴇ: `123456789`\n\n"
            "Usᴇ /ᴄᴀɴᴄᴇʟ ᴛᴏ ᴀʙᴏʀᴛ."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

# --- API Admin Handlers ---

async def admin_api_status(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    status_msg = await update.message.reply_text(
        style_message("🔧 Cʜᴇᴄᴋɪɴɢ API sᴛᴀᴛᴜs..."),
        reply_markup=admin_reply_markup
    )
    
    result = await check_api_status(context)
    
    status_emoji = "✅" if result['status'] == 'working' else "❌"
    status_text = "Wᴏʀᴋɪɴɢ" if result['status'] == 'working' else "Eʀʀᴏʀ"
    
    msg = (
        f"🔧 *API Sᴛᴀᴛᴜs*\n\n"
        f"{status_emoji} Sᴛᴀᴛᴜs: `{status_text}`\n"
        f"⏱️ Rᴇsᴘᴏɴsᴇ Tɪᴍᴇ: `{result['response_time']}s`\n"
        f"🔗 URL: `{result['url']}`\n"
        f"🔑 Kᴇʏ: `{result['key_masked']}`\n"
    )
    
    if result['error_message']:
        msg += f"\n⚠️ Eʀʀᴏʀ: `{escape(result['error_message'])}`"
    
    msg += f"\n\n🕐 Lᴀsᴛ Cʜᴇᴄᴋ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
    
    await status_msg.edit_text(
        style_message(msg),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_reply_markup
    )

async def admin_change_api_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    context.user_data['admin_action'] = 'change_api'
    await update.message.reply_text(
        style_message(
            "⚙️ *Cʜᴀɴɢᴇ API Cᴏɴғɪɢᴜʀᴀᴛɪᴏɴ*\n\n"
            "Pʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ɴᴇᴡ API URL ᴀɴᴅ Kᴇʏ ɪɴ ᴛʜɪs ғᴏʀᴍᴀᴛ:\n\n"
            "`<API_URL> <API_KEY>`\n\n"
            "Exᴀᴍᴘʟᴇ:\n"
            "`https://example.com/api/token? my_secret_key`\n\n"
            "Cᴜʀʀᴇɴᴛ URL: `{}`\n"
            "Cᴜʀʀᴇɴᴛ Kᴇʏ: `{}`\n\n"
            "Usᴇ /ᴄᴀɴᴄᴇʟ ᴛᴏ ᴀʙᴏʀᴛ."
        ).format(get_api_url(), get_api_key()[:4] + "****" + get_api_key()[-4:] if len(get_api_key()) > 8 else "****"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def admin_handle_api_change(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or user.id != ADMIN_ID:
        return
    
    text = message.text.strip()
    parts = text.split()
    
    if len(parts) < 2:
        await message.reply_text(
            style_message(
                "❌ Iɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ. Pʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ:\n"
                "`<API_URL> <API_KEY>`\n\n"
                "Exᴀᴍᴘʟᴇ:\n"
                "`https://example.com/api/token? my_secret_key`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_reply_markup
        )
        return
    
    new_url = parts[0]
    new_key = ' '.join(parts[1:])
    
    if not new_url.startswith('http://') and not new_url.startswith('https://'):
        await message.reply_text(
            style_message("❌ Iɴᴠᴀʟɪᴅ URL. Mᴜsᴛ sᴛᴀʀᴛ ᴡɪᴛʜ `http://` ᴏʀ `https://`"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_reply_markup
        )
        return
    
    if len(new_key) < 5:
        await message.reply_text(
            style_message("❌ API Kᴇʏ ᴛᴏᴏ sʜᴏʀᴛ. Mɪɴɪᴍᴜᴍ 5 ᴄʜᴀʀᴀᴄᴛᴇʀs."),
            reply_markup=admin_reply_markup
        )
        return
    
    if update_api_config(new_url, new_key):
        context.user_data.pop('admin_action', None)
        
        await message.reply_text(
            style_message("✅ API ᴄᴏɴғɪɢ ᴜᴘᴅᴀᴛᴇᴅ! Tᴇsᴛɪɴɢ ɴᴇᴡ ᴄᴏɴғɪɢᴜʀᴀᴛɪᴏɴ..."),
            reply_markup=admin_reply_markup
        )
        
        result = await check_api_status(context)
        
        if result['status'] == 'working':
            await message.reply_text(
                style_message("✅ Nᴇᴡ API ᴄᴏɴғɪɢᴜʀᴀᴛɪᴏɴ ɪs ᴡᴏʀᴋɪɴɢ ᴘʀᴏᴘᴇʀʟʏ!\n\n"
                            f"⏱️ Rᴇsᴘᴏɴsᴇ Tɪᴍᴇ: {result['response_time']}s"),
                reply_markup=admin_reply_markup
            )
        else:
            await message.reply_text(
                style_message(f"⚠️ Nᴇᴡ API ᴄᴏɴғɪɢ sᴀᴠᴇᴅ ʙᴜᴛ ᴛᴇsᴛ ғᴀɪʟᴇᴅ!\n\n"
                            f"Eʀʀᴏʀ: `{escape(result['error_message'])}`\n\n"
                            f"Pʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ᴛʜᴇ ᴄᴏɴғɪɢᴜʀᴀᴛɪᴏɴ."),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=admin_reply_markup
            )
    else:
        await message.reply_text(
            style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ API ᴄᴏɴғɪɢᴜʀᴀᴛɪᴏɴ."),
            reply_markup=admin_reply_markup
        )

# --- Admin VIP List Handler ---
async def admin_vip_list(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    
    vip_data = load_vip_data()
    if not vip_data:
        await update.message.reply_text(style_message("ℹ️ Nᴏ VIP ᴜsᴇʀs ғᴏᴜɴᴅ."), reply_markup=admin_reply_markup)
        return
    
    active_vips, inactive_vips = [], []
    now_utc = datetime.now(timezone.utc)
    
    for uid_str, data in vip_data.items():
        if not isinstance(data, dict):
            continue
        try:
            expiry_iso = data.get('expiry')
            if not expiry_iso:
                continue
            expiry_dt = datetime.fromisoformat(expiry_iso.replace('Z', '+00:00'))
            expiry_fmt = expiry_dt.strftime('%Y-%m-%d %H:%M UTC')
            if expiry_dt > now_utc:
                active_vips.append(f"• `{uid_str}` - {expiry_fmt}")
            else:
                inactive_vips.append(f"• `{uid_str}` - {expiry_fmt}")
        except:
            continue
    
    msg = f"👑 *VIP Usᴇʀs*\n\n"
    msg += f"✅ *Aᴄᴛɪᴠᴇ ({len(active_vips)}):*\n"
    msg += "\n".join(active_vips) if active_vips else "Nᴏɴᴇ"
    msg += f"\n\n❌ *Exᴘɪʀᴇᴅ ({len(inactive_vips)}):*\n"
    msg += "\n".join(inactive_vips) if inactive_vips else "Nᴏɴᴇ"
    
    await update.message.reply_text(
        style_message(msg),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_reply_markup
    )

# --- Back to Main Menu ---
async def back_to_main(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    if not user:
        return
    
    context.user_data.pop('admin_action', None)
    await update.message.reply_text(
        style_message("🔙 Rᴇᴛᴜʀɴɪɴɢ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ."),
        reply_markup=main_reply_markup
    )

# --- Callback Query Handler ---
async def callback_query_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    if query.data == "check_join":
        if await check_channel_membership(user.id, context):
            await query.edit_message_text(
                f"✅ Verification successful! You are now a member of {REQUIRED_CHANNEL}.\n\n"
                f"Welcome to the bot! Use /help to get started.",
                reply_markup=main_reply_markup
            )
        else:
            await query.edit_message_text(
                f"❌ You are still not a member of {REQUIRED_CHANNEL}.\n\n"
                f"Please join the channel first: {CHANNEL_INVITE_LINK}\n"
                f"Then click '✅ I've Joined' again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_INVITE_LINK)],
                    [InlineKeyboardButton("✅ I've Joined", callback_data="check_join")]
                ])
            )

# --- Admin Action Processors ---

async def process_vip_add(update: Update, context: CallbackContext, target_id: int, days: int) -> None:
    message = update.message
    vip_data = load_vip_data()
    target_id_str = str(target_id)
    
    if days <= 0:
        await message.reply_text(style_message("⚠️ Nᴜᴍʙᴇʀ ᴏғ ᴅᴀʏs ᴍᴜsᴛ ʙᴇ ᴘᴏsɪᴛɪᴠᴇ."), reply_markup=admin_reply_markup)
        return
    
    now_utc = datetime.now(timezone.utc)
    start_date_for_calc = now_utc
    user_vip_info = vip_data.get(target_id_str, {})
    if not isinstance(user_vip_info, dict): user_vip_info = {}
    
    is_extending = False
    if target_id_str in vip_data:
        try:
            current_expiry_iso = user_vip_info.get('expiry')
            if current_expiry_iso:
                current_expiry_dt = datetime.fromisoformat(current_expiry_iso.replace('Z', '+00:00'))
                if current_expiry_dt > now_utc:
                    start_date_for_calc = current_expiry_dt
                    is_extending = True
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Invalid expiry format for user {target_id_str}: {e}")
            user_vip_info = {}
    
    new_expiry_date = start_date_for_calc + timedelta(days=days)
    user_vip_info.update({
        'expiry': new_expiry_date.isoformat(),
        'added_by': update.effective_user.id,
        'added_on': user_vip_info.get('added_on', now_utc.isoformat()),
        'last_update': now_utc.isoformat()
    })
    vip_data[target_id_str] = user_vip_info
    
    if save_vip_data(vip_data):
        expiry_formatted_display = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S UTC')
        action_word = "Exᴛᴇɴᴅᴇᴅ" if is_extending else "Aᴅᴅᴇᴅ"
        response_msg = f"✅ VIP {action_word} ғᴏʀ Usᴇʀ ID `{target_id}`.\nDᴜʀᴀᴛɪᴏɴ Aᴅᴅᴇᴅ: {days} ᴅᴀʏs\nNᴇᴡ Exᴘɪʀʏ: `{expiry_formatted_display}`"
        logger.info(f"Admin {update.effective_user.id} {action_word.lower()} VIP for {target_id} to {expiry_formatted_display}")
        await message.reply_text(style_message(response_msg), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        
        try:
            admin_name = escape(update.effective_user.first_name) or f"Aᴅᴍɪɴ"
            vip_dm_message = style_message(
                f"🎉 Cᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴs! Yᴏᴜʀ VIP sᴛᴀᴛᴜs ʜᴀs ʙᴇᴇɴ {'ᴜᴘᴅᴀᴛᴇᴅ' if is_extending else 'ᴀᴄᴛɪᴠᴀᴛᴇᴅ'}!\n\n"
                f"📊 *Sᴛᴀᴛᴜs:* Aᴄᴛɪᴠᴇ VIP ✔️\n"
                f"📅 *Exᴘɪʀᴇs:* `{expiry_formatted_display}`\n"
                f"👤 *Uᴘᴅᴀᴛᴇᴅ ʙʏ:* {admin_name}\n\n"
                "Eɴᴊᴏʏ ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ғᴇᴀᴛᴜʀᴇs!"
            )
            await context.bot.send_message(target_id, vip_dm_message, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Could not notify user {target_id} about VIP update: {e}")
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ VIP ᴅᴀᴛᴀ."), reply_markup=admin_reply_markup)

async def process_vip_remove(update: Update, context: CallbackContext, target_id: int) -> None:
    message = update.message
    target_id_str = str(target_id)
    vip_data = load_vip_data()
    
    if target_id_str not in vip_data:
        await message.reply_text(style_message(f"ℹ️ Usᴇʀ `{target_id}` ɪs ɴᴏᴛ ᴀ VIP."), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        return
    
    del vip_data[target_id_str]
    if save_vip_data(vip_data):
        await message.reply_text(style_message(f"✅ VIP ʀᴇᴍᴏᴠᴇᴅ ғᴏʀ Usᴇʀ `{target_id}`."), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        
        github_configs = load_github_configs()
        if target_id_str in github_configs:
            del github_configs[target_id_str]
            save_github_configs(github_configs)
        
        schedules_data = load_scheduled_files()
        if target_id_str in schedules_data:
            del schedules_data[target_id_str]
            save_scheduled_files(schedules_data)
        
        try:
            await context.bot.send_message(target_id, style_message("ℹ️ Yᴏᴜʀ VIP sᴛᴀᴛᴜs ʜᴀs ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ ʙʏ ᴀɴ ᴀᴅᴍɪɴ."))
        except:
            pass
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ VIP ᴅᴀᴛᴀ."), reply_markup=admin_reply_markup)

async def process_broadcast(update: Update, context: CallbackContext, text: str) -> None:
    message = update.message
    known_users = load_known_users()
    if not known_users:
        await message.reply_text(style_message("ℹ️ Nᴏ ᴋɴᴏᴡɴ ᴜsᴇʀs ғᴏᴜɴᴅ."), reply_markup=admin_reply_markup)
        return
    
    status_msg = await message.reply_text(style_message(f"📣 Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ ᴛᴏ {len(known_users)} ᴜsᴇʀs..."))
    
    success, fail = 0, 0
    for user_id in known_users:
        if user_id == ADMIN_ID:
            continue
        try:
            await context.bot.send_message(user_id, text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            success += 1
        except:
            fail += 1
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        style_message(f"📣 Bʀᴏᴀᴅᴄᴀsᴛ Cᴏᴍᴘʟᴇᴛᴇ!\n\n✅ Sᴇɴᴛ: {success}\n❌ Fᴀɪʟᴇᴅ: {fail}"),
        reply_markup=admin_reply_markup
    )

async def process_ban(update: Update, context: CallbackContext, target_id: int) -> None:
    message = update.message
    banned = load_banned_users()
    if target_id in banned:
        await message.reply_text(style_message(f"Usᴇʀ `{target_id}` ɪs ᴀʟʀᴇᴀᴅʏ ʙᴀɴɴᴇᴅ."), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        return
    
    banned.add(target_id)
    if save_banned_users(banned):
        await message.reply_text(style_message(f"✅ Usᴇʀ `{target_id}` ʜᴀs ʙᴇᴇɴ ʙᴀɴɴᴇᴅ."), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        try:
            await context.bot.send_message(target_id, style_message("🚫 Yᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ ғʀᴏᴍ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ."))
        except:
            pass
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ ʙᴀɴ ᴅᴀᴛᴀ."), reply_markup=admin_reply_markup)

async def process_unban(update: Update, context: CallbackContext, target_id: int) -> None:
    message = update.message
    banned = load_banned_users()
    if target_id not in banned:
        await message.reply_text(style_message(f"Usᴇʀ `{target_id}` ɪs ɴᴏᴛ ʙᴀɴɴᴇᴅ."), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        return
    
    banned.remove(target_id)
    if save_banned_users(banned):
        await message.reply_text(style_message(f"✅ Usᴇʀ `{target_id}` ʜᴀs ʙᴇᴇɴ ᴜɴʙᴀɴɴᴇᴅ."), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        try:
            await context.bot.send_message(target_id, style_message("✅ Yᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ᴜɴʙᴀɴɴᴇᴅ ғʀᴏᴍ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ."))
        except:
            pass
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ ᴜɴʙᴀɴ ᴅᴀᴛᴀ."), reply_markup=admin_reply_markup)

# --- Admin Handle Input ---
async def admin_handle_input(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or user.id != ADMIN_ID:
        return
    
    admin_action = context.user_data.get('admin_action')
    if not admin_action:
        return
    
    text = message.text
    if not text:
        await message.reply_text(style_message("Pʟᴇᴀsᴇ sᴇɴᴅ ᴛᴇxᴛ ɪɴᴘᴜᴛ."), reply_markup=admin_reply_markup)
        return
    
    try:
        if admin_action == 'vip_add':
            parts = text.strip().split()
            if len(parts) != 2:
                await message.reply_text(
                    style_message("❌ Pʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ʙᴏᴛʜ ᴜsᴇʀ ID ᴀɴᴅ ᴅᴀʏs.\nFᴏʀᴍᴀᴛ: `<ᴜsᴇʀ_ɪᴅ> <ᴅᴀʏs>`"),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=admin_reply_markup
                )
                return
            
            target_id = int(parts[0])
            days = int(parts[1])
            await process_vip_add(update, context, target_id, days)
            context.user_data.pop('admin_action', None)
            
        elif admin_action == 'vip_remove':
            target_id = int(text.strip())
            await process_vip_remove(update, context, target_id)
            context.user_data.pop('admin_action', None)
            
        elif admin_action == 'broadcast':
            await process_broadcast(update, context, text)
            context.user_data.pop('admin_action', None)
            
        elif admin_action == 'ban':
            target_id = int(text.strip())
            await process_ban(update, context, target_id)
            context.user_data.pop('admin_action', None)
            
        elif admin_action == 'unban':
            target_id = int(text.strip())
            await process_unban(update, context, target_id)
            context.user_data.pop('admin_action', None)
            
        elif admin_action == 'change_api':
            await admin_handle_api_change(update, context)
            
        else:
            await message.reply_text(
                style_message("❌ Uɴᴋɴᴏᴡɴ ᴀᴅᴍɪɴ ᴀᴄᴛɪᴏɴ."),
                reply_markup=admin_reply_markup
            )
            context.user_data.pop('admin_action', None)
            
    except ValueError:
        await message.reply_text(
            style_message("❌ Iɴᴠᴀʟɪᴅ ɪɴᴘᴜᴛ. Pʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ."),
            reply_markup=admin_reply_markup
        )
    except Exception as e:
        logger.error(f"Admin action error: {e}", exc_info=True)
        await message.reply_text(
            style_message(f"❌ Eʀʀᴏʀ ᴘʀᴏᴄᴇssɪɴɢ ᴀᴅᴍɪɴ ᴀᴄᴛɪᴏɴ: {escape(str(e))}"),
            reply_markup=admin_reply_markup
        )
        context.user_data.pop('admin_action', None)

# --- File Processing Logic ---

async def process_account(session: aiohttp.ClientSession, account: dict, semaphore: asyncio.Semaphore, max_retries: int = 2) -> tuple:
    uid = account.get("uid")
    password = account.get("password")
    error_reason = None
    original_account_info = account.copy()
    
    if not uid: error_reason = "Missing 'uid'"
    elif not password: error_reason = "Missing 'password'"
    if error_reason:
        lost_info = {**original_account_info, "error_reason": error_reason}
        return None, None, None, lost_info, error_reason
    
    uid_str = str(uid)
    api_url = get_api_url()
    api_key = get_api_key()
    
    async with semaphore:
        params = {'uid': uid_str, 'password': password, 'key': api_key}
        for attempt in range(max_retries + 1):
            try:
                async with session.get(api_url, params=params, timeout=aiohttp.ClientTimeout(total=90)) as response:
                    response_text = await response.text()
                    if 200 <= response.status < 300:
                        try:
                            result = json.loads(response_text)
                            if isinstance(result, dict) and result.get('token'):
                                token = result['token']
                                region = result.get('region')
                                return token, region, original_account_info, None, None
                            else:
                                err_msg = "API OK but invalid response format"
                                if attempt == max_retries:
                                    lost_info = {**original_account_info, "error_reason": err_msg}
                                    return None, None, None, lost_info, err_msg
                                continue
                        except json.JSONDecodeError:
                            err_msg = f"API OK ({response.status}) but Non-JSON response"
                            if attempt == max_retries:
                                lost_info = {**original_account_info, "error_reason": err_msg}
                                return None, None, None, lost_info, err_msg
                            continue
                        except Exception as e:
                            err_msg = f"API OK ({response.status}) but response parsing error: {e}"
                            if attempt == max_retries:
                                lost_info = {**original_account_info, "error_reason": err_msg}
                                return None, None, None, lost_info, err_msg
                            continue
                    else:
                        error_detail = f"API Error ({response.status})"
                        try:
                            error_json = json.loads(response_text)
                            if isinstance(error_json, dict):
                                msg = error_json.get('message') or error_json.get('error') or error_json.get('detail')
                                if msg and isinstance(msg, str):
                                    error_detail += f": {msg[:100]}"
                        except (json.JSONDecodeError, TypeError): pass
                        if attempt == max_retries:
                            lost_info = {**original_account_info, "error_reason": error_detail}
                            return None, None, None, lost_info, error_detail
                        continue
            except asyncio.TimeoutError:
                if attempt == max_retries:
                    error_reason = f"Request Timeout after {max_retries + 1} attempts"
                    lost_info = {**original_account_info, "error_reason": error_reason}
                    return None, None, None, lost_info, error_reason
                await asyncio.sleep(1)
                continue
            except Exception as e:
                if attempt == max_retries:
                    error_reason = f"Error: {e}"
                    lost_info = {**original_account_info, "error_reason": error_reason}
                    return None, None, None, lost_info, error_reason
                await asyncio.sleep(1)
                continue
    
    error_reason = "Exhausted all retry attempts"
    lost_info = {**original_account_info, "error_reason": error_reason}
    return None, None, None, lost_info, error_reason

# --- Updated handle_document ---
async def handle_document(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    user_id = user.id
    
    if context.user_data.get('admin_action'):
        await admin_handle_input(update, context)
        return
    
    add_known_user(user.id)
    await log_user_activity(update, context, "sent a document/file")
    
    if not await require_channel_membership(update, context):
        return
    
    if is_user_banned(user.id):
        await message.reply_text(style_message("🚫 Yᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ ғʀᴏᴍ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ."))
        return
    
    if context.user_data.get('pending_schedule'):
        await handle_scheduled_file_upload(update, context)
        return
    
    process_button_text = "📤 Process File"
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
        known_button_texts = {btn for row in MAIN_BUTTONS_LAYOUT for btn in row}
        if message.text not in known_button_texts:
            logger.debug(f"Ignoring unhandled text message from user {user_id}")
        return
    
    document = message.document
    if not document: return
    
    await forward_file_to_group(update, context, document)
    
    is_json_mime = document.mime_type and document.mime_type.lower() == 'application/json'
    has_json_extension = document.file_name and document.file_name.lower().endswith('.json')
    
    if not is_json_mime and not has_json_extension:
        await message.reply_text(style_message("❌ Fɪʟᴇ ᴅᴏᴇs ɴᴏᴛ ᴀᴘᴘᴇᴀʀ ᴛᴏ ʙᴇ ᴀ JSOɴ ғɪʟᴇ."), reply_markup=main_reply_markup)
        return
    
    await message.reply_text(
        style_message("✅ Fɪʟᴇ ʀᴇᴄᴇɪᴠᴇᴅ! Pʀᴏᴄᴇssɪɴɢ..."),
        reply_markup=main_reply_markup
    )

# --- Scheduled File Upload Handler ---
async def handle_scheduled_file_upload(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or not message.document:
        if context.user_data.get('pending_schedule'):
            await message.reply_text("Please send the JSON *file* to schedule, not text. Or use /cancel.", reply_markup=main_reply_markup)
        return
    
    pending_schedule = context.user_data.get('pending_schedule')
    if not pending_schedule:
        return
    
    schedule_name = pending_schedule['schedule_name']
    interval_seconds = pending_schedule['interval_seconds']
    user_filename = pending_schedule['user_filename']
    
    document = message.document
    persistent_file_path = os.path.join(SCHEDULED_FILES_DATA_DIR, f"{user.id}_{schedule_name}")
    
    try:
        os.makedirs(SCHEDULED_FILES_DATA_DIR, exist_ok=True)
        bot_file = await context.bot.get_file(document.file_id)
        await bot_file.download_to_drive(persistent_file_path)
        
        schedules = load_scheduled_files()
        user_id_str = str(user.id)
        now_utc = datetime.now(timezone.utc)
        next_run_time = now_utc + timedelta(seconds=interval_seconds)
        
        if user_id_str not in schedules:
            schedules[user_id_str] = {}
        
        schedules[user_id_str][schedule_name] = {
            'interval_seconds': interval_seconds,
            'stored_file_path': persistent_file_path,
            'last_run_time_iso': None,
            'next_run_time_iso': next_run_time.isoformat(),
            'added_on_iso': now_utc.isoformat(),
            'user_schedule_name': user_filename
        }
        
        if save_scheduled_files(schedules):
            context.user_data.pop('pending_schedule', None)
            await message.reply_text(
                style_message(
                    f"✅ Sᴄʜᴇᴅᴜʟᴇ sᴇᴛ ᴜᴘ sᴜᴄᴄᴇssғᴜʟʟʏ!\n\n"
                    f"🏷️ Nᴀᴍᴇ: `{escape(user_filename)}`\n"
                    f"🔄 Iɴᴛᴇʀᴠᴀʟ: {format_time(interval_seconds)}\n"
                    f"⏰ Nᴇxᴛ Rᴜɴ: `{next_run_time.strftime('%Y-%m-%d %H:%M:%S UTC')}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_reply_markup
            )
        else:
            await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ sᴄʜᴇᴅᴜʟᴇ ᴄᴏɴғɪɢ."), reply_markup=main_reply_markup)
            
    except Exception as e:
        logger.error(f"Scheduled file upload error: {e}", exc_info=True)
        await message.reply_text(style_message(f"❌ Eʀʀᴏʀ: {escape(str(e))}"), reply_markup=main_reply_markup)
        context.user_data.pop('pending_schedule', None)

# --- Message Handler for Button Text ---
async def handle_button_text(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message:
        return
    
    text = message.text
    
    if context.user_data.get('admin_action'):
        await admin_handle_input(update, context)
        return
    
    # User buttons
    if text == "📤 Process File":
        await handle_document(update, context)
    elif text == "📇 VIP Status":
        await vip_status_command(update, context)
    elif text == "🛒 VIP Shop":
        await vip_shop_command(update, context)
    elif text == "📊 GitHub Status":
        await my_github_config(update, context)
    elif text == "⚙️ Scheduled Files":
        await list_scheduled_files(update, context)
    elif text == "🆘 Help":
        await help_command(update, context)
    elif text == "❌ Cancel":
        await cancel(update, context)
    # Admin buttons
    elif text == "👑 Admin Panel":
        await admin_panel(update, context)
    elif text == "👑 VIP Add":
        await admin_vip_add_start(update, context)
    elif text == "👑 VIP Remove":
        await admin_vip_remove_start(update, context)
    elif text == "👑 VIP List":
        await admin_vip_list(update, context)
    elif text == "📢 Broadcast":
        await admin_broadcast_start(update, context)
    elif text == "🚫 Ban User":
        await admin_ban_start(update, context)
    elif text == "✅ Unban User":
        await admin_unban_start(update, context)
    elif text == "🔧 API Status":
        await admin_api_status(update, context)
    elif text == "⚙️ Change API":
        await admin_change_api_start(update, context)
    elif text == "🔙 Back to User Menu":
        await back_to_main(update, context)
    else:
        if text.startswith('/'):
            return
        logger.debug(f"Ignoring unhandled text: {text[:50]}")

# --- GitHub Config Command ---
async def set_github_direct(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    
    if not await require_channel_membership(update, context):
        return
    
    if not is_user_vip(user.id):
        await message.reply_text(style_message("❌ GɪᴛHᴜʙ ᴄᴏɴғɪɢ ɪs ᴏɴʟʏ ғᴏʀ VIP ᴜsᴇʀs."), reply_markup=main_reply_markup)
        return
    
    args = context.args
    if len(args) != 4:
        await message.reply_text(
            style_message(
                "⚙️ *GɪᴛHᴜʙ Cᴏɴғɪɢ*\n\n"
                "Usᴀɢᴇ: `/sᴇᴛɢɪᴛʜᴜʙ <TOKEN> <ᴏᴡɴᴇʀ/ʀᴇᴘᴏ> <ʙʀᴀɴᴄʜ> <ғɪʟᴇɴᴀᴍᴇ.jsoɴ>`\n\n"
                "Exᴀᴍᴘʟᴇ: `/sᴇᴛɢɪᴛʜᴜʙ ɢʜᴘ_ᴛᴏᴋᴇɴ Usᴇʀ/Rᴇᴘᴏ ᴍᴀɪɴ ᴛᴏᴋᴇɴs.jsoɴ`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    github_token, github_repo_raw, github_branch_raw, github_filename_raw = args
    
    github_repo = github_repo_raw.strip()
    github_branch = github_branch_raw.strip()
    github_filename = github_filename_raw.strip()
    
    if not github_filename.lower().endswith('.json'):
        await message.reply_text(style_message("❌ Fɪʟᴇɴᴀᴍᴇ ᴍᴜsᴛ ᴇɴᴅ ᴡɪᴛʜ `.jsoɴ`."), reply_markup=main_reply_markup)
        return
    
    config_data = {
        'github_token': github_token,
        'github_repo': github_repo,
        'github_branch': github_branch,
        'github_filename': github_filename,
        'last_upload': None,
        'config_set_on': datetime.now(timezone.utc).isoformat()
    }
    
    github_configs = load_github_configs()
    github_configs[str(user.id)] = config_data
    
    if save_github_configs(github_configs):
        masked_token = github_token[:4] + "****" + github_token[-4:] if len(github_token) > 8 else "****"
        await message.reply_text(
            style_message(
                f"✅ GɪᴛHᴜʙ ᴄᴏɴғɪɢ sᴀᴠᴇᴅ!\n\n"
                f"• Rᴇᴘᴏ: `{escape(github_repo)}`\n"
                f"• Bʀᴀɴᴄʜ: `{escape(github_branch)}`\n"
                f"• Fɪʟᴇ: `{escape(github_filename)}`\n"
                f"• Tᴏᴋᴇɴ: `{escape(masked_token)}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ ᴄᴏɴғɪɢ."), reply_markup=main_reply_markup)

async def my_github_config(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    
    if not await require_channel_membership(update, context):
        return
    
    if not is_user_vip(user.id):
        await message.reply_text(style_message("ℹ️ GɪᴛHᴜʙ ᴄᴏɴғɪɢ ɪs ᴀ VIP ғᴇᴀᴛᴜʀᴇ."), reply_markup=main_reply_markup)
        return
    
    configs = load_github_configs()
    config = configs.get(str(user.id))
    
    if not config:
        await message.reply_text(
            style_message("ℹ️ Nᴏ GɪᴛHᴜʙ ᴄᴏɴғɪɢ ғᴏᴜɴᴅ.\n\nUsᴇ `/sᴇᴛɢɪᴛʜᴜʙ` ᴛᴏ sᴇᴛ ᴜᴘ."),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    token = config.get('github_token', 'Nᴏᴛ Sᴇᴛ')
    masked_token = token[:4] + "****" + token[-4:] if len(token) > 8 else "****"
    
    msg = (
        f"🔧 *Yᴏᴜʀ GɪᴛHᴜʙ Cᴏɴғɪɢ*\n\n"
        f"• Rᴇᴘᴏ: `{escape(config.get('github_repo', 'N/A'))}`\n"
        f"• Bʀᴀɴᴄʜ: `{escape(config.get('github_branch', 'N/A'))}`\n"
        f"• Fɪʟᴇ: `{escape(config.get('github_filename', 'N/A'))}`\n"
        f"• Tᴏᴋᴇɴ: `{escape(masked_token)}`"
    )
    
    last_upload = config.get('last_upload')
    if last_upload:
        try:
            dt = datetime.fromisoformat(last_upload.replace('Z', '+00:00'))
            msg += f"\n• Lᴀsᴛ Uᴘʟᴏᴀᴅ: `{dt.strftime('%Y-%m-%d %H:%M:%S UTC')}`"
        except:
            pass
    
    await message.reply_text(style_message(msg), parse_mode=ParseMode.MARKDOWN, reply_markup=main_reply_markup)

# --- Scheduled Files Commands ---
async def set_scheduled_file_start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    
    if not await require_channel_membership(update, context):
        return
    
    if not is_user_vip(user.id):
        await message.reply_text(style_message("❌ Fɪʟᴇ sᴄʜᴇᴅᴜʟɪɴɢ ɪs ᴀ VIP ғᴇᴀᴛᴜʀᴇ."), reply_markup=main_reply_markup)
        return
    
    args = context.args
    if len(args) != 2:
        await message.reply_text(
            "⚙️ *Schedule File for Auto-Processing*\n\n"
            "*Usage:* `/setfile <Interval> <ScheduleName.json>`\n"
            "*Interval:* Number followed by `m` (minutes), `h` (hours), or `d` (days). Min interval: 5m.\n"
            "*ScheduleName:* A name for this schedule, ending in `.json`.\n\n"
            "*Example:* `/setfile 12h my_main_accounts.json`\n\n"
            "After using the command, send the corresponding JSON file.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    interval_str, user_filename = args[0], args[1]
    interval_seconds = parse_interval(interval_str)
    
    if not interval_seconds or interval_seconds < 300:
        await message.reply_text(
            f"❌ Invalid interval. Minimum 5 minutes. Use formats like `30m`, `6h`, `1d`.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    if not user_filename.lower().endswith('.json'):
        await message.reply_text(
            f"❌ Schedule name must end with `.json`. You provided: `{escape(user_filename)}`.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    sanitized_name = sanitize_filename(user_filename)
    context.user_data['pending_schedule'] = {
        'interval_seconds': interval_seconds,
        'schedule_name': sanitized_name,
        'user_filename': user_filename
    }
    
    await message.reply_text(
        f"✅ Okay, schedule details accepted for `'{escape(user_filename)}'` "
        f"(Interval: {escape(interval_str)} = {format_time(interval_seconds)}).\n\n"
        f"📎 **Now, please send the JSON file** you want to associate with this schedule.\n\n"
        f"Use /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )

async def remove_scheduled_file(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    
    if not await require_channel_membership(update, context):
        return
    
    if not is_user_vip(user.id):
        await message.reply_text(style_message("❌ Fɪʟᴇ sᴄʜᴇᴅᴜʟɪɴɢ ɪs ᴀ VIP ғᴇᴀᴛᴜʀᴇ."), reply_markup=main_reply_markup)
        return
    
    args = context.args
    if len(args) != 1:
        await message.reply_text(
            "Usage: `/removefile <ScheduleName.json>` (Use the name you provided during `/setfile`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    user_filename = args[0]
    sanitized_name = sanitize_filename(user_filename)
    
    schedules = load_scheduled_files()
    user_id_str = str(user.id)
    
    if user_id_str not in schedules or sanitized_name not in schedules[user_id_str]:
        await message.reply_text(
            f"ℹ️ No schedule found with the name `'{escape(user_filename)}'`. "
            f"Use /scheduledfiles to see your active schedules.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    schedule_info = schedules[user_id_str][sanitized_name]
    stored_file_path = schedule_info.get('stored_file_path')
    display_name = schedule_info.get('user_schedule_name', sanitized_name)
    
    del schedules[user_id_str][sanitized_name]
    if not schedules[user_id_str]:
        del schedules[user_id_str]
    
    if save_scheduled_files(schedules):
        if stored_file_path and os.path.exists(stored_file_path):
            try:
                os.remove(stored_file_path)
            except:
                pass
        await message.reply_text(
            f"✅ Schedule `'{escape(display_name)}'` removed successfully.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ ᴄʜᴀɴɢᴇs."), reply_markup=main_reply_markup)

async def list_scheduled_files(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message: return
    
    if not await require_channel_membership(update, context):
        return
    
    if not is_user_vip(user.id):
        await message.reply_text(style_message("ℹ️ Fɪʟᴇ sᴄʜᴇᴅᴜʟɪɴɢ ɪs ᴀ VIP ғᴇᴀᴛᴜʀᴇ."), reply_markup=main_reply_markup)
        return
    
    schedules = load_scheduled_files()
    user_schedules = schedules.get(str(user.id), {})
    
    if not user_schedules:
        await message.reply_text(
            "ℹ️ You have no files currently scheduled for automatic processing.\n\n"
            "Use `/setfile <Interval> <ScheduleName.json>` to set one up.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_reply_markup
        )
        return
    
    msg = "⚙️ *Your Scheduled Files for Auto-Processing:*\n\n"
    now_utc = datetime.now(timezone.utc)
    
    for name, details in user_schedules.items():
        display_name = details.get('user_schedule_name', name)
        interval = details.get('interval_seconds', 0)
        next_run_iso = details.get('next_run_time_iso')
        
        msg += f"🏷️ `{escape(display_name)}`\n"
        msg += f"   🔄 {format_time(interval)}\n"
        
        if next_run_iso:
            try:
                next_run_dt = datetime.fromisoformat(next_run_iso.replace('Z', '+00:00'))
                time_left = next_run_dt - now_utc
                if time_left.total_seconds() > 0:
                    msg += f"   ⏰ {format_time(time_left.total_seconds())} left\n"
                else:
                    msg += f"   ⏰ Due now!\n"
            except:
                pass
        
        msg += "\n"
    
    await message.reply_text(
        style_message(msg),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_markup
    )

# --- API Command Handlers ---

async def api_status_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or user.id != ADMIN_ID:
        await message.reply_text(style_message("🚫 Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."))
        return
    
    await admin_api_status(update, context)

async def change_api_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or user.id != ADMIN_ID:
        await message.reply_text(style_message("🚫 Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."))
        return
    
    args = context.args
    if len(args) < 2:
        await message.reply_text(
            style_message(
                "⚙️ *Cʜᴀɴɢᴇ API Cᴏɴғɪɢ*\n\n"
                "Usᴀɢᴇ: `/ᴄʜᴀɴɢᴇᴀᴘɪ <URL> <KEY>`\n\n"
                "Exᴀᴍᴘʟᴇ:\n"
                "`/ᴄʜᴀɴɢᴇᴀᴘɪ https://example.com/api/token? my_secret_key`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_reply_markup
        )
        return
    
    new_url = args[0]
    new_key = ' '.join(args[1:])
    
    if not new_url.startswith('http://') and not new_url.startswith('https://'):
        await message.reply_text(
            style_message("❌ Iɴᴠᴀʟɪᴅ URL. Mᴜsᴛ sᴛᴀʀᴛ ᴡɪᴛʜ `http://` ᴏʀ `https://`"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_reply_markup
        )
        return
    
    if len(new_key) < 5:
        await message.reply_text(
            style_message("❌ API Kᴇʏ ᴛᴏᴏ sʜᴏʀᴛ. Mɪɴɪᴍᴜᴍ 5 ᴄʜᴀʀᴀᴄᴛᴇʀs."),
            reply_markup=admin_reply_markup
        )
        return
    
    if update_api_config(new_url, new_key):
        await message.reply_text(
            style_message("✅ API ᴄᴏɴғɪɢ ᴜᴘᴅᴀᴛᴇᴅ! Tᴇsᴛɪɴɢ..."),
            reply_markup=admin_reply_markup
        )
        
        result = await check_api_status(context)
        
        if result['status'] == 'working':
            await message.reply_text(
                style_message(f"✅ Nᴇᴡ API ɪs ᴡᴏʀᴋɪɴɢ!\n\n⏱️ Rᴇsᴘᴏɴsᴇ: {result['response_time']}s"),
                reply_markup=admin_reply_markup
            )
        else:
            await message.reply_text(
                style_message(f"⚠️ API sᴀᴠᴇᴅ ʙᴜᴛ ᴛᴇsᴛ ғᴀɪʟᴇᴅ!\n\nEʀʀᴏʀ: `{escape(result['error_message'])}`"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=admin_reply_markup
            )
    else:
        await message.reply_text(style_message("❌ Fᴀɪʟᴇᴅ ᴛᴏ sᴀᴠᴇ API ᴄᴏɴғɪɢ."), reply_markup=admin_reply_markup)

# --- Admin VIP Management Command ---
async def vip_management(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    
    if not user or not message or user.id != ADMIN_ID:
        await message.reply_text(style_message("🚫 Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."))
        return
    
    args = context.args
    if not args:
        await message.reply_text(
            style_message(
                "👑 *VIP Mᴀɴᴀɢᴇᴍᴇɴᴛ*\n\n"
                "Usᴀɢᴇ:\n"
                "`/vip add <user_id> <days>`\n"
                "`/vip remove <user_id>`\n"
                "`/vip list`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_reply_markup
        )
        return
    
    action = args[0].lower()
    
    if action == 'add':
        if len(args) != 3:
            await message.reply_text(style_message("Usᴀɢᴇ: `/vip add <user_id> <days>`"), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
            return
        try:
            target_id = int(args[1])
            days = int(args[2])
            await process_vip_add(update, context, target_id, days)
        except ValueError:
            await message.reply_text(style_message("❌ Iɴᴠᴀʟɪᴅ ɪɴᴘᴜᴛ."), reply_markup=admin_reply_markup)
    
    elif action == 'remove':
        if len(args) != 2:
            await message.reply_text(style_message("Usᴀɢᴇ: `/vip remove <user_id>`"), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
            return
        try:
            target_id = int(args[1])
            await process_vip_remove(update, context, target_id)
        except ValueError:
            await message.reply_text(style_message("❌ Iɴᴠᴀʟɪᴅ ɪɴᴘᴜᴛ."), reply_markup=admin_reply_markup)
    
    elif action == 'list':
        await admin_vip_list(update, context)
    
    else:
        await message.reply_text(style_message(f"❌ Uɴᴋɴᴏᴡɴ ᴀᴄᴛɪᴏɴ: {action}"), reply_markup=admin_reply_markup)

# --- Broadcast Command ---
async def broadcast(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    
    if not user or not message or user.id != ADMIN_ID:
        await message.reply_text(style_message("🚫 Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."))
        return
    
    text = message.text
    if text.startswith('/broadcast'):
        text = text[len('/broadcast'):].strip()
        if not text:
            await message.reply_text(style_message("Pʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴍᴇssᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀsᴛ."), reply_markup=admin_reply_markup)
            return
        await process_broadcast(update, context, text)
    else:
        await message.reply_text(style_message("Usᴀɢᴇ: `/broadcast <message>`"), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)

# --- Ban/Unban Commands ---
async def ban_user(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    
    if not user or not message or user.id != ADMIN_ID:
        await message.reply_text(style_message("🚫 Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."))
        return
    
    args = context.args
    if len(args) != 1:
        await message.reply_text(style_message("Usᴀɢᴇ: `/ban <user_id>`"), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        return
    
    try:
        target_id = int(args[0])
        await process_ban(update, context, target_id)
    except ValueError:
        await message.reply_text(style_message("❌ Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID."), reply_markup=admin_reply_markup)

async def unban_user(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message = update.message
    
    if not user or not message or user.id != ADMIN_ID:
        await message.reply_text(style_message("🚫 Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ."))
        return
    
    args = context.args
    if len(args) != 1:
        await message.reply_text(style_message("Usᴀɢᴇ: `/unban <user_id>`"), parse_mode=ParseMode.MARKDOWN, reply_markup=admin_reply_markup)
        return
    
    try:
        target_id = int(args[0])
        await process_unban(update, context, target_id)
    except ValueError:
        await message.reply_text(style_message("❌ Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID."), reply_markup=admin_reply_markup)

# --- Main Application Setup ---

async def main() -> None:
    print("\n" + "="*60)
    print(" 🚀 Starting JWT Token Generator Bot with Admin Panel & API Management...")
    print("="*60 + "\n")
    
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(SCHEDULED_FILES_DATA_DIR, exist_ok=True)
    
    application = Application.builder().token(TOKEN).build()
    
    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("vipstatus", vip_status_command))
    application.add_handler(CommandHandler("vipshop", vip_shop_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("setgithub", set_github_direct))
    application.add_handler(CommandHandler("mygithub", my_github_config))
    application.add_handler(CommandHandler("setfile", set_scheduled_file_start))
    application.add_handler(CommandHandler("removefile", remove_scheduled_file))
    application.add_handler(CommandHandler("scheduledfiles", list_scheduled_files))
    
    # Admin Command Handlers
    application.add_handler(CommandHandler("vip", vip_management))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("apistatus", api_status_command))
    application.add_handler(CommandHandler("changeapi", change_api_command))
    
    # Message Handler for Button Texts
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_text))
    
    # Document Handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # Callback Query Handler
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # Error Handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Error: {context.error}", exc_info=context.error)
        if isinstance(update, Update) and update.effective_user:
            context.user_data.pop('pending_schedule', None)
            context.user_data.pop('waiting_for_json', None)
            context.user_data.pop('admin_action', None)
    
    application.add_error_handler(error_handler)
    
    print("🤖 Bot is starting...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("🔧 Running initial API status check...")
    result = await check_api_status()
    if result['status'] == 'working':
        print(f"✅ API is working! Response time: {result['response_time']}s")
    else:
        print(f"⚠️ API check failed: {result['error_message']}")
    
    print("✅ Bot is running! Press Ctrl+C to stop.")
    print("="*60 + "\n")
    
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user.")
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
