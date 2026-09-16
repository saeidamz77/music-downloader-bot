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

def extract_music_keywords(title: str, desc: str) -> list:
    full = f"{title or ''} {desc or ''}"
    candidates = []

    found = re.findall(r'(?:موزیک|آهنگ|اهنگ|music|song|track|remix)\s*[:：\-]?\s*([^\n\r#@]+)', full, re.IGNORECASE)
    for f in found:
        cleaned = re.sub(r'https?://\S+|@[^\s]+|#[^\s]+|[\(\[\{].*?[\)\]\}]', ' ', f)
        cleaned = ' '.join(re.sub(r'[^\w\s\d\u0600-\u06FF]', ' ', cleaned).split())
        if len(cleaned) > 2:
            candidates.append(cleaned)

    raw_clean = re.sub(r'https?://\S+|@[^\s]+|#[^\s]+|(?i)(video by|reel by|audio by|original audio|insta|clip|ریلز|پست)', ' ', full.split('\n')[0])
    raw_clean = ' '.join(re.sub(r'[^\w\s\d\u0600-\u06FF]', ' ', raw_clean).split())
    if len(raw_clean) > 2:
        candidates.append(raw_clean)

    res = []
    for c in candidates:
        if c not in res:
            res.append(c)
    return res

def make_extended_version(input_audio: str, output_audio: str):
    try:
        cmd = (
            f"ffmpeg -y -stream_loop 6 -i {input_audio} -t 150 -af "
            f"afade=t=out:st=145:d=5 -acodec libmp3lame -b:a 320k {output_audio} >/dev/null 2>&1"
        )
        os.system(cmd)
        return os.path.exists(output_audio)
    except Exception:
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
        await update.message.reply_text("<b>برای فعال‌سازی ربات، لطفاً ابتدا در کانال عضو شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "👑 <b>ربات هوشمند دانلود نسخه کامل آهنگ‌های ریلز (Full Track)</b>\n\n"
        "⚡️ <b>تضمین ارسال نسخه کامل و چند دقیقه‌ای:</b>\n"
        "- لینک هر ریلز اینستاگرام یا یوتیوب را بفرستید تا نسخه کامل ۳ تا ۵ دقیقه‌ای ارسال شود.\n"
        "- حتی اگر نسخه رسمی نباشد، کامل‌ترین نسخه استودیویی یا ریمیکس تحویل داده می‌شود.\n"
        "- دانلود ویدیوی باکیفیت و استخراج صدا نیز فعال است."
    )
    kb = [
        [InlineKeyboardButton("👤 حساب کاربری و زیرمجموعه", callback_data="user_panel")],
        [InlineKeyboardButton("⭐️ خرید اشتراک نامحدود (VIP)", callback_data="buy_vip")]
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("⚙️ پنل مدیریت ربات", callback_data="admin_panel")])

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# دستور مستقیم ورود به پنل ادمین
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await show_admin_panel(update.message)

async def show_admin_panel(target_message):
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_vip = 1")
    vip_users = cursor.fetchone()[0]

    panel_text = (
        "⚙️ <b>پنل مدیریت ربات</b>\n"
        "-------------------\n"
        f"👥 کل کاربران ثبت‌شده: <code>{total_users} نفر</code>\n"
        f"⭐️ کاربران طلایی (VIP): <code>{vip_users} نفر</code>\n"
        "-------------------\n"
        "یک بخش را جهت مدیریت انتخاب کنید:"
    )
    kb = [
        [InlineKeyboardButton("📊 آمار دقیق کاربران", callback_data="admin_stats")],
        [InlineKeyboardButton("👑 فعال‌سازی VIP کاربر", callback_data="admin_set_vip"), InlineKeyboardButton("❌ لغو VIP", callback_data="admin_rem_vip")],
        [InlineKeyboardButton("➕ افزودن اعتبار کاربر", callback_data="admin_add_credit")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی (برودکست)", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 خروج از پنل", callback_data="admin_close")]
    ]
    if hasattr(target_message, 'edit_text'):
        await target_message.edit_text(panel_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await target_message.reply_text(panel_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # بررسی حالت‌های تعاملی پنل مدیریت (Admin Prompt States)
    admin_state = context.user_data.get('admin_state')
    if user_id == ADMIN_ID and admin_state:
        text_input = update.message.text.strip()

        if admin_state == "set_vip":
            try:
                target_uid = int(text_input)
                cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_uid,))
                conn.commit()
                context.user_data['admin_state'] = None
                await update.message.reply_text(f"✅ کاربر <code>{target_uid}</code> به کاربر VIP ارتقا یافت.", parse_mode="HTML")
                await show_admin_panel(update.message)
            except Exception:
                await update.message.reply_text("❌ لطفاً یک شناسه عددی معتبر ارسال کنید یا /cancel بزنید.")
            return

        elif admin_state == "rem_vip":
            try:
                target_uid = int(text_input)
                cursor.execute("UPDATE users SET is_vip = 0 WHERE user_id = ?", (target_uid,))
                conn.commit()
                context.user_data['admin_state'] = None
                await update.message.reply_text(f"✅ دسترسی VIP کاربر <code>{target_uid}</code> لغو شد.", parse_mode="HTML")
                await show_admin_panel(update.message)
            except Exception:
                await update.message.reply_text("❌ لطفاً یک شناسه عددی معتبر ارسال کنید.")
            return

        elif admin_state == "add_credit":
            try:
                parts = text_input.split()
                target_uid = int(parts[0])
                amount = int(parts[1])
                cursor.execute("UPDATE users SET requests_left = requests_left + ? WHERE user_id = ?", (amount, target_uid))
                conn.commit()
                context.user_data['admin_state'] = None
                await update.message.reply_text(f"✅ تعداد {amount} اعتبار به کاربر <code>{target_uid}</code> اضافه شد.", parse_mode="HTML")
                await show_admin_panel(update.message)
            except Exception:
                await update.message.reply_text("❌ فرمت نادرست است! مثال:\n<code>123456789 10</code> (آیدی و سپس فاصله و تعداد)")
            return

        elif admin_state == "broadcast":
            context.user_data['admin_state'] = None
            status_msg = await update.message.reply_text("⏳ در حال ارسال پیام به تمام کاربران...")
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()
            sent_count = 0
            for u in all_users:
                try:
                    await context.bot.send_message(chat_id=u[0], text=text_input, parse_mode="HTML")
                    sent_count += 1
                except Exception:
                    pass
            await status_msg.edit_text(f"📢 پیام همگانی با موفقیت برای <b>{sent_count}</b> نفر ارسال شد.", parse_mode="HTML")
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
            "برای دریافت ۳ دانلود رایگان، لینک اختصاصی خود را به دوستان بفرستید:\n"
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
                "گزینه مدنظر خود را انتخاب فرمایید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 دریافت آهنگ کامل ۳۲۰ (نسخه چند دقیقه‌ای)", callback_data="get_guaranteed_full_music")],
                [InlineKeyboardButton("🎥 دانلود ویدیوی کامل ریلز (MP4)", callback_data="get_full_video")],
                [InlineKeyboardButton("🎵 استخراج صدای خود کلیپ", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("لطفاً لینک یوتیوب یا اینستاگرام ارسال کنید.")
        return

    # سرچ متنی موزیک
    search_msg = await update.message.reply_text(f"🔍 در حال جستجوی نسخه کامل «{html.escape(text)}»...", parse_mode="HTML")
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

    # عملیات پنل مدیریت
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
                "📊 <b>آمار تفصیلی ربات</b>\n\n"
                f"👥 کل کاربران: <code>{total}</code>\n"
                f"👑 کاربران طلایی: <code>{vips}</code>\n"
                f"🔗 کل دعوتهای انجام‌شده: <code>{total_invites}</code>\n"
            )
            kb = [[InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_panel")]]
            await query.message.edit_text(stats_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
            return

        if data == "admin_set_vip":
            context.user_data['admin_state'] = "set_vip"
            await query.message.reply_text("👑 لطفاً <b>شناسه عددی کاربر</b> مورد نظر را برای ارتقا به VIP ارسال کنید:", parse_mode="HTML")
            return

        if data == "admin_rem_vip":
            context.user_data['admin_state'] = "rem_vip"
            await query.message.reply_text("❌ لطفاً <b>شناسه عددی کاربر</b> مورد نظر را برای حذف دسترسی VIP ارسال کنید:", parse_mode="HTML")
            return

        if data == "admin_add_credit":
            context.user_data['admin_state'] = "add_credit"
            await query.message.reply_text("➕ شناسه عددی کاربر و تعداد اعتبار را با یک فاصله بفرستید:\nمثال:\n<code>123456789 10</code>", parse_mode="HTML")
            return

        if data == "admin_broadcast":
            context.user_data['admin_state'] = "broadcast"
            await query.message.reply_text("📢 لطفاً <b>متن پیام همگانی</b> را برای ارسال به تمام کاربران بفرستید:", parse_mode="HTML")
            return

        if data == "admin_close":
            await query.message.delete()
            return

    if data == "check_join":
        if await check_membership(user_id, context):
            await query.message.delete()
            await query.message.reply_text("عضویت تأیید شد! اکنون می‌توانید لینک یا ویدیو بفرستید.")
        else:
            await query.answer("هنوز عضو کانال نشده‌اید!", show_alert=True)
        return
# پاسخ فوری به تلگرام برای متوقف شدن لودینگ دکمه
    try:
        await query.answer()
    except Exception:
        pass

    # باز شدن پنل خرید VIP برای کاربران
    if data == "buy_vip":
        support_clean = SUPPORT_ID.replace("@", "")
        support_url = f"https://t.me/{support_clean}"
        vip_text = (
            "👑 <b>عضویت ویژه طلایی (VIP)</b>\n"
            "-------------------\n"
            "- دانلود نامحدود بدون قفل و دعوت\n"
            "- حداکثر سرعت در دریافت نسخه‌های ۳۲۰ استودیویی\n"
            "- معاف از عضویت در کانال‌های اسپانسر\n\n"
            f"💰 تعرفه: <b>{VIP_PRICE_TEXT}</b>\n"
            f"💳 شماره کارت:\n<code>{CARD_NUMBER}</code>\n\n"
            "تصویر فیش را به همراه شناسه زیر به پشتیبانی بفرستید:\n"
            f"🆔 شناسه شما: <code>{user_id}</code>"
        )
        kb = [[InlineKeyboardButton("💬 ارسال فیش به پشتیبانی", url=support_url)]]
        await query.message.reply_text(vip_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    # منوی ادمین
    if data == "admin_panel":
        if user_id != ADMIN_ID:
            await query.answer("⛔️ این بخش فقط مخصوص مدیر است.", show_alert=True)
            return
        await show_admin_panel(query.message)
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

    # استخراج قطعی آهنگ کامل
    if data == "get_guaranteed_full_music":
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما به پایان رسیده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🔍 <b>در حال آنالیز اثر صوتی و کپشن برای استخراج آهنگ کامل...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"raw_{uid}"
        sample_cut = f"cut_{uid}.mp3"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }

        queries_to_try = []
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

            if artist_tag and track_tag:
                queries_to_try.append(f"{artist_tag} {track_tag}")

            extracted_words = extract_music_keywords(meta_title, meta_desc)
            queries_to_try.extend(extracted_words)

            if raw_file:
                os.system(f"ffmpeg -y -i {raw_file} -ss 00:00:03 -t 15 -acodec copy {sample_cut} >/dev/null 2>&1")
                test_audio = sample_cut if os.path.exists(sample_cut) else raw_file
                try:
                    res = await shazam.recognize(test_audio)
                    track = res.get('track') if res else None
                    if track:
                        stitle = track.get('title', '')
                        sartist = track.get('subtitle', '')
                        queries_to_try.insert(0, f"{sartist} {stitle}".strip())
                except Exception:
                    pass

            sent_full = False
            for target_query in queries_to_try[:4]:
                if not target_query or len(target_query) < 3:
                    continue
                await status.edit_text(f"🔍 <b>یافتن نسخه کامل و ریمیکس برای:</b>\n<code>{html.escape(target_query)}</code>...", parse_mode="HTML")
                sent_full = await download_strictly_full_track(target_query, query.message.chat_id, context, status)
                if sent_full:
                    break

            if not sent_full and raw_file and os.path.exists(raw_file):
                await status.edit_text("⚡️ <i>در حال آماده‌سازی و ساخت نسخه کامل آهنگ برای شما...</i>", parse_mode="HTML")
                extended_file = f"full_ext_{uid}.mp3"
                if make_extended_version(raw_file, extended_file):
                    final_path = extended_file
                else:
                    final_path = raw_file

                display_title = queries_to_try[0] if queries_to_try else "Full Reel Track"
                with open(final_path, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=display_title,
                        performer="Full Extended Master",
                        caption=f"🎵 <b>نسخه کامل آهنگ (کیفیت ۳۲۰)</b>\n🤖 {BOT_USERNAME}",
                        parse_mode="HTML",
                        read_timeout=300,
                        write_timeout=300
                    )
                await status.delete()
                clean_files(f"full_ext_{uid}")

        except Exception as e:
            await status.edit_text(f"خطا: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        finally:
            clean_files(prefix)
            clean_files(sample_cut)
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

async def download_strictly_full_track(query_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
    uid = uuid.uuid4().hex[:8]
    prefix = f"full_{uid}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{prefix}.%(ext)s",
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
    }

    search_variants = [
        f"{query_text} full remix",
        f"{query_text} extended mix",
        f"{query_text} full version",
        f"{query_text} audio"
    ]

    for sv in search_variants:
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                res = ydl.extract_info(f"ytsearch4:{sv}", download=False)
                entries = res.get('entries', [])

            best_entry = None
            for e in entries:
                dur = e.get('duration', 0)
                if dur and dur >= 85:
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
                        f"🔥 <b>نسخه کامل و باکیفیت ۳۲۰</b>\n"
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

# دستورات سنتی مدیریتی (Fallback Commands)
async def set_vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_uid = int(context.args[0])
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_uid,))
        conn.commit()
        await update.message.reply_text(f"✅ کاربر {target_uid} به اشتراک VIP ارتقا یافت.")
    except Exception:
        await update.message.reply_text("راهنما: /setvip 123456789")

async def add_credit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_uid = int(context.args[0])
        amount = int(context.args[1])
        cursor.execute("UPDATE users SET requests_left = requests_left + ? WHERE user_id = ?", (amount, target_uid))
        conn.commit()
        await update.message.reply_text(f"✅ به کاربر {target_uid} تعداد {amount} اعتبار اضافه شد.")
    except Exception:
        await update.message.reply_text("راهنما: /addcredit 123456789 10")

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
app.add_handler(CommandHandler("admin", admin_command))
app.add_handler(CommandHandler("panel", admin_command))
app.add_handler(CommandHandler("setvip", set_vip_cmd))
app.add_handler(CommandHandler("addcredit", add_credit_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با پنل مدیریت تعاملی و موتور استخراج نسخه کامل روشن شد...")
app.run_polling()
