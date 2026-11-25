import asyncio
import os
import uuid
import time
import subprocess
import shutil
import json
import re  

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified
from pyrogram import idle

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import edge_tts
import docx  
from mutagen.mp3 import MP3 

# ==========================================
# RENDER / ENVIRONMENT CONFIGURATION
# ==========================================
# Set these values in Render Environment Variables. Never commit secrets.
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID, API_HASH or BOT_TOKEN environment variable")

DATA_DIR = os.environ.get("DATA_DIR", "/var/data")
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# ADMIN DETAILS
# ==========================================
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
if not ADMIN_ID:
    raise RuntimeError("Missing ADMIN_ID environment variable")  

# ==========================================
# CONFIGURATION & LIMITS
# ==========================================
VOICE_NAME = "hi-IN-MadhurNeural"
CONCURRENCY_LIMIT = 15   
DAILY_LIMIT_BYTES = 8 * 1024 * 1024  # 8 MB in Bytes

USER_PREFS = {}
USER_STATE = {} 
PENDING_TASKS = {} 
ACTIVE_TASKS = {} 
USER_QUEUE = {} 

app = Client(os.path.join(DATA_DIR, "ultimate_tts_bot_v8"), api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

BASE_DIR = os.path.join(DATA_DIR, "workspace_tts")
os.makedirs(BASE_DIR, exist_ok=True)

BGM_DIR = os.path.join(BASE_DIR, "bgm_files")
os.makedirs(BGM_DIR, exist_ok=True)

# ==========================================
# DATABASE & MEMBERSHIP MANAGEMENT
# ==========================================
USERS_FILE = os.path.join(DATA_DIR, "users_db.json")

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f: return json.load(f)
        except: pass
    return {str(ADMIN_ID): {"expire_time": 9999999999, "notified_5h": False, "daily_usage": 0, "last_reset": 0}}

def save_users(db):
    with open(USERS_FILE, "w") as f: json.dump(db, f)

USERS_DB = load_users()
if str(ADMIN_ID) not in USERS_DB:
    USERS_DB[str(ADMIN_ID)] = {"expire_time": 9999999999, "notified_5h": False, "daily_usage": 0, "last_reset": 0}
    save_users(USERS_DB)

async def expiration_checker():
    while True:
        now = time.time()
        for uid, info in list(USERS_DB.items()):
            if uid == str(ADMIN_ID): continue
            exp = info.get("expire_time", 0)
            notified = info.get("notified_5h", False)
            if 0 < (exp - now) <= 18000 and not notified:
                msg = "⚠️ Aapka bot ka access band hone vala hai aap jaldi se payment karke bot ka membership le and payment screenshot is user id par send karen: @Novelgroupofficial1"
                try:
                    await app.send_message(int(uid), msg)
                    USERS_DB[uid]["notified_5h"] = True
                    save_users(USERS_DB)
                except: pass
        await asyncio.sleep(600)  

# NAYA FIX: 8MB Daily Limit Checker Function
def check_daily_limit(chat_id: str, file_size: int) -> bool:
    if chat_id == str(ADMIN_ID): return True
    
    now = time.time()
    user_data = USERS_DB.get(chat_id, {})
    
    # Check 24 hours reset
    if now - user_data.get("last_reset", 0) > 86400:
        user_data["daily_usage"] = 0
        user_data["last_reset"] = now
        
    current_usage = user_data.get("daily_usage", 0)
    
    if current_usage + file_size > DAILY_LIMIT_BYTES:
        return False
        
    user_data["daily_usage"] = current_usage + file_size
    USERS_DB[chat_id] = user_data
    save_users(USERS_DB)
    return True

# ==========================================
# UI KEYBOARDS
# ==========================================
def get_main_keyboard(chat_id):
    keys = [
        [InlineKeyboardButton("⚙️ Settings (Speed/Pitch/BGM)", callback_data="settings")],
        [InlineKeyboardButton("💎 Buy Membership", callback_data="buy_membership")],
        [InlineKeyboardButton("❓ Help & Info", callback_data="help")]
    ]
    if str(chat_id) == str(ADMIN_ID):
        keys.append([InlineKeyboardButton("👥 Manage Members", callback_data="manage_members")])
    return InlineKeyboardMarkup(keys)

def get_settings_keyboard(chat_id):
    prefs = USER_PREFS.get(chat_id, {"speed": "+0%", "pitch": "+0Hz", "bgm": False, "bgm_volume": 10, "active_bgm": None})
    bgm_status = "✅ ON" if prefs.get("bgm") else "❌ OFF"
    bgm_vol = prefs.get("bgm_volume", 10)
    
    active_bgm = prefs.get("active_bgm")
    display_bgm = active_bgm[:15] + "..." if active_bgm and len(active_bgm) > 18 else (active_bgm or "None")
        
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Speed: {prefs['speed']}", callback_data="none"), InlineKeyboardButton("✏️ Change", callback_data="set_speed")],
        [InlineKeyboardButton(f"🎵 Pitch: {prefs['pitch']}", callback_data="none"), InlineKeyboardButton("✏️ Change", callback_data="set_pitch")],
        [InlineKeyboardButton(f"🎼 BGM Status: {bgm_status} (Tap)", callback_data="toggle_bgm")],
        [InlineKeyboardButton(f"🎵 Track: {display_bgm}", callback_data="none"), InlineKeyboardButton(f"🔊 Vol: {bgm_vol}%", callback_data="set_bgm_vol")],
        [InlineKeyboardButton("🎶 All Background Musics", callback_data="list_bgm")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])

def get_split_keyboard(msg_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Hour", callback_data=f"split_3600_{msg_id}"), InlineKeyboardButton("2 Hours", callback_data=f"split_7200_{msg_id}")],
        [InlineKeyboardButton("3 Hours", callback_data=f"split_10800_{msg_id}"), InlineKeyboardButton("4 Hours", callback_data=f"split_14400_{msg_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_task_{msg_id}")]
    ])

def get_cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Job", callback_data="cancel_process")]])

# ==========================================
# UTILITY FUNCTIONS
# ==========================================
def init_user_prefs(chat_id):
    if chat_id not in USER_PREFS:
        USER_PREFS[chat_id] = {"speed": "+0%", "pitch": "+0Hz", "bgm": False, "bgm_volume": 10, "active_bgm": None}

def make_text_emotional(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)
    replacements = {"।": "। \n\n", ".": ". \n\n", "?": "? \n\n", "!": "! \n\n", ",": ", \n", ";": "; \n"}
    for old, new in replacements.items(): text = text.replace(old, new)
    return text

def extract_full_text_epub(epub_path: str) -> str:
    all_text, seen_hashes = [], set()
    try:
        book = epub.read_epub(epub_path)
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                try:
                    content = item.get_body_content()
                    if isinstance(content, bytes): content = content.decode('utf-8', errors='replace')
                    soup = BeautifulSoup(content, 'html.parser')
                    for tag in soup(["script", "style", "head"]): tag.decompose()
                    text = soup.get_text(separator=' ', strip=True)
                    if len(text) <= 150: continue
                    text_hash = hash(text[:200])
                    if text_hash in seen_hashes: continue
                    seen_hashes.add(text_hash)
                    all_text.append(text)
                except: continue
    except: pass
    return " ".join(all_text)

def extract_full_text_docx(docx_path: str) -> str:
    try: return "\n".join([para.text for para in docx.Document(docx_path).paragraphs if para.text.strip()])
    except: return ""

def extract_full_text_txt(txt_path: str) -> str:
    try:
        with open(txt_path, 'r', encoding='utf-8', errors='replace') as f: return f.read()
    except: return ""

def chunk_text(text: str, max_length: int = 3000) -> list:
    sentences = re.split(r'(?<=[।.!?])\s+', text.strip())
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 < max_length:
            current_chunk += sentence + " "
        else:
            if current_chunk.strip(): chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    if current_chunk.strip(): chunks.append(current_chunk.strip())
    return chunks

def safe_remove(path: str):
    try:
        if path and os.path.exists(path):
            if os.path.isdir(path): shutil.rmtree(path, ignore_errors=True)
            else: os.remove(path)
    except: pass

async def update_progress(msg: Message, text: str, last_update_time: float, reply_markup=None) -> float:
    now = time.time()
    if now - last_update_time >= 3.0:
        try:
            await msg.edit_text(text, reply_markup=reply_markup)
            return now
        except: pass
    return last_update_time

async def check_auth(client, message: Message) -> bool:
    chat_id = str(message.chat.id)
    if chat_id == str(ADMIN_ID): return True
    now = time.time()
    if chat_id in USERS_DB and USERS_DB[chat_id].get("expire_time", 0) > now: return True
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("📩 Request Access", callback_data=f"req_access_{chat_id}")], [InlineKeyboardButton("💎 Buy Membership", callback_data="buy_membership")]])
    try: await message.reply("🚫 **Access Denied / Expired!**\nAapke paas is bot ko use karne ki active membership nahi hai. Kripya Admin se request karein ya Buy karein.", reply_markup=btn)
    except: pass
    return False

# ==========================================
# QUEUE RUNNER & PROCESSOR 
# ==========================================
async def run_queue(chat_id, initial_item):
    current_item = initial_item
    while current_item:
        try:
            await process_file_to_audio(
                chat_id, current_item["file_path"], current_item["file_ext"], 
                current_item["unique_id"], current_item["msg"], current_item["split_duration"], 
                current_item["original_name"]
            )
        except Exception as e: print(f"Queue Error: {e}")
            
        if ACTIVE_TASKS.get(chat_id): ACTIVE_TASKS[chat_id]["cancel"] = False
            
        if chat_id in USER_QUEUE and len(USER_QUEUE[chat_id]) > 0:
            current_item = USER_QUEUE[chat_id].pop(0)
            await current_item["msg"].edit_text(f"🚀 **Aapka number aa gaya!**\n`{current_item['original_name']}` ki processing start ho rahi hai...")
        else: current_item = None
    ACTIVE_TASKS.pop(chat_id, None)

async def process_file_to_audio(chat_id: int, file_path: str, file_ext: str, unique_id: str, msg: Message, split_duration: int, original_name: str):
    try: await msg.edit_text(f"📖 **{file_ext.upper()}** file se text extract ho raha hai...", reply_markup=get_cancel_keyboard())
    except: pass

    if file_ext == '.epub': full_text = await asyncio.to_thread(extract_full_text_epub, file_path)
    elif file_ext == '.docx': full_text = await asyncio.to_thread(extract_full_text_docx, file_path)
    else: full_text = await asyncio.to_thread(extract_full_text_txt, file_path)

    if not full_text.strip():
        await msg.edit_text("❌ File mein koi valid text nahi mila.")
        safe_remove(file_path)
        return

    full_text = make_text_emotional(full_text)
    all_chunks = chunk_text(full_text)
    total_chunks = len(all_chunks)

    temp_run_dir = os.path.join(BASE_DIR, f"run_{unique_id}")
    os.makedirs(temp_run_dir, exist_ok=True)

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    init_user_prefs(chat_id)
    user_settings = USER_PREFS[chat_id]

    async def generate_chunk_audio(i, chunk):
        async with semaphore:
            part_path = os.path.join(temp_run_dir, f"raw_{str(i).zfill(5)}.mp3")
            retries = 0
            while retries < 3:
                if ACTIVE_TASKS.get(chat_id, {}).get("cancel"): return None
                try:
                    communicate = edge_tts.Communicate(chunk, VOICE_NAME, rate=user_settings["speed"], pitch=user_settings["pitch"])
                    await communicate.save(part_path)
                    if os.path.exists(part_path) and os.path.getsize(part_path) > 0: return part_path
                except:
                    retries += 1
                    await asyncio.sleep(2)
            return None

    async def send_part_with_retry(audio_path, title, file_name, dashboard_text, audio_duration):
        retries = 0
        while retries < 10:
            if ACTIVE_TASKS.get(chat_id, {}).get("cancel"): return
            try:
                await update_progress(msg, dashboard_text + f"\n\n📤 **Network Uploading:** `{file_name}`...", 0, reply_markup=get_cancel_keyboard())
                await app.send_audio(chat_id=chat_id, audio=audio_path, title=title, file_name=file_name, performer="AudioBook Pro", duration=int(audio_duration))
                return
            except:
                retries += 1
                await asyncio.sleep(5)

    async def process_batch(current_batch_files, part_number, parts_sent, dashboard_text, batch_duration):
        concat_file = os.path.join(temp_run_dir, f"concat_{part_number}.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for p in current_batch_files: f.write(f"file '{p.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
        
        safe_novel_name = original_name.replace(" ", "_").replace("/", "_")
        raw_merge_audio = os.path.join(temp_run_dir, f"raw_merge_{part_number}.mp3")
        final_audio = os.path.join(temp_run_dir, f"{safe_novel_name}_Part_{part_number}.mp3")
        
        proc_concat = await asyncio.create_subprocess_exec("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", raw_merge_audio, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc_concat.communicate()

        bgm_name = user_settings.get("active_bgm")
        if user_settings.get("bgm") and bgm_name and os.path.exists(os.path.join(BGM_DIR, bgm_name)):
            bgm_path = os.path.join(BGM_DIR, bgm_name)
            mix_dash = dashboard_text.replace("Tayaar kar raha hai...", f"🎼 '{bgm_name[:10]}...' mix kar raha hai...")
            await update_progress(msg, mix_dash, 0, reply_markup=get_cancel_keyboard())
            vol_decimal = user_settings.get("bgm_volume", 10) / 100.0
            
            mix_cmd = [
                "ffmpeg", "-y", "-threads", "0", 
                "-i", raw_merge_audio, "-stream_loop", "-1", "-i", bgm_path, 
                "-filter_complex", f"[0:a]volume=1.5[main];[1:a]volume={vol_decimal:.2f}[bg];[main][bg]amix=inputs=2:duration=first:dropout_transition=2", 
                "-c:a", "libmp3lame", "-b:a", "32k", "-write_xing", "0", "-id3v2_version", "3", final_audio
            ]
            proc_mix = await asyncio.create_subprocess_exec(*mix_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc_mix.communicate()
        else:
            fix_dash = dashboard_text.replace("Tayaar kar raha hai...", "⚙️ Optimizing Audio Duration...")
            await update_progress(msg, fix_dash, 0, reply_markup=get_cancel_keyboard())
            fix_cmd = ["ffmpeg", "-y", "-threads", "0", "-i", raw_merge_audio, "-c:a", "copy", "-write_xing", "0", "-id3v2_version", "3", final_audio]
            proc_fix = await asyncio.create_subprocess_exec(*fix_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc_fix.communicate()

        file_title = f"Part {part_number} | {original_name}"
        upload_file_name = f"Part_{part_number}_{safe_novel_name}.mp3"
        await send_part_with_retry(final_audio, file_title, upload_file_name, dashboard_text, batch_duration)
        
        for p in current_batch_files: safe_remove(p)
        safe_remove(concat_file)
        safe_remove(raw_merge_audio)
        safe_remove(final_audio)

    try:
        tasks = [asyncio.create_task(generate_chunk_audio(i, chunk)) for i, chunk in enumerate(all_chunks)]
        current_batch_files, current_batch_dur, part_number, parts_sent, completed_tasks = [], 0.0, 1, 0, 0
        start_time = time.time()
        last_update = start_time

        for future in tasks:
            if ACTIVE_TASKS.get(chat_id, {}).get("cancel"): raise Exception("Process Cancelled by User.")
            result = await future
            completed_tasks += 1
            if result:
                try: dur = MP3(result).info.length 
                except: dur = 0
                if current_batch_dur + dur > split_duration and current_batch_files:
                    dashboard_text = f"⚡ **Dashboard**\n📁 `{original_name}`\n🔄 **Blocks:** `{completed_tasks}/{total_chunks}`\n⚙️ **Status:** Part {part_number} Tayaar kar raha hai..."
                    await update_progress(msg, dashboard_text, 0, reply_markup=get_cancel_keyboard())
                    await process_batch(current_batch_files, part_number, parts_sent, dashboard_text, current_batch_dur)
                    parts_sent += 1
                    current_batch_files = []
                    current_batch_dur = 0.0
                    part_number += 1
                current_batch_files.append(result)
                current_batch_dur += dur

            percent = (completed_tasks / total_chunks) * 100
            bar = "█" * int(percent / 10) + "░" * (10 - int(percent / 10))
            elapsed_sec = int(time.time() - start_time)
            avg = elapsed_sec / completed_tasks if completed_tasks > 0 else 0
            eta_str = time.strftime('%M:%S', time.gmtime(int(avg * (total_chunks - completed_tasks))))
            dash = (f"⚡ **Dashboard**\n📁 `{original_name}`\n🔄 `[{bar}] {percent:.1f}%`\n🎙 **Build:** `Part {part_number}`\n⏱ **Elapsed:** `{time.strftime('%M:%S', time.gmtime(elapsed_sec))}` | ⏳ **ETA:** `{eta_str}`")
            last_update = await update_progress(msg, dash, last_update, reply_markup=get_cancel_keyboard())

        if current_batch_files:
            if ACTIVE_TASKS.get(chat_id, {}).get("cancel"): raise Exception("Process Cancelled by User.")
            dash = f"⚡ **Dashboard**\n📁 `{original_name}`\n⚙️ **Status:** Final Part Tayaar kar raha hai..."
            await update_progress(msg, dash, 0, reply_markup=get_cancel_keyboard())
            await process_batch(current_batch_files, part_number, parts_sent, dash, current_batch_dur)
            parts_sent += 1

        await msg.delete()
        await app.send_message(chat_id, f"✅ **Mission Complete!**\n`{original_name}` successfully **{parts_sent}** parts mein bhej di gayi hai.")
    except Exception as e:
        try:
            if "Cancelled" in str(e): await msg.edit_text(f"🛑 **Job Cancelled!** `{original_name}` skip ho gayi.")
            else: await msg.edit_text(f"❌ **Error:**\n{str(e)}")
        except: pass
    finally:
        safe_remove(temp_run_dir)
        safe_remove(file_path)
# ==========================================
# TELEGRAM HANDLERS
# ==========================================
@app.on_message(filters.photo & filters.private & filters.command("setqr"))
async def set_qr_cmd(client, message: Message):
    if str(message.chat.id) != str(ADMIN_ID): return
    qr_path = os.path.join(BASE_DIR, "qr_code.jpg")
    await message.download(file_name=qr_path)
    await message.reply("✅ **QR Code successfully saved!**\nUsers ko ab Membership menu me yahi QR code dikhai dega.")

@app.on_message(filters.audio & filters.private)
async def handle_audio_bgm(client, message: Message):
    if not await check_auth(client, message): return
    chat_id = message.chat.id
    init_user_prefs(chat_id)
    await message.reply("📥 **BGM download ho raha hai...**")
    file_name = message.audio.file_name or f"Music_{message.id}.mp3"
    if not file_name.lower().endswith(".mp3"): file_name += ".mp3"
    bgm_path = os.path.join(BGM_DIR, file_name)
    try:
        await client.download_media(message.audio.file_id, file_name=bgm_path)
        USER_PREFS[chat_id]["active_bgm"], USER_PREFS[chat_id]["bgm"] = file_name, True
        await message.reply(f"✅ **Music Save Ho Gaya!**\n🎶 Name: `{file_name}`")
    except Exception as e: await message.reply(f"❌ Error: {e}")

@app.on_message(filters.command("clearqueue") & filters.private)
async def clear_queue_cmd(client, message: Message):
    chat_id = message.chat.id
    count = 0
    if chat_id in USER_QUEUE and len(USER_QUEUE[chat_id]) > 0:
        count, USER_QUEUE[chat_id] = len(USER_QUEUE[chat_id]), []
    if chat_id in ACTIVE_TASKS: ACTIVE_TASKS[chat_id]["cancel"] = True
    await message.reply(f"🗑 **System Cleared!**\n**{count}** files aur atki hui process force-cancel ho gayi hai.")

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    if (time.time() - message.date.timestamp()) > 60: return
    chat_id = message.chat.id
    
    if str(chat_id) != str(ADMIN_ID):
        now = time.time()
        if str(chat_id) not in USERS_DB or USERS_DB[str(chat_id)].get("expire_time", 0) < now:
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("📩 Request Access", callback_data=f"req_access_{chat_id}")], [InlineKeyboardButton("💎 Buy Membership", callback_data="buy_membership")]])
            return await message.reply("👋 **Welcome to Ultimate TTS Bot!**\n\n🚫 Aapke paas is bot ki active membership nahi hai. Kripya niche se Request karein ya Membership Buy karein.", reply_markup=btn)
            
    USER_STATE[chat_id] = None  
    init_user_prefs(chat_id)
    text = "👋 **Welcome to Ultimate TTS Bot (V8 8MB LIMIT PRO)!**\n\nFile bhejein ya Settings change karein:"
    await message.reply(text, reply_markup=get_main_keyboard(chat_id))

@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data, chat_id = query.data, str(query.message.chat.id)
    
    if data == "buy_membership":
        text = (
            "💎 **Premium Membership Plans** 💎\n\n"
            "• 1 month : 250 rupees\n"
            "• 2 month : 500 rupees\n"
            "• 3 month : 750 rupees\n"
            "• 6 month : 1500 rupees\n"
            "• 1 year : 3000 rupees\n\n"
            "📞 **Payment Number:** `9355813735`\n\n"
            "✅ Payment karke screenshot is ID par send karein: @Novelgroupofficial1"
        )
        qr_path = os.path.join(BASE_DIR, "qr_code.jpg")
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]])
        if os.path.exists(qr_path):
            await query.message.delete()
            await client.send_photo(chat_id, photo=qr_path, caption=text, reply_markup=btn)
        else: await query.message.edit_text(text, reply_markup=btn)
        return

    if data.startswith("req_access_"):
        uid = data.split("_")[2]
        user = query.from_user
        username = f"@{user.username}" if user.username else "No Username"
        await query.answer("Request sent to Admin!", show_alert=True)
        await query.message.edit_text("✅ Aapki request Admin ko bhej di gayi hai. Kripya wait karein.")
        admin_btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Accept", callback_data=f"auth_acc_{uid}"), InlineKeyboardButton("❌ Reject", callback_data=f"auth_rej_{uid}")]])
        await client.send_message(ADMIN_ID, f"🔔 **New Access Request!**\n👤 Name: {user.first_name}\n🔗 User: {username}\n🆔 ID: `{uid}`", reply_markup=admin_btn)
        return

    if data.startswith("auth_acc_"):
        if chat_id != str(ADMIN_ID): return await query.answer("Not admin!", show_alert=True)
        uid = data.split("_")[2]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Day", callback_data=f"setdur_{uid}_1"), InlineKeyboardButton("3 Days", callback_data=f"setdur_{uid}_3")],
            [InlineKeyboardButton("1 Week", callback_data=f"setdur_{uid}_7"), InlineKeyboardButton("1 Month", callback_data=f"setdur_{uid}_30")],
            [InlineKeyboardButton("2 Months", callback_data=f"setdur_{uid}_60"), InlineKeyboardButton("3 Months", callback_data=f"setdur_{uid}_90")],
            [InlineKeyboardButton("6 Months", callback_data=f"setdur_{uid}_180"), InlineKeyboardButton("1 Year", callback_data=f"setdur_{uid}_365")]
        ])
        await query.message.edit_text(f"Select Duration for `{uid}`:", reply_markup=kb)
        return

    if data.startswith("auth_rej_"):
        if chat_id != str(ADMIN_ID): return
        uid = data.split("_")[2]
        await query.message.edit_text("❌ Request Rejected.")
        try: await client.send_message(int(uid), "❌ **Request Rejected!**\nAdmin ne aapki access request decline kar di hai.")
        except: pass
        return

    if data.startswith("setdur_"):
        if chat_id != str(ADMIN_ID): return
        parts = data.split("_")
        uid, days = parts[1], int(parts[2])
        USERS_DB[uid] = {"expire_time": time.time() + (days * 86400), "notified_5h": False, "daily_usage": 0, "last_reset": time.time()}
        save_users(USERS_DB)
        await query.message.edit_text(f"✅ Granted {days} days to `{uid}`.")
        try: await client.send_message(int(uid), f"🎉 **Congratulations!**\nAapko **{days} days** ki Premium Membership mil gayi hai.\nClick 👉 /start")
        except: pass
        return

    if data == "manage_members":
        if chat_id != str(ADMIN_ID): return
        now = time.time()
        active = [u for u in USERS_DB if u != str(ADMIN_ID) and USERS_DB[u].get("expire_time", 0) > now]
        if not active: return await query.answer("No active members!", show_alert=True)
        kb = []
        for u in active[:15]:
            rem_sec = USERS_DB[u].get("expire_time", 0) - now
            days = int(rem_sec / 86400)
            label = f"👤 {u} ({days} Days left)" if days > 0 else f"👤 {u} ({int(rem_sec/3600)} Hrs left)"
            kb.append([InlineKeyboardButton(label, callback_data=f"editusr_{u}")])
        kb.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")])
        await query.message.edit_text("👥 **Active Members List:**\nTap on a user to Manage or Reject.", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("editusr_"):
        if chat_id != str(ADMIN_ID): return
        uid = data.split("_")[1]
        rem_sec = USERS_DB.get(uid, {}).get("expire_time", 0) - time.time()
        days = int(rem_sec / 86400)
        
        udata = USERS_DB.get(uid, {})
        usage_mb = udata.get("daily_usage", 0) / (1024*1024)
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add 1 Month", callback_data=f"addm_{uid}")],
            [InlineKeyboardButton("❌ Reject / Revoke Access", callback_data=f"revoke_{uid}")],
            [InlineKeyboardButton("🔙 Back to List", callback_data="manage_members")]
        ])
        await query.message.edit_text(f"👤 **Manage User:** `{uid}`\n⏳ **Remaining Time:** `{max(0, days)} Days`\n📊 **Today's Usage:** `{usage_mb:.2f} MB / 8 MB`\n\nYahan se aap is user ka access hata (Reject) sakte hain ya time badha sakte hain:", reply_markup=kb)
        return

    if data.startswith("addm_"):
        if chat_id != str(ADMIN_ID): return
        uid = data.split("_")[1]
        if uid in USERS_DB:
            USERS_DB[uid]["expire_time"] += (30 * 86400)
            USERS_DB[uid]["notified_5h"] = False
            save_users(USERS_DB)
            await query.answer("Added 30 days!", show_alert=True)
            await callback_handler(client, query) 
        return

    if data.startswith("revoke_"):
        if chat_id != str(ADMIN_ID): return
        uid = data.split("_")[1]
        if uid in USERS_DB:
            USERS_DB[uid]["expire_time"] = 0
            save_users(USERS_DB)
            await query.message.edit_text(f"✅ User `{uid}` ka access Revoke (Reject) kar diya gaya hai. Wo ab bot use nahi kar payega.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to List", callback_data="manage_members")]]))
            try: await client.send_message(int(uid), "🚫 **Access Revoked!**\nAdmin ne aapka access reject/cancel kar diya hai. Ab aap bot use nahi kar sakte.")
            except: pass
        return

    if chat_id != str(ADMIN_ID):
        if chat_id not in USERS_DB or USERS_DB[chat_id].get("expire_time", 0) < time.time():
            return await query.answer("Membership Expired!", show_alert=True)

    chat_id = int(chat_id)
    if data == "cancel_process":
        if chat_id in ACTIVE_TASKS and ACTIVE_TASKS[chat_id].get("is_running"):
            ACTIVE_TASKS[chat_id]["cancel"] = True
            await query.message.edit_text("⚠️ **Cancelling...**")
        else: await query.answer("Koi active task nahi hai.", show_alert=True)
        return

    init_user_prefs(chat_id)
    try:
        if data == "toggle_bgm":
            USER_PREFS[chat_id]["bgm"] = not USER_PREFS[chat_id].get("bgm", False)
            if USER_PREFS[chat_id]["bgm"] and not USER_PREFS[chat_id].get("active_bgm"):
                await query.answer("⚠️ Pehle koi Music bhejein!", show_alert=True)
                USER_PREFS[chat_id]["bgm"] = False
            else: await query.message.edit_reply_markup(get_settings_keyboard(chat_id))
                
        elif data == "list_bgm":
            bgm_files = sorted([f for f in os.listdir(BGM_DIR) if f.endswith('.mp3')])
            if not bgm_files: return await query.answer("❌ Koi Music save nahi hai!", show_alert=True)
            kb = [[InlineKeyboardButton(f"🎵 {fname[:30]}", callback_data=f"selbgm_{i}")] for i, fname in enumerate(bgm_files)]
            kb.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")])
            await query.message.edit_text("🎶 **Apni Music Library:**", reply_markup=InlineKeyboardMarkup(kb))
            
        elif data.startswith("selbgm_"):
            idx = int(data.split("_")[1])
            bgm_files = sorted([f for f in os.listdir(BGM_DIR) if f.endswith('.mp3')])
            if idx < len(bgm_files):
                USER_PREFS[chat_id]["active_bgm"], USER_PREFS[chat_id]["bgm"] = bgm_files[idx], True
                await query.answer("✅ Selected", show_alert=False)
                await query.message.edit_text("⚙️ **Settings Menu:**\nMusic set ho gaya!", reply_markup=get_settings_keyboard(chat_id))
                try: await client.send_audio(chat_id=chat_id, audio=os.path.join(BGM_DIR, bgm_files[idx]), caption=f"🎧 **BGM Demo:** `{bgm_files[idx]}`\nYeh music ab active ho chuka hai!")
                except: pass
            else: await query.answer("❌ Error!", show_alert=True)

        elif data.startswith("split_"):
            parts = data.split("_")
            split_dur, msg_id = int(parts[1]), int(parts[2])
            task = PENDING_TASKS.pop(msg_id, None)
            if not task: return await query.message.edit_text("❌ Expired.")
            unique_id = uuid.uuid4().hex[:6]
            
            async def dl(file_id, path):
                while True:
                    try: return await client.download_media(file_id, file_name=path)
                    except: await asyncio.sleep(5)

            if task["type"] == "document":
                file_ext, original_name = task["file_ext"], os.path.splitext(task["file_name"])[0].title()
                file_path = os.path.join(BASE_DIR, f"novel_{unique_id}{file_ext}")
                await query.message.edit_text(f"📥 **Downloading...**")
                await dl(task["file_id"], file_path)
            else:
                file_ext, original_name = ".txt", "Text_Snippet"
                file_path = os.path.join(BASE_DIR, f"text_{unique_id}.txt")
                with open(file_path, "w", encoding="utf-8") as f: f.write(task["content"])

            q_item = {"file_path": file_path, "file_ext": file_ext, "unique_id": unique_id, "split_duration": split_dur, "original_name": original_name, "msg": query.message}
            if chat_id not in USER_QUEUE: USER_QUEUE[chat_id] = []

            if ACTIVE_TASKS.get(chat_id, {}).get("is_running"):
                USER_QUEUE[chat_id].append(q_item)
                await query.message.edit_text(f"⏳ **Queue Position: #{len(USER_QUEUE[chat_id])}**")
            else:
                ACTIVE_TASKS[chat_id] = {"cancel": False, "is_running": True}
                asyncio.create_task(run_queue(chat_id, q_item))

        elif data.startswith("cancel_task_"):
            msg_id = int(data.split("_")[2])
            PENDING_TASKS.pop(msg_id, None)
            await query.message.edit_text("❌ Cancelled.", reply_markup=get_main_keyboard(chat_id))

        elif data == "main_menu":
            USER_STATE[chat_id] = None
            if query.message.photo:
                await query.message.delete()
                await app.send_message(chat_id, "👋 **Main Menu:**", reply_markup=get_main_keyboard(chat_id))
            else: await query.message.edit_text("👋 **Main Menu:**", reply_markup=get_main_keyboard(chat_id))
            
        elif data == "settings":
            USER_STATE[chat_id] = None
            await query.message.edit_text("⚙️ **Settings Menu:**", reply_markup=get_settings_keyboard(chat_id))
            
        elif data == "set_bgm_vol":
            USER_STATE[chat_id] = "edit_bgm_volume"
            await query.message.edit_text("🔊 **Custom BGM Volume % (e.g. 5, 10):**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="settings")]]))

        elif data == "help":
            USER_STATE[chat_id] = None
            await query.message.edit_text("📖 **Help:** BGM set karein, Files bhejein.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]))
            
        elif data == "set_speed":
            USER_STATE[chat_id] = "edit_speed"
            await query.message.edit_text("🚀 **Type Speed (e.g. +20%, 1.2):**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="settings")]]))
            
        elif data == "set_pitch":
            USER_STATE[chat_id] = "edit_pitch"
            await query.message.edit_text("🎵 **Type Pitch (e.g. -5Hz, +10Hz):**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="settings")]]))

        elif data == "none": await query.answer("Current setting.", show_alert=False)
            
    except MessageNotModified: pass 

@app.on_message(filters.document & filters.private)
async def handle_document(client, message: Message):
    if (time.time() - message.date.timestamp()) > 60: return
    if not await check_auth(client, message): return
    
    # NAYA FIX: 8MB Daily Limit Logic for Users
    file_size = message.document.file_size
    if not check_daily_limit(str(message.chat.id), file_size):
        return await message.reply("❌ **Daily Limit Exceeded!**\nAapki 24 ghante me 8MB file process karne ki limit poori ho chuki hai. Kripya kal dobara try karein.")
        
    USER_STATE[message.chat.id] = None 
    raw_file_name = message.document.file_name
    file_ext = os.path.splitext(raw_file_name)[1].lower()
    if file_ext not in ['.epub', '.docx', '.txt']: return await message.reply("❌ Kripya sirf `.epub`, `.docx`, ya `.txt` send karein.")
    
    msg_id = message.id
    PENDING_TASKS[msg_id] = {"type": "document", "file_id": message.document.file_id, "file_name": raw_file_name, "file_ext": file_ext}
    await message.reply(f"⏱ **{raw_file_name}**\nSelect hour split:", reply_markup=get_split_keyboard(msg_id))

@app.on_message(filters.text & filters.private & ~filters.command(["start", "users", "clearqueue", "setqr"]))
async def handle_normal_text(client, message: Message):
    if (time.time() - message.date.timestamp()) > 60: return
    if not await check_auth(client, message): return
    chat_id = message.chat.id
    state = USER_STATE.get(chat_id)
    init_user_prefs(chat_id)

    if state == "edit_speed":
        raw_val = message.text.strip()
        try:
            val_i = int(float(raw_val.replace('%', '').replace('+', ''))) if '%' in raw_val else (int((float(raw_val) - 1.0) * 100) if '.' in raw_val else int(float(raw_val.replace('+', ''))))
            speed_str = f"+{val_i}%" if val_i >= 0 else f"{val_i}%"
            USER_PREFS[chat_id]["speed"] = speed_str
            USER_STATE[chat_id] = None
            await message.reply(f"✅ Speed: **{speed_str}**", reply_markup=get_settings_keyboard(chat_id))
        except: await message.reply("❌ Invalid format.", reply_markup=get_settings_keyboard(chat_id))
        return

    elif state == "edit_pitch":
        raw_val = message.text.strip().lower()
        try:
            val_f = float(raw_val.replace('hz', '').replace('+', ''))
            val_i = int((val_f - 1.0) * 100) if ('.' in raw_val and 0 < val_f <= 3.0) else int(val_f)
            pitch_str = f"+{val_i}Hz" if val_i >= 0 else f"{val_i}Hz"
            USER_PREFS[chat_id]["pitch"] = pitch_str
            USER_STATE[chat_id] = None
            await message.reply(f"✅ Pitch: **{pitch_str}**", reply_markup=get_settings_keyboard(chat_id))
        except: await message.reply("❌ Invalid format.", reply_markup=get_settings_keyboard(chat_id))
        return

    elif state == "edit_bgm_volume":
        try:
            vol_i = int(message.text.strip().replace('%', ''))
            if not (1 <= vol_i <= 100): raise ValueError
            USER_PREFS[chat_id]["bgm_volume"] = vol_i
            USER_STATE[chat_id] = None
            await message.reply(f"✅ Vol: **{vol_i}%**", reply_markup=get_settings_keyboard(chat_id))
        except: await message.reply("❌ 1 se 100 ke beech likhein.", reply_markup=get_settings_keyboard(chat_id))
        return

    # NAYA FIX: Apply 8MB Limit to direct text snippet messages too
    text_size = len(message.text.encode('utf-8'))
    if not check_daily_limit(str(chat_id), text_size):
        return await message.reply("❌ **Daily Limit Exceeded!**\nAapki 24 ghante me 8MB data process karne ki limit poori ho chuki hai.")

    msg_id = message.id
    PENDING_TASKS[msg_id] = {"type": "text", "content": message.text}
    await message.reply("⏱ **Text Snippet**\nSelect hour split:", reply_markup=get_split_keyboard(msg_id))

async def main():
    print("Render TTS Bot started (8MB Limit Active).")
    await app.start()
    asyncio.create_task(expiration_checker())
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())