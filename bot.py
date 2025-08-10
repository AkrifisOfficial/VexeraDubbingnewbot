import os
import sys
import re
import logging
from dotenv import load_dotenv
import psycopg2
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
VK_ACCESS_TOKEN = os.getenv('VK_ACCESS_TOKEN')  # Токен для VK API

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
                    cover_url TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    id SERIAL PRIMARY KEY,
                    anime_id INTEGER REFERENCES anime(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL,
                    video_url TEXT NOT NULL,
                    vk_video_id TEXT,
                    vk_owner_id TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    is_admin BOOLEAN DEFAULT FALSE
                )
            ''')
        conn.commit()
    logger.info("Database tables created or verified")

def add_anime(title, description, cover_url):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO anime (title, description, cover_url) VALUES (%s, %s, %s) RETURNING id",
                (title, description, cover_url)
            )
            anime_id = cursor.fetchone()[0]
        conn.commit()
    logger.info(f"Added anime: {title} (ID: {anime_id})")
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
            cursor.execute("SELECT number, video_url, vk_video_id, vk_owner_id FROM episodes WHERE anime_id = %s ORDER BY number", (anime_id,))
            return cursor.fetchall()

def add_episode(anime_id, number, video_url, vk_video_id=None, vk_owner_id=None):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO episodes (anime_id, number, video_url, vk_video_id, vk_owner_id) VALUES (%s, %s, %s, %s, %s)",
                (anime_id, number, video_url, vk_video_id, vk_owner_id)
            )
        conn.commit()
    logger.info(f"Added episode {number} for anime ID {anime_id}")

def set_admin(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id, is_admin) VALUES (%s, TRUE) "
                "ON CONFLICT (user_id) DO UPDATE SET is_admin = EXCLUDED.is_admin",
                (user_id,)
            )
        conn.commit()
    logger.info(f"Set admin privileges for user ID: {user_id}")

def is_admin(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            return result and result[0]

# ===================== Функции для работы с VK =====================
def parse_vk_url(url):
    """Извлекает owner_id и video_id из URL ВКонтакте"""
    pattern = r'vk\.com\/video(-?\d+_\d+)'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None

def get_vk_video_url(video_id):
    """Получает прямую ссылку на видео через VK API"""
    if not VK_ACCESS_TOKEN:
        logger.warning("VK_ACCESS_TOKEN not set! Cannot get direct video link.")
        return None
    
    try:
        response = requests.get(
            "https://api.vk.com/method/video.get",
            params={
                "access_token": VK_ACCESS_TOKEN,
                "videos": video_id,
                "v": "5.131"
            }
        ).json()
        
        if 'response' in response and 'items' in response['response']:
            video = response['response']['items'][0]
            # Ищем ссылку на видео с максимальным качеством
            if 'files' in video:
                # Приоритет: 1080p -> 720p -> 480p -> 360p
                for quality in ['mp4_1080', 'mp4_720', 'mp4_480', 'mp4_360']:
                    if quality in video['files']:
                        return video['files'][quality]
            
            # Если нет прямых ссылок, возвращаем ссылку на плеер
            return f"https://vk.com/video{video_id}"
        
        logger.error(f"VK API error: {response.get('error', 'Unknown error')}")
        return None
    except Exception as e:
        logger.error(f"Error getting VK video: {str(e)}")
        return None

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
            for number, _, _, _ in episodes
        ]
        keyboard = episodes_buttons
    else:
        keyboard = []
    
    keyboard.append([InlineKeyboardButton("Назад к списку", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Редактируем текущее сообщение вместо отправки нового
    await query.edit_message_text(
        f"<b>{title}</b>\n\n{description}",
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    
    # Отправляем обложку отдельно, если она есть
    if cover_url:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=cover_url,
            caption=f"Обложка: {title}",
            reply_to_message_id=query.message.message_id
        )

async def watch_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    anime_id = int(data[1])
    episode_number = int(data[2])
    
    episodes = get_episodes(anime_id)
    video_url = None
    vk_video_id = None
    vk_owner_id = None
    
    # Ищем нужную серию
    for num, url, vid, oid in episodes:
        if num == episode_number:
            video_url = url
            vk_video_id = vid
            vk_owner_id = oid
            break
    
    if not video_url:
        await query.edit_message_text("Серия не найдена")
        return
    
    # Если это VK видео, попробуем получить прямую ссылку
    if vk_video_id and vk_owner_id:
        full_vk_id = f"{vk_owner_id}_{vk_video_id}"
        direct_url = get_vk_video_url(full_vk_id)
        if direct_url:
            video_url = direct_url
    
    # Проверяем тип ссылки
    if video_url.startswith("http"):
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🎬 Серия {episode_number}:\n{video_url}"
        )
    else:
        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=video_url,
            caption=f"Серия {episode_number}",
            supports_streaming=True
        )

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Получаем список аниме
    anime_list = get_anime_list()
    
    if not anime_list:
        await query.edit_message_text("Аниме пока нет в базе данных.")
        return
    
    # Создаем клавиатуру с аниме
    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"anime_{id}")]
        for id, title in anime_list
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Редактируем текущее сообщение
    await query.edit_message_text(
        "Выберите аниме:",
        reply_markup=reply_markup
    )

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
    
    # Если команда вызвана из callback, редактируем сообщение
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
        "Отправьте номер серии и один из вариантов:\n"
        "1. Ссылку на видео ВКонтакте (например: https://vk.com/video-12345678_456239017)\n"
        "2. Прямую ссылку на видеофайл\n"
        "3. Видеофайл с подписью в формате: <b>Номер серии</b>\n\n"
        "Пример для VK:\n"
        "1 | https://vk.com/video-12345678_456239017\n\n"
        "Пример для прямой ссылки:\n"
        "1 | https://example.com/episode1.mp4",
        parse_mode="HTML"
    )

async def receive_episode_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'selected_anime_id' not in context.user_data:
        return
    
    try:
        anime_id = context.user_data['selected_anime_id']
        vk_video_id = None
        vk_owner_id = None
        
        if update.message.video:
            # Если прислали видеофайл
            if not update.message.caption:
                await update.message.reply_text("Отправьте номер серии в подписи к видео")
                return
                
            episode_number = int(update.message.caption)
            video_file = await update.message.video.get_file()
            video_url = video_file.file_path  # Прямая ссылка на видео в Telegram
        else:
            # Если прислали текст с ссылкой
            data = update.message.text.split('|')
            if len(data) < 2:
                await update.message.reply_text("Неверный формат данных. Нужно: Номер серии | Ссылка")
                return
            
            episode_number = int(data[0].strip())
            video_url = data[1].strip()
            
            # Проверяем, является ли ссылка VK видео
            vk_full_id = parse_vk_url(video_url)
            if vk_full_id:
                # Извлекаем owner_id и video_id
                parts = vk_full_id.split('_')
                if len(parts) == 2:
                    vk_owner_id = parts[0]
                    vk_video_id = parts[1]
                    
                    # Получаем прямую ссылку на видео
                    direct_url = get_vk_video_url(vk_full_id)
                    if direct_url:
                        video_url = direct_url
                        logger.info(f"Got direct VK video URL: {direct_url}")
                    else:
                        # Если не удалось получить прямую ссылку, используем оригинальный URL
                        video_url = f"https://vk.com/video{vk_full_id}"
                        logger.warning("Using VK page URL instead of direct link")
        
        # Сохраняем в базу
        add_episode(anime_id, episode_number, video_url, vk_video_id, vk_owner_id)
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
            cursor.execute("SELECT COUNT(*) FROM anime")
            anime_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM episodes")
            episodes_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
            admins_count = cursor.fetchone()[0]
    
    stats_text = (
        "📊 Статистика бота:\n"
        f"• Аниме в базе: {anime_count}\n"
        f"• Серий в базе: {episodes_count}\n"
        f"• Администраторов: {admins_count}"
    )
    
    await query.edit_message_text(stats_text)

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_admin_panel(update, context)

# ===================== Главная функция =====================
def main():
    # Инициализация базы данных с обработкой ошибок
    try:
        init_db()
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
    
    # Обработчики CallbackQuery
    application.add_handler(CallbackQueryHandler(anime_details, pattern="^anime_"))
    application.add_handler(CallbackQueryHandler(watch_episode, pattern="^episode_"))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    
    # Админ-панель
    application.add_handler(CallbackQueryHandler(show_admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(add_anime_handler, pattern="^admin_add_anime$"))
    application.add_handler(CallbackQueryHandler(ad
