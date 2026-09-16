import os
import re
import sys
import uuid
import glob
import html
import sqlite3
import threading
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

# ==================== تنظیمات مستقیم ربات ====================
TOKEN = "8924723567:AAH1ag1Ccc_t8DTy6u6ayw1kM8I9SWziuBY"
BOT_USERNAME = "@Instadlmusicbot"
SUPPORT_ID = "@saeed_mz77"
CHANNEL_ID = "@ainewss2026"
ADMIN_ID = 1773399042  # آیدی عددی شما
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

def extract_clean_song_name(title: str, description: str) -> str:
    """استخراج نام آهنگ از متن کپشن، توضیحات و عنوان ریلز"""
    full_text = f"{title or ''} {description or ''}"
    if not full_text.strip():
        return ""
    
    # الگوهای پیدا کردن نام موزیک در کپشن‌های اینستاگرام (مثلا: موزیک: فلان / آهنگ: فلان / Music: Name)
    match = re.search(r'(?:موزیک|آهنگ|اهنگ|music|song|track)\s*[:：\-]\s*([^\n\r#@]+)', full_text, re.IGNORECASE)
    if match:
        candidate = match.group(1)
    else:
        # اگر الگوی مستقیم نبود، خط اول کپشن یا عنوان را پاکسازی می‌کنیم
        lines = [line.strip() for line in full_text.split('\n') if line.strip()]
        candidate = lines[0] if lines else full_text

    # تمیزکاری نام
    candidate = re.sub(r'https?://\S+', '', candidate)
    candidate = re.sub(r'@[a-zA-Z0-9_.]+', '', candidate)
    candidate = re.sub(r'#[a-zA-Z0-9_]+', '', candidate)
    candidate = re.sub(r'(?i)(video by|reel by|audio by|original sound|original audio|remix|slowed|reverb|insta|clip|ریلز|پست)', '', candidate)
    candidate = re.sub(r'[\(\[\{].*?[\)\]\}]', '', candidate)
    candidate = re.sub(r'[^\w\s\d\u0600-\u06FF]', ' ', candidate)
    cleaned = ' '.join(candidate.split())
    return cleaned if len(cleaned) > 2 else ""

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
        await update.message.reply_text("<b>برای استفاده از ربات، ابتدا عضو کانال شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "🎧 <b>ربات استخراج و دانلود نسخه کامل موزیک</b>\n\n"
        "▫️ لینک ریلز را ارسال کنید تا حتی از روی کپشن و تگ‌های ریلز، آهنگ کامل و ۳۲۰ برای شما ارسال شود.\n"
        "▫️ اگر نسخه استودیویی رسمی هم نباشد، نسخه کامل ریمیکس یا صدای ریلز تحویل داده می‌شود.\n"
        "▫️ امکان دریافت ویدیو یا سرچ نام خواننده نیز فعال است."
    )
    kb = [
        [InlineKeyboardButton("👤 حساب کاربری و زیرمجموعه", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ خرید اشتراک نامحدود (VIP)", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID and ADMIN_ID != 0:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        msg = (
            "🔒 <b>اعتبار رایگان شما تمام شده است!</b>\n\n"
            "برای شارژ رایگان، لینک زیر را به دوستان بفرستید (هر دعوت = ۳ دانلود):\n"
            f"<code>{invite_link}</code>\n\n"
            "یا اشتراک VIP تهیه فرمایید."
        )
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    if is_link(text):
        if any(d in text for d in ["instagram.com", "youtube.com", "youtu.be"]):
            context.user_data['media_url'] = text
            credit_txt = "نامحدود (VIP)" if is_vip else f"{req_left} عدد"
            menu_text = (
                "🎯 <b>رسانه دریافت شد</b>\n"
                f"وضعیت اعتبار: <code>{credit_txt}</code>\n"
                "-------------------\n"
                "عملیات مورد نظر را انتخاب کنید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 دریافت آهنگ کامل (کپشن + شازام + وب)", callback_data="smart_extract_music")],
                [InlineKeyboardButton("🎥 دانلود ویدیوی کامل (MP4)", callback_data="get_full_video")],
                [InlineKeyboardButton("🎵 فقط صدای فایل (۳۲۰)", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("لطفاً لینک یوتیوب یا اینستاگرام ارسال کنید.")
        return

    # جستجوی متنی عنوان
    search_msg = await update.message.reply_text(f"🔍 در حال جستجوی «{html.escape(text)}»...", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{text}", download=False)
            tracks = res.get('entries', [])

        if not tracks:
            await search_msg.edit_text("❌ قطعه‌ای یافت نشد.")
            return

        context.user_data['tracks'] = {str(i): t for i, t in enumerate(tracks)}
        list_text = "🎵 <b>نتایج پیدا شد؛ قطعه را انتخاب کنید:</b>\n-------------------\n"
        buttons = []
        for i, t in enumerate(tracks):
            title = t.get('title', 'Unknown')[:35]
            dur = t.get('duration_string', '--:--')
            list_text += f"{i+1}. <b>{html.escape(title)}</b> [<code>{dur}</code>]\n"
            buttons.append([InlineKeyboardButton(f"{i+1}. {title}", callback_data=f"select_{i}")])

        await search_msg.edit_text(list_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await search_msg.edit_text(f"خطا در جستجو: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("عضویت تأیید شد! اکنون می‌توانید لینک یا ویدیو بفرستید.")
        else:
            await query.answer("هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "👑 <b>عضویت ویژه طلایی (VIP)</b>\n"
            "-------------------\n"
            "- دانلود نامحدود و بدون قفل\n"
            "- دریافت آهنگ کامل ۳۲۰ بدون هیچ معطلی\n\n"
            f"تعرفه: <b>{VIP_PRICE_TEXT}</b>\n"
            f"کارت:\n<code>{CARD_NUMBER}</code>\n\n"
            "فیش را همراه با شناسه زیر به پشتیبانی بفرستید:\n"
            f"شناسه: <code>{user_id}</code>"
        )
        kb = [[InlineKeyboardButton("💬 ارسال فیش به پشتیبانی", url=support_url)]]
        await query.message.reply_text(vip_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_panel":
        cursor.execute("SELECT requests_left, invites_count, is_vip FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        req_left, inv_count, is_vip = row if row else (0, 0, 0)
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"

        panel_text = (
            "👤 <b>پنل کاربری</b>\n"
            "-------------------\n"
            f"شناسه: <code>{user_id}</code>\n"
            f"وضعیت: <code>{'VIP' if is_vip else 'عادی'}</code>\n"
            f"اعتبار دانلود: <code>{req_left if not is_vip else 'نامحدود'}</code>\n"
            f"تعداد دعوت‌ها: <code>{inv_count} نفر</code>\n\n"
            f"🔗 لینک دعوت شما (هر نفر = ۳ دانلود رایگان):\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # موتور استخراج نسخه کامل موزیک
    if data == "smart_extract_music":
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما تمام شده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🔍 <b>در حال کاوش کپشن و آنالیز صوتی ریلز...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"raw_{uid}"
        sample_cut = f"cut_{uid}.mp3"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }

        detected_name = ""
        meta_title = ""
        meta_desc = ""

        try:
            # ۱. استخراج اطلاعات اولیه، کپشن و صدا
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                meta_title = info.get('title', '')
                meta_desc = info.get('description', '')
                track_tag = info.get('track', '')
                artist_tag = info.get('artist', '')

            raw_file = get_output_file(prefix)

            # ۲. بررسی تگ‌های رسمی ریلز
            if artist_tag and track_tag:
                detected_name = f"{artist_tag} {track_tag}"

            # ۳. اگر نبود، استخراج نام از داخل متن کپشن
            if not detected_name:
                caption_name = extract_clean_song_name(meta_title, meta_desc)
                if len(caption_name) > 3:
                    detected_name = caption_name

            # ۴. اگر در کپشن هم نبود، تست با Shazam
            if not detected_name and raw_file:
                os.system(f"ffmpeg -y -i {raw_file} -ss 00:00:04 -t 18 -acodec copy {sample_cut} >/dev/null 2>&1")
                test_audio = sample_cut if os.path.exists(sample_cut) else raw_file
                try:
                    res = await shazam.recognize(test_audio)
                    track = res.get('track') if res else None
                    if track:
                        stitle = track.get('title', '')
                        sartist = track.get('subtitle', '')
                        detected_name = f"{sartist} {stitle}".strip()
                except Exception:
                    pass

            download_done = False

            # ۵. جستجو و دانلود قطعی نسخه کامل چند دقیقه‌ای
            if detected_name:
                await status.edit_text(f"🔍 <b>نام اثر شناسایی شد:</b> <code>{html.escape(detected_name)}</code>\n⚡️ <i>در حال ارسال نسخه کامل ۳۲۰...</i>", parse_mode="HTML")
                download_done = await download_full_track(detected_name, query.message.chat_id, context, status)

            # ۶. اگر آهنگ رسمی نبود و نسخه جداگانه‌ای پیدا نشد، تحویل قطعی صدای خود ریلز با کیفیت ۳۲۰
            if not download_done and raw_file and os.path.exists(raw_file):
                await status.edit_text("⚡️ <i>نسخه کامل رسمی منتشر نشده بود؛ صدای باکیفیت و کامل ریلز ارسال می‌شود:</i>", parse_mode="HTML")
                clean_title = detected_name or extract_clean_song_name(meta_title, "") or "Reel Audio"
                with open(raw_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=clean_title,
                        performer="Original Reel Sound",
                        caption=f"🎵 موزیک ریلز با کیفیت ۳۲۰\n{BOT_USERNAME}",
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()

        except Exception as e:
            await status.edit_text(f"خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            clean_files(prefix)
            clean_files(sample_cut)
        return

    # دانلود ویدیو یا صدای مستقیم
    if data in ["get_full_video", "get_clip_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("سهمیه شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "get_full_video")
        status = await query.message.reply_text("در حال دانلود و ارسال فایل...", parse_mode="HTML")
        await process_direct_media(target_url, is_video, query.message.chat_id, context, status)
        return

    if data.startswith("select_"):
        idx = data.split("_")[1]
        track = context.user_data.get('tracks', {}).get(idx)
        if not track:
            await query.edit_message_text("این درخواست منقضی شده است.")
            return

        context.user_data['selected_track'] = track
        title = track.get('title', 'Music')
        dur = track.get('duration_string', '--:--')

        card = f"<b>{html.escape(title)}</b>\nمدت: <code>{dur}</code>\n\nفرمت دریافت را انتخاب کنید:"
        kb = [
            [InlineKeyboardButton("دریافت فایل صوتی (MP3)", callback_data="dl_audio_selected")],
            [InlineKeyboardButton("دریافت موزیک ویدیو (MP4)", callback_data="dl_vid_selected")]
        ]
        await query.edit_message_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    if data in ["dl_audio_selected", "dl_vid_selected"]:
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما تمام شده است.")
            return
        target_url = context.user_data.get('selected_track', {}).get('webpage_url')
        is_video = (data == "dl_vid_selected")
        status = await query.message.reply_text("در حال ارسال فایل...", parse_mode="HTML")
        await process_direct_media(target_url, is_video, query.message.chat_id, context, status)

async def download_full_track(query_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
    uid = uuid.uuid4().hex[:8]
    prefix = f"dl_{uid}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{prefix}.%(ext)s",
        'default_search': 'ytsearch1',
        'max_filesize': 50 * 1024 * 1024,
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
    }

    search_queries = [
        f"{query_text} full audio",
        f"{query_text} remix full",
        f"{query_text}"
    ]

    for sq in search_queries:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{sq}", download=True)
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]
                title = info.get('title', query_text)
                uploader = info.get('uploader', 'Artist')
                dur = info.get('duration', 0)

            out_file = get_output_file(prefix)
            if out_file:
                caption = f"🎵 <b>{html.escape(title)}</b>\n👤 <code>{html.escape(uploader)}</code>\n🔥 نسخه کامل استودیویی ۳۲۰\n{BOT_USERNAME}"
                with open(out_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        title=title,
                        performer=uploader,
                        duration=dur,
                        caption=caption,
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status_msg.delete()
                clean_files(prefix)
                return True
        except Exception:
            clean_files(prefix)
            continue

    clean_files(prefix)
    return False

async def process_direct_media(target_url, is_video, chat_id, context, status_msg):
    uid = uuid.uuid4().hex[:8]
    prefix = f"direct_{uid}"
    ydl_opts = {'outtmpl': f"{prefix}.%(ext)s", 'max_filesize': 50 * 1024 * 1024, 'quiet': True}
    if not is_video:
        ydl_opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]})
    else:
        ydl_opts.update({'format': 'best[ext=mp4]/best'})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            title = info.get('title', 'Media')
            uploader = info.get('uploader', 'Artist')
            dur = info.get('duration', 0)

        out_file = get_output_file(prefix)
        if not out_file: raise Exception("فایل آماده نشد.")

        caption = f"🎬 <b>{html.escape(title)}</b>\n{BOT_USERNAME}"
        with open(out_file, 'rb') as f:
            if not is_video:
                await context.bot.send_audio(chat_id=chat_id, audio=f, title=title, performer=uploader, duration=dur, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)

        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        clean_files(prefix)

# وب‌سرور سبک داخلی Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is healthy and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

app = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(300)
    .read_timeout(300)
    .write_timeout(300)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با موتور استخراج کپشن و دانلود نسخه کامل فعال شد...")
app.run_polling()
