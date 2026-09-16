import os
import re
import sys
import uuid
import glob
import html
import sqlite3
import threading
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote
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
# =========================================================================

# دیتابیس کاربران
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
    if not CHANNEL_ID:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

def is_link(text: str) -> bool:
    return bool(re.search(r'https?://[^\s]+', text))

def clean_filename_pattern(prefix: str):
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

def sanitize_query(raw_title: str) -> str:
    if not raw_title: return ""
    text = re.sub(r'https?://\S+', '', raw_title)
    text = re.sub(r'@[a-zA-Z0-9_.]+', '', text)
    text = re.sub(r'#[a-zA-Z0-9_]+', '', text)
    text = re.sub(r'(?i)(video by|reel by|audio by|original audio|remix|clip|insta|soundtrack|موزیک|اهنگ|آهنگ)', '', text)
    text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', text)
    text = re.sub(r'[^\w\s\d]', ' ', text)
    return ' '.join(text.split())

def search_google_for_mp3(query: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    search_terms = [f"{query} دانلود آهنگ 320", f"{query} mp3 320 download"]
    for term in search_terms:
        try:
            google_url = f"https://www.google.com/search?q={requests.utils.quote(term)}"
            resp = requests.get(google_url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')

            page_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('/url?q='):
                    clean_url = href.split('/url?q=')[1].split('&')[0]
                    clean_url = unquote(clean_url)
                    if "google.com" not in clean_url and clean_url.startswith('http'):
                        page_links.append(clean_url)
                elif href.startswith('http') and "google.com" not in href:
                    page_links.append(href)

            for page in page_links[:3]:
                try:
                    p_resp = requests.get(page, headers=headers, timeout=8)
                    p_soup = BeautifulSoup(p_resp.text, 'html.parser')
                    mp3_links = [l['href'] for l in p_soup.find_all('a', href=True) if l['href'].endswith('.mp3')]
                    for mp3 in mp3_links:
                        if '320' in mp3:
                            return mp3
                    if mp3_links:
                        return mp3_links[0]
                except Exception:
                    continue
        except Exception:
            continue
    return None

async def download_direct_mp3_url(mp3_url: str, output_path: str) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(mp3_url, headers=headers, stream=True, timeout=25)
        if r.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk: f.write(chunk)
            return True
    except Exception:
        pass
    return False

# ==================== هندلرهای پیام و فرامین تلگرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    referrer_id = int(args[0]) if (args and args[0].isdigit()) else None
    get_or_create_user(user_id, referrer_id)

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 ورود و عضویت در کانال", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text(
            "<b>برای استفاده از ربات، ابتدا عضو کانال ما شوید:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    welcome_text = (
        "<b>به ربات هوشمند دانلود و استخراج کامل موزیک خوش آمدید</b>\n\n"
        "<b>امکانات ویژه:</b>\n"
        "- ارسال لینک ریلز اینستاگرام یا یوتیوب: استخراج نسخه کامل استودیویی ۳۲۰ با شازام و سرچ گوگل\n"
        "- دانلود ویدیو: دریافت فایل ویدیویی کامل با بالاترین کیفیت\n"
        "- ارسال مستقیم ویدیو یا ویس: تشخیص آهنگ از روی فایل ارسالی\n"
        "- جستجوی متنی: ارسال نام آهنگ یا خواننده\n\n"
        "<i>لینک ریلز یا نام آهنگ خود را بفرستید:</i>"
    )
    kb = [
        [InlineKeyboardButton("حساب کاربری و زیرمجموعه", callback_data="user_panel")],
        [InlineKeyboardButton("خرید اشتراک نامحدود (VIP)", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID and ADMIN_ID != 0:
        kb.append([InlineKeyboardButton("پنل مدیریت", callback_data="admin_panel")])

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("عضویت در کانال", url=channel_link)],
            [InlineKeyboardButton("بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text("لطفاً ابتدا عضو کانال شوید.", reply_markup=InlineKeyboardMarkup(kb))
        return

    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    req_left, is_vip = (u[0], u[1]) if u else (0, 0)

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = (
            "<b>اعتبار رایگان شما تمام شده است!</b>\n\n"
            "برای ادامه:\n"
            "۱. دوستان خود را دعوت کنید (هر دعوت = ۳ دانلود رایگان):\n"
            f"<code>{invite_link}</code>\n\n"
            "۲. یا اشتراک نامحدود VIP تهیه کنید."
        )
        kb = [[InlineKeyboardButton("خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    if is_link(text):
        if any(d in text for d in ["instagram.com", "youtube.com", "youtu.be"]):
            context.user_data['media_url'] = text
            credit_txt = "نامحدود (VIP)" if is_vip else f"{req_left} عدد"
            menu_text = (
                "<b>رسانه شناسایی شد</b>\n"
                f"وضعیت اعتبار: <code>{credit_txt}</code>\n"
                "------------------\n"
                "گزینه مدنظر خود را انتخاب کنید:"
            )
            buttons = [
                [InlineKeyboardButton("پیدا کردن و دانلود نسخه کامل ۳۲۰ آهنگ", callback_data="get_full_music")],
                [InlineKeyboardButton("دانلود ویدیوی کامل (MP4)", callback_data="get_full_video")],
                [InlineKeyboardButton("استخراج صدای کلیپ", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("لطفاً لینک یوتیوب یا اینستاگرام ارسال کنید.")
        return

    search_msg = await update.message.reply_text(f"در حال جستجوی «{html.escape(text)}»...", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{text}", download=False)
            tracks = res.get('entries', [])

        if not tracks:
            await search_msg.edit_text("قطعه‌ای یافت نشد.")
            return

        context.user_data['tracks'] = {str(i): t for i, t in enumerate(tracks)}
        list_text = "<b>نتایج یافت‌شده؛ موزیک مدنظر را انتخاب کنید:</b>\n------------------\n"
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
            await query.message.reply_text("عضویت تأیید شد! اکنون می‌توانید لینک یا ویدیو ارسال کنید.")
        else:
            await query.answer("هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "<b>عضویت ویژه طلایی (VIP)</b>\n"
            "------------------\n"
            "- دانلود نامحدود و بدون قفل\n"
            "- بالاترین کیفیت صدای ۳۲۰ بدون معطلی\n"
            "- معاف از عضویت در کانال‌های اسپانسر\n\n"
            f"تعرفه: <b>{VIP_PRICE_TEXT}</b>\n"
            f"کارت واریز:\n<code>{CARD_NUMBER}</code>\n\n"
            "تصویر فیش را به همراه شناسه عددی خود برای پشتیبانی بفرستید:\n"
            f"شناسه شما: <code>{user_id}</code>"
        )
        kb = [[InlineKeyboardButton("ارتباط با پشتیبانی و ارسال فیش", url=support_url)]]
        await query.message.reply_text(vip_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_panel":
        cursor.execute("SELECT requests_left, invites_count, is_vip FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        req_left, inv_count, is_vip = row if row else (0, 0, 0)
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"

        panel_text = (
            "<b>پنل کاربری</b>\n"
            "------------------\n"
            f"شناسه: <code>{user_id}</code>\n"
            f"وضعیت: <code>{'VIP' if is_vip else 'عادی'}</code>\n"
            f"اعتبار دانلود باقی‌مانده: <code>{req_left if not is_vip else 'نامحدود'}</code>\n"
            f"تعداد زیرمجموعه‌ها: <code>{inv_count} نفر</code>\n\n"
            f"لینک دعوت شما (هر دعوت = ۳ دانلود هدیه):\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # پردازش اصلی دریافت آهنگ کامل
    if data == "get_full_music":
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما به اتمام رسیده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("در حال کاوش فرکانسی و جستجوی اثر...", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"scan_{uid}"
        sample_cut = f"cut_{uid}.mp3"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }

        detected_song = None
        raw_meta_title = ""

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                raw_meta_title = info.get('title', '')
                track_tag = info.get('track', '')
                artist_tag = info.get('artist', '')

            raw_file = get_output_file(prefix)

            # ۱. شازام
            if raw_file:
                os.system(f"ffmpeg -y -i {raw_file} -ss 00:00:04 -t 20 -acodec copy {sample_cut} >/dev/null 2>&1")
                test_audio = sample_cut if os.path.exists(sample_cut) else raw_file
                try:
                    res = await shazam.recognize(test_audio)
                    track = res.get('track') if res else None
                    if track:
                        stitle = track.get('title', '')
                        sartist = track.get('subtitle', '')
                        detected_song = f"{sartist} {stitle}".strip()
                except Exception:
                    pass

            # ۲. متادیتای ریلز
            if not detected_song:
                if artist_tag and track_tag:
                    detected_song = f"{artist_tag} {track_tag}"
                else:
                    cleaned = sanitize_query(raw_meta_title)
                    if len(cleaned) > 2:
                        detected_song = cleaned

            download_ok = False

            # ۳. استخراج ۳۲۰ از یوتیوب
            if detected_song:
                await status.edit_text(f"نام قطعه: <code>{html.escape(detected_song)}</code>\nدر حال دریافت نسخه استودیویی ۳۲۰...", parse_mode="HTML")
                download_ok = await fetch_and_send_full_mp3(detected_song, query.message.chat_id, context, status)

            # ۴. سرچ مستقیم در گوگل
            if not download_ok and detected_song:
                await status.edit_text(f"در حال جستجو در صفحات گوگل: <code>{html.escape(detected_song)}</code>...", parse_mode="HTML")
                google_mp3_url = search_google_for_mp3(detected_song)
                if google_mp3_url:
                    google_file = f"google_{uid}.mp3"
                    if await download_direct_mp3_url(google_mp3_url, google_file):
                        caption = (
                            f"<b>{html.escape(detected_song)}</b>\n"
                            f"یافت‌شده از موتور جستجوی گوگل (کیفیت ۳۲۰)\n"
                            f"{BOT_USERNAME}"
                        )
                        with open(google_file, 'rb') as f:
                            await context.bot.send_audio(
                                chat_id=query.message.chat_id,
                                audio=f,
                                title=detected_song,
                                performer="Google Search Master",
                                caption=caption,
                                parse_mode="HTML",
                                read_timeout=300,
                                write_timeout=300
                            )
                        download_ok = True
                        await status.delete()
                        clean_filename_pattern(f"google_{uid}")

            # ۵. در صورت نیافتن، ارسال صدای اصلی کلیپ با ۳۲۰
            if not download_ok and raw_file and os.path.exists(raw_file):
                await status.edit_text("نسخه کامل رسمی منتشر نشده؛ ارسال صدای باکیفیت خود کلیپ:", parse_mode="HTML")
                with open(raw_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=sanitize_query(raw_meta_title) or "Original Audio",
                        performer="Direct Reel Sound",
                        caption=f"صدای اورجینال ریلز (کیفیت ۳۲۰)\n{BOT_USERNAME}",
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()

        except Exception as e:
            await status.edit_text(f"خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            clean_filename_pattern(prefix)
            clean_filename_pattern(sample_cut)
        return

    # دریافت فیلم کامل یا صدای ساده کلیپ
    if data in ["get_full_video", "get_clip_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("سهمیه شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "get_full_video")
        status = await query.message.reply_text("در حال پردازش و ارسال فایل...", parse_mode="HTML")
        await process_url_direct(target_url, is_video, query.message.chat_id, context, status)
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
            await query.message.reply_text("اعتبار شما به پایان رسیده است.")
            return
        target_url = context.user_data.get('selected_track', {}).get('webpage_url')
        is_video = (data == "dl_vid_selected")
        status = await query.message.reply_text("در حال ارسال فایل...", parse_mode="HTML")
        await process_url_direct(target_url, is_video, query.message.chat_id, context, status)

async def fetch_and_send_full_mp3(query_str: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
    uid = uuid.uuid4().hex[:8]
    prefix = f"track_{uid}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{prefix}.%(ext)s",
        'default_search': 'ytsearch1',
        'max_filesize': 50 * 1024 * 1024,
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
    }
    search_queries = [f"{query_str} audio full", f"{query_str} official audio", f"{query_str}"]

    for sq in search_queries:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{sq}", download=True)
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]
                title = info.get('title', query_str)
                uploader = info.get('uploader', 'Artist')
                dur = info.get('duration', 0)

            actual_file = get_output_file(prefix)
            if actual_file:
                caption = (
                    f"<b>{html.escape(title)}</b>\n"
                    f"هنرمند: <code>{html.escape(uploader)}</code>\n"
                    f"نسخه کامل استودیویی ۳۲۰\n"
                    f"{BOT_USERNAME}"
                )
                with open(actual_file, 'rb') as f:
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
                clean_filename_pattern(prefix)
                return True
        except Exception:
            clean_filename_pattern(prefix)
            continue

    clean_filename_pattern(prefix)
    return False

async def process_url_direct(target_url, is_video, chat_id, context, status_msg):
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

        actual_file = get_output_file(prefix)
        if not actual_file: raise Exception("فایل آماده نشد.")

        caption = f"<b>{html.escape(title)}</b>\n{BOT_USERNAME}"
        with open(actual_file, 'rb') as f:
            if not is_video:
                await context.bot.send_audio(chat_id=chat_id, audio=f, title=title, performer=uploader, duration=dur, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)

        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        clean_filename_pattern(prefix)

# وب‌سرور سبک برای هماهنگی با پورت Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is healthy and online!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# ساخت اپلیکیشن
if not TOKEN:
    print("خطای بحرانی: اجرای ربات به دلیل نبود BOT_TOKEN متوقف شد.", file=sys.stderr)
    sys.exit(1)

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

print("ربات با موتور شازام، سرچ گوگل و وب‌سرور داخلی فعال شد...")
app.run_polling()
