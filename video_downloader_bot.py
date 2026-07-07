import os
import json
import time
import re
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
import yt_dlp
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultVideo,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    filters,
    ContextTypes,
)

# ================== SOZLAMALAR ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8969856307:AAGfRXEtbZUaL_jZBamBtYD2iTfJmmLNyLo")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()]
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

SAVED_FILE = "saved_videos.json"
USERS_FILE = "users.json"
RATINGS_FILE = "ratings.json"

COOLDOWN_SECONDS = 8

URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(instagram\.com|youtube\.com|youtu\.be|tiktok\.com|vm\.tiktok\.com)/\S+"
)

# Render'ning "Secret Files" joylashuvi (/etc/secrets/) faqat o'qish uchun (read-only),
# lekin yt-dlp cookie faylini ba'zan yozishga urinadi. Shuning uchun uni yoziladigan
# joyga nusxalab olamiz.
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

# In-memory holatlar
last_request_time = {}
pending_urls = {}
pending_saves = {}
save_counter = {"value": 0}
ai_mode_users = set()


# ================== RENDER UCHUN KEEP-ALIVE SERVER ==================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlamoqda!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


# ================== KO'P TILLI MATNLAR ==================

TEXTS = {
    "uz": {
        "welcome": (
            "👋 Salom, *{name}*!\n\n"
            "🎬 Men *Instagram*, *YouTube* va *TikTok* dan video/audio yuklab beruvchi zamonaviy botman.\n\n"
            "*Qanday foydalanish kerak?*\n"
            "1️⃣ Menga video havolasini yuboring\n"
            "2️⃣ Format va sifatni tanlang\n"
            "3️⃣ Yuklanish jarayonini kuzating ⏳\n"
            "4️⃣ Tayyor bo'lgach, xohlasangiz *\"💾 Saqlash\"* tugmasi bilan botda saqlab qo'ying\n\n"
            "🤖 *\"AI bilan suhbat\"* tugmasi orqali menga istalgan savolingizni ham berishingiz mumkin!\n\n"
            "⚠️ Fayl hajmi 50MB dan oshsa, Telegram cheklovi tufayli yuborilmaydi."
        ),
        "menu_download": "🔗 Video yuklash",
        "menu_saved": "💾 Saqlangan videolarim",
        "menu_ai": "🤖 AI bilan suhbat",
        "menu_help": "🆘 Yordam",
        "menu_language": "🌐 Til",
        "ai_exit": "⬅️ AI rejimidan chiqish",
        "choose_language": "Tilni tanlang / Выберите язык / Choose language:",
        "language_set": "✅ Til o'zbek tiliga o'zgartirildi.",
        "ask_link": "🔗 Instagram, YouTube yoki TikTok havolasini yuboring.",
        "invalid_link": "Iltimos, faqat YouTube, Instagram yoki TikTok havolasini yuboring, yoki quyidagi menyudan foydalaning.",
        "cooldown": "⏱ Iltimos, {sec} soniya kuting va qayta urinib ko'ring.",
        "choose_format": "Qanday formatda yuklab beray?",
        "quality_best": "🎬 Eng yaxshi sifat",
        "quality_720": "📺 720p",
        "quality_480": "📱 480p",
        "quality_audio": "🎵 Audio (MP3)",
        "format_selected": "✅ Tanlandi: {choice}",
        "no_url_found": "⚠️ Havola topilmadi, qaytadan yuboring.",
        "starting": "⏳ Boshlanmoqda...",
        "downloading": "⏳ Yuklanmoqda...\n{bar} {percent:.0f}%",
        "uploading": "📤 Yuborilmoqda...",
        "size_limit": "⚠️ Fayl hajmi {size:.1f}MB — Telegramning 50MB cheklovidan katta, yuborib bo'lmaydi.",
        "download_failed": "❌ Yuklab bo'lmadi. Havola noto'g'ri, kontent o'chirilgan yoki akkaunt yopiq (private) bo'lishi mumkin.",
        "unexpected_error": "❌ Kutilmagan xatolik: {error}",
        "trying_image": "🖼 Video topilmadi, rasm sifatida urinib ko'ryapman...",
        "saved_ok": "✅ Saqlandi!",
        "already_saved": "ℹ️ Bu allaqachon saqlangan.",
        "save_expired": "⚠️ Bu tugma muddati o'tgan, videoni qayta yuklab ko'ring.",
        "deleted": "🗑 O'chirildi",
        "not_found": "❌ Topilmadi.",
        "no_saved": "📭 Sizda hali saqlangan videolar yo'q.\n\nVideo yuklab, ostidagi \"💾 Saqlash\" tugmasini bosing.",
        "saved_count": "💾 Sizda {count} ta saqlangan fayl bor:",
        "rate_prompt": "Yuklama sifatidan mamnunmisiz? Baholang:",
        "rate_thanks": "🙏 Rahmat, bahoyingiz uchun!",
        "ai_on": "🤖 AI rejimi yoqildi! Endi menga istalgan savolingizni yozing.\n\nChiqish uchun pastdagi tugmani bosing.",
        "ai_off": "✅ AI rejimidan chiqdingiz.",
        "ai_not_configured": "⚠️ AI hali sozlanmagan (GROQ_API_KEY topilmadi). Admin bilan bog'laning.",
        "ai_error": "❌ AI javob berishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        "help_text": (
            "🆘 *Yordam*\n\n"
            "*Bot qanday ishlaydi?*\n"
            "Instagram, YouTube yoki TikTok havolasini yuboring, so'ng format va sifatni tanlang.\n\n"
            "*Videoni qanday saqlab qo'yaman?*\n"
            "Yuklab bo'lingach, *\"💾 Saqlash\"* tugmasini bosing.\n\n"
            "*Buyruqlar:*\n"
            "/start — botni qayta ishga tushirish\n"
            "/help — yordam\n"
            "/language — tilni o'zgartirish"
        ),
    },
    "ru": {
        "welcome": (
            "👋 Привет, *{name}*!\n\n"
            "🎬 Я современный бот для скачивания видео/аудио с *Instagram*, *YouTube* и *TikTok*.\n\n"
            "*Как пользоваться?*\n"
            "1️⃣ Отправьте мне ссылку на видео\n"
            "2️⃣ Выберите формат и качество\n"
            "3️⃣ Дождитесь загрузки ⏳\n"
            "4️⃣ Нажмите *\"💾 Сохранить\"*, чтобы сохранить видео в боте\n\n"
            "🤖 Через кнопку *\"AI чат\"* вы можете задать мне любой вопрос!\n\n"
            "⚠️ Если файл больше 50МБ, Telegram не позволит его отправить."
        ),
        "menu_download": "🔗 Скачать видео",
        "menu_saved": "💾 Мои сохранённые",
        "menu_ai": "🤖 AI чат",
        "menu_help": "🆘 Помощь",
        "menu_language": "🌐 Язык",
        "ai_exit": "⬅️ Выйти из AI режима",
        "choose_language": "Tilni tanlang / Выберите язык / Choose language:",
        "language_set": "✅ Язык изменён на русский.",
        "ask_link": "🔗 Отправьте ссылку с Instagram, YouTube или TikTok.",
        "invalid_link": "Пожалуйста, отправьте только ссылку с YouTube, Instagram или TikTok, либо используйте меню ниже.",
        "cooldown": "⏱ Пожалуйста, подождите {sec} секунд и попробуйте снова.",
        "choose_format": "В каком формате скачать?",
        "quality_best": "🎬 Лучшее качество",
        "quality_720": "📺 720p",
        "quality_480": "📱 480p",
        "quality_audio": "🎵 Аудио (MP3)",
        "format_selected": "✅ Выбрано: {choice}",
        "no_url_found": "⚠️ Ссылка не найдена, отправьте заново.",
        "starting": "⏳ Начинаем...",
        "downloading": "⏳ Загрузка...\n{bar} {percent:.0f}%",
        "uploading": "📤 Отправка...",
        "size_limit": "⚠️ Размер файла {size:.1f}МБ — превышает лимит Telegram в 50МБ.",
        "download_failed": "❌ Не удалось скачать. Ссылка неверна, контент удалён или аккаунт закрыт.",
        "unexpected_error": "❌ Непредвиденная ошибка: {error}",
        "trying_image": "🖼 Видео не найдено, пробую скачать как изображение...",
        "saved_ok": "✅ Сохранено!",
        "already_saved": "ℹ️ Это уже сохранено.",
        "save_expired": "⚠️ Срок действия кнопки истёк, скачайте видео заново.",
        "deleted": "🗑 Удалено",
        "not_found": "❌ Не найдено.",
        "no_saved": "📭 У вас пока нет сохранённых видео.\n\nСкачайте видео и нажмите \"💾 Сохранить\".",
        "saved_count": "💾 У вас {count} сохранённых файлов:",
        "rate_prompt": "Довольны качеством загрузки? Оцените:",
        "rate_thanks": "🙏 Спасибо за вашу оценку!",
        "ai_on": "🤖 AI режим включён! Напишите мне любой вопрос.\n\nДля выхода нажмите кнопку ниже.",
        "ai_off": "✅ Вы вышли из AI режима.",
        "ai_not_configured": "⚠️ AI ещё не настроен (GROQ_API_KEY не найден). Обратитесь к администратору.",
        "ai_error": "❌ Произошла ошибка при ответе AI. Попробуйте позже.",
        "help_text": (
            "🆘 *Помощь*\n\n"
            "*Как работает бот?*\n"
            "Отправьте ссылку с Instagram, YouTube или TikTok, затем выберите формат и качество.\n\n"
            "*Как сохранить видео?*\n"
            "После скачивания нажмите *\"💾 Сохранить\"*.\n\n"
            "*Команды:*\n"
            "/start — перезапустить бота\n"
            "/help — помощь\n"
            "/language — сменить язык"
        ),
    },
    "en": {
        "welcome": (
            "👋 Hello, *{name}*!\n\n"
            "🎬 I'm a modern bot for downloading video/audio from *Instagram*, *YouTube* and *TikTok*.\n\n"
            "*How to use?*\n"
            "1️⃣ Send me a video link\n"
            "2️⃣ Choose format and quality\n"
            "3️⃣ Wait for the download ⏳\n"
            "4️⃣ Tap *\"💾 Save\"* to keep it in the bot\n\n"
            "🤖 You can also chat with me via the *\"AI Chat\"* button!\n\n"
            "⚠️ Files over 50MB can't be sent due to Telegram's limit."
        ),
        "menu_download": "🔗 Download video",
        "menu_saved": "💾 My saved videos",
        "menu_ai": "🤖 AI Chat",
        "menu_help": "🆘 Help",
        "menu_language": "🌐 Language",
        "ai_exit": "⬅️ Exit AI mode",
        "choose_language": "Tilni tanlang / Выберите язык / Choose language:",
        "language_set": "✅ Language set to English.",
        "ask_link": "🔗 Send an Instagram, YouTube or TikTok link.",
        "invalid_link": "Please send only a YouTube, Instagram or TikTok link, or use the menu below.",
        "cooldown": "⏱ Please wait {sec} seconds and try again.",
        "choose_format": "Which format should I download?",
        "quality_best": "🎬 Best quality",
        "quality_720": "📺 720p",
        "quality_480": "📱 480p",
        "quality_audio": "🎵 Audio (MP3)",
        "format_selected": "✅ Selected: {choice}",
        "no_url_found": "⚠️ Link not found, please send it again.",
        "starting": "⏳ Starting...",
        "downloading": "⏳ Downloading...\n{bar} {percent:.0f}%",
        "uploading": "📤 Uploading...",
        "size_limit": "⚠️ File size {size:.1f}MB exceeds Telegram's 50MB limit.",
        "download_failed": "❌ Couldn't download. The link may be invalid, content deleted, or account private.",
        "unexpected_error": "❌ Unexpected error: {error}",
        "trying_image": "🖼 No video found, trying to fetch it as an image...",
        "saved_ok": "✅ Saved!",
        "already_saved": "ℹ️ Already saved.",
        "save_expired": "⚠️ This button expired, please download the video again.",
        "deleted": "🗑 Deleted",
        "not_found": "❌ Not found.",
        "no_saved": "📭 You have no saved videos yet.\n\nDownload a video and tap \"💾 Save\".",
        "saved_count": "💾 You have {count} saved files:",
        "rate_prompt": "Happy with the download quality? Rate it:",
        "rate_thanks": "🙏 Thanks for your rating!",
        "ai_on": "🤖 AI mode enabled! Send me any question.\n\nTap the button below to exit.",
        "ai_off": "✅ You've exited AI mode.",
        "ai_not_configured": "⚠️ AI isn't configured yet (GROQ_API_KEY missing). Contact the admin.",
        "ai_error": "❌ An error occurred getting the AI response. Try again later.",
        "help_text": (
            "🆘 *Help*\n\n"
            "*How does the bot work?*\n"
            "Send an Instagram, YouTube or TikTok link, then choose format and quality.\n\n"
            "*How do I save a video?*\n"
            "After downloading, tap *\"💾 Save\"*.\n\n"
            "*Commands:*\n"
            "/start — restart the bot\n"
            "/help — help\n"
            "/language — change language"
        ),
    },
}

DEFAULT_LANG = "uz"


def t(lang: str, key: str, **kwargs) -> str:
    lang_dict = TEXTS.get(lang, TEXTS[DEFAULT_LANG])
    text = lang_dict.get(key, TEXTS[DEFAULT_LANG].get(key, key))
    return text.format(**kwargs) if kwargs else text


def build_main_menu(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [t(lang, "menu_download"), t(lang, "menu_saved")],
            [t(lang, "menu_ai"), t(lang, "menu_help")],
            [t(lang, "menu_language")],
        ],
        resize_keyboard=True,
    )


def build_ai_menu(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[t(lang, "ai_exit")]], resize_keyboard=True)


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
        users[key] = {"username": username or "noma'lum", "downloads": 0, "lang": DEFAULT_LANG}
        save_json(USERS_FILE, users)


def get_user_lang(user_id: int) -> str:
    users = load_json(USERS_FILE)
    return users.get(str(user_id), {}).get("lang", DEFAULT_LANG)


def set_user_lang(user_id: int, lang: str):
    users = load_json(USERS_FILE)
    key = str(user_id)
    if key not in users:
        users[key] = {"username": "noma'lum", "downloads": 0}
    users[key]["lang"] = lang
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


def add_rating(score: int):
    data = load_json(RATINGS_FILE)
    data["count"] = data.get("count", 0) + 1
    data["sum"] = data.get("sum", 0) + score
    save_json(RATINGS_FILE, data)


def get_average_rating():
    data = load_json(RATINGS_FILE)
    count = data.get("count", 0)
    if count == 0:
        return None, 0
    return data.get("sum", 0) / count, count


# ================== COOKIE PARSING ==================

def parse_netscape_cookies(cookies_path: str) -> dict:
    cookies = {}
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except Exception as e:
        print(f"[COOKIES O'QISH XATOLIK] {e}")
    return cookies


def fetch_instagram_image(url: str, cookies_path: str = None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    cookies = parse_netscape_cookies(cookies_path) if cookies_path and os.path.exists(cookies_path) else None

    resp = requests.get(url, headers=headers, cookies=cookies, timeout=15)
    resp.raise_for_status()

    match = re.search(r'<meta property="og:image" content="([^"]+)"', resp.text)
    if not match:
        return None

    image_url = match.group(1).replace("&amp;", "&")
    img_resp = requests.get(image_url, headers=headers, timeout=15)
    img_resp.raise_for_status()

    filename = os.path.join(DOWNLOAD_DIR, f"insta_image_{int(time.time())}.jpg")
    with open(filename, "wb") as f:
        f.write(img_resp.content)
    return filename


# ================== AI (Groq) ==================

async def ask_groq(user_text: str, lang: str) -> str:
    if not GROQ_API_KEY:
        return t(lang, "ai_not_configured")

    lang_names = {"uz": "Uzbek", "ru": "Russian", "en": "English"}
    system_prompt = f"You are a helpful, friendly AI assistant. Reply in {lang_names.get(lang, 'Uzbek')} language, concise and clear."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 1000,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[GROQ XATOLIK] {e}")
        return t(lang, "ai_error")


# ================== KOMANDALAR ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)
    lang = get_user_lang(user.id)

    welcome_text = t(lang, "welcome", name=user.first_name)
    await update.message.reply_text(
        welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=build_main_menu(lang)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(
        t(lang, "help_text"), parse_mode=ParseMode.MARKDOWN, reply_markup=build_main_menu(lang)
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🇺🇿 Oʻzbekcha", callback_data="lang:uz"),
                InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )
    await update.message.reply_text(t(lang, "choose_language"), reply_markup=keyboard)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Bu buyruq faqat adminlar uchun.")
        return

    users = load_json(USERS_FILE)
    total_users = len(users)
    total_downloads = sum(u.get("downloads", 0) for u in users.values())
    avg_rating, rating_count = get_average_rating()

    top_users = sorted(users.items(), key=lambda x: x[1].get("downloads", 0), reverse=True)[:5]
    top_text = "\n".join(
        f"{i+1}. @{u[1]['username']} — {u[1]['downloads']} ta"
        for i, u in enumerate(top_users)
    ) or "Ma'lumot yo'q"

    rating_text = f"{avg_rating:.1f} / 5 ({rating_count} ta baho)" if avg_rating else "Hali baho yo'q"

    text = f"""
📊 *Bot statistikasi*

👥 Jami foydalanuvchilar: *{total_users}*
📥 Jami yuklamalar: *{total_downloads}*
⭐ O'rtacha reyting: *{rating_text}*

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
    lang = get_user_lang(user_id)
    videos = get_saved_videos(user_id)

    if not videos:
        await update.message.reply_text(t(lang, "no_saved"), reply_markup=build_main_menu(lang))
        return

    await update.message.reply_text(t(lang, "saved_count", count=len(videos)))

    for i, video in enumerate(videos, start=1):
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑", callback_data=f"delete:{i - 1}")]]
        )
        caption = f"{i}. {video['title']}"
        if video.get("type") == "audio":
            await update.message.reply_audio(audio=video["file_id"], caption=caption, reply_markup=keyboard)
        elif video.get("type") == "photo":
            await update.message.reply_photo(photo=video["file_id"], caption=caption, reply_markup=keyboard)
        else:
            await update.message.reply_video(video=video["file_id"], caption=caption, reply_markup=keyboard)


# ================== HAVOLANI QABUL QILISH ==================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    register_user(user.id, user.username)
    lang = get_user_lang(user.id)

    # --- AI rejimidan chiqish ---
    if text == t(lang, "ai_exit"):
        ai_mode_users.discard(user.id)
        await update.message.reply_text(t(lang, "ai_off"), reply_markup=build_main_menu(lang))
        return

    # --- AI rejimini yoqish ---
    if text == t(lang, "menu_ai"):
        ai_mode_users.add(user.id)
        await update.message.reply_text(t(lang, "ai_on"), reply_markup=build_ai_menu(lang))
        return

    # --- AI rejimida bo'lsa ---
    if user.id in ai_mode_users:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        answer = await ask_groq(text, lang)
        await update.message.reply_text(answer, reply_markup=build_ai_menu(lang))
        return

    if text == t(lang, "menu_download"):
        await update.message.reply_text(t(lang, "ask_link"))
        return
    if text == t(lang, "menu_saved"):
        await show_saved_videos(update, context)
        return
    if text == t(lang, "menu_help"):
        await help_command(update, context)
        return
    if text == t(lang, "menu_language"):
        await language_command(update, context)
        return

    if not URL_PATTERN.search(text):
        await update.message.reply_text(t(lang, "invalid_link"))
        return

    # --- Cooldown ---
    now = time.time()
    last = last_request_time.get(user.id, 0)
    if now - last < COOLDOWN_SECONDS:
        wait = int(COOLDOWN_SECONDS - (now - last))
        await update.message.reply_text(t(lang, "cooldown", sec=wait))
        return
    last_request_time[user.id] = now

    pending_urls[user.id] = text

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "quality_best"), callback_data="fmt:best")],
            [
                InlineKeyboardButton(t(lang, "quality_720"), callback_data="fmt:720"),
                InlineKeyboardButton(t(lang, "quality_480"), callback_data="fmt:480"),
            ],
            [InlineKeyboardButton(t(lang, "quality_audio"), callback_data="fmt:audio")],
        ]
    )
    await update.message.reply_text(t(lang, "choose_format"), reply_markup=keyboard)


# ================== YUKLASH JARAYONI ==================

def build_format_string(quality: str) -> str:
    if quality == "720":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    if quality == "480":
        return "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    return "bestvideo+bestaudio/best"  # "best"


async def do_download(update_message, context: ContextTypes.DEFAULT_TYPE, url: str, quality: str, user_id: int, lang: str):
    status_msg = await update_message.reply_text(t(lang, "starting"))
    await context.bot.send_chat_action(chat_id=update_message.chat_id, action=ChatAction.UPLOAD_VIDEO)

    last_percent = {"value": -10}

    def progress_hook(d):
        if d["status"] == "downloading":
            percent_str = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                percent = float(percent_str)
            except ValueError:
                return
            if percent - last_percent["value"] >= 10:
                last_percent["value"] = percent
                bar_filled = int(percent // 10)
                bar = "🟩" * bar_filled + "⬜" * (10 - bar_filled)
                try:
                    context.application.create_task(
                        status_msg.edit_text(t(lang, "downloading", bar=bar, percent=percent))
                    )
                except Exception:
                    pass

    media_type = "audio" if quality == "audio" else "video"

    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "quiet": True,
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    }

    if COOKIES_PATH:
        ydl_opts["cookiefile"] = COOKIES_PATH

    if "youtube.com" in url or "youtu.be" in url:
        ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}

    if media_type == "audio":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]
    else:
        ydl_opts["format"] = build_format_string(quality)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if media_type == "audio":
                filename = os.path.splitext(filename)[0] + ".mp3"

        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        if file_size_mb > 50:
            os.remove(filename)
            await status_msg.edit_text(t(lang, "size_limit", size=file_size_mb))
            return

        await status_msg.edit_text(t(lang, "uploading"))
        title = info.get("title", "Nomsiz fayl")

        temp_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💾", callback_data="save_pending")]]
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

        save_counter["value"] += 1
        save_key = save_counter["value"]
        pending_saves[save_key] = {"file_id": real_file_id, "title": title, "media_type": media_type}

        new_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("💾", callback_data=f"save:{save_key}")]]
        )
        await sent_message.edit_reply_markup(reply_markup=new_keyboard)

        os.remove(filename)
        await status_msg.delete()
        increment_download_count(user_id)

        # --- Reyting so'rash ---
        rating_keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⭐" * n, callback_data=f"rate:{n}") for n in range(1, 6)]]
        )
        await update_message.reply_text(t(lang, "rate_prompt"), reply_markup=rating_keyboard)

    except yt_dlp.utils.DownloadError as e:
        print(f"[YT-DLP XATOLIK] URL: {url}\nSabab: {e}")

        if "instagram.com" in url:
            try:
                await status_msg.edit_text(t(lang, "trying_image"))
                image_path = fetch_instagram_image(url, COOKIES_PATH)

                if image_path:
                    title = "Instagram rasm"
                    temp_keyboard = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("💾", callback_data="save_pending")]]
                    )
                    with open(image_path, "rb") as f:
                        sent_message = await update_message.reply_photo(
                            photo=f, caption=title, reply_markup=temp_keyboard
                        )
                    real_file_id = sent_message.photo[-1].file_id

                    save_counter["value"] += 1
                    save_key = save_counter["value"]
                    pending_saves[save_key] = {"file_id": real_file_id, "title": title, "media_type": "photo"}
                    new_keyboard = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("💾", callback_data=f"save:{save_key}")]]
                    )
                    await sent_message.edit_reply_markup(reply_markup=new_keyboard)

                    os.remove(image_path)
                    await status_msg.delete()
                    increment_download_count(user_id)
                    return
            except Exception as img_err:
                print(f"[RASM YUKLASH XATOLIK] {img_err}")

        await status_msg.edit_text(t(lang, "download_failed"))
    except Exception as e:
        print(f"[KUTILMAGAN XATOLIK] URL: {url}\nSabab: {e}")
        await status_msg.edit_text(t(lang, "unexpected_error", error=e))


# ================== INLINE TUGMALAR ==================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    lang = get_user_lang(user_id)

    if data.startswith("lang:"):
        new_lang = data.split(":", 1)[1]
        set_user_lang(user_id, new_lang)
        await query.answer()
        await query.edit_message_text(t(new_lang, "language_set"))
        await query.message.reply_text(
            t(new_lang, "welcome", name=query.from_user.first_name),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_main_menu(new_lang),
        )
        return

    if data.startswith("fmt:"):
        quality = data.split(":", 1)[1]
        url = pending_urls.pop(user_id, None)
        await query.answer()

        labels = {
            "best": t(lang, "quality_best"),
            "720": t(lang, "quality_720"),
            "480": t(lang, "quality_480"),
            "audio": t(lang, "quality_audio"),
        }
        await query.edit_message_text(t(lang, "format_selected", choice=labels.get(quality, quality)))

        if not url:
            await query.message.reply_text(t(lang, "no_url_found"))
            return

        await do_download(query.message, context, url, quality, user_id, lang)
        return

    if data.startswith("rate:"):
        score = int(data.split(":", 1)[1])
        add_rating(score)
        await query.answer(t(lang, "rate_thanks"), show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if data.startswith("save:"):
        save_key = int(data.split(":", 1)[1])
        info = pending_saves.pop(save_key, None)

        if not info:
            await query.answer(t(lang, "save_expired"), show_alert=True)
            return

        added = add_saved_video(user_id, info["file_id"], info["title"], info["media_type"])
        if added:
            await query.answer(t(lang, "saved_ok"), show_alert=True)
        else:
            await query.answer(t(lang, "already_saved"), show_alert=True)
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
            await query.edit_message_caption(caption=t(lang, "deleted"))
        else:
            await query.answer(t(lang, "not_found"), show_alert=True)
        return

    await query.answer()


# ================== INLINE REJIM ==================
# Foydalanuvchi istalgan chatda "@BotUsername https://youtube.com/..." deb yozganda ishlaydi.
# Eslatma: bu rejim BotFather orqali yoqilishi kerak (/setinline).
# Faqat to'g'ridan-to'g'ri (progressive) format mavjud bo'lgan holatlarda ishlaydi —
# ko'pincha YouTube va TikTok uchun, Instagram uchun kafolatlanmaydi.

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.inline_query.query.strip()

    if not query_text or not URL_PATTERN.search(query_text):
        return

    try:
        ydl_opts = {
            "quiet": True,
            "noplaylist": True,
            "format": "best[ext=mp4]/best",
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
        }
        if COOKIES_PATH:
            ydl_opts["cookiefile"] = COOKIES_PATH

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query_text, download=False)

        direct_url = info.get("url")
        thumbnail = info.get("thumbnail", "")
        title = info.get("title", "Video")[:100]

        if not direct_url:
            results = [
                InlineQueryResultArticle(
                    id="no-direct-url",
                    title="⚠️ To'g'ridan-to'g'ri havola topilmadi",
                    description="Botga o'tib to'liq yuklab oling",
                    input_message_content=InputTextMessageContent(
                        f"Videoni yuklash uchun botga o'ting: {query_text}"
                    ),
                )
            ]
            await update.inline_query.answer(results, cache_time=5)
            return

        results = [
            InlineQueryResultVideo(
                id=str(info.get("id", "video")),
                video_url=direct_url,
                mime_type="video/mp4",
                thumbnail_url=thumbnail or "https://via.placeholder.com/150",
                title=title,
                description="Video yuklab olish",
            )
        ]
        await update.inline_query.answer(results, cache_time=5)

    except Exception as e:
        print(f"[INLINE XATOLIK] {e}")
        results = [
            InlineQueryResultArticle(
                id="error",
                title="⚠️ Xatolik yuz berdi",
                description="Botga o'tib qayta urinib ko'ring",
                input_message_content=InputTextMessageContent(
                    f"Videoni yuklash uchun botga o'ting: {query_text}"
                ),
            )
        ]
        await update.inline_query.answer(results, cache_time=5)


# ================== ISHGA TUSHIRISH ==================

def main():
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
