import os
import sys
import logging
import subprocess
from dotenv import load_dotenv
import psycopg2
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
DATABASE_URL = os.getenv('DATABASE_URL')

# Проверка конфигурации
if not all([BOT_TOKEN, DATABASE_URL]):
    print("ERROR: Missing required environment variables!")
    sys.exit(1)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== Database Functions =====================
def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anime (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    cover_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    id SERIAL PRIMARY KEY,
                    anime_id INTEGER REFERENCES anime(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL,
                    video_url TEXT NOT NULL,
                    file_id TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    is_admin BOOLEAN DEFAULT FALSE,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
    logger.info("Database initialized")

# ... (остальные database functions остаются без изменений)

# ===================== Video Processing =====================
def compress_video(input_path, output_path, target_size_mb=45):
    """Сжимает видео до указанного размера"""
    try:
        duration = float(subprocess.check_output(
            f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}",
            shell=True
        ).decode().strip())
        
        target_size_kb = target_size_mb * 8000
        bitrate = int(target_size_kb / duration)
        
        subprocess.run([
            'ffmpeg', '-i', input_path,
            '-vcodec', 'libx264',
            '-crf', '28',
            '-preset', 'fast',
            '-acodec', 'aac',
            '-b:v', f'{bitrate}k',
            output_path
        ], check=True)
        return True
    except Exception as e:
        logger.error(f"Video compression failed: {e}")
        return False

async def upload_video_to_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE, video_url: str, anime_id: int, episode_number: int):
    """Загружает видео в Telegram и возвращает file_id"""
    try:
        # Скачивание видео (реализация зависит от источника)
        # Здесь должен быть код для скачивания видео по URL
        # Например, используя yt-dlp или requests
        
        # Временные файлы
        input_path = f"temp_{anime_id}_{episode_number}.mp4"
        output_path = f"compressed_{anime_id}_{episode_number}.mp4"
        
        # Сжатие видео
        if not compress_video(input_path, output_path):
            raise Exception("Video compression failed")
        
        # Загрузка в Telegram
        with open(output_path, 'rb') as video_file:
            message = await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_file,
                caption=f"🎬 Серия {episode_number}",
                supports_streaming=True
            )
        
        # Сохраняем file_id в базу
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE episodes SET file_id = %s WHERE anime_id = %s AND number = %s",
                    (message.video.file_id, anime_id, episode_number)
                )
            conn.commit()
        
        # Удаляем временные файлы
        os.remove(input_path)
        os.remove(output_path)
        
        return message.video.file_id
    except Exception as e:
        logger.error(f"Video upload failed: {e}")
        return None

# ===================== Handlers =====================
async def watch_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик просмотра серии"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    anime_id = int(data[1])
    episode_number = int(data[2])
    
    episodes = get_episodes(anime_id)
    video_data = next((ep for ep in episodes if ep[0] == episode_number), None)
    
    if not video_data:
        await query.edit_message_text("Серия не найдена")
        return
    
    _, video_url, file_id = video_data
    anime = get_anime_details(anime_id)
    anime_title = anime[1] if anime else "Неизвестное аниме"
    
    # Проверяем, является ли видео из ВК
    is_vk_video = "vk.com" in video_url.lower()
    
    if is_vk_video:
        # Создаем клавиатуру с кнопками
        keyboard = [
            [InlineKeyboardButton("▶️ Смотреть в ВК", url=video_url)],
            [InlineKeyboardButton("🔙 Назад к аниме", callback_data=f"anime_{anime_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем постер с кнопками
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=anime[3] if anime and anime[3] else None,
            caption=f"🎬 <b>{anime_title}</b>\n🔹 Серия {episode_number}\n\nВидео доступно в ВК:",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    elif file_id:
        # Отправляем видео из Telegram
        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=file_id,
            caption=f"🎬 <b>{anime_title}</b>\n🔹 Серия {episode_number}",
            parse_mode="HTML",
            supports_streaming=True
        )
    else:
        # Просто отправляем ссылку
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🎬 <b>{anime_title}</b>\n🔹 Серия {episode_number}\n\nСсылка: {video_url}",
            parse_mode="HTML"
        )

# ... (остальные handlers остаются без изменений)

# ===================== Main =====================
def main():
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("auth", admin_auth))
    application.add_handler(CommandHandler("admin", admin_command))
    
    application.add_handler(CallbackQueryHandler(anime_details, pattern="^anime_"))
    application.add_handler(CallbackQueryHandler(watch_episode, pattern="^episode_"))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    
    # Админ-панель
    application.add_handler(CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(add_anime_handler, pattern="^admin_add_anime$"))
    application.add_handler(CallbackQueryHandler(add_episode_handler, pattern="^admin_add_episode$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(select_anime_for_episode, pattern="^admin_episode_"))
    application.add_handler(CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$"))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anime_data))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_episode_data))
    application.add_handler(MessageHandler(filters.VIDEO, receive_episode_data))
    
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
