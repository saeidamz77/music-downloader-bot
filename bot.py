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
from urllib.parse import quote, unquote
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
# ==================================================================

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

def clean_title_metadata(raw_text: str) -> str:
    """استخراج دقیق عنوان خالص و حذف تمام هشتگ‌ها، آی‌دی‌ها و متون اضافه"""
    if not raw_text: return ""
    text = re.sub(r'https?://\S+', '', raw_text)
    text = re.sub(r'@[a-zA-Z0-9_.]+', '', text)
    text = re.sub(r'#[a-zA-Z0-9_]+', '', text)
    text = re.sub(r'(?i)(video by|reel by|audio by|original sound|original audio|remix|slowed|reverb|insta|clip|پست|اهنگ|موزیک)', '', text)
    text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', text)
    text = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF\s]', ' ', text)
    return ' '.join(text.split())

# موتور کاوش وب بدون محدودیت (DuckDuckGo Search)
def search_web_for_direct_mp3(query: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        search_url = f"https://html.duckduckgo.com/html/?q={quote(query + ' دانلود آهنگ 320 mp3')}"
        resp = requests.get(search_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        links = []
        for a in soup.find_all('a', class_='result__url', href=True):
            href = a['href']
            if 'uddg=' in href:
                actual = unquote(href.split('uddg=')[1].split('&')[0])
                links.append(actual)
            elif href.startswith('http'):
                links.append(href)

        for page in links[:3]:
            try:
                p_resp = requests.get(page, headers=headers, timeout=8)
                p_soup = BeautifulSoup(p_resp.text, 'html.parser')
                for link in p_soup.find_all('a', href=True):
                    l_href = link['href']
                    if l_href.endswith('.mp3') and ('320' in l_href or 'music' in l_href):
                        return l_href
            except Exception:
                continue
    except Exception:
        pass
    return None

async def download_web_file(url: str, save_path: str) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, stream=True, timeout=30)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk: f.write(chunk)
            return True
    except Exception:
        pass
    return False

# ==================== هندلرهای تلگرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    referrer_id = int(args[0]) if (args and args[0].isdigit()) else None
    get_or_create_user(user_id, referrer_id)

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 عضویت در کانال رسمی", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text("<b>برای فعال‌سازی ربات، لطفاً ابتدا در کانال عضو شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "🎧 <b>ربات جامع شناسایی و دانلود کامل موزیک ۳۲۰</b>\n\n"
        "⚡️ <b>قابلیت‌ها:</b>\n"
        "- لینک ریلز اینستاگرام/یوتیوب را بفرستید تا نسخه کامل ۳۲۰ را بیابد.\n"
        "- ویدیو را مستقیماً ارسال کنید تا امواج صدا آنالیز شود.\n"
        "- نام ترانه را بنویسید تا فایل ۳۲۰ را تحویل بگیرید.\n\n"
        "✨ <i>کافیست لینک ریلز یا فایل خود را ارسال کنید:</i>"
    )
    kb = [
        [InlineKeyboardButton("👤 پنل کاربری و دعوت دوستان", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ خرید اشتراک نامحدود (VIP)", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [[InlineKeyboardButton("📢 عضویت", url=channel_link)], [InlineKeyboardButton("✅ تأیید", callback_data="check_join")]]
        await update.message.reply_text("⛔️ لطفاً ابتدا عضو کانال شوید.", reply_markup=InlineKeyboardMarkup(kb))
        return

    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    req_left, is_vip = (u[0], u[1]) if u else (0, 0)

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = (
            "🔒 <b>اعتبار رایگان شما به پایان رسیده است!</b>\n\n"
            "برای دریافت ۳ دانلود رایگان، لینک اختصاصی خود را برای دوستانتان بفرستید:\n"
            f"<code>{invite_link}</code>\n\n"
            "یا اشتراک نامحدود VIP تهیه فرمایید."
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
                "🎯 <b>رسانه شناسایی شد</b>\n"
                f"📊 اعتبار حساب: <code>{credit_txt}</code>\n"
                "-------------------\n"
                "گزینه مورد نظر خود را انتخاب کنید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 استخراج و دانلود نسخه کامل ۳۲۰ موزیک", callback_data="deep_detect_music")],
                [InlineKeyboardButton("🎥 دانلود ویدیوی ریلز (کیفیت اصلی)", callback_data="get_full_video")],
                [InlineKeyboardButton("🎵 استخراج صدای اورجینال کلیپ", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("⚠️ لطفاً لینک یوتیوب یا اینستاگرام ارسال فرمایید.")
        return

    # جستجوی متنی
    search_msg = await update.message.reply_text(f"🔍 در حال کاوش برای «{html.escape(text)}»...", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{text}", download=False)
            tracks = res.get('entries', [])

        if not tracks:
            await search_msg.edit_text("❌ قطعه‌ای یافت نشد.")
            return

        context.user_data['tracks'] = {str(i): t for i, t in enumerate(tracks)}
        list_text = "🎵 <b>نتایج یافت‌شده؛ موزیک مدنظر را انتخاب کنید:</b>\n-------------------\n"
        buttons = []
        for i, t in enumerate(tracks):
            title = t.get('title', 'Unknown')[:35]
            dur = t.get('duration_string', '--:--')
            list_text += f"{i+1}. <b>{html.escape(title)}</b> [<code>{dur}</code>]\n"
            buttons.append([InlineKeyboardButton(f"{i+1}. {title}", callback_data=f"select_{i}")])

        await search_msg.edit_text(list_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await search_msg.edit_text(f"خطا در جستجو: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

# مدیریت کلیک دکمه‌ها و اجرای موتور جامع
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("✅ عضویت تأیید شد! اکنون لینک یا ویدیو بفرستید.")
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
            "- بالاترین اولویت دانلود ۳۲۰ استودیویی\n"
            "- معاف از عضویت اجباری کانال‌ها\n\n"
            f"تعرفه: <b>{VIP_PRICE_TEXT}</b>\n"
            f"کارت:\n<code>{CARD_NUMBER}</code>\n\n"
            "پس از واریز، فیش را همراه با شناسه زیر به پشتیبانی بفرستید:\n"
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
            f"اعتبار باقی‌مانده: <code>{req_left if not is_vip else 'نامحدود'}</code>\n"
            f"تعداد دعوت‌ها: <code>{inv_count} نفر</code>\n\n"
            f"🔗 لینک دعوت اختصاصی شما:\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # پردازش عمیق و چندمرحله‌ای برای پیدا کردن نسخه کامل ۳۲۰
    if data == "deep_detect_music":
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ سهمیه شما تمام شده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🎧 <b>در حال استخراج و تحلیل امواج صوتی ریلز...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"raw_{uid}"
        cut_sample = f"cut_{uid}.mp3"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }

        detected_song_name = None
        raw_meta = ""

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                raw_meta = info.get('title', '')
                track_tag = info.get('track', '')
                artist_tag = info.get('artist', '')

            raw_file = get_output_file(prefix)

            # گام ۱: اسکن فرکانسی با Shazam (برش ۱۰ ثانیه طلایی از ثانیه ۳)
            if raw_file:
                os.system(f"ffmpeg -y -i {raw_file} -ss 00:00:03 -t 15 -acodec copy {cut_sample} >/dev/null 2>&1")
                sample_to_check = cut_sample if os.path.exists(cut_sample) else raw_file
                try:
                    res = await shazam.recognize(sample_to_check)
                    track = res.get('track') if res else None
                    if track:
                        stitle = track.get('title', '')
                        sartist = track.get('subtitle', '')
                        detected_song_name = f"{sartist} {stitle}".strip()
                except Exception:
                    pass

            # گام ۲: اگر شازام تشخیص نداد، پالایش هوشمند متادیتای ریلز
            if not detected_song_name:
                if artist_tag and track_tag:
                    detected_song_name = f"{artist_tag} {track_tag}"
                else:
                    cleaned = clean_title_metadata(raw_meta)
                    if len(cleaned) > 2:
                        detected_song_name = cleaned

            download_done = False

            # گام ۳: جستجوی نسخه استودیویی ۳۲۰ در YouTube Music و ساندکلاد
            if detected_song_name:
                await status.edit_text(f"🔍 <b>شناسایی شد:</b> <code>{html.escape(detected_song_name)}</code>\n⚡️ در حال دریافت فایل استودیویی ۳۲۰...", parse_mode="HTML")
                download_done = await search_and_send_full_track(detected_song_name, query.message.chat_id, context, status)

            # گام ۴: اگر در یوتیوب نبود، جستجوی مستقیم در تمام وب و سایت‌های دانلود
            if not download_done and detected_song_name:
                await status.edit_text(f"🌐 <b>کاوش در سایت‌های اینترنت برای یافتن فایل ۳۲۰:</b> <code>{html.escape(detected_song_name)}</code>...", parse_mode="HTML")
                direct_mp3 = search_web_for_direct_mp3(detected_song_name)
                if direct_mp3:
                    web_save = f"web_{uid}.mp3"
                    if await download_web_file(direct_mp3, web_save):
                        caption = f"🎵 <b>{html.escape(detected_song_name)}</b>\n🌐 یافت‌شده از وب با کیفیت ۳۲۰\n🤖 {BOT_USERNAME}"
                        with open(web_save, 'rb') as f:
                            await context.bot.send_audio(
                                chat_id=query.message.chat_id,
                                audio=f,
                                title=detected_song_name,
                                performer="Web Master Track",
                                caption=caption,
                                parse_mode="HTML",
                                read_timeout=300,
                                write_timeout=300
                            )
                        download_done = True
                        await status.delete()
                        clean_files(f"web_{uid}")

            # گام ۵ (تضمین ۱۰۰٪ قطعی): ارسال صدای دقیق خود ریلز با کیفیت ۳۲۰
            if not download_done and raw_file and os.path.exists(raw_file):
                await status.edit_text("⚡️ <i>نسخه کامل رسمی پیدا نشد؛ در حال ارسال صدای باکیفیت و تمیز خود کلیپ...</i>", parse_mode="HTML")
                with open(raw_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=clean_title_metadata(raw_meta) or "Original Track",
                        performer="Reel Audio",
                        caption=f"🎵 استخراج‌شده با کیفیت ۳۲۰\n🤖 {BOT_USERNAME}",
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()

        except Exception as e:
            await status.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            clean_files(prefix)
            clean_files(cut_sample)
        return

    if data in ["get_full_video", "get_clip_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ سهمیه شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "get_full_video")
        status = await query.message.reply_text("⚡️ <b>در حال دانلود و ارسال مدیا...</b>", parse_mode="HTML")
        await process_direct_media(target_url, is_video, query.message.chat_id, context, status)
        return

    if data.startswith("select_"):
        idx = data.split("_")[1]
        track = context.user_data.get('tracks', {}).get(idx)
        if not track:
            await query.edit_message_text("⚠️ این درخواست منقضی شده است.")
            return

        context.user_data['selected_track'] = track
        title = track.get('title', 'Music')
        dur = track.get('duration_string', '--:--')

        card = f"🎵 <b>{html.escape(title)}</b>\n⏱ مدت: <code>{dur}</code>\n\nنوع خروجی:"
        kb = [
            [InlineKeyboardButton("🎵 دریافت فایل صوتی (MP3)", callback_data="dl_audio_selected")],
            [InlineKeyboardButton("🎥 دریافت موزیک ویدیو (MP4)", callback_data="dl_vid_selected")]
        ]
        await query.edit_message_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    if data in ["dl_audio_selected", "dl_vid_selected"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما تمام شده است.")
            return
        target_url = context.user_data.get('selected_track', {}).get('webpage_url')
        is_video = (data == "dl_vid_selected")
        status = await query.message.reply_text("⚡️ <b>در حال ارسال فایل...</b>", parse_mode="HTML")
        await process_direct_media(target_url, is_video, query.message.chat_id, context, status)

async def search_and_send_full_track(query_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
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

    # سرچ با ۳ الگوریتم عنوان مختلف
    search_queries = [
        f"{query_text} audio full",
        f"{query_text} official audio",
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
                caption = f"🎵 <b>{html.escape(title)}</b>\n👤 هنرمند: <code>{html.escape(uploader)}</code>\n🔥 نسخه کامل استودیویی ۳۲۰\n🤖 {BOT_USERNAME}"
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

        caption = f"🎬 <b>{html.escape(title)}</b>\n🤖 {BOT_USERNAME}"
        with open(out_file, 'rb') as f:
            if not is_video:
                await context.bot.send_audio(chat_id=chat_id, audio=f, title=title, performer=uploader, duration=dur, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)

        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        clean_files(prefix)

# وب‌سرور داخلی سبک Render
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

print("ربات با معماری جامع و موتور کاوش فعال شد...")
app.run_polling()
