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

# ==================== تنظیمات دستی و مستقیم ====================
TOKEN = os.environ.get("BOT_TOKEN") or "8924723567:AAH1ag1Ccc_t8DTy6u6ayw1kM8I9SWziuBY"
BOT_USERNAME = os.environ.get("BOT_USERNAME") or "@Instadlmusicbot"
SUPPORT_ID = "@saeed_mz77"
CHANNEL_ID = os.environ.get("CHANNEL_ID") or "@ainewss2026"
ADMIN_ID = int(os.environ.get("ADMIN_ID") or "1773399042")

VIP_PRICE_TEXT = "ماهانه 350 هزار تومان | دائمی 500 هزار تومان"
CARD_NUMBER = "6219-8619-4353-1938 به نام  سعید محمدزاده"
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
    """استخراج دقیق عنوان آهنگ بدون زوائد اینستاگرام"""
    if not text: return ""
    clean = re.sub(r'https?://\S+|@[^\s]+|#[^\s]+', ' ', text)
    clean = re.sub(r'(?i)(video by|reel by|audio by|original audio|insta|clip|ریلز|پست)', ' ', clean)
    clean = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', clean)
    clean = re.sub(r'[^\w\s\d\u0600-\u06FF]', ' ', clean)
    return ' '.join(clean.split())

def extract_music_keywords(title: str, desc: str) -> list:
    full = f"{title or ''} {desc or ''}"
    candidates = []

    found = re.findall(r'(?:موزیک|آهنگ|اهنگ|music|song|track)\s*[:：\-]?\s*([^\n\r#@]+)', full, re.IGNORECASE)
    for f in found:
        cleaned = clean_song_query(f)
        if len(cleaned) > 2:
            candidates.append(cleaned)

    raw_first = clean_song_query(full.split('\n')[0])
    if len(raw_first) > 2:
        candidates.append(raw_first)

    unique = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    return unique

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
        "یک بخش را انتخاب فرمایید:"
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
            [InlineKeyboardButton("📢 ورود و عضویت در کانال", url=channel_link)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join")]
        ]
        await update.message.reply_text("<b>برای فعال‌سازی ربات، ابتدا عضو کانال شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "🎧 <b>به ربات هوشمند های موزیک خوش آمدید</b>\n\n"
        "⚡️ <b>روش‌های سریع پیدا کردن و دانلود آهنگ:</b>\n"
        "▫️ لینک ریلز اینستاگرام یا یوتیوب را بفرستید تا دقیق‌ترین نسخه‌های کامل پیدا شوند.\n"
        "▫️ ویس یا فایل ویدیویی بفرستید تا امواج صوتی شناسایی شود.\n"
        "▫️ نام آهنگ یا تکه‌ای از متن ترانه را بنویسید.\n\n"
        "✨ <i>لینک ریلز یا نام آهنگ را بفرستید:</i>"
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
            await update.message.reply_text(" عملیات لغو شد.")
            await show_admin_panel(update.message)
            return

        if admin_state == "set_vip":
            context.user_data['admin_state'] = None
            try:
                target_uid = int(text_input)
                get_or_create_user(target_uid)
                cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_uid,))
                conn.commit()
                await update.message.reply_text(f"✅ کاربر <code>{target_uid}</code> به کاربر VIP ارتقا یافت.", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ لطفاً شناسه عددی ارسال کنید.")
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
                await update.message.reply_text("❌ لطفاً شناسه عددی ارسال کنید.")
            await show_admin_panel(update.message)
            return

        elif admin_state == "add_credit":
            context.user_data['admin_state'] = None
            try:
                parts = text_input.split()
                target_uid = int(parts[0])
                amount = int(parts[1])
                get_or_create_user(target_uid)
                cursor.execute("UPDATE users SET requests_left = requests_left + ? WHERE user_id = ?", (amount, target_uid))
                conn.commit()
                await update.message.reply_text(f"✅ تعداد {amount} اعتبار به کاربر <code>{target_uid}</code> اضافه شد.", parse_mode="HTML")
            except Exception:
                await update.message.reply_text("❌ مثال صحیح: <code>1773399042 10</code>", parse_mode="HTML")
            await show_admin_panel(update.message)
            return

        elif admin_state == "broadcast":
            context.user_data['admin_state'] = None
            status_msg = await update.message.reply_text("⏳ در حال ارسال پیام همگانی...")
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()
            sent_count = 0
            for u in all_users:
                try:
                    await context.bot.send_message(chat_id=u[0], text=text_input, parse_mode="HTML")
                    sent_count += 1
                except Exception:
                    pass
            await status_msg.edit_text(f"📢 پیام به <b>{sent_count}</b> کاربر ارسال شد.", parse_mode="HTML")
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
        msg = (
            "🔒 <b>اعتبار رایگان شما به پایان رسیده است!</b>\n\n"
            "برای دریافت اعتبار، لینک زیر را به دوستان بفرستید (هر دعوت = ۳ دانلود رایگان):\n"
            f"<code>{invite_link}</code>\n\n"
            "یا اشتراک VIP تهیه فرمایید."
        )
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    # اگر لینک ریلز یا یوتیوب باشد
    if is_link(text):
        if any(d in text for d in ["instagram.com", "youtube.com", "youtu.be"]):
            context.user_data['media_url'] = text
            credit_txt = "نامحدود (VIP)" if is_vip else f"{req_left} عدد"
            menu_text = (
                "🎯 <b>رسانه دریافت شد</b>\n"
                f"📊 اعتبار شما: <code>{credit_txt}</code>\n"
                "-------------------\n"
                "لطفاً عملیات مورد نظر را انتخاب فرمایید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 پیدا کردن و دانلود نسخه کامل ۳۲۰ (موتور های‌موزیک)", callback_data="himusic_style_search")],
                [InlineKeyboardButton("🎥 دانلود ویدیوی کامل ریلز (MP4)", callback_data="get_full_video")],
                [InlineKeyboardButton("🎵 فقط صدای اصلی کلیپ", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("لطفاً لینک یوتیوب یا اینستاگرام ارسال فرمایید.")
        return

    # جستجوی متنی نام موزیک
    await execute_himusic_text_search(text, update.message, context)

# تابع جستجوی متنی دقیق سبک HiMusic
async def execute_himusic_text_search(query_str: str, message_obj, context: ContextTypes.DEFAULT_TYPE):
    status = await message_obj.reply_text(f"🔍 <b>در حال جستجوی قطعه «{html.escape(query_str)}»...</b>", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{query_str}", download=False)
            entries = res.get('entries', [])

        valid_tracks = [e for e in entries if e.get('duration', 0) >= 40]
        if not valid_tracks:
            await status.edit_text("❌ نتیجه‌ای با این عنوان یافت نشد.")
            return

        context.user_data['search_results'] = {str(i): t for i, t in enumerate(valid_tracks)}
        list_text = (
            f"🎵 <b>نتایج یافت‌شده برای:</b> <code>{html.escape(query_str)}</code>\n"
            "-------------------\n"
            "جهت دانلود نسخه ۳۲۰ روی موزیک مورد نظر کلیک کنید:\n\n"
        )
        buttons = []
        for i, t in enumerate(valid_tracks):
            title = t.get('title', 'Unknown')[:35]
            dur = t.get('duration_string', '--:--')
            uploader = t.get('uploader', 'Artist')[:15]
            list_text += f"{i+1}. <b>{html.escape(title)}</b>\n👤 {html.escape(uploader)} | ⏱ {dur}\n\n"
            buttons.append([InlineKeyboardButton(f"🎶 {i+1}. {title}", callback_data=f"himusic_dl_{i}")])

        await status.edit_text(list_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await status.edit_text(f"خطا در جستجو: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    try:
        await query.answer()
    except Exception:
        pass

    if data.startswith("admin_"):
        if user_id != ADMIN_ID:
            await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
            return

        if data == "admin_panel":
            await show_admin_panel(query.message)
            return

        if data == "admin_stats":
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
            vips = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(invites_count) FROM users")
            total_invites = cursor.fetchone()[0] or 0
            stats_text = (
                "📊 <b>آمار دقیق ربات</b>\n\n"
                f"👥 کل کاربران: <code>{total} نفر</code>\n"
                f"👑 کاربران VIP: <code>{vips} نفر</code>\n"
                f"🔗 کل زیرمجموعه‌ها: <code>{total_invites} عدد</code>\n"
            )
            kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]]
            await query.message.edit_text(stats_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            return

        if data == "admin_set_vip":
            context.user_data['admin_state'] = "set_vip"
            await query.message.reply_text("👑 <b>شناسه کاربر</b> را برای ارتقا به VIP ارسال فرمایید:\n(جهت لغو /cancel بزنید)", parse_mode="HTML")
            return

        if data == "admin_rem_vip":
            context.user_data['admin_state'] = "rem_vip"
            await query.message.reply_text("❌ <b>شناسه کاربر</b> را برای لغو VIP بفرستید:", parse_mode="HTML")
            return

        if data == "admin_add_credit":
            context.user_data['admin_state'] = "add_credit"
            await query.message.reply_text("➕ شناسه و تعداد اعتبار را با فاصله بفرستید:\nمثال: <code>1773399042 10</code>", parse_mode="HTML")
            return

        if data == "admin_broadcast":
            context.user_data['admin_state'] = "broadcast"
            await query.message.reply_text("📢 <b>متن پیام همگانی</b> را ارسال کنید:", parse_mode="HTML")
            return

        if data == "admin_close":
            await query.message.delete()
            return

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("عضویت تأیید شد! اکنون می‌توانید لینک یا نام آهنگ را بفرستید.")
        else:
            await query.answer("هنوز عضو کانال نشده‌اید!", show_alert=True)
        return

    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "👑 <b>عضویت ویژه طلایی (VIP)</b>\n"
            "-------------------\n"
            "- دانلود نامحدود نسخه‌های کامل و استودیویی\n"
            "- دریافت آهنگ کامل ۳۲۰ بدون هیچ معطلی\n\n"
            f"تعرفه: <b>{VIP_PRICE_TEXT}</b>\n"
            f"کارت:\n<code>{CARD_NUMBER}</code>\n\n"
            "فیش را همراه با شناسه زیر به پشتیبانی بفرستید:\n"
            f"شناسه: <code>{user_id}</code>"
        )
        kb = [[InlineKeyboardButton("💬 ارتباط با پشتیبانی و خرید", url=support_url)]]
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
            f"🔗 لینک دعوت شما (هر نفر = ۳ دانلود هدیه):\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # موتور کاوش ریلز به سبک های‌موزیک
    if data == "himusic_style_search":
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما به پایان رسیده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🔍 <b>در حال تحلیل صدا و اسکن دقیق عنوان...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"scan_{uid}"
        sample_cut = f"cut_{uid}.mp3"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }

        detected_queries = []
        meta_title = ""
        meta_desc = ""

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                meta_title = info.get('title', '')
                meta_desc = info.get('description', '')
                track_tag = info.get('track', '')
                artist_tag = info.get('artist', '')

            raw_file = get_output_file(prefix)

            # ۱. شازام
            if raw_file:
                os.system(f"ffmpeg -y -i {raw_file} -ss 00:00:03 -t 15 -acodec copy {sample_cut} >/dev/null 2>&1")
                test_audio = sample_cut if os.path.exists(sample_cut) else raw_file
                try:
                    res = await shazam.recognize(test_audio)
                    track = res.get('track') if res else None
                    if track:
                        stitle = clean_song_query(track.get('title', ''))
                        sartist = clean_song_query(track.get('subtitle', ''))
                        if stitle:
                            detected_queries.append(f"{sartist} {stitle}".strip())
                except Exception:
                    pass

            # ۲. بررسی متادیتای تگ‌شده
            if artist_tag and track_tag:
                detected_queries.append(f"{artist_tag} {track_tag}")

            # ۳. استخراج از کپشن
            caption_words = extract_music_keywords(meta_title, meta_desc)
            detected_queries.extend(caption_words)

            target_song = detected_queries[0] if detected_queries else None

            if target_song:
                # جستجو و ارائه لیست سبک های‌موزیک
                ydl_search = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
                with yt_dlp.YoutubeDL(ydl_search) as ydl:
                    res = ydl.extract_info(f"ytsearch4:{target_song}", download=False)
                    tracks = res.get('entries', [])

                valid_tracks = [t for t in tracks if t.get('duration', 0) >= 40]

                if valid_tracks:
                    context.user_data['search_results'] = {str(i): t for i, t in enumerate(valid_tracks)}
                    list_text = (
                        f"🎯 <b>موزیک ریلز شناسایی شد:</b> <code>{html.escape(target_song)}</code>\n"
                        "-------------------\n"
                        "نسخه مورد نظر را جهت دریافت انتخاب فرمایید:\n\n"
                    )
                    buttons = []
                    for i, t in enumerate(valid_tracks):
                        title = t.get('title', 'Unknown')[:35]
                        dur = t.get('duration_string', '--:--')
                        uploader = t.get('uploader', 'Artist')[:15]
                        list_text += f"{i+1}. <b>{html.escape(title)}</b>\n👤 {html.escape(uploader)} | ⏱ {dur}\n\n"
                        buttons.append([InlineKeyboardButton(f"🎶 {i+1}. {title}", callback_data=f"himusic_dl_{i}")])

                    await status.edit_text(list_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
                    return

            # در صورتی که در دیتابیس‌ها نسخه دیگری نبود، ارسال صدای باکیفیت خود ریلز
            if raw_file and os.path.exists(raw_file):
                await status.edit_text("⚡️ <i>نسخه رسمی جداگانه منتشر نشده؛ در حال ارسال صدای باکیفیت خود کلیپ...</i>", parse_mode="HTML")
                display_title = detected_queries[0] if detected_queries else "Reel Audio"
                with open(raw_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=display_title,
                        performer="Original Reel Sound",
                        caption=f"🎵 <b>صدای اصلی با کیفیت ۳۲۰</b>\n🤖 {BOT_USERNAME}",
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

    # دانلود قطعی ترک انتخابی توسط کاربر (۳۲۰ استودیویی سبک های‌موزیک)
    if data.startswith("himusic_dl_"):
        idx = data.replace("himusic_dl_", "")
        track_info = context.user_data.get('search_results', {}).get(idx)
        if not track_info:
            await query.edit_message_text("⚠️ درخواست منقضی شده است. لطفاً مجدداً ارسال فرمایید.")
            return

        status = await query.message.reply_text("⚡️ <b>در حال دانلود و ارسال نسخه ۳۲۰...</b>", parse_mode="HTML")
        webpage_url = track_info.get('webpage_url')
        target_title = track_info.get('title', 'Music')

        uid = uuid.uuid4().hex[:8]
        prefix = f"himusic_{uid}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'quiet': True,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([webpage_url])

            actual_file = get_output_file(prefix)
            if actual_file:
                uploader = track_info.get('uploader', 'Artist')
                dur = track_info.get('duration', 0)
                caption = (
                    f"🎵 <b>{html.escape(target_title)}</b>\n"
                    f"👤 <code>{html.escape(uploader)}</code>\n"
                    f"🔥 <b>نسخه کامل و اورجینال ۳۲۰</b>\n"
                    f"🤖 {BOT_USERNAME}"
                )
                with open(actual_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=target_title,
                        performer=uploader,
                        duration=dur,
                        caption=caption,
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()
            else:
                await status.edit_text("❌ خطا در آماده‌سازی فایل.")
        except Exception as e:
            await status.edit_text(f"خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            clean_files(prefix)
        return

    # دانلود ویدیو یا صدای اصلی کلیپ
    if data in ["get_full_video", "get_clip_audio"]:
        if not consume_credit(user_id):
            await query.message.reply_text("سهمیه شما تمام شده است.")
            return

        target_url = context.user_data.get('media_url')
        is_video = (data == "get_full_video")
        status = await query.message.reply_text("در حال پردازش و ارسال فایل...", parse_mode="HTML")
        await process_direct_media(target_url, is_video, query.message.chat_id, context, status)
        return

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

# وب‌سرور سبک برای Render
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
app.add_handler(CommandHandler("admin", admin_command))
app.add_handler(CommandHandler("panel", admin_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با سیستم جستجو و دانلود سبک های‌موزیک فعال شد...")
app.run_polling()
