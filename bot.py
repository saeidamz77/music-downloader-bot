import os
import re
import uuid
import glob
import html
import sqlite3
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

# ==================== دریافت تنظیمات از متغیرهای سرور ====================
TOKEN = os.environ.get("BOT_TOKEN", "توکن_ربات_شما")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "@YourBotUsername")
SUPPORT_ID = os.environ.get("SUPPORT_ID", "@saeed_mz77")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@YourChannelID")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

VIP_PRICE_TEXT = "ماهانه ۵۰ هزار تومان | دائمی ۱۰۰ هزار تومان"
CARD_NUMBER = "۶۰۳۷-xxxx-xxxx-xxxx به نام شما"
# =========================================================================

# راه‌اندازی دیتابیس کاربران
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

# دستور استارت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    referrer_id = None
    if args and args[0].isdigit():
        referrer_id = int(args[0])

    get_or_create_user(user_id, referrer_id)

    if not await check_membership(user_id, context):
        channel_link = f"https://t.me/{CHANNEL_ID.replace('@', '')}"
        kb = [
            [InlineKeyboardButton("📢 ورود به کانال و عضویت", url=channel_link)],
            [InlineKeyboardButton("✅ عضو شدم (بررسی مجدد)", callback_data="check_join")]
        ]
        await update.message.reply_text(
            "⚠️ <b>برای استفاده از ربات، ابتدا باید در کانال رسمی عضو شوید:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    welcome = (
        "🎧 <b>به ربات هوشمند استخراج و دانلود مدیا خوش آمدید!</b>\n\n"
        "▫️ <b>ارسال لینک ریلز/یوتیوب:</b> دریافت نسخه کامل آهنگ ۳۲۰، فیلم MP4 یا فایل صوتی کلیپ.\n"
        "▫️ <b>ارسال نام آهنگ یا خواننده:</b> جستجوی جامع و ارسال مستقیم فایل.\n\n"
        "👥 <i>برای دریافت شارژ رایگان دوستان خود را دعوت کنید!</i>"
    )
    kb = [
        [InlineKeyboardButton("👥 زیرمجموعه‌گیری و حساب کاربری", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ خرید اشتراک نامحدود (VIP)", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])

    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# مدیریت پیام‌های متنی
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
    req_left = u[0] if u else 0
    is_vip = u[1] if u else 0

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = (
            "🔒 <b>اعتبار دانلود رایگان شما تمام شده است!</b>\n\n"
            "برای فعال‌سازی مجدد یکی از راه‌های زیر را انتخاب کنید:\n"
            "۱. دوستان خود را با لینک زیر دعوت کنید (هر دعوت = ۳ دانلود هدیه):\n"
            f"<code>{invite_link}</code>\n\n"
            "۲. ارتقای حساب به اشتراک نامحدود VIP."
        )
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    # در صورت ارسال لینک
    if is_link(text):
        if any(d in text for d in ["instagram.com", "youtube.com", "youtu.be"]):
            context.user_data['media_url'] = text
            credit_status = "VIP" if is_vip else f"{req_left} دانلود"
            panel = (
                "🎬 <b>رسانه شناسایی شد</b>\n"
                f"📊 اعتبار باقی‌مانده شما: <code>{credit_status}</code>\n"
                "──────────────────\n"
                "عملیات مدنظر را انتخاب کنید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 دریافت آهنگ کامل ۳۲۰ (شناسایی هوشمند)", callback_data="full_music_detect")],
                [
                    InlineKeyboardButton("🎥 دانلود ویدیو (MP4)", callback_data="dl_vid"),
                    InlineKeyboardButton("🎵 فقط صدای کلیپ", callback_data="dl_raw_audio")
                ]
            ]
            await update.message.reply_text(panel, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("⚠️ لطفاً فقط لینک یوتیوب یا اینستاگرام ارسال فرمایید.")
        return

    # جستجوی متنی عنوان آهنگ
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

# مدیریت کلیک دکمه‌ها
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("✅ عضویت تأیید شد! اکنون می‌توانید لینک یا نام موزیک را بفرستید.")
        else:
            await query.answer("❌ هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "⭐️ <b>خرید اشتراک طلایی (VIP)</b>\n"
            "──────────────────\n"
            "مزایای اکانت طلایی:\n"
            "• دانلود کاملاً نامحدود و دائمی\n"
            "• سرعت حداکثری و اولویت کیفیت ۳۲۰\n"
            "• معاف از عضویت در کانال‌های اجباری\n\n"
            f"💰 هزینه اشتراک: <b>{VIP_PRICE_TEXT}</b>\n"
            f"💳 شماره کارت:\n<code>{CARD_NUMBER}</code>\n\n"
            "پس از واریز، فیش پرداختی را همراه با آیدی عددی خود به پشتیبان ارسال کنید:\n"
            f"🆔 شناسه کاربری شما: <code>{user_id}</code>"
        )
        kb = [[InlineKeyboardButton("💬 ارسال رسید به پشتیبانی", url=support_url)]]
        await query.message.reply_text(vip_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "user_panel":
        cursor.execute("SELECT requests_left, invites_count, is_vip FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        req_left, inv_count, is_vip = row if row else (0, 0, 0)
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"

        panel_text = (
            "👤 <b>پنل کاربری و زیرمجموعه‌گیری</b>\n"
            "──────────────────\n"
            f"🆔 شناسه: <code>{user_id}</code>\n"
            f"⭐️ وضعیت حساب: <code>{'کاربر طلایی (VIP)' if is_vip else 'کاربر عادی'}</code>\n"
            f"⚡️ اعتبار دانلود باقی‌مانده: <code>{req_left if not is_vip else 'نامحدود'}</code>\n"
            f"👥 تعداد زیرمجموعه‌ها: <code>{inv_count} نفر</code>\n\n"
            f"🔗 لینک اختصاصی شما برای دعوت:\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    if data == "admin_panel" and user_id == ADMIN_ID:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
        total_vip = cursor.fetchone()[0]
        admin_text = (
            "👑 <b>پنل مدیریت ربات</b>\n"
            "──────────────────\n"
            f"👥 کل کاربران: <code>{total_users} نفر</code>\n"
            f"⭐️ اعضای VIP: <code>{total_vip} نفر</code>\n\n"
            "دستورات:\n"
            "▫️ ارتقا به VIP: <code>/setvip 123456789</code>\n"
            "▫️ افزایش اعتبار: <code>/addcredit 123456789 10</code>"
        )
        await query.message.reply_text(admin_text, parse_mode="HTML")
        return

    if data == "full_music_detect":
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما تمام شده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🎧 <b>در حال آنالیز و استخراج مشخصات آهنگ اصلی...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"scan_{uid}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            'quiet': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', '')
                track = info.get('track', '')
                artist = info.get('artist', '')

            search_query = f"{artist} {track}".strip() if (artist and track) else title
            search_query = re.sub(r'Video by ["\'«»]|_audio|remix|clip', '', search_query, flags=re.IGNORECASE).strip()

            await status.edit_text(f"🔍 نام قطعه شناسایی شد: <code>{html.escape(search_query)}</code>\n⚡️ در حال دریافت نسخه کامل ۳۲۰...", parse_mode="HTML")
            
            success = await download_full_track(search_query, query, context, status)
            if not success:
                clip_file = get_output_file(prefix)
                if clip_file:
                    with open(clip_file, 'rb') as f:
                        await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=f,
                            title=search_query or "Audio Track",
                            performer="Original Media",
                            caption=f"🎵 صدای اصلی استخراج‌شده از ریلز\n🤖 {BOT_USERNAME}",
                            read_timeout=300,
                            write_timeout=300
                        )

            for f in glob.glob(f"{prefix}*"):
                try: os.remove(f)
                except: pass
            await status.delete()

        except Exception as e:
            for f in glob.glob(f"{prefix}*"):
                try: os.remove(f)
                except: pass
            await status.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        return

    if data in ["dl_vid", "dl_raw_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("⛔️ اعتبار شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "dl_vid")
        status = await query.message.reply_text("⚡️ <b>در حال دانلود و ارسال فایل...</b>", parse_mode="HTML")
        await process_direct(target_url, is_video, query, context, status)
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
        status = await query.message.reply_text("⚡️ <b>در حال دریافت و آپلود فایل...</b>", parse_mode="HTML")
        await process_direct(target_url, is_video, query, context, status)

# دانلود نسخه کامل از یوتیوب
async def download_full_track(search_query: str, query, context, status_msg) -> bool:
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

        caption = f"🎵 <b>{html.escape(title)}</b>\n👤 <code>{html.escape(uploader)}</code>\n🔥 <b>نسخه کامل ۳۲۰</b>\n🤖 {BOT_USERNAME}"
        with open(actual_file, 'rb') as f:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=f,
                title=title,
                performer=uploader,
                duration=dur,
                caption=caption,
                parse_mode="HTML",
                read_timeout=300,
                write_timeout=300
            )

        for f in glob.glob(f"{prefix}*"):
            try: os.remove(f)
            except: pass
        return True
    except Exception:
        for f in glob.glob(f"{prefix}*"):
            try: os.remove(f)
            except: pass
        return False

# دانلود مستقیم لینک‌ها
async def process_direct(target_url, is_video, query, context, status_msg):
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
            raise Exception("فایل خروجی ایجاد نشد.")

        caption = f"🎵 <b>{html.escape(title)}</b>\n🤖 {BOT_USERNAME}"
        with open(actual_file, 'rb') as f:
            if not is_video:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    title=title,
                    performer=uploader,
                    duration=dur,
                    caption=caption,
                    parse_mode="HTML",
                    read_timeout=300,
                    write_timeout=300
                )
            else:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=f,
                    caption=caption,
                    parse_mode="HTML",
                    read_timeout=300,
                    write_timeout=300
                )

        for f in glob.glob(f"{prefix}*"):
            try: os.remove(f)
            except: pass
        await status_msg.delete()
    except Exception as e:
        for f in glob.glob(f"{prefix}*"):
            try: os.remove(f)
            except: pass
        await status_msg.edit_text(f"❌ خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

# دستورات ادمین
async def set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_uid = int(context.args[0])
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_uid,))
        conn.commit()
        await update.message.reply_text(f"✅ کاربر {target_uid} به عضویت VIP ارتقا یافت.")
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

# بیلد نهایی ربات
app = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(300)
    .read_timeout(300)
    .write_timeout(300)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("invite", start))
app.add_handler(CommandHandler("setvip", set_vip))
app.add_handler(CommandHandler("addcredit", add_credit))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با تنظیمات Render و پشتیبانی @saeed_mz77 فعال شد...")
app.run_polling()
