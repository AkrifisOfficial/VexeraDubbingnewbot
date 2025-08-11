import os
import sys
import logging
from dotenv import load_dotenv
import psycopg2
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
        conn.commit()
    logger.info("✅ База данных инициализирована")

def add_anime(title, description, cover_url):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO anime (title, description, cover_url) VALUES (%s, %s, %s) RETURNING id",
                (title, description, cover_url)
            )
            anime_id = cursor.fetchone()[0]
        conn.commit()
    logger.info(f"➕ Аниме добавлено: {title} (ID: {anime_id})")
    return anime_id

def get_anime_list():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, title FROM anime ORDER BY title")
            return cursor.fetchall()

def get_anime_details(anime_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, title, description, cover_url FROM anime WHERE id = %s", (anime_id,))
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
    logger.info(f"➕ Серия {number} добавлена для аниме ID {anime_id}")

def set_admin(user_id):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id, is_admin) VALUES (%s, TRUE) "
                "ON CONFLICT (user_id) DO UPDATE SET is_admin = EXCLUDED.is_admin",
                (user_id,)
            )
        conn.commit()
    logger.info(f"👑 Админские права выданы пользователю ID: {user_id}")

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
        f"👋 Привет, {user.first_name}!\n\n"
        "Я бот для просмотра аниме от озвучки VexeraDubbing.\n"
        "Воспользуйся командой /menu, чтобы посмотреть доступные аниме."
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        anime_list = get_anime_list()
        
        if not anime_list:
            await update.message.reply_text("📭 Список аниме пока пуст")
            return
        
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"anime_{id}")]
            for id, title in anime_list
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎌 Выберите аниме из списка:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка в функции menu: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка при загрузке списка аниме")

async def anime_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        anime_id = int(query.data.split('_')[1])
        anime = get_anime_details(anime_id)
        
        if not anime:
            await query.edit_message_text("⚠️ Аниме не найдено")
            return
        
        anime_id, title, description, cover_url = anime
        
        # Получаем список серий
        episodes = get_episodes(anime_id)
        
        keyboard = []
        if episodes:
            # Кнопки для каждой серии
            for number, video_url in episodes:
                keyboard.append([InlineKeyboardButton(f"▶️ Серия {number}", callback_data=f"episode_{anime_id}_{number}")])
        
        # Кнопка "Назад" в главное меню
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Редактируем текущее сообщение
        await query.edit_message_text(
            f"📺 <b>{title}</b>\n\n"
            f"{description}\n\n"
            f"🔢 Доступно серий: {len(episodes)}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        # Отправляем обложку отдельно
        if cover_url:
            try:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=cover_url,
                    caption=f"🎴 Обложка: {title}",
                    reply_to_message_id=query.message.message_id
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке обложки: {str(e)}")
    except Exception as e:
        logger.error(f"Ошибка в функции anime_details: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка при загрузке информации")

async def watch_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        data = query.data.split('_')
        anime_id = int(data[1])
        episode_number = int(data[2])
        
        episodes = get_episodes(anime_id)
        video_url = next((url for num, url in episodes if num == episode_number), None)
        
        if not video_url:
            await query.edit_message_text("⚠️ Серия не найдена")
            return
        
        # Отправляем видео или ссылку
        if video_url.startswith("http"):
            # Для ссылок ВКонтакте и других
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"🎥 Серия {episode_number}:\n{video_url}"
            )
        else:
            # Для прямых ссылок на видео
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_url,
                caption=f"🎬 Серия {episode_number}",
                supports_streaming=True
            )
    except Exception as e:
        logger.error(f"Ошибка в функции watch_episode: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка при загрузке серии")

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        # Получаем список аниме
        anime_list = get_anime_list()
        
        if not anime_list:
            await query.edit_message_text("📭 Список аниме пока пуст")
            return
        
        # Создаем клавиатуру с аниме
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"anime_{id}")]
            for id, title in anime_list
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Редактируем текущее сообщение
        await query.edit_message_text(
            "🎌 Выберите аниме из списка:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка в функции back_to_menu: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка при загрузке меню")

# ===================== Админ-панель =====================
async def admin_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        args = context.args
        
        if not args:
            await update.message.reply_text(
                "🔒 Для входа введите:\n"
                f"/auth <пароль>\n\n"
                "Например: /auth MySecretPassword"
            )
            return
        
        if args[0] == ADMIN_PASSWORD:
            set_admin(user_id)
            await update.message.reply_text(
                "✅ Вы успешно авторизованы как администратор!\n"
                "Используйте /admin для доступа к панели управления."
            )
        else:
            await update.message.reply_text("❌ Неверный пароль")
    except Exception as e:
        logger.error(f"Ошибка в функции admin_auth: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка при авторизации")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if not is_admin(user_id):
            await update.message.reply_text("🚫 Доступ запрещен")
            return
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить аниме", callback_data="admin_add_anime")],
            [InlineKeyboardButton("🎬 Добавить серию", callback_data="admin_add_episode")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚙️ <b>Панель администратора</b>",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка в функции admin_command: {str(e)}")
        await update.message.reply_text("⚠️ Произошла ошибка при загрузке панели")

async def add_anime_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        if not is_admin(query.from_user.id):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        await query.edit_message_text(
            "📝 <b>Добавление нового аниме</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>Название | Описание | URL обложки</code>\n\n"
            "Пример:\n"
            "<code>Наруто | История о ниндзя | https://example.com/naruto.jpg</code>",
            parse_mode="HTML"
        )
        context.user_data['awaiting_anime_data'] = True
    except Exception as e:
        logger.error(f"Ошибка в функции add_anime_handler: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка")

async def add_episode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        if not is_admin(query.from_user.id):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        anime_list = get_anime_list()
        if not anime_list:
            await query.edit_message_text("ℹ️ Сначала добавьте аниме")
            return
        
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"admin_episode_{id}")]
            for id, title in anime_list
        ]
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📺 Выберите аниме для добавления серии:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка в функции add_episode_handler: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка")

async def receive_anime_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if 'awaiting_anime_data' not in context.user_data:
            return
        
        data = update.message.text.split('|')
        if len(data) < 3:
            await update.message.reply_text(
                "❌ Неверный формат. Требуется:\n"
                "<code>Название | Описание | URL обложки</code>\n"
                "Попробуйте снова:"
            )
            return
        
        title = data[0].strip()
        description = data[1].strip()
        cover_url = data[2].strip()
        
        anime_id = add_anime(title, description, cover_url)
        await update.message.reply_text(
            f"✅ Аниме <b>{title}</b> успешно добавлено!",
            parse_mode="HTML"
        )
        del context.user_data['awaiting_anime_data']
        await admin_command(update, context)
    except Exception as e:
        logger.error(f"Ошибка в функции receive_anime_data: {str(e)}")
        await update.message.reply_text("⚠️ Ошибка при добавлении аниме")

async def select_anime_for_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        anime_id = int(query.data.split('_')[2])
        context.user_data['selected_anime_id'] = anime_id
        
        await query.edit_message_text(
            "📤 <b>Добавление серии</b>\n\n"
            "Отправьте номер серии и видео одним из способов:\n"
            "1. Ссылку на видео (ВКонтакте, YouTube и др.)\n"
            "2. Видеофайл с подписью\n\n"
            "Пример для ссылки:\n"
            "<code>1 | https://vk.com/video-12345678_456239017</code>\n\n"
            "Пример для видеофайла:\n"
            "<code>1</code> (в подписи к видео)",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка в функции select_anime_for_episode: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка")

async def receive_episode_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if 'selected_anime_id' not in context.user_data:
            return
        
        anime_id = context.user_data['selected_anime_id']
        
        if update.message.video:
            # Если прислали видеофайл
            if not update.message.caption:
                await update.message.reply_text("ℹ️ Укажите номер серии в подписи к видео")
                return
                
            episode_number = int(update.message.caption)
            video_file = await update.message.video.get_file()
            video_url = video_file.file_path  # Прямая ссылка на видео в Telegram
        else:
            # Если прислали текст с ссылкой
            data = update.message.text.split('|')
            if len(data) < 2:
                await update.message.reply_text(
                    "❌ Неверный формат. Требуется:\n"
                    "<code>Номер | Ссылка</code>\n"
                    "Попробуйте снова:"
                )
                return
            
            episode_number = int(data[0].strip())
            video_url = data[1].strip()
        
        # Сохраняем в базу
        add_episode(anime_id, episode_number, video_url)
        await update.message.reply_text(
            f"✅ Серия {episode_number} успешно добавлена!"
        )
        
        del context.user_data['selected_anime_id']
        await admin_command(update, context)
    except ValueError:
        await update.message.reply_text("❌ Номер серии должен быть числом")
    except Exception as e:
        logger.error(f"Ошибка в функции receive_episode_data: {str(e)}")
        await update.message.reply_text(f"⚠️ Ошибка при добавлении серии: {str(e)}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        if not is_admin(query.from_user.id):
            await query.edit_message_text("🚫 Доступ запрещен")
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
            "📊 <b>Статистика бота</b>\n\n"
            f"• 🎌 Аниме в базе: <b>{anime_count}</b>\n"
            f"• 🎬 Серий в базе: <b>{episodes_count}</b>\n"
            f"• 👑 Администраторов: <b>{admins_count}</b>"
        )
        
        await query.edit_message_text(stats_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в функции admin_stats: {str(e)}")
        await query.edit_message_text("⚠️ Произошла ошибка при загрузке статистики")

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await admin_command(update, context)

# ===================== Главная функция =====================
def main():
    # Инициализация базы данных с обработкой ошибок
    try:
        init_db()
        logger.info("✅ Бот запускается...")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
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
    application.add_handler(CallbackQueryHandler(admin_command, pattern="^admin_panel$"))
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
    logger.info("✅ Бот запущен и ожидает сообщений...")
    application.run_polling()

if __name__ == '__main__':
    main()
