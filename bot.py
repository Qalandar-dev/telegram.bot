import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# 🤫 TOKEN'ni xavfsiz joyda saqlash tavsiya etiladi
TOKEN = "8905601571:AAGr0PpNVZRT28UOuVA3bGzhiIH0rARI6BA"

# Futbolchilar ma'lumotlar bazasi
PLAYERS = {
    "🇦🇷 Messi": {
        "image": "images/messi.jpg",
        "info": "🏆 Epic Lionel Messi\n\n⭐ Reyting: 106\n🎯 Pozitsiya: RWF\n🦶 Chap oyoq\n🇦🇷 Argentina",
    },
    "🇵🇹 Ronaldo": {
        "image": "images/ronaldo.jpg",
        "info": "🏆 Epic Cristiano Ronaldo\n\n⭐ Reyting: 106\n🎯 Pozitsiya: CF\n🦶 O'ng oyoq\n🇵🇹 Portugaliya",
    },
    "🇧🇷 Neymar": {
        "image": "images/neymar.jpg",
        "info": "🏆 Epic Neymar Jr\n\n⭐ Reyting: 105\n🎯 Pozitsiya: LWF\n🦶 O'ng oyoq\n🇧🇷 Braziliya",
    },
    "🇧🇷 Ronaldinho": {
        "image": "images/ronaldinho.jpg",
        "info": "🏆 Epic Ronaldinho\n\n⭐ Reyting: 106\n🎯 Pozitsiya: AMF\n🦶 O'ng oyoq\n🇧🇷 Braziliya",
    },
}

# Asosiy menyu tugmalari
MAIN_KEYBOARD = [
    ["🏆 Epic kartalar"],
    ["⚽ O'yinchi qidirish", "📊 Reytinglar"],
    ["📰 Yangiliklar", "📅 Eventlar"],
]

# Epic menyu tugmalari
EPIC_KEYBOARD = [
    ["🇦🇷 Messi", "🇵🇹 Ronaldo"],
    ["🇧🇷 Neymar", "🇧🇷 Ronaldinho"],
    ["⬅️ Orqaga"],
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botni ishga tushirish va asosiy menyuni ko'rsatish"""
    await update.message.reply_text(
        "⚽ eFoot Hub botiga xush kelibsiz!\nKerakli bo'limni tanlang:",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi xabarlarini qayta ishlash"""
    text = update.message.text

    if text == "🏆 Epic kartalar":
        await update.message.reply_text(
            "Epic futbolchini tanlang:",
            reply_markup=ReplyKeyboardMarkup(EPIC_KEYBOARD, resize_keyboard=True),
        )

    elif text == "⬅️ Orqaga":
        await start(update, context)

    elif text in PLAYERS:
        player = PLAYERS[text]
        image_path = player["image"]
        info_text = player["info"]

        # Rasm mavjudligini tekshirish (Bot o'chib qolmasligi uchun)
        if os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=info_text)
        else:
            # Agar rasm topilmasa, faqat matnning o'zini yuboradi
            await update.message.reply_text(
                f"⚠️ Rasm topilmadi, lekin ma'lumotlar:\n\n{info_text}"
            )

    elif text == "⚽ O'yinchi qidirish":
        await update.message.reply_text(
            "🔍 O'yinchi nomini kiriting (Tez orada qidiruv tizimi qo'shiladi)."
        )

    elif text == "📊 Reytinglar":
        await update.message.reply_text("📊 Haftalik va umumiy reytinglar.")

    elif text == "📰 Yangiliklar":
        await update.message.reply_text("📰 eFootball yangiliklari tez orada qo'shiladi.")

    elif text == "📅 Eventlar":
        await update.message.reply_text(
            "📅 Yangi eventlar va sovg'alar ro'yxati tez orada."
        )


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu))

    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()