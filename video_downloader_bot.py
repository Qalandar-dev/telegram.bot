import os
import json
import time
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import yt_dlp
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ================== SOZLAMALAR ==================
# Render'da bu qiymatlar Environment Variables orqali beriladi.
# Lokal kompyuterda ishga tushirsangiz, pastdagi "SIZNING_BOT_TOKEN" ni to'g'ridan-to'g'ri o'zgartirsangiz ham bo'ladi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8969856307:AAGfRXEtbZUaL_jZBamBtYD2iTfJmmLNyLo")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()]

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Render'ning "Secret Files" joylashuvi (/etc/secrets/) faqat o'qish uchun (read-only),
# lekin yt-dlp cookie faylini ba'zan yozishga urinadi. Shuning uchun uni yoziladigan
# joyga (downloads papkasiga) nusxalab olamiz va o'sha nusxa bilan ishlaymiz.
COOKIES_WRITABLE_PATH = os.path.join(DOWNLOAD_DIR, "cookies.txt")

def prepare_cookies_file():
    import shutil
    for source in ("/etc/secrets/cookies.txt", "cookies.txt"):
        if os.path.exists(source):
            try:
                shutil.copy(source, COOKIES_WRITABLE_PATH)
                print(f"[COOKIES] {source} dan nusxa olindi: {COOKIES_WRITABLE_PATH}")
                return COOKIES_WRITABLE_PATH
            except Exception as e:
                print(f"[COOKIES XATOLIK] {e}")
    return None

COOKIES_PATH = prepare_cookies_file()


# ================== RENDER UCHUN KEEP-ALIVE SERVER ==================
# Render bepul tarifida bot "uxlab qolmasligi" uchun shu mini-server ishlaydi.
# UptimeRobot (yoki shunga o'xshash xizmat) shu manzilga muntazam so'rov yuborib turadi.

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlamoqda!")

    def log_message(self, format, *args):
        pass  # konsolni keraksiz loglar bilan to'ldirmaslik uchun


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

SAVED_FILE = "saved_videos.json"
USERS_FILE = "users.json"

COOLDOWN_SECONDS = 8  # bir foydalanuvchi ikkita so'rov orasidagi minimal vaqt

URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(instagram\.com|youtube\.com|youtu\.be|tiktok\.com|vm\.tiktok\.com)/\S+"
)

# --- Menu tugmalari ---
MENU_DOWNLOAD = "🔗 Video yuklash"
MENU_SAVED = "💾 Saqlangan videolarim"
MENU_HELP = "🆘 Yordam"

MAIN_MENU = ReplyKeyboardMarkup(
    [[MENU_DOWNLOAD, MENU_SAVED], [MENU_HELP]],
    resize_keyboard=True,
)

# So'rov vaqtlarini xotirada saqlash (cooldown uchun)
last_request_time = {}
# Foydalanuvchi yuborgan URL'ni vaqtincha saqlab turish (format tanlashi kutilayotganda)
pending_urls = {}
# Saqlash tugmasi bosilganda kerakli file_id/sarlavha ma'lumotini vaqtincha saqlab turish
# (Telegram callback_data uzunligi 64 bayt bilan cheklangani uchun file_id'ni to'g'ridan-to'g'ri tugmaga yozib bo'lmaydi)
pending_saves = {}
save_counter = {"value": 0}


# ================== MA'LUMOTLAR (JSON) ==================

def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_user(user_id: int, username: str):
    users = load_json(USERS_FILE)
    key = str(user_id)
    if key not in users:
        users[key] = {"username": username or "noma'lum", "downloads": 0}
        save_json(USERS_FILE, users)


def increment_download_count(user_id: int):
    users = load_json(USERS_FILE)
    key = str(user_id)
    if key in users:
        users[key]["downloads"] = users[key].get("downloads", 0) + 1
        save_json(USERS_FILE, users)


def add_saved_video(user_id: int, file_id: str, title: str, media_type: str):
    data = load_json(SAVED_FILE)
    key = str(user_id)
    if key not in data:
        data[key] = []
    if any(v["file_id"] == file_id for v in data[key]):
        return False
    data[key].append({"file_id": file_id, "title": title, "type": media_type})
    save_json(SAVED_FILE, data)
    return True


def get_saved_videos(user_id: int) -> list:
    return load_json(SAVED_FILE).get(str(user_id), [])


# ================== KOMANDALAR ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)

    welcome_text = f"""
👋 Salom, *{user.first_name}*!

🎬 Men *Instagram*, *YouTube* va *TikTok* dan video/audio yuklab beruvchi zamonaviy botman.

*Qanday foydalanish kerak?*
1️⃣ Menga video havolasini yuboring
2️⃣ 🎬 Video yoki 🎵 Audio formatini tanlang
3️⃣ Yuklanish jarayonini kuzating ⏳
4️⃣ Tayyor bo'lgach, xohlasangiz *"💾 Saqlash"* tugmasi bilan botda saqlab qo'ying

*Qo'llab-quvvatlanadigan platformalar:*
📸 Instagram — post, reels
▶️ YouTube — video, shorts
🎵 TikTok

⚠️ Fayl hajmi 50MB dan oshsa, Telegram cheklovi tufayli yuborilmaydi.

Quyidagi menyudan foydalaning yoki to'g'ridan-to'g'ri havola yuboring! 🚀
"""
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_MENU)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🆘 *Yordam*

*Bot qanday ishlaydi?*
Instagram, YouTube yoki TikTok havolasini yuboring, so'ng formatni tanlang.

*Videoni qanday saqlab qo'yaman?*
Yuklab bo'lingach, *"💾 Saqlash"* tugmasini bosing — keyin *"💾 Saqlangan videolarim"* bo'limidan qayta topasiz.

*Nega xatolik chiqyapti?*
• Havola noto'g'ri yoki video o'chirilgan
• Akkaunt yopiq (private)
• Fayl hajmi 50MB dan katta
• Juda tez-tez so'rov yuborilgan (biroz kuting)

*Buyruqlar:*
/start — botni qayta ishga tushirish
/help — yordam
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_MENU)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Bu buyruq faqat adminlar uchun.")
        return

    users = load_json(USERS_FILE)
    total_users = len(users)
    total_downloads = sum(u.get("downloads", 0) for u in users.values())

    top_users = sorted(users.items(), key=lambda x: x[1].get("downloads", 0), reverse=True)[:5]
    top_text = "\n".join(
        f"{i+1}. @{u[1]['username']} — {u[1]['downloads']} ta"
        for i, u in enumerate(top_users)
    ) or "Ma'lumot yo'q"

    text = f"""
📊 *Bot statistikasi*

👥 Jami foydalanuvchilar: *{total_users}*
📥 Jami yuklamalar: *{total_downloads}*

🏆 *Eng faol foydalanuvchilar:*
{top_text}
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Bu buyruq faqat adminlar uchun.")
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Foydalanish: /broadcast Xabar matni")
        return

    users = load_json(USERS_FILE)
    sent, failed = 0, 0
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=int(user_id), text=f"📢 {text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Yuborildi: {sent} ta\n❌ Xato: {failed} ta")


async def show_saved_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    videos = get_saved_videos(user_id)

    if not videos:
        await update.message.reply_text(
            "📭 Sizda hali saqlangan videolar yo'q.\n\n"
            "Video yuklab, ostidagi \"💾 Saqlash\" tugmasini bosing.",
            reply_markup=MAIN_MENU,
        )
        return

    await update.message.reply_text(f"💾 Sizda {len(videos)} ta saqlangan fayl bor:")

    for i, video in enumerate(videos, start=1):
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑 O'chirish", callback_data=f"delete:{i - 1}")]]
        )
        caption = f"{i}. {video['title']}"
        if video.get("type") == "audio":
            await update.message.reply_audio(audio=video["file_id"], caption=caption, reply_markup=keyboard)
        else:
            await update.message.reply_video(video=video["file_id"], caption=caption, reply_markup=keyboard)


# ================== HAVOLANI QABUL QILISH ==================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    register_user(user.id, user.username)

    if text == MENU_DOWNLOAD:
        await update.message.reply_text("🔗 Instagram, YouTube yoki TikTok havolasini yuboring.")
        return
    if text == MENU_SAVED:
        await show_saved_videos(update, context)
        return
    if text == MENU_HELP:
        await help_command(update, context)
        return

    if not URL_PATTERN.search(text):
        await update.message.reply_text(
            "Iltimos, faqat YouTube, Instagram yoki TikTok havolasini yuboring, "
            "yoki quyidagi menyudan foydalaning."
        )
        return

    # --- Cooldown tekshiruvi ---
    now = time.time()
    last = last_request_time.get(user.id, 0)
    if now - last < COOLDOWN_SECONDS:
        wait = int(COOLDOWN_SECONDS - (now - last))
        await update.message.reply_text(f"⏱ Iltimos, {wait} soniya kuting va qayta urinib ko'ring.")
        return
    last_request_time[user.id] = now

    # URL'ni vaqtincha saqlaymiz, formatni tanlaguncha
    pending_urls[user.id] = text

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎬 Video", callback_data="fmt:video"),
                InlineKeyboardButton("🎵 Audio (MP3)", callback_data="fmt:audio"),
            ]
        ]
    )
    await update.message.reply_text("Qanday formatda yuklab beray?", reply_markup=keyboard)


# ================== YUKLASH JARAYONI ==================

async def do_download(update_message, context: ContextTypes.DEFAULT_TYPE, url: str, media_type: str, user_id: int):
    status_msg = await update_message.reply_text("⏳ Boshlanmoqda...")
    await context.bot.send_chat_action(chat_id=update_message.chat_id, action=ChatAction.UPLOAD_VIDEO)

    last_percent = {"value": -10}

    def progress_hook(d):
        if d["status"] == "downloading":
            percent_str = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                percent = float(percent_str)
            except ValueError:
                return
            # Har 10% da bir marta yangilaymiz (Telegramni spam qilib qo'ymaslik uchun)
            if percent - last_percent["value"] >= 10:
                last_percent["value"] = percent
                bar_filled = int(percent // 10)
                bar = "🟩" * bar_filled + "⬜" * (10 - bar_filled)
                try:
                    context.application.create_task(
                        status_msg.edit_text(f"⏳ Yuklanmoqda...\n{bar} {percent:.0f}%")
                    )
                except Exception:
                    pass

    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "quiet": True,
        "noplaylist": True,
        "progress_hooks": [progress_hook],
    }

    # Instagram ko'pincha login (cookies) talab qiladi.
    if "instagram.com" in url and COOKIES_PATH:
        ydl_opts["cookiefile"] = COOKIES_PATH

    if media_type == "audio":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        ydl_opts["format"] = "mp4/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if media_type == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"

        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        if file_size_mb > 50:
            os.remove(filename)
            await status_msg.edit_text(
                f"⚠️ Fayl hajmi {file_size_mb:.1f}MB — Telegramning 50MB "
                f"cheklovidan katta, yuborib bo'lmaydi."
            )
            return

        await status_msg.edit_text("📤 Yuborilmoqda...")
        title = info.get("title", "Nomsiz fayl")

        temp_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💾 Saqlash", callback_data="save_pending")]]
        )

        with open(filename, "rb") as f:
            if media_type == "audio":
                sent_message = await update_message.reply_audio(
                    audio=f, title=title, caption=title, reply_markup=temp_keyboard
                )
                real_file_id = sent_message.audio.file_id
            else:
                sent_message = await update_message.reply_video(
                    video=f, caption=title, reply_markup=temp_keyboard
                )
                real_file_id = sent_message.video.file_id

        # file_id uzun bo'lgani uchun uni to'g'ridan-to'g'ri tugmaga yozib bo'lmaydi
        # (Telegram callback_data cheklovi — 64 bayt). Shuning uchun qisqa kalit yaratamiz.
        save_counter["value"] += 1
        save_key = save_counter["value"]
        pending_saves[save_key] = {
            "file_id": real_file_id,
            "title": title,
            "media_type": media_type,
        }

        new_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💾 Saqlash", callback_data=f"save:{save_key}")]]
        )
        await sent_message.edit_reply_markup(reply_markup=new_keyboard)

        os.remove(filename)
        await status_msg.delete()
        increment_download_count(user_id)

    except yt_dlp.utils.DownloadError as e:
        print(f"[YT-DLP XATOLIK] URL: {url}\nSabab: {e}")
        await status_msg.edit_text(
            "❌ Yuklab bo'lmadi. Havola noto'g'ri, kontent o'chirilgan "
            "yoki akkaunt yopiq (private) bo'lishi mumkin."
        )
    except Exception as e:
        print(f"[KUTILMAGAN XATOLIK] URL: {url}\nSabab: {e}")
        await status_msg.edit_text(f"❌ Kutilmagan xatolik: {e}")


# ================== INLINE TUGMALAR ==================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith("fmt:"):
        media_type = data.split(":", 1)[1]
        url = pending_urls.pop(user_id, None)
        await query.answer()
        await query.edit_message_text(f"✅ Tanlandi: {'🎵 Audio' if media_type == 'audio' else '🎬 Video'}")

        if not url:
            await query.message.reply_text("⚠️ Havola topilmadi, qaytadan yuboring.")
            return

        await do_download(query.message, context, url, media_type, user_id)
        return

    if data.startswith("save:"):
        save_key = int(data.split(":", 1)[1])
        info = pending_saves.pop(save_key, None)

        if not info:
            await query.answer("⚠️ Bu tugma muddati o'tgan, videoni qayta yuklab ko'ring.", show_alert=True)
            return

        added = add_saved_video(user_id, info["file_id"], info["title"], info["media_type"])
        if added:
            await query.answer("✅ Saqlandi!", show_alert=True)
        else:
            await query.answer("ℹ️ Bu allaqachon saqlangan.", show_alert=True)
        return

    if data.startswith("delete:"):
        index = int(data.split(":", 1)[1])
        all_data = load_json(SAVED_FILE)
        key = str(user_id)
        videos = all_data.get(key, [])
        await query.answer()
        if 0 <= index < len(videos):
            videos.pop(index)
            all_data[key] = videos
            save_json(SAVED_FILE, all_data)
            await query.edit_message_caption(caption="🗑 O'chirildi")
        else:
            await query.answer("❌ Topilmadi.", show_alert=True)
        return

    await query.answer()


# ================== ISHGA TUSHIRISH ==================

def main():
    # Keep-alive serverni alohida oqimda (thread) ishga tushiramiz,
    # shunda u botning asosiy ishlashiga xalaqit bermaydi.
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
