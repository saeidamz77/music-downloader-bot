import os
import re
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

# ==================== تنظیمات سرور و مدیریت ====================
TOKEN = os.environ.get("8924723567:AAH1ag1Ccc_t8DTy6u6ayw1kM8I9SWziuBY", "توکن_ربات")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Instadlmusicbot")
SUPPORT_ID = os.environ.get("SUPPORT_ID", "@saeed_mz77")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ainewss2026")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1773399042"))

VIP_PRICE_TEXT = "ماهانه 350 هزار تومان | دائمی 500 هزار تومان"
CARD_NUMBER = "6219-8619-4353-1938 به نام سعید محمدزاده"
# ==============================================================

# راه‌اندازی دیتابیس
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

def clean_filename_pattern(prefix: str):
    matches = glob.glob(f"{prefix}*")
    for f in matches:
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
    """پاکسازی فوق‌پیشرفته متادیتاهای نامربوط ریلز"""
    if not raw_title: return ""
    text = re.sub(r'https?://\S+', '', raw_title)
    text = re.sub(r'@[a-zA-Z0-9_.]+', '', text)
    text = re.sub(r'#[a-zA-Z0-9_]+', '', text)
    text = re.sub(r'(?i)(video by|reel by|audio by|original audio|remix|clip|insta|soundtrack|موزیک|اهنگ|آهنگ)', '', text)
    text = re.sub(r'[\(\[\{].*?[\)\]\}]', '', text)
    text = re.sub(r'[^\w\s\d]', ' ', text)
    return ' '.join(text.split())

# رابط استارت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    referrer_id = int(args[0]) if (args and args[0].isdigit()) else None
    get_or_create_user(user_id, referrer_id)

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 ورود و عضویت در کانال", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت و فعال‌سازی", callback_data="check_join")]
        ]
        await update.message.reply_text(
            "💎 <b>برای استفاده از ربات، ابتدا عضو کانال ما شوید:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    welcome_text = (
        "👑 <b>به دستیار هوشمند دانلود و رهگیری موزیک خوش آمدید</b>\n\n"
        "🌟 <b>امکانات فوق‌پیشرفته ربات:</b>\n"
        "├ 🎵 <b>ارسال لینک ریلز اینستا/یوتیوب:</b> استخراج قطعی نسخه کامل و استودیویی ۳۲۰ آهنگ\n"
        "├ 🎬 <b>دانلود ویدیو:</b> دریافت فایل ویدیویی اصلی ریلز با کیفیت Full HD\n"
        "├ 🎙 <b>ارسال مستقیم ویدیو یا وویس:</b> گوش دادن هوشمند و تحویل فایل آهنگ\n"
        "└ 🔍 <b>جستجوی هوشمند متنی:</b> نام خواننده یا آهنگ را بفرستید\n\n"
        "✨ <i>لینک ریلز یا ویدیوی خود را ارسال کنید تا شروع کنیم!</i>"
    )
    kb = [
        [InlineKeyboardButton("👤 حساب کاربری و زیرمجموعه", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ ارتقا به حساب طلایی (VIP)", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت سرور", callback_data="admin_panel")])

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# پیام متنی یا لینک
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 عضویت در کانال", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text("⛔️ لطفاً ابتدا عضو کانال شوید.", reply_markup=InlineKeyboardMarkup(kb))
        return

    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    req_left, is_vip = (u[0], u[1]) if u else (0, 0)

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = (
            "🔒 <b>سهمیه رایگان شما به اتمام رسید!</b>\n\n"
            "برای ادامه می‌توانید یکی از دو راه زیر را انتخاب کنید:\n\n"
            "۱. <b>دعوت از دوستان (رایگان):</b>\n"
            f"🔗 <code>{invite_link}</code>\n"
            "<i>(به ازای هر نفر ۳ دانلود رایگان هدیه بگیرید)</i>\n\n"
            "۲. <b>خرید اشتراک VIP و دانلود نامحدود</b>"
        )
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک نامحدود", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    if is_link(text):
        if any(d in text for d in ["instagram.com", "youtube.com", "youtu.be"]):
            context.user_data['media_url'] = text
            credit_txt = "💎 نامحدود (VIP)" if is_vip else f"⚡️ {req_left} عدد"
            menu_text = (
                "🎯 <b>رسانه با موفقیت شناسایی شد</b>\n"
                f"📊 وضعیت اعتبار شما: <code>{credit_txt}</code>\n"
                "──────────────────\n"
                "لطفاً عملیات مورد نظر خود را انتخاب فرمایید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 پیدا کردن و ارسال نسخه کامل ۳۲۰ آهنگ", callback_data="get_full_music")],
                [InlineKeyboardButton("🎥 دانلود ویدیوی کامل ریلز (MP4)", callback_data="get_full_video")],
                [InlineKeyboardButton("🎵 استخراج صدای اورجینال کلیپ", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("⚠️ لطفاً فقط لینک یوتیوب یا اینستاگرام ارسال فرمایید.")
        return

    # سرچ متنی
    search_msg = await update.message.reply_text(f"🔍 <b>در حال جستجوی قطعه «{html.escape(text)}» در دیتابیس جهانی...</b>", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{text}", download=False)
            tracks = res.get('entries', [])

        if not tracks:
            await search_msg.edit_text("❌ نتیجه‌ای با این عنوان یافت نشد.")
            return

        context.user_data['tracks'] = {str(i): t for i, t in enumerate(tracks)}
        list_text = "🎵 <b>نتایج برتر پیدا شد؛ قطعه مدنظر را لمس کنید:</b>\n──────────────────\n"
        buttons = []
        for i, t in enumerate(tracks):
            title = t.get('title', 'Unknown')[:35]
            dur = t.get('duration_string', '--:--')
            list_text += f"▫️ {i+1}. <b>{html.escape(title)}</b> [<code>{dur}</code>]\n"
            buttons.append([InlineKeyboardButton(f"🎶 {i+1}. {title}", callback_data=f"select_{i}")])

        await search_msg.edit_text(list_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await search_msg.edit_text(f"⚠️ خطا در جستجو: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

# دریافت فایل ویدیویی مستقیم تلگرام
async def handle_direct_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_membership(user_id, context):
        await update.message.reply_text("⛔️ لطفاً ابتدا عضو کانال شوید.")
        return

    if not consume_credit(user_id):
        await update.message.reply_text("🔒 اعتبار دانلود شما تمام شده است.")
        return

    status = await update.message.reply_text("🎧 <b>در حال پردازش فرکانسی و گوش دادن به اثر صوتی...</b>", parse_mode="HTML")
    media = update.message.video or update.message.video_note or update.message.document
    uid = uuid.uuid4().hex[:6]
    input_file = f"in_{uid}.mp4"
    audio_sample = f"sample_{uid}.mp3"

    try:
        file_obj = await context.bot.get_file(media.file_id)
        await file_obj.download_to_drive(input_file)

        # استخراج قطعه ۳۰ ثانیه میانی برای شازام با کیفیت بالا
        os.system(f"ffmpeg -y -i {input_file} -vn -ss 00:00:03 -t 25 -acodec libmp3lame -q:a 2 {audio_sample} >/dev/null 2>&1")

        match = await shazam.recognize(audio_sample)
        track = match.get('track') if match else None

        if track:
            title = track.get('title', '')
            artist = track.get('subtitle', '')
            query_str = f"{artist} {title}".strip()

            await status.edit_text(
                f"✅ <b>قطعه با هوش مصنوعی پیدا شد!</b>\n\n"
                f"🎵 آهنگ: <b>{html.escape(title)}</b>\n"
                f"👤 خواننده: <b>{html.escape(artist)}</b>\n\n"
                f"⚡️ <i>در حال ارسال نسخه ۳۲۰ کامل و اورجینال...</i>",
                parse_mode="HTML"
            )
            await fetch_and_send_full_mp3(query_str, update.effective_chat.id, context, status)
        else:
            # ارسال صدای استخراج‌شده
            full_audio = f"full_raw_{uid}.mp3"
            os.system(f"ffmpeg -y -i {input_file} -vn -acodec libmp3lame -b:a 320k {full_audio} >/dev/null 2>&1")
            await status.edit_text("⚡️ <i>نسخه استودیویی منتشر نشده؛ در حال ارسال صدای باکیفیت خود فایل...</i>", parse_mode="HTML")
            with open(full_audio, 'rb') as f:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f,
                    title="Extracted Master Track",
                    performer="Direct Extraction",
                    caption=f"🎵 استخراج‌شده با کیفیت ۳۲۰\n🤖 {BOT_USERNAME}",
                    parse_mode="HTML",
                    read_timeout=300,
                    write_timeout=300
                )
            await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        clean_filename_pattern(f"in_{uid}")
        clean_filename_pattern(f"sample_{uid}")
        clean_filename_pattern(f"full_raw_{uid}")

# دکمه‌های شیشه‌ای
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("✅ عضویت با موفقیت تأیید شد! اکنون لینک یا ویدیو را ارسال نمایید.")
        else:
            await query.answer("❌ هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "👑 <b>عضویت ویژه طلایی (VIP Membership)</b>\n"
            "──────────────────\n"
            "✨ <b>مزایای سطح طلایی:</b>\n"
            "├ 🚀 سرعت حداکثری دانلود بدون کوچک‌ترین معطلی\n"
            "├ 🎵 دانلود نامحدود نسخه‌های کامل استودیویی ۳۲۰\n"
            "├ 🎥 دانلود نامحدود تمام ریلزها و ویدیوها\n"
            "└ 🔓 بدون نیاز به عضویت در کانال‌های اسپانسر\n\n"
            f"💰 تعرفه عضویت: <b>{VIP_PRICE_TEXT}</b>\n"
            f"💳 شماره کارت جهت واریز:\n<code>{CARD_NUMBER}</code>\n\n"
            "لطفاً پس از واریز، فیش را به همراه شناسه زیر ارسال فرمایید:\n"
            f"🆔 شناسه کاربری شما: <code>{user_id}</code>"
        )
        kb = [[InlineKeyboardButton("💬 ارسال فیش و فعال‌سازی فوری", url=support_url)]]
        await query.message.reply_text(vip_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_panel":
        cursor.execute("SELECT requests_left, invites_count, is_vip FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        req_left, inv_count, is_vip = row if row else (0, 0, 0)
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"

        panel_text = (
            "👤 <b>میز کاربری و باشگاه مشتریان</b>\n"
            "──────────────────\n"
            f"🆔 شناسه اکانت: <code>{user_id}</code>\n"
            f"⭐️ سطح کاربری: <code>{'کاربر طلایی (VIP)' if is_vip else 'کاربر معمولی'}</code>\n"
            f"⚡️ اعتبار باقی‌مانده: <code>{req_left if not is_vip else 'نامحدود'}</code>\n"
            f"👥 تعداد دعوت‌های موفق: <code>{inv_count} نفر</code>\n\n"
            f"🔗 <b>لینک اختصاصی دعوت شما (۳ دانلود رایگان به ازای هر دعوت):</b>\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # پردازش اصلی: استخراج آهنگ کامل ۳۲۰
    if data == "get_full_music":
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار دانلود شما به پایان رسیده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🎧 <b>در حال کاوش فرکانسی و تحلیل اثر انگشت صوتی...</b>", parse_mode="HTML")

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

            # مرحله ۱: برش قطعه میانی برای تشخیص دقیق شازام
            if raw_file:
                os.system(f"ffmpeg -y -i {raw_file} -ss 00:00:05 -t 22 -acodec copy {sample_cut} >/dev/null 2>&1")
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

            # مرحله ۲: در صورت عدم تشخیص، استفاده از متادیتاهای تگ‌شده ریلز
            if not detected_song:
                if artist_tag and track_tag:
                    detected_song = f"{artist_tag} {track_tag}"
                else:
                    cleaned = sanitize_query(raw_meta_title)
                    if len(cleaned) > 3:
                        detected_song = cleaned

            # مرحله ۳: دریافت فایل کامل استودیویی ۳۲۰
            download_ok = False
            if detected_song:
                await status.edit_text(f"🔍 <b>قطعه شناسایی شد:</b> <code>{html.escape(detected_song)}</code>\n⚡️ <i>در حال ارسال نسخه استودیویی ۳۲۰...</i>", parse_mode="HTML")
                download_ok = await fetch_and_send_full_mp3(detected_song, query.message.chat_id, context, status)

            # مرحله ۴ (پشتیبان تضمینی): ارسال صدای اصلی کلیپ با کیفیت ۳۲۰
            if not download_ok and raw_file and os.path.exists(raw_file):
                await status.edit_text("⚡️ <i>نسخه رسمی یافت نشد؛ ارسال صدای استخراج‌شده اصلی کلیپ...</i>", parse_mode="HTML")
                with open(raw_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=sanitize_query(raw_meta_title) or "Original Audio",
                        performer="Direct Clip Sound",
                        caption=f"🎵 صدای اورجینال ریلز (۳۲۰ کیلو‌بیت)\n🤖 {BOT_USERNAME}",
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()

        except Exception as e:
            await status.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            clean_filename_pattern(prefix)
            clean_filename_pattern(sample_cut)
        return

    # دریافت فیلم یا صدای مستقیم کلیپ
    if data in ["get_full_video", "get_clip_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ سهمیه دانلود شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "get_full_video")
        status = await query.message.reply_text("⚡️ <b>در حال پردازش و آپلود رسانه...</b>", parse_mode="HTML")
        await process_url_direct(target_url, is_video, query.message.chat_id, context, status)
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

        card = f"🎵 <b>{html.escape(title)}</b>\n⏱ مدت زمان: <code>{dur}</code>\n\nفرمتی که مایلید را انتخاب کنید:"
        kb = [
            [InlineKeyboardButton("🎵 دریافت فایل صوتی (MP3)", callback_data="dl_audio_selected")],
            [InlineKeyboardButton("🎥 دریافت موزیک ویدیو (MP4)", callback_data="dl_vid_selected")]
        ]
        await query.edit_message_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    if data in ["dl_audio_selected", "dl_vid_selected"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما به پایان رسیده است.")
            return
        target_url = context.user_data.get('selected_track', {}).get('webpage_url')
        is_video = (data == "dl_vid_selected")
        status = await query.message.reply_text("⚡️ <b>در حال ارسال فایل...</b>", parse_mode="HTML")
        await process_url_direct(target_url, is_video, query.message.chat_id, context, status)

# تابع دانلود قطعی نسخه ۳۲۰ استودیویی با چند لایه جستجو
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
    search_queries = [
        f"{query_str} audio full",
        f"{query_str} official audio",
        f"{query_str}"
    ]

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
                    f"🎵 <b>{html.escape(title)}</b>\n"
                    f"👤 هنرمند: <code>{html.escape(uploader)}</code>\n"
                    f"🔥 <b>نسخه اورجینال استودیویی ۳۲۰</b>\n"
                    f"🤖 {BOT_USERNAME}"
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

# دانلود مستقیم ویدیو یا فایل صوتی
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
        if not actual_file: raise Exception("فایل نهایی آماده نشد.")

        caption = f"🎬 <b>{html.escape(title)}</b>\n🤖 {BOT_USERNAME}"
        with open(actual_file, 'rb') as f:
            if not is_video:
                await context.bot.send_audio(chat_id=chat_id, audio=f, title=title, performer=uploader, duration=dur, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)

        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        clean_filename_pattern(prefix)

# دستورات مدیریت
async def set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_uid = int(context.args[0])
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_uid,))
        conn.commit()
        await update.message.reply_text(f"✅ کاربر {target_uid} به اشتراک طلایی VIP ارتقا یافت.")
    except Exception:
        await update.message.reply_text("راهنما: /setvip 123456789")

async def add_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_uid = int(context.args[0])
        amount = int(context.args[1])
        cursor.execute("UPDATE users SET requests_left = requests_left + ? WHERE user_id = ?", (amount, target_uid))
        conn.commit()
        await update.message.reply_text(f"✅ به کاربر {target_uid} تعداد {amount} اعتبار اضافه شد.")
    except Exception:
        await update.message.reply_text("راهنما: /addcredit 123456789 10")

# وب‌سرور داخلی سبک برای فعال ماندن روی Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is online and working!")

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
app.add_handler(CommandHandler("setvip", set_vip))
app.add_handler(CommandHandler("addcredit", add_credit))
app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE | (filters.Document.ALL & ~filters.COMMAND), handle_direct_media))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با موتور پیشرفته تشخیص آهنگ و دانلود ویدیو فعال شد...")
app.run_polling()
