import os
import re
import sys
import uuid
import glob
import html
import sqlite3
import threading
import requests
from urllib.parse import quote, unquote
from bs4 import BeautifulSoup
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
    clean = re.sub(r'(?i)(video by|reel by|audio by|original audio|remix|slowed|reverb|insta|clip|ریلز|پست|چنل|کانال)', ' ', clean)
    clean = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', clean)
    clean = re.sub(r'[^\w\s\d\u0600-\u06FF]', ' ', clean)
    return ' '.join(clean.split())

# ==================== موتور مستقل سرچ و دانلود MP3 از وب ====================
def search_direct_web_mp3(query: str):
    """جستجوی مستقیم لینک فایل MP3 با کیفیت ۳۲۰ از ایندکس‌های وب بدون وابستگی به یوتیوب"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }
    
    search_queries = [
        f"{query} mp3 320",
        f"{query} دانلود آهنگ ۳۲۰"
    ]
    
    found_urls = []
    
    for sq in search_queries:
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote(sq)}"
            r = requests.get(url, headers=headers, timeout=8)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            page_links = []
            for a in soup.find_all('a', class_='result__url', href=True):
                raw_href = a['href']
                if 'uddg=' in raw_href:
                    real_u = unquote(raw_href.split('uddg=')[1].split('&')[0])
                    page_links.append(real_u)
                elif raw_href.startswith('http'):
                    page_links.append(raw_href)

            for page in page_links[:4]:
                try:
                    pr = requests.get(page, headers=headers, timeout=6)
                    psoup = BeautifulSoup(pr.text, 'html.parser')
                    for lk in psoup.find_all('a', href=True):
                        href = lk['href']
                        if href.endswith('.mp3') and ('320' in href or 'music' in href or 'dl' in href):
                            if href not in found_urls:
                                found_urls.append(href)
                                if len(found_urls) >= 3:
                                    return found_urls
                except Exception:
                    continue
        except Exception:
            continue
            
    return found_urls

def download_file_stream(url: str, out_path: str) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, stream=True, timeout=25)
        if r.status_code == 200:
            with open(out_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=32768):
                    if chunk: f.write(chunk)
            return True
    except Exception:
        pass
    return False

# ==================== استخراج عنوان از لینک ریلز ====================
def extract_reel_metadata(url: str) -> str:
    try:
        shortcode_match = re.search(r'/(?:reel|reels|p)/([A-Za-z0-9_-]+)', url)
        if shortcode_match:
            code = shortcode_match.group(1)
            oembed = f"https://api.instagram.com/oembed/?url=https://www.instagram.com/p/{code}/"
            r = requests.get(oembed, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            if r.status_code == 200:
                t = r.json().get('title', '')
                f = re.findall(r'(?:موزیک|آهنگ|اهنگ|music|song|track)\s*[:：\-]?\s*([^\n\r#@]+)', t, re.IGNORECASE)
                if f: return clean_song_query(f[0])
                first_l = clean_song_query(t.split('\n')[0])
                if len(first_l) > 2: return first_l
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
        "یک بخش را انتخاب فرمایید:"
    )
    kb = [
        [InlineKeyboardButton("📊 آمار کاربران", callback_data="admin_stats")],
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

# ==================== هندلرهای پیام ====================
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
        await update.message.reply_text("<b>برای فعال‌سازی ابتدا در کانال عضو شوید:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    welcome_text = (
        "🎧 <b>ربات مستقل دانلود و استخراج آهنگ کامل (۳۲۰)</b>\n\n"
        "⚡️ نام آهنگ، نام خواننده یا لینک ریلز را ارسال کنید تا نسخه ۳۲۰ کامل تحویل داده شود."
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
                await update.message.reply_text("❌ فقط عدد بفرستید.")
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
                await update.message.reply_text("❌ فقط عدد بفرستید.")
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
                await update.message.reply_text(f"✅ {amount} اعتبار اضافه شد.", parse_mode="HTML")
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
        await update.message.reply_text("لطفاً ابتدا در کانال عضو شوید.", reply_markup=InlineKeyboardMarkup(kb))
        return

    cursor.execute("SELECT requests_left, is_vip FROM users WHERE user_id = ?", (user_id,))
    u = cursor.fetchone()
    req_left, is_vip = (u[0], u[1]) if u else (0, 0)

    if not is_vip and req_left <= 0:
        bot_user = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_user}?start={user_id}"
        msg = f"🔒 <b>اعتبار رایگان شما تمام شده است!</b>\n\nبرای شارژ، لینک زیر را بفرستید:\n<code>{invite_link}</code>"
        kb = [[InlineKeyboardButton("⭐️ خرید اشتراک VIP", callback_data="buy_vip")]]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    text = update.message.text.strip()

    # تشخیص لینک یا متن
    if is_link(text):
        if not consume_credit(user_id):
            await update.message.reply_text("اعتبار شما به پایان رسیده است.")
            return

        status = await update.message.reply_text("🔍 <b>در حال استخراج نام اثر از ریلز...</b>", parse_mode="HTML")
        extracted_name = extract_reel_metadata(text)
        if extracted_name:
            await status.edit_text(f"🎯 <b>اثر شناسایی شد:</b> <code>{html.escape(extracted_name)}</code>\n⚡️ در حال جستجو و دانلود نسخه ۳۲۰...", parse_mode="HTML")
            await search_and_deliver_best_mp3(extracted_name, update.message.chat_id, context, status)
        else:
            await status.edit_text("❌ نام ریلز خوانده نشد؛ لطفاً **نام آهنگ یا خواننده را مستقیماً تایپ کنید** تا فوراً فایل ۳۲۰ آماده شود.")
        return

    # پردازش متنی مستقیم
    if not consume_credit(user_id):
        await update.message.reply_text("اعتبار شما تمام شده است.")
        return

    status = await update.message.reply_text(f"🔍 <b>در حال جستجوی نسخه اصلی ۳۲۰ «{html.escape(text)}»...</b>", parse_mode="HTML")
    await search_and_deliver_best_mp3(text, update.message.chat_id, context, status)

# ==================== تابع توزیع و دانلود موزیک ۳۲۰ ====================
async def search_and_deliver_best_mp3(query_text: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, status_msg):
    uid = uuid.uuid4().hex[:8]
    out_file = f"song_{uid}.mp3"
    
    # اولویت ۱: موتور وب مستقل (بدون وابستگی به یوتیوب و بدون ارور پلیر)
    mp3_links = search_direct_web_mp3(query_text)
    for link in mp3_links:
        if download_file_stream(link, out_file):
            if os.path.exists(out_file) and os.path.getsize(out_file) > 1024 * 1024:
                caption = f"🎵 <b>{html.escape(query_text)}</b>\n🔥 نسخه کامل استودیویی ۳۲۰\n🤖 {BOT_USERNAME}"
                with open(out_file, 'rb') as f:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        title=query_text,
                        performer="Studio Master",
                        caption=caption,
                        parse_mode="HTML"
                    )
                await status_msg.delete()
                clean_files(f"song_{uid}")
                return

    # اولویت ۲: کلاینت‌های ضدبلاک جایگزین وب (fallback)
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"song_{uid}.%(ext)s",
            'quiet': True,
            'extractor_args': {
                'youtube': {'player_client': ['web_creator', 'tv']}
            },
            'http_headers': {'User-Agent': 'Mozilla/5.0'}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch1:{query_text} audio", download=True)
            entries = res.get('entries', [])
            if entries:
                f_path = get_output_file(f"song_{uid}")
                if f_path:
                    with open(f_path, 'rb') as f:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=f,
                            title=query_text,
                            caption=f"🎵 <b>{html.escape(query_text)}</b>\n🤖 {BOT_USERNAME}",
                            parse_mode="HTML"
                        )
                    await status_msg.delete()
                    clean_files(f"song_{uid}")
                    return
    except Exception:
        pass

    clean_files(f"song_{uid}")
    await status_msg.edit_text("❌ قطعه‌ای با این نام در سرورها یافت نشد. لطفاً نام لاتین یا دقیق‌تر آن را بفرستید.")

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

# وب‌سرور Render
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
app.add_handler(CallbackQueryHandler(button_click))

print("ربات با موتور جستجوی سراسری وب فعال شد...")
app.run_polling()
