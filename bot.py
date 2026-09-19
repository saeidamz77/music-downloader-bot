import os
import re
import sys
import uuid
import glob
import html
import sqlite3
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import yt_dlp
from shazamio import Shazam

# ==================== تنظیمات مدیریت و ربات ====================
TOKEN = os.environ.get("BOT_TOKEN") or "8924723567:AAH1ag1Ccc_t8DTy6u6ayw1kM8I9SWziuBY"
BOT_USERNAME = os.environ.get("BOT_USERNAME") or "@Instadlmusicbot"
SUPPORT_ID = "@saeed_mz77"
CHANNEL_ID = os.environ.get("CHANNEL_ID") or "@ainewss2026"
ADMIN_ID = int(os.environ.get("ADMIN_ID") or "1773399042")

VIP_PRICE_TEXT = "ماهانه 350 هزار تومان | دائمی 500 هزار تومان"
CARD_NUMBER = "6219-8619-4353-1938 به نام سعید محمدزاده"
# ==============================================================

conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    invited_by INTEGER,
    requests_left INTEGER DEFAULT 3,
    invites_count INTEGER DEFAULT 0,
    is_vip INTEGER DEFAULT 0
)
""")
conn.commit()

shazam = Shazam()

def get_or_create_user(user_id, referrer_id=None):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, invited_by, requests_left, invites_count, is_vip) VALUES (?, ?, 3, 0, 0)",
            (user_id, referrer_id)
        )
        if referrer_id and referrer_id != user_id:
            cursor.execute(
                "UPDATE users SET invites_count = invites_count + 1, requests_left = requests_left + 3 WHERE user_id = ?",
                (referrer_id,)
            )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    return user

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not CHANNEL_ID or CHANNEL_ID == "@YourChannelID":
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

def is_link(text: str) -> bool:
    return bool(re.search(r'https?://[^\s]+', text))

def clean_files(prefix: str):
    for f in glob.glob(f"{prefix}*"):
        try: os.remove(f)
        except: pass

def get_output_file(prefix: str):
    matches = glob.glob(f"{prefix}.*")
    valid = [f for f in matches if not f.endswith(('.jpg', '.png', '.webp', '.part', '.ytdl'))]
    return valid[0] if valid else None

def consume_credit(user_id: int) -> bool:
    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row: return False
    requests_left, is_vip = row
    if is_vip == 1: return True
    if requests_left > 0:
        cursor.execute("UPDATE users SET requests_left = requests_left - 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    return False

def clean_song_query(text: str) -> str:
    if not text: return ""
    clean = re.sub(r'https?://\S+|@[^\s]+|#[^\s]+', ' ', text)
    clean = re.sub(r'(?i)(video by|reel by|audio by|original audio|remix|slowed|reverb|insta|clip|ریلز|پست)', ' ', clean)
    clean = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', clean)
    clean = re.sub(r'[^\w\s\d\u0600-\u06FF]', ' ', clean)
    return ' '.join(clean.split())

# استخراج عنوان و کپشن ریلز اینستاگرام از متادیتای سبک oEmbed
def get_instagram_title_fast(url: str) -> str:
    try:
        clean_url = url.split('?')[0].rstrip('/')
        oembed_url = f"https://api.instagram.com/oembed/?url={clean_url}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(oembed_url, headers=headers, timeout=6)
        if r.status_code == 200:
            data = r.json()
            title = data.get('title', '')
            author = data.get('author_name', '')
            found = re.findall(r'(?:موزیک|آهنگ|اهنگ|music|song|track)\s*[:：\-]?\s*([^\n\r#@]+)', title, re.IGNORECASE)
            if found:
                return clean_song_query(found[0])
            first_line = clean_song_query(title.split('\n')[0])
            if len(first_line) > 3:
                return first_line
    except Exception:
        pass
    return ""

# ==================== پنل مدیریت ====================
async def show_admin_panel(message_target):
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
    vip_users = cursor.fetchone()[0]

    panel_text = (
        "⚙️ <b>پنل مدیریت ربات</b>\n"
        "-------------------\n"
        f"👥 کل کاربران: <code>{total_users} نفر</code>\n"
        f"⭐️ کاربران VIP: <code>{vip_users} نفر</code>\n"
        "-------------------\n"
        "یک بخش را انتخاب کنید:"
    )
    kb = [
        [InlineKeyboardButton("📊 آمار دقیق کاربران", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 فعال‌سازی VIP", callback_data="admin_set_vip"), InlineKeyboardButton("❌ لغو VIP", callback_data="admin_rem_vip")],
        [InlineKeyboardButton("➕ افزودن اعتبار", callback_data="admin_add_credit")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 بستن منو", callback_data="admin_close")]
    ]
    try:
        if hasattr(message_target, 'edit_text'):
            await message_target.edit_text(panel_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await message_target.reply_text(panel_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        pass

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await show_admin_panel(update.message)

# ==================== هندلرهای پیام و فرامین تلگرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    referrer_id = int(args[0]) if (args and args[0].isdigit()) else None
    get_or_create_user(user_id, referrer_id)

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 عضویت در کانال", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text("<b>برای فعال‌سازی ابتدا عضو کانال شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "🎧 <b>ربات دانلود آهنگ کامل (Full 320 Track)</b>\n\n"
        "⚡️ <b>روش‌های سریع دریافت آهنگ:</b>\n"
        "▫️ لینک ریلز اینستاگرام یا یوتیوب را بفرستید.\n"
        "▫️ ویدیو یا ویس کلیپ را مستقیماً به داخل همین چت فوروارد کنید.\n"
        "▫️ نام آهنگ یا خواننده را بنویسید."
    )
    kb = [
        [InlineKeyboardButton("👤 حساب کاربری", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    admin_state = context.user_data.get('admin_state')
    if user_id == ADMIN_ID and admin_state:
        text_input = update.message.text.strip()
        if text_input in ["/cancel", "انصراف", "کنسل"]:
            context.user_data['admin_state'] = None
            await update.message.reply_text("عملیات لغو شد.")
            await show_admin_panel(update.message)
            return

        if admin_state == "set_vip":
            context.user_data['admin_state'] = None
            try:
                target_uid = int(text_input)
                get_or_create_user(target_uid)
                cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_uid,))
                conn.commit()
                await update.message.reply_text(f"✅ کاربر <code>{target_uid}</code> به VIP ارتقا یافت.", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ فقط شناسه عددی بفرستید.")
            await show_admin_panel(update.message)
            return

        elif admin_state == "rem_vip":
            context.user_data['admin_state'] = None
            try:
                target_uid = int(text_input)
                cursor.execute("UPDATE users SET is_vip = 0 WHERE user_id = ?", (target_uid,))
                conn.commit()
                await update.message.reply_text(f"✅ اشتراک VIP کاربر <code>{target_uid}</code> لغو شد.", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ فقط شناسه عددی بفرستید.")
            await show_admin_panel(update.message)
            return

        elif admin_state == "add_credit":
            context.user_data['admin_state'] = None
            try:
                parts = text_input.split()
                target_uid, amount = int(parts[0]), int(parts[1])
                get_or_create_user(target_uid)
                cursor.execute("UPDATE users SET requests_left = requests_left + ? WHERE user_id = ?", (amount, target_uid))
                conn.commit()
                await update.message.reply_text(f"✅ تعداد {amount} اعتبار اضافه شد.", parse_mode="HTML")
            except Exception:
                await update.message.reply_text("❌ مثال: <code>1773399042 10</code>", parse_mode="HTML")
            await show_admin_panel(update.message)
            return

        elif admin_state == "broadcast":
            context.user_data['admin_state'] = None
            status_msg = await update.message.reply_text("⏳ در حال ارسال...")
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()
            sent_count = 0
            for u in all_users:
                try:
                    await context.bot.send_message(chat_id=u[0], text=text_input, parse_mode="HTML")
                    sent_count += 1
                except Exception:
                    pass
            await status_msg.edit_text(f"📢 به {sent_count} کاربر ارسال شد.")
            await show_admin_panel(update.message)
            return

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [[InlineKeyboardButton("📢 عضویت", url=channel_link)], [InlineKeyboardButton("✅ تأیید", callback_data="check_join")]]
        await update.message.reply_text("لطفاً ابتدا عضو کانال شوید.", reply_markup=InlineKeyboardMarkup(kb))
        return

    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    req_left, is_vip = (u[0], u[1]) if u else (0, 0)

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = f"🔒 <b>اعتبار شما تمام شده است!</b>\n\nبرای شارژ، لینک زیر را بفرستید:\n<code>{invite_link}</code>"
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    if is_link(text):
        context.user_data['media_url'] = text
        credit_txt = "نامحدود (VIP)" if is_vip else f"{req_left} عدد"
        menu_text = f"🎯 <b>رسانه شناسایی شد</b> (اعتبار: <code>{credit_txt}</code>)\nروی دریافت قطعه کامل بزنید:"
        buttons = [
            [InlineKeyboardButton("🔥 دریافت آهنگ کامل ۳۲۰", callback_data="fast_full_music")]
        ]
        await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # سرچ متنی مستقیم آهنگ
    search_msg = await update.message.reply_text(f"🔍 در حال سرچ «{html.escape(text)}»...", parse_mode="HTML")
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
        'http_headers': {'User-Agent': 'Mozilla/5.0'}
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch4:{text}", download=False)
            tracks = res.get('entries', [])

        valid = [t for t in tracks if t.get('duration', 0) >= 40]
        if not valid:
            await search_msg.edit_text("❌ قطعه‌ای یافت نشد.")
            return

        context.user_data['tracks'] = {str(i): t for i, t in enumerate(valid)}
        buttons = []
        for i, t in enumerate(valid):
            title = t.get('title', 'Unknown')[:35]
            dur = t.get('duration_string', '--:--')
            buttons.append([InlineKeyboardButton(f"🎶 {i+1}. {title} [{dur}]", callback_data=f"select_{i}")])

        await search_msg.edit_text("🎵 قطعه مورد نظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await search_msg.edit_text(f"خطا در جستجو: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

# هندلر دریافت مستقیم ویدیو و ویس (بدون ارور لینک)
async def handle_direct_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_membership(user_id, context):
        await update.message.reply_text("ابتدا در کانال عضو شوید.")
        return

    if not consume_credit(user_id):
        await update.message.reply_text("سهمیه دانلود شما تمام شده است.")
        return

    status = await update.message.reply_text("🎧 <b>در حال تحلیل صوتی فایل...</b>", parse_mode="HTML")
    uid = uuid.uuid4().hex[:6]
    temp_file = f"up_{uid}.mp3"

    try:
        target = update.message.video or update.message.audio or update.message.voice or update.message.document
        bot_file = await context.bot.get_file(target.file_id)
        await bot_file.download_to_drive(temp_file)

        res = await shazam.recognize(temp_file)
        track = res.get('track') if res else None
        if track:
            stitle = clean_song_query(track.get('title', ''))
            sartist = clean_song_query(track.get('subtitle', ''))
            song_name = f"{sartist} {stitle}".strip()
            await status.edit_text(f"🔍 <b>شناسایی شد:</b> <code>{html.escape(song_name)}</code>\n⚡️ در حال دانلود نسخه کامل ۳۲۰...", parse_mode="HTML")
            await download_and_send_full_track(song_name, update.message.chat_id, context, status)
        else:
            await status.edit_text("❌ نام قطعه با تحلیل صوتی شناسایی نشد؛ لطفاً نام آهنگ را بنویسید.")
    except Exception as e:
        await status.edit_text(f"خطا: {e}")
    finally:
        clean_files(f"up_{uid}")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    try: await query.answer()
    except: pass

    if data.startswith("admin_"):
        if user_id != ADMIN_ID: return
        if data == "admin_panel": await show_admin_panel(query.message)
        elif data == "admin_stats":
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
            vips = cursor.fetchone()[0]
            await query.message.edit_text(f"📊 کل کاربران: {total}\n👑 کاربران VIP: {vips}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]))
        elif data == "admin_set_vip":
            context.user_data['admin_state'] = "set_vip"
            await query.message.reply_text("👑 شناسه کاربر را بفرستید:")
        elif data == "admin_rem_vip":
            context.user_data['admin_state'] = "rem_vip"
            await query.message.reply_text("❌ شناسه کاربر برای لغو VIP:")
        elif data == "admin_add_credit":
            context.user_data['admin_state'] = "add_credit"
            await query.message.reply_text("➕ فرمت: <code>1773399042 10</code>", parse_mode="HTML")
        elif data == "admin_broadcast":
            context.user_data['admin_state'] = "broadcast"
            await query.message.reply_text("📢 متن پیام همگانی را بفرستید:")
        elif data == "admin_close":
            await query.message.delete()
        return

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("عضویت تأیید شد!")
        else:
            await query.answer("هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        sup_url = f"https://t.me/{SUPPORT_ID.replace('@', '')}"
        vip_text = f"👑 <b>عضویت طلایی</b>\nتعرفه: {VIP_PRICE_TEXT}\nکارت: <code>{CARD_NUMBER}</code>"
        await query.message.reply_text(vip_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 پشتیبانی", url=sup_url)]]))
        return

    if data == "user_panel":
        cursor.execute("SELECT requests_left, invites_count, is_vip FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        req_left, inv_count, is_vip = row if row else (0, 0, 0)
        bot_user = BOT_USERNAME.replace("@", "")
        p_text = f"👤 شناسه: <code>{user_id}</code>\n⭐️ وضعیت: {'VIP' if is_vip else 'عادی'}\n⚡️ اعتبار: {req_left if not is_vip else 'نامحدود'}\n🔗 لینک دعوت:\n<code>https://t.me/{bot_user}?start={user_id}</code>"
        await query.message.reply_text(p_text, parse_mode="HTML")
        return

    # استخراج قطعی نسخه کامل چند دقیقه‌ای
    if data == "fast_full_music":
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما تمام شده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("⚡️ <b>در حال استخراج نام اثر و دریافت آهنگ کامل...</b>", parse_mode="HTML")

        # گام ۱: خواندن سریع عنوان بدون نیاز به دانلود ریلز
        target_song = get_instagram_title_fast(url)

        # گام ۲: اگر با oEmbed گرفته نشد، استفاده از yt-dlp کلاینت موبایل
        if not target_song:
            try:
                ydl_opts_meta = {'quiet': True, 'skip_download': True, 'extractor_args': {'youtube': {'player_client': ['android']}}}
                with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                    info = ydl.extract_info(url, download=False)
                    target_song = info.get('track') or clean_song_query(info.get('title', ''))
            except Exception:
                pass

        if not target_song:
            target_song = "Music"

        # گام ۳: جستجو و دانلود قطعی نسخه ۳۲۰ کامل (بالای ۱ دقیقه)
        download_success = await download_and_send_full_track(target_song, query.message.chat_id, context, status)
        if not download_success:
            await status.edit_text("❌ اینستاگرام دسترسی لینک را مسدود کرد. لطفاً **خود ویدیو یا فایل صوتی ریلز** را فوروارد کنید تا ربات فوراً آهنگ کامل را تحویل دهد.")
        return

    if data.startswith("select_"):
        idx = data.split("_")[1]
        track = context.user_data.get('tracks', {}).get(idx)
        if not track:
            await query.edit_message_text("درخواست منقضی شده است.")
            return

        status = await query.edit_message_text("⚡️ در حال دریافت قطعه انتخابی...", parse_mode="HTML")
        uid = uuid.uuid4().hex[:6]
        prefix = f"pick_{uid}"
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
            'http_headers': {'User-Agent': 'Mozilla/5.0'}
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track['webpage_url']])
            f_path = get_output_file(prefix)
            if f_path:
                with open(f_path, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=track.get('title', 'Music'),
                        performer=track.get('uploader', 'Artist'),
                        duration=track.get('duration', 0),
                        caption=f"🎵 <b>{html.escape(track.get('title', 'Music'))}</b>\n🤖 {BOT_USERNAME}",
                        parse_mode="HTML"
                    )
                await status.delete()
        except Exception as e:
            await status.edit_text(f"خطا: {e}")
        finally:
            clean_files(prefix)

# دانلود آهنگ کامل و چند دقیقه‌ای
async def download_and_send_full_track(query_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
    uid = uuid.uuid4().hex[:8]
    prefix = f"full_{uid}"
    
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f"{prefix}.%(ext)s",
        'quiet': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
        'http_headers': {'User-Agent': 'Mozilla/5.0'}
    }

    search_queries = [
        f"{query_text} official audio",
        f"{query_text}"
    ]

    for sq in search_queries:
        try:
            search_opts = {
                'quiet': True,
                'extractor_args': {'youtube': {'player_client': ['android', 'ios']}},
                'http_headers': {'User-Agent': 'Mozilla/5.0'}
            }
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                res = ydl.extract_info(f"ytsearch3:{sq}", download=False)
                entries = res.get('entries', [])

            best_entry = None
            for e in entries:
                dur = e.get('duration', 0)
                if dur and dur >= 45:
                    best_entry = e
                    break

            if best_entry:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([best_entry['webpage_url']])

                out_file = get_output_file(prefix)
                if out_file:
                    title = best_entry.get('title', query_text)
                    uploader = best_entry.get('uploader', 'Artist')
                    dur = best_entry.get('duration', 0)

                    caption = (
                        f"🎵 <b>{html.escape(title)}</b>\n"
                        f"👤 <code>{html.escape(uploader)}</code>\n"
                        f"🔥 <b>نسخه کامل استودیویی ۳۲۰</b>\n"
                        f"🤖 {BOT_USERNAME}"
                    )
                    with open(out_file, 'rb') as f:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=f,
                            title=title,
                            performer=uploader,
                            duration=dur,
                            caption=caption,
                            parse_mode="HTML",
                            read_timeout=120,
                            write_timeout=120
                        )
                    await status_msg.delete()
                    clean_files(prefix)
                    return True
        except Exception:
            clean_files(prefix)
            continue

    clean_files(prefix)
    return False

# وب‌سرور داخلی Render جهت پورت بایندینگ
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is online and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

app = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(60)
    .read_timeout(60)
    .write_timeout(60)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_command))
app.add_handler(CommandHandler("panel", admin_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL, handle_direct_upload))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با معماری ضدبلاک و دریافت مستقیم فایل فعال شد...")
app.run_polling()
