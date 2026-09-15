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

# ==================== تنظیمات سرور و محیط ====================
TOKEN = os.environ.get("BOT_TOKEN", "8924723567:AAH1ag1Ccc_t8DTy6u6ayw1kM8I9SWziuBY")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Instadlmusicbot")
SUPPORT_ID = os.environ.get("SUPPORT_ID", "@saeed_mz77")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@ainewss2026")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1773399042"))

VIP_PRICE_TEXT = "ماهانه ۵۰ هزار تومان | دائمی ۱۰۰ هزار تومان"
CARD_NUMBER = "۶۰۳۷-xxxx-xxxx-xxxx به نام شما"
# ==============================================================

# پایگاه داده محلی SQLite
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

def get_output_file(prefix: str):
    matches = glob.glob(f"{prefix}.*")
    valid = [f for f in matches if not f.endswith(('.jpg', '.png', '.webp', '.part', '.ytdl'))]
    return valid[0] if valid else None

def consume_credit(user_id: int) -> bool:
    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return False
    requests_left, is_vip = row
    if is_vip == 1:
        return True
    if requests_left > 0:
        cursor.execute("UPDATE users SET requests_left = requests_left - 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    return False

# دستور شروع
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    referrer_id = int(args[0]) if (args and args[0].isdigit()) else None
    get_or_create_user(user_id, referrer_id)

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 ورود به کانال و عضویت", url=channel_link)],
            [InlineKeyboardButton("✅ عضو شدم (بررسی)", callback_data="check_join")]
        ]
        await update.message.reply_text(
            "⚠️ <b>برای فعال‌سازی ربات، ابتدا عضو کانال ما شوید:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    welcome = (
        "🎧 <b>ربات هوشمند تشخیص و دانلود کامل موزیک</b>\n\n"
        "▫️ <b>ارسال لینک ریلز/یوتیوب:</b> امواج صوتی آنالیز شده و نسخه کامل ۳۲۰ ارسال می‌شود.\n"
        "▫️ <b>ارسال فایل ویدیویی:</b> می‌توانید مستقیماً ویدیو بفرستید تا آهنگ آن پیدا شود.\n"
        "▫️ <b>جستجوی نام آهنگ:</b> نام قطعه یا خواننده را بنویسید."
    )
    kb = [
        [InlineKeyboardButton("👥 زیرمجموعه‌گیری و شارژ رایگان", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ خرید اشتراک نامحدود VIP", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])

    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# مدیریت پیام‌های متنی و لینک‌ها
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 ورود به کانال", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text("⛔️ لطفاً ابتدا در کانال عضو شوید.", reply_markup=InlineKeyboardMarkup(kb))
        return

    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    req_left, is_vip = (u[0], u[1]) if u else (0, 0)

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = (
            "🔒 <b>اعتبار دانلود رایگان شما تمام شده است!</b>\n\n"
            "برای دریافت اعتبار بیشتر:\n"
            "۱. دوستان خود را با لینک زیر دعوت کنید (هر دعوت = ۳ دانلود رایگان):\n"
            f"<code>{invite_link}</code>\n\n"
            "۲. تهیه اشتراک نامحدود VIP."
        )
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    if is_link(text):
        if any(d in text for d in ["instagram.com", "youtube.com", "youtu.be"]):
            context.user_data['media_url'] = text
            panel = (
                "🎬 <b>رسانه دریافت شد</b>\n"
                "──────────────────\n"
                "عملیات مورد نظر را انتخاب کنید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 دریافت موزیک کامل ۳۲۰ (سیستم هوشمند)", callback_data="full_music_detect")],
                [
                    InlineKeyboardButton("🎥 دانلود فیلم (MP4)", callback_data="dl_vid"),
                    InlineKeyboardButton("🎵 استخراج صدای کلیپ", callback_data="dl_raw_audio")
                ]
            ]
            await update.message.reply_text(panel, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("⚠️ لطفاً فقط لینک یوتیوب یا اینستاگرام ارسال کنید.")
        return

    # جستجوی متنی
    search_msg = await update.message.reply_text(f"🔍 در حال جستجوی <code>{html.escape(text)}</code>...", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{text}", download=False)
            tracks = res.get('entries', [])

        if not tracks:
            await search_msg.edit_text("❌ نتیجه‌ای یافت نشد.")
            return

        context.user_data['tracks'] = {str(i): t for i, t in enumerate(tracks)}
        list_text = "🎵 <b>نتایج یافت‌شده؛ موزیک مدنظر را لمس کنید:</b>\n──────────────────\n"
        buttons = []
        for i, t in enumerate(tracks):
            title = t.get('title', 'Unknown')[:35]
            dur = t.get('duration_string', '--:--')
            list_text += f"{i+1}. <b>{html.escape(title)}</b> [<code>{dur}</code>]\n"
            buttons.append([InlineKeyboardButton(f"🎶 {i+1}. {title}", callback_data=f"select_{i}")])

        await search_msg.edit_text(list_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await search_msg.edit_text(f"⚠️ خطا در جستجو: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

# دریافت فایل ویدیویی ارسالی مستقیم داخل چت
async def handle_video_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_membership(user_id, context):
        await update.message.reply_text("⛔️ لطفاً ابتدا در کانال عضو شوید.")
        return

    if not consume_credit(user_id):
        await update.message.reply_text("🔒 اعتبار دانلود شما تمام شده است.")
        return

    status = await update.message.reply_text("🎧 <b>در حال تحلیل فایل ویدیویی و تطبیق امواج صوتی...</b>", parse_mode="HTML")
    video = update.message.video or update.message.video_note or update.message.document
    uid = uuid.uuid4().hex[:6]
    input_file = f"sample_{uid}.mp4"
    audio_file = f"sample_{uid}.mp3"

    try:
        file_obj = await context.bot.get_file(video.file_id)
        await file_obj.download_to_drive(input_file)

        os.system(f"ffmpeg -y -i {input_file} -vn -acodec libmp3lame -b:a 320k {audio_file} >/dev/null 2>&1")

        match = await shazam.recognize(audio_file)
        track = match.get('track') if match else None

        downloaded = False
        if track:
            song_title = track.get('title', '')
            artist = track.get('subtitle', '')
            full_query = f"{artist} {song_title}".strip()

            await status.edit_text(
                f"✅ <b>موزیک با موفقیت پیدا شد!</b>\n\n"
                f"🎵 قطعه: <b>{html.escape(song_title)}</b>\n"
                f"👤 خواننده: <b>{html.escape(artist)}</b>\n\n"
                f"⚡️ <i>در حال ارسال نسخه کامل ۳۲۰...</i>",
                parse_mode="HTML"
            )
            downloaded = await download_and_send_full_track(full_query, update.effective_chat.id, context, status)

        # اگر در شازام پیدا نشد، صدای شفاف خود فایل ارسال شود
        if not downloaded and os.path.exists(audio_file):
            await status.edit_text("⚡️ <i>نسخه رسمی یافت نشد؛ ارسال بالاترین کیفیت صدای فایل...</i>", parse_mode="HTML")
            with open(audio_file, 'rb') as f:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f,
                    title="Original Video Audio",
                    performer="Direct Audio",
                    caption=f"🎵 استخراج‌شده با کیفیت ۳۲۰\n🤖 {BOT_USERNAME}",
                    parse_mode="HTML",
                    read_timeout=300,
                    write_timeout=300
                )
            await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        for f in glob.glob(f"sample_{uid}*"):
            try: os.remove(f)
            except: pass

# پردازش دکمه‌ها
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("✅ عضویت تأیید شد! اکنون می‌توانید لینک یا ویدیو بفرستید.")
        else:
            await query.answer("❌ هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "⭐️ <b>خرید اشتراک طلایی (VIP)</b>\n"
            "──────────────────\n"
            "• دانلود نامحدود بدون قفل دعوت\n"
            "• حداکثر سرعت دانلود نسخه استودیویی ۳۲۰\n"
            "• معاف از عضویت اجباری در کانال‌ها\n\n"
            f"💰 تعرفه: <b>{VIP_PRICE_TEXT}</b>\n"
            f"💳 شماره کارت:\n<code>{CARD_NUMBER}</code>\n\n"
            "فیش واریز را همراه با آیدی زیر به پشتیبانی بفرستید:\n"
            f"🆔 شناسه شما: <code>{user_id}</code>"
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
            "👤 <b>پنل کاربری و دعوت دوستان</b>\n"
            "──────────────────\n"
            f"🆔 شناسه: <code>{user_id}</code>\n"
            f"⭐️ وضعیت: <code>{'VIP' if is_vip else 'عادی'}</code>\n"
            f"⚡️ اعتبار دانلود: <code>{req_left if not is_vip else 'نامحدود'}</code>\n"
            f"👥 زیرمجموعه‌ها: <code>{inv_count} نفر</code>\n\n"
            f"🔗 لینک اختصاصی شما برای دریافت شارژ:\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # پردازش شازام و دانلود چندلایه
    if data == "full_music_detect":
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما تمام شده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🎧 <b>در حال تحلیل صوتی و پیدا کردن موزیک...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        clip_prefix = f"clip_{uid}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{clip_prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }

        detected_query = None
        raw_title = ""

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                raw_title = info.get('title', '')
                track_meta = info.get('track', '')
                artist_meta = info.get('artist', '')

            clip_file = get_output_file(clip_prefix)

            # لایه ۱: تطبیق فرکانسی با Shazam
            if clip_file:
                try:
                    out = await shazam.recognize(clip_file)
                    track = out.get('track') if out else None
                    if track:
                        song_title = track.get('title', '')
                        artist = track.get('subtitle', '')
                        detected_query = f"{artist} {song_title}".strip()
                except Exception:
                    pass

            # لایه ۲: استخراج عنوان از متادیتای ریلز
            if not detected_query:
                if artist_meta and track_meta:
                    detected_query = f"{artist_meta} {track_meta}"
                elif raw_title:
                    clean = re.sub(r'Video by ["\'«»]|_audio|remix|clip|insta', '', raw_title, flags=re.IGNORECASE).strip()
                    if len(clean) > 3:
                        detected_query = clean

            downloaded = False
            if detected_query:
                await status.edit_text(f"🔍 در حال یافتن نسخه کامل: <code>{html.escape(detected_query)}</code>...", parse_mode="HTML")
                downloaded = await download_and_send_full_track(detected_query, query.message.chat_id, context, status)

            # لایه ۳ (تضمینی): ارسال مستقیم بالاترین کیفیت صدای کلیپ
            if not downloaded and clip_file and os.path.exists(clip_file):
                await status.edit_text("⚡️ <i>نسخه کامل رسمی یافت نشد؛ ارسال صدای مستقیم کلیپ...</i>", parse_mode="HTML")
                clean_caption_title = re.sub(r'Video by ["\'«»]|_audio', '', raw_title, flags=re.IGNORECASE).strip() or "Audio Track"
                with open(clip_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=clean_caption_title,
                        performer="Original Audio",
                        caption=f"🎵 صدای استخراج‌شده اصلی (کیفیت ۳۲۰)\n🤖 {BOT_USERNAME}",
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()

        except Exception as e:
            await status.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            for f in glob.glob(f"{clip_prefix}*"):
                try: os.remove(f)
                except: pass
        return

    # دانلود مستقیم ویدیو یا صدای خام
    if data in ["dl_vid", "dl_raw_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "dl_vid")
        status = await query.message.reply_text("⚡️ <b>در حال دانلود و ارسال...</b>", parse_mode="HTML")
        await process_direct(target_url, is_video, query.message.chat_id, context, status)
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

        card = f"🎵 <b>{html.escape(title)}</b>\n⏱ زمان: <code>{dur}</code>\n\nنوع دریافت را انتخاب کنید:"
        kb = [
            [InlineKeyboardButton("🎵 دریافت فایل صوتی (MP3)", callback_data="dl_audio_selected")],
            [InlineKeyboardButton("🎥 دریافت نسخه تصویری (MP4)", callback_data="dl_vid_selected")]
        ]
        await query.edit_message_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    if data in ["dl_audio_selected", "dl_vid_selected"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما تمام شده است.")
            return
        target_url = context.user_data.get('selected_track', {}).get('webpage_url')
        is_video = (data == "dl_vid_selected")
        status = await query.message.reply_text("⚡️ <b>در حال ارسال فایل...</b>", parse_mode="HTML")
        await process_direct(target_url, is_video, query.message.chat_id, context, status)

# دانلود قطعی نسخه ۳۲۰
async def download_and_send_full_track(search_query: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
    uid = uuid.uuid4().hex[:8]
    prefix = f"full_{uid}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{prefix}.%(ext)s",
        'default_search': 'ytsearch1',
        'max_filesize': 50 * 1024 * 1024,
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{search_query} audio", download=True)
            if 'entries' in info and info['entries']:
                info = info['entries'][0]
            title = info.get('title', search_query)
            uploader = info.get('uploader', 'Artist')
            dur = info.get('duration', 0)

        actual_file = get_output_file(prefix)
        if not actual_file:
            return False

        caption = f"🎵 <b>{html.escape(title)}</b>\n👤 <code>{html.escape(uploader)}</code>\n🔥 <b>نسخه کامل استودیویی ۳۲۰</b>\n🤖 {BOT_USERNAME}"
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
        return True
    except Exception:
        return False
    finally:
        for f in glob.glob(f"{prefix}*"):
            try: os.remove(f)
            except: pass

async def process_direct(target_url, is_video, chat_id, context, status_msg):
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
        if not actual_file:
            raise Exception("فایل خروجی آماده نشد.")

        caption = f"🎵 <b>{html.escape(title)}</b>\n🤖 {BOT_USERNAME}"
        with open(actual_file, 'rb') as f:
            if not is_video:
                await context.bot.send_audio(chat_id=chat_id, audio=f, title=title, performer=uploader, duration=dur, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=chat_id, video=f, caption=caption, parse_mode="HTML", read_timeout=300, write_timeout=300)

        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    finally:
        for f in glob.glob(f"{prefix}*"):
            try: os.remove(f)
            except: pass

# وب‌سرور داخلی سبک برای برطرف شدن خطای پورت رندر
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
app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE | (filters.Document.ALL & ~filters.COMMAND), handle_video_file))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با موتور شازام، فال‌بک ۳ لایه و وب‌سرور آماده شد...")
app.run_polling()
