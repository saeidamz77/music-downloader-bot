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

# ==================== تنظیمات سرور و مدیریت ====================
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

# هدرها و کلاینت‌های ضدبلاک اختصاصی برای یوتیوب و اینستاگرام
ANTI_BLOCK_CONFIG = {
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios']
        },
        'instagram': {
            'api_client': ['web', 'graph']
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
        'Accept-Language': 'en-US,en;q=0.9',
    }
}

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

# ==================== موتور دانلود کمکی اینستاگرام (Fallback) ====================
def download_instagram_fallback(url: str, output_path: str) -> bool:
    """دریافت مستقیم در صورت بلاک شدن توسط سرور اینستاگرام"""
    api_endpoints = [
        "https://api.cobalt.tools/api/json",
        "https://co.wuk.sh/api/json"
    ]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {"url": url, "downloadMode": "audio"}

    for endpoint in api_endpoints:
        try:
            res = requests.post(endpoint, json=payload, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                stream_url = data.get("url")
                if stream_url:
                    r = requests.get(stream_url, stream=True, timeout=25)
                    if r.status_code == 200:
                        with open(output_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=16384):
                                if chunk: f.write(chunk)
                        return True
        except Exception:
            continue
    return False

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
        "یک بخش را جهت مدیریت انتخاب کنید:"
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
        await update.message.reply_text("<b>برای فعال‌سازی ربات، لطفاً ابتدا در کانال عضو شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "👑 <b>ربات پیشرفته دانلود و استخراج کامل موزیک ۳۲۰</b>\n\n"
        "⚡️ <b>قابلیت‌ها:</b>\n"
        "- مجهز به سیستم ضدبلاک یوتیوب و اسکرپر هوشمند اینستاگرام\n"
        "- استخراج دقیق آهنگ کامل حتی در صورت ارور دادن ریلز\n"
        "- دانلود مستقیم ویدیوی باکیفیت و استخراج صدای اصلی"
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
                await update.message.reply_text("❌ شناسه باید فقط عدد باشد.")
            await show_admin_panel(update.message)
            return

        elif admin_state == "rem_vip":
            context.user_data['admin_state'] = None
            try:
                target_uid = int(text_input)
                cursor.execute("UPDATE users SET is_vip = 0 WHERE user_id = ?", (target_uid,))
                conn.commit()
                await update.message.reply_text(f"✅ دسترسی VIP کاربر <code>{target_uid}</code> لغو شد.", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ شناسه باید فقط عدد باشد.")
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
                await update.message.reply_text(f"✅ تعداد {amount} اعتبار به کاربر <code>{target_uid}</code> افزوده شد.", parse_mode="HTML")
            except Exception:
                await update.message.reply_text("❌ فرمت صحیح: <code>1773399042 10</code>", parse_mode="HTML")
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
            await status_msg.edit_text(f"📢 پیام به <b>{sent_count}</b> کاربر با موفقیت ارسال شد.", parse_mode="HTML")
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
            "برای دریافت اعتبار، لینک زیر را برای دوستان خود بفرستید:\n"
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
                "گزینه مدنظر را انتخاب کنید:"
            )
            buttons = [
                [InlineKeyboardButton("🔥 پیدا کردن و دانلود نسخه ۳۲۰ (موتور ضدبلاک)", callback_data="deep_universal_music")],
                [InlineKeyboardButton("🎥 دانلود ویدیوی کامل ریلز (MP4)", callback_data="get_full_video")],
                [InlineKeyboardButton("🎵 صدای اصلی کلیپ", callback_data="get_clip_audio")]
            ]
            await update.message.reply_text(menu_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text("لطفاً لینک یوتیوب یا اینستاگرام ارسال کنید.")
        return

    # جستجوی متنی با کلاینت‌های ضدبلاک
    search_msg = await update.message.reply_text(f"🔍 در حال جستجوی «{html.escape(text)}»...", parse_mode="HTML")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
    ydl_opts.update(ANTI_BLOCK_CONFIG)
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
            f"🔗 لینک دعوت شما:\n<code>{invite_link}</code>"
        )
        await query.message.reply_text(panel_text, parse_mode="HTML")
        return

    # پردازش عمیق و ضدبلاک برای استخراج ریلز و آهنگ کامل
    if data == "deep_universal_music":
        if not consume_credit(user_id):
            await query.message.reply_text("اعتبار شما به پایان رسیده است.")
            return

        url = context.user_data.get('media_url')
        status = await query.edit_message_text("🔍 <b>در حال کاوش فرکانسی و آنالیز اثر (ضدبلاک)...</b>", parse_mode="HTML")

        uid = uuid.uuid4().hex[:6]
        prefix = f"raw_{uid}"
        sample_cut = f"cut_{uid}.mp3"
        fallback_file = f"{prefix}.mp3"

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{prefix}.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'quiet': True,
        }
        ydl_opts.update(ANTI_BLOCK_CONFIG)

        search_pool = []
        meta_title = ""
        meta_desc = ""

        try:
            # تلاش ۱: دانلود با yt-dlp و هدرهای ضدبلاک
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    meta_title = info.get('title', '')
                    meta_desc = info.get('description', '')
                    track_tag = info.get('track', '')
                    artist_tag = info.get('artist', '')
                    if artist_tag and track_tag:
                        search_pool.append(f"{artist_tag} {track_tag}")
            except Exception:
                # تلاش ۲ (دور زدن ارور empty media response): استفاده از API کمکی اینستاگرام
                download_instagram_fallback(url, fallback_file)

            raw_file = get_output_file(prefix)

            # ۱. تحلیل اثر انگشت صوتی با Shazam
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
                            search_pool.insert(0, f"{sartist} {stitle}".strip())
                except Exception:
                    pass

            # ۲. بررسی کلمات کلیدی کپشن
            caption_words = extract_music_keywords(meta_title, meta_desc)
            search_pool.extend(caption_words)

            download_success = False

            # ۳. جستجوی نسخه استودیویی ۳۲۰ در یوتیوب با کلاینت اندروید
            for target_query in search_pool:
                if not target_query or len(target_query) < 3:
                    continue

                await status.edit_text(f"🌐 <b>در حال دانلود قطعه اصلی ۳۲۰:</b>\n<code>{html.escape(target_query)}</code>...", parse_mode="HTML")
                download_success = await execute_safe_download_and_send(target_query, query.message.chat_id, context, status)
                if download_success:
                    break

            # ۴. اگر نسخه مجزایی نبود، صدای شفاف خود کلیپ را ارسال می‌کند
            if not download_success and raw_file and os.path.exists(raw_file):
                await status.edit_text("⚡️ <i>نسخه کامل مجزا منتشر نشده؛ ارسال صدای باکیفیت خود کلیپ...</i>", parse_mode="HTML")
                display_title = search_pool[0] if search_pool else "Original Track"
                with open(raw_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=display_title,
                        performer="Original Reel Sound",
                        caption=f"🎵 صدای استخراج‌شده با کیفیت ۳۲۰\n🤖 {BOT_USERNAME}",
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

async def execute_safe_download_and_send(query_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg) -> bool:
    uid = uuid.uuid4().hex[:8]
    prefix = f"safe_{uid}"
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"{prefix}.%(ext)s",
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
    }
    ydl_opts.update(ANTI_BLOCK_CONFIG)

    search_queries = [
        f"{query_text} official audio",
        f"{query_text}"
    ]

    for sq in search_queries:
        try:
            search_opts = {'quiet': True}
            search_opts.update(ANTI_BLOCK_CONFIG)

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
                        f"🔥 <b>کیفیت ۳۲۰ استودیویی</b>\n"
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
    ydl_opts.update(ANTI_BLOCK_CONFIG)

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

# وب‌سرور سبک جهت رفع خطای پورت رندر
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

print("ربات با معماری ضدبلاک اینستاگرام و یوتیوب فعال شد...")
app.run_polling()
