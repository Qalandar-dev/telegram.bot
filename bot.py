import os
import json
import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# 1. Loglarni sozlash (Xatoliklarni Render logs'da ko'rish uchun)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Baza fayli nomi
DB_FILE = "users_db.json"
ADMIN_ID = 7770204757  # ⚠️ DIQQAT: Bu yerga o'zingizning Telegram ID'angizni yozing!

# Foydalanuvchini bazaga qo'shish funksiyasi
def save_user(user_id, username):
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f:
            json.dump({}, f)
    
    with open(DB_FILE, "r") as f:
        data = json.load(f)
    
    if str(user_id) not in data:
        data[str(user_id)] = {"username": username or "Mavjud emas"}
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)

# Bazadagi barcha foydalanuvchilarni olish
def get_all_users():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

# --- KLAVIATURALAR ---
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🎮 Efootball Master", "ℹ️ Bot haqida"],
        ["⚙️ Sozlamalar", "👤 Profil"]
    ],
    resize_keyboard=True
)

# --- BUYRUKLAR (COMMANDS) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username) # Foydalanuvchini bazaga saqlaymiz
    
    welcome_text = (
        f"⚽️ **Assalomu alaykum, {user.first_name}!**\n\n"
        f"eFootball Master botiga xush kelibsiz! Bu yerda siz eng so'nggi yangiliklar, "
        f"taktikalar va turnirlar haqida ma'lumot olishingiz mumkin.\n\n"
        f"👇 Kerakli bo'limni tanlang:"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

# --- ADMIN PANEL (FAQAT ADMIN UCHUN) ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return # Agar admin bo'lmasa, buyruq ishlamaydi
        
    users = get_all_users()
    count = len(users)
    
    admin_text = (
        f"🖥 **Admin Panelga xush kelibsiz!**\n\n"
        f"👥 Jami foydalanuvchilar: `{count}` ta\n\n"
        f"📢 Hammaga xabar yuborish uchun: `/send [xabar matni]` ko'rinishida yozing."
    )
    await update.message.reply_text(admin_text, parse_mode="Markdown")

async def admin_send_reklama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
        
    # Buyruqdan keyingi matnni olish
    if not context.args:
        await update.message.reply_text("❌ Xato! Xabar matnini yozing. M-n: `/send Salom jamoa`")
        return
        
    reklama_text = " ".join(context.args)
    users = get_all_users()
    
    await update.message.reply_text(f"⏳ {len(users)} ta foydalanuvchiga xabar yuborish boshlandi...")
    
    success = 0
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=int(user_id), text=reklama_text)
            success += 1
        except Exception as e:
            logger.error(f"Xabar yuborilmadi {user_id}: {e}")
            
    await update.message.reply_text(f"✅ Xabar tarqatish yakunlandi!\n🎯 Muvaffaqiyatli yetkazildi: {success} ta.")

# --- MATNLARNI QAYTA ISHLASH (MESSAGE HANDLER) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    save_user(user.id, user.username) # Har ehtimolga qarshi bazani yangilash

    if text == "🎮 Efootball Master":
        # Chiroyli Inline tugmalar
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏆 Turnirlar", callback_data="turnir"),
             InlineKeyboardButton("📋 Taktikalar", callback_data="taktika")],
            [InlineKeyboardButton("🌐 Bizning Kanal", url="https://t.me/Google")] # O'zingizni kanalingiz linkini qo'ying
        ])
        await update.message.reply_text("🎮 Kerakli menyuni tanlang:", reply_markup=keyboard)
        
    elif text == "ℹ️ Bot haqida":
        await update.message.reply_text("ℹ️ Ushbu bot eFootball ishqibozlari uchun maxsus yaratilgan mukammal tizimdir.")
        
    elif text == "👤 Profil":
        profil_text = (
            f"👤 **Sizning Profilingiz:**\n\n"
            f"🆔 ID: `{user.id}`\n"
            f"✍️ Ism: {user.first_name}\n"
            f"🔗 Username: @{user.username or 'yoq'}"
        )
        await update.message.reply_text(profil_text, parse_mode="Markdown")
        
    elif text == "⚙️ Sozlamalar":
        await update.message.reply_text("⚙️ Sozlamalar bo'limi tez kunda ishga tushadi.")

# --- INLINE TUGMALAR JAVOBI (CALLBACK QUERY) ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Tugma bosilganda qotib qolmasligi uchun
    
    if query.data == "turnir":
        await query.message.edit_text("🏆 Hozirda faol turnirlar mavjud emas. Tez kunda yangi turnir start oladi!")
        
    elif query.data == "taktika":
        await query.message.edit_text("📋 Eng kuchli taktikalar:\n\n1. 4-2-1-3 (Hujumkor)\n2. 4-3-3 (Klassik)\n3. 5-2-2-1 (Himoyaviy)")

# --- XATOLIKLARNI BOSHqarish ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Botda kutilmagan xatolik yuz berdi:", exc_info=context.error)

# --- ASOSIY ISHGA TUSHIRISH (MAIN) ---
def main():
    # Render'dagi Environment Variables'dan tokenni olish
    TOKEN = os.getenv("BOT_TOKEN")
    
    if not TOKEN:
        print("❌ Xato: BOT_TOKEN topilmadi!")
        return

    # Bot ilovasini qurish
    app = Application.builder().token(TOKEN).build()

    # Handlerlarni ro'yxatdan o'tkazish
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("send", admin_send_reklama))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Xatolik signalini ulash
    app.add_error_handler(error_handler)

    # Botni ishga tushirish (Polling rejimida Render uchun eng qulayi)
    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()

if __name__ == '__main__':
    main()