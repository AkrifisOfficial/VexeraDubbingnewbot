import os
import sys
import logging
from dotenv import load_dotenv
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Загружаем переменные окружения из .env
load_dotenv()

# Загрузка переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
DATABASE_URL = os.getenv('DATABASE_URL')

# Проверка переменных
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set!")
    sys.exit(1)

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set!")
    sys.exit(1)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== Функции работы с PostgreSQL =====================
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
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    id SERIAL PRIMARY KEY,
                    total_users INTEGER DEFAULT 0,
                    total_anime INTEGER DEFAULT 0,
                    total_episodes INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
    logger.info("Database tables created or verified")

def update_stats():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users")
            users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM anime")
            anime = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM episodes")
            episodes = cursor.fetchone()[0]
            
            cursor.execute('''
                INSERT INTO stats (total_users, total_anime, total_episodes) 
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                total_users = EXCLUDED.total_users,
                total_anime = EXCLUDED.total_anime,
                total_episodes = EXCLUDED.total_episodes,
                last_updated = CURRENT_TIMESTAMP
            ''', (users, anime, episodes))
            conn.commit()

def add_anime(title, description, cover_url):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO anime (title, description, cover_url) VALUES (%s, %s, %s) RETURNING id",
                (title, description, cover_url)
            )
            anime_id = cursor.fetchone()[0]
        conn.commit()
    update_stats()
    return anime_id

def get_anime_list():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, title FROM anime ORDER BY title")
            return cursor.fetchall()

def get_anime_details(anime_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM anime WHERE id = %s", (anime_id,))
            return cursor.fetchone()

def get_episodes(anime_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT number, video_url FROM episodes WHERE anime_id = %s ORDER BY number", (anime_id,))
            return cursor.fetchall()

def add_episode(anime_id, number, video_url):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO episodes (anime_id, number, video_url) VALUES (%s, %s, %s)",
                (anime_id, number, video_url)
            )
        conn.commit()
    update_stats()

def set_admin(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id, is_admin) VALUES (%s, TRUE) "
                "ON CONFLICT (user_id) DO UPDATE SET is_admin = EXCLUDED.is_admin",
                (user_id,)
            )
        conn.commit()

def is_admin(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            return result and result[0]

# ===================== Обработчики команд =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Привет {user.first_name}!\n"
        "Я бот для просмотра аниме от озвучки VexeraDubbing.\n"
        "Используй /menu для просмотра доступного аниме."
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    anime_list = get_anime_list()
    
    if not anime_list:
        await update.message.reply_text("Аниме пока нет в базе данных.")
        return
    
    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"anime_{id}")]
        for id, title in anime_list
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите аниме:", reply_markup=reply_markup)

async def anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    anime_id = int(query.data.split('_')[1])
    anime = get_anime_details(anime_id)
    
    if not anime:
        await query.edit_message_text("Аниме не найдено")
        return
    
    _, title, description, cover_url = anime
    
    # Получаем список серий
    episodes = get_episodes(anime_id)
    
    if episodes:
        episodes_buttons = [
            [InlineKeyboardButton(f"Серия {number}", callback_data=f"episode_{anime_id}_{number}")]
            for number, _ in episodes
        ]
        keyboard = episodes_buttons
    else:
        keyboard = []
    
    keyboard.append([InlineKeyboardButton("Назад к списку", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Сначала отправляем постер с кнопками серий
    if cover_url:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=cover_url,
            caption=f"<b>{title}</b>\n\n{description}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    else:
        await query.edit_message_text(
            f"<b>{title}</b>\n\n{description}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

async def watch_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    anime_id = int(data[1])
    episode_number = int(data[2])
    
    episodes = get_episodes(anime_id)
    video_url = next((url for num, url in episodes if num == episode_number), None)
    
    if not video_url:
        await query.edit_message_text("Серия не найдена")
        return
    
    # Отправляем видео прямо в Telegram
    try:
        if video_url.startswith("http"):
            # Если это ссылка на видео
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_url,
                caption=f"Серия {episode_number}",
                supports_streaming=True
            )
        else:
            # Если это file_id видео в Telegram
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_url,
                caption=f"Серия {episode_number}",
                supports_streaming=True
            )
    except Exception as e:
        logger.error(f"Error sending video: {str(e)}")
        await query.edit_message_text("Ошибка при отправке видео")

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    anime_list = get_anime_list()
    
    if not anime_list:
        await query.edit_message_text("Аниме пока нет в базе данных.")
        return
    
    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"anime_{id}")]
        for id, title in anime_list
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите аниме:", reply_markup=reply_markup)

# ===================== Статистика =====================
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM stats ORDER BY last_updated DESC LIMIT 1")
            stats = cursor.fetchone()
            
            if stats:
                _, users, anime, episodes, updated = stats
                message = (
                    "📊 <b>Статистика бота</b>\n\n"
                    f"👥 Пользователей: <b>{users}</b>\n"
                    f"🎬 Аниме в базе: <b>{anime}</b>\n"
                    f"📺 Серий в базе: <b>{episodes}</b>\n"
                    f"🕒 Обновлено: <b>{updated.strftime('%Y-%m-%d %H:%M')}</b>"
                )
            else:
                message = "Статистика пока недоступна"
    
    await update.message.reply_text(message, parse_mode="HTML")

# ===================== Админ-панель =====================
async def admin_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if not args:
        await update.message.reply_text("Использование: /auth <пароль>")
        return
    
    if args[0] == ADMIN_PASSWORD:
        set_admin(user_id)
        await update.message.reply_text("✅ Вы вошли в админ-панель!")
        await show_admin_panel(update, context)
    else:
        await update.message.reply_text("❌ Неверный пароль")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await show_admin_panel(update, context)
    else:
        await update.message.reply_text(
            "❌ Вы не администратор!\n"
            "Используйте команду /auth <пароль> для доступа."
        )

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Доступ запрещен")
        return
    
    keyboard = [
        [InlineKeyboardButton("Добавить аниме", callback_data="admin_add_anime")],
        [InlineKeyboardButton("Добавить серию", callback_data="admin_add_episode")],
        [InlineKeyboardButton("Статистика", callback_data="admin_stats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Админ-панель:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("Админ-панель:", reply_markup=reply_markup)

async def add_anime_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Доступ запрещен")
        return
    
    await query.edit_message_text(
        "Отправьте данные в формате:\n"
        "<b>Название | Описание | URL обложки</b>\n\n"
        "Пример:\n"
        "Наруто | История о ниндзя | https://example.com/cover.jpg",
        parse_mode="HTML"
    )
    context.user_data['awaiting_anime_data'] = True

async def add_episode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Доступ запрещен")
        return
    
    anime_list = get_anime_list()
    if not anime_list:
        await query.edit_message_text("Сначала добавьте аниме")
        return
    
    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"admin_episode_{id}")]
        for id, title in anime_list
    ]
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="admin_cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите аниме:", reply_markup=reply_markup)

async def receive_anime_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'awaiting_anime_data' not in context.user_data:
        return
    
    try:
        data = update.message.text.split('|')
        if len(data) < 3:
            await update.message.reply_text("Неверный формат данных. Нужно: Название | Описание | URL обложки")
            return
        
        title = data[0].strip()
        description = data[1].strip()
        cover_url = data[2].strip()
        
        anime_id = add_anime(title, description, cover_url)
        await update.message.reply_text(f"✅ Аниме '{title}' добавлено! ID: {anime_id}")
        del context.user_data['awaiting_anime_data']
        
    except Exception as e:
        logger.error(f"Error adding anime: {e}")
        await update.message.reply_text("Ошибка при добавлении аниме")

async def select_anime_for_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    anime_id = int(query.data.split('_')[2])
    context.user_data['selected_anime_id'] = anime_id
    
    await query.edit_message_text(
        "Отправьте номер серии и видео одним из способов:\n"
        "1. Ссылку на видео (любой источник)\n"
        "2. Видеофайл с подписью\n\n"
        "Пример для ссылки:\n"
        "1 | https://example.com/episode1.mp4\n\n"
        "Пример для видеофайла:\n"
        "1 (в подписи к видео)",
        parse_mode="HTML"
    )

async def receive_episode_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'selected_anime_id' not in context.user_data:
        return
    
    try:
        anime_id = context.user_data['selected_anime_id']
        
        if update.message.video:
            # Если прислали видеофайл
            if not update.message.caption:
                await update.message.reply_text("Отправьте номер серии в подписи к видео")
                return
                
            episode_number = int(update.message.caption)
            video_file = await update.message.video.get_file()
            video_url = video_file.file_id  # Сохраняем file_id для Telegram
        else:
            # Если прислали текст с ссылкой
            data = update.message.text.split('|')
            if len(data) < 2:
                await update.message.reply_text("Неверный формат данных. Нужно: Номер серии | Ссылка")
                return
            
            episode_number = int(data[0].strip())
            video_url = data[1].strip()
        
        # Сохраняем в базу
        add_episode(anime_id, episode_number, video_url)
        await update.message.reply_text(f"✅ Серия {episode_number} добавлена!")
        
        del context.user_data['selected_anime_id']
        
    except ValueError:
        await update.message.reply_text("Номер серии должен быть числом")
    except Exception as e:
        logger.error(f"Error adding episode: {str(e)}")
        await update.message.reply_text(f"Ошибка при добавлении серии: {str(e)}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Доступ запрещен")
        return
    
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM stats ORDER BY last_updated DESC LIMIT 1")
            stats = cursor.fetchone()
            
            if stats:
                _, users, anime, episodes, updated = stats
                message = (
                    "📊 <b>Статистика бота</b>\n\n"
                    f"👥 Пользователей: <b>{users}</b>\n"
                    f"🎬 Аниме в базе: <b>{anime}</b>\n"
                    f"📺 Серий в базе: <b>{episodes}</b>\n"
                    f"🕒 Обновлено: <b>{updated.strftime('%Y-%m-%d %H:%M')}</b>"
                )
            else:
                message = "Статистика пока недоступна"
    
    await query.edit_message_text(message, parse_mode="HTML")

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_admin_panel(update, context)

# ===================== Главная функция =====================
def main():
    # Инициализация базы данных
    try:
        init_db()
        update_stats()  # Первоначальное обновление статистики
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("auth", admin_auth))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("stats", stats_command))  # Новая команда статистики
    
    # Обработчики CallbackQuery
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
    
    # Запуск бота
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == '__main'
