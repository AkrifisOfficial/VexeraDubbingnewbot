import os
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

class AnimeBot:
    def __init__(self):
        self.states = {}
        self.db_conn = self.get_db_connection()

    def get_db_connection(self):
        """Установка соединения с базой данных"""
        return psycopg2.connect(os.getenv('DATABASE_URL'), sslmode='require')

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.states[user.id] = {'step': None}
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n"
            "Я бот для просмотра аниме с озвучкой VexeraDubbing.\n\n"
            "📌 Используй /menu для просмотра доступного аниме"
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT id, title FROM anime ORDER BY title")
            anime_list = cursor.fetchall()

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

    async def anime_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        anime_id = int(query.data.split('_')[1])
        
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT title, description, cover_url FROM anime WHERE id = %s", (anime_id,))
            anime = cursor.fetchone()
            
            cursor.execute("SELECT number FROM episodes WHERE anime_id = %s ORDER BY number", (anime_id,))
            episodes = cursor.fetchall()

        if not anime:
            await query.edit_message_text("❌ Аниме не найдено")
            return

        title, description, cover_url = anime
        
        episodes_buttons = [
            [InlineKeyboardButton(f"▶️ Серия {num}", callback_data=f"episode_{anime_id}_{num}")]
            for num, in episodes
        ]
        
        control_buttons = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
            [InlineKeyboardButton("📥 Добавить серию", callback_data=f"add_episode_{anime_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(episodes_buttons + control_buttons)
        
        await query.edit_message_text(
            f"📺 <b>{title}</b>\n\n"
            f"{description}\n\n"
            f"🔢 Доступно серий: {len(episodes)}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        if cover_url:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=cover_url,
                reply_to_message_id=query.message.message_id
            )

    async def watch_episode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        _, anime_id, episode_num = query.data.split('_')
        
        with self.db_conn.cursor() as cursor:
            cursor.execute(
                "SELECT video_url FROM episodes WHERE anime_id = %s AND number = %s",
                (anime_id, episode_num)
            )
            result = cursor.fetchone()
        
        if not result:
            await query.edit_message_text("❌ Серия не найдена")
            return
            
        video_url = result[0]
        
        if video_url.startswith('http'):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"🎥 Серия {episode_num}:\n{video_url}"
            )
        else:
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video_url,
                caption=f"🎥 Серия {episode_num}",
                supports_streaming=True
            )

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.menu(update.callback_query.message, context)

    async def admin_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        args = context.args
        
        if not args:
            await update.message.reply_text(
                "🔒 Для входа введите:\n"
                f"/auth <пароль>\n\n"
                "Пример: /auth MySecret123"
            )
            return
        
        if args[0] == ADMIN_PASSWORD:
            self.states[user.id] = {'is_admin': True}
            await update.message.reply_text(
                "✅ Вы успешно авторизованы как администратор!"
            )
            await self.show_admin_panel(update, context)
        else:
            await update.message.reply_text("❌ Неверный пароль")

    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await update.message.reply_text("🚫 Доступ запрещен")
            return
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить аниме", callback_data="admin_add_anime")],
            [InlineKeyboardButton("📤 Добавить серии", callback_data="admin_add_episodes")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "⚙️ <b>Панель администратора</b>",
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "⚙️ <b>Панель администратора</b>",
                parse_mode="HTML",
                reply_markup=reply_markup
            )

    async def add_anime_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        self.states[user.id]['step'] = 'awaiting_anime_data'
        await query.edit_message_text(
            "📝 <b>Добавление нового аниме</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>Название | Описание | URL_обложки</code>\n\n"
            "Пример:\n"
            "<code>Наруто | История о ниндзя | https://example.com/naruto.jpg</code>\n\n"
            "Для отмены введите /cancel",
            parse_mode="HTML"
        )

    async def process_anime_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if self.states.get(user.id, {}).get('step') != 'awaiting_anime_data':
            return
        
        try:
            data = update.message.text.split('|')
            if len(data) < 3:
                await update.message.reply_text(
                    "❌ Неверный формат. Нужно: Название | Описание | URL_обложки\n"
                    "Попробуйте еще раз:"
                )
                return
            
            title = data[0].strip()
            description = data[1].strip()
            cover_url = data[2].strip()
            
            with self.db_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO anime (title, description, cover_url) VALUES (%s, %s, %s) RETURNING id",
                    (title, description, cover_url)
                )
                anime_id = cursor.fetchone()[0]
                self.db_conn.commit()
            
            self.states[user.id]['step'] = None
            await update.message.reply_text(
                f"✅ Аниме <b>{title}</b> успешно добавлено! (ID: {anime_id})",
                parse_mode="HTML"
            )
            await self.show_admin_panel(update, context)
            
        except Exception as e:
            logger.error(f"Error adding anime: {e}")
            await update.message.reply_text(
                "⚠️ Произошла ошибка при добавлении аниме. Попробуйте позже."
            )

    async def add_episodes_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        with self.db_conn.cursor() as cursor:
            cursor.execute("SELECT id, title FROM anime ORDER BY title")
            anime_list = cursor.fetchall()
        
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"select_anime_{id}")]
            for id, title in anime_list
        ]
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📺 Выберите аниме для добавления серий:",
            reply_markup=reply_markup
        )

    async def select_anime_for_episodes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        anime_id = int(query.data.split('_')[2])
        user = query.from_user
        
        self.states[user.id]['step'] = 'awaiting_episodes'
        self.states[user.id]['selected_anime'] = anime_id
        
        await query.edit_message_text(
            "📤 <b>Добавление серий</b>\n\n"
            "Отправьте номер серии и ссылку на видео (VK или прямую) в формате:\n"
            "<code>Номер | URL</code>\n\n"
            "Примеры:\n"
            "<code>1 | https://vk.com/video-12345678_456239017</code>\n"
            "<code>2 | https://example.com/episode2.mp4</code>\n\n"
            "Или отправьте видеофайл с подписью в формате:\n"
            "<code>Номер</code>\n\n"
            "Для отмены введите /cancel",
            parse_mode="HTML"
        )

    def extract_vk_video_id(self, url):
        """Извлекает идентификатор видео из VK ссылки"""
        patterns = [
            r'vk\.com\/video(?P<owner_id>-?\d+)_(?P<video_id>\d+)',
            r'vk\.com\/video\.php\?.*id=(?P<video_id>\d+).*owner_id=(?P<owner_id>-?\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"{match.group('owner_id')}_{match.group('video_id')}"
        return None

    async def process_episode_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if self.states.get(user.id, {}).get('step') != 'awaiting_episodes':
            return
        
        try:
            anime_id = self.states[user.id]['selected_anime']
            
            if update.message.video:
                if not update.message.caption:
                    await update.message.reply_text("ℹ️ Укажите номер серии в подписи к видео")
                    return
                
                episode_num = int(update.message.caption)
                video_file = await update.message.video.get_file()
                video_url = video_file.file_path
            else:
                data = update.message.text.split('|')
                if len(data) < 2:
                    await update.message.reply_text(
                        "❌ Неверный формат. Нужно: Номер | URL\n"
                        "Попробуйте еще раз:"
                    )
                    return
                
                episode_num = int(data[0].strip())
                input_url = data[1].strip()
                
                # Обработка VK ссылки
                vk_video_id = self.extract_vk_video_id(input_url)
                video_url = f"https://vk.com/video{vk_video_id}" if vk_video_id else input_url
            
            with self.db_conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO episodes (anime_id, number, video_url) VALUES (%s, %s, %s)",
                    (anime_id, episode_num, video_url)
                )
                self.db_conn.commit()
            
            await update.message.reply_text(
                f"✅ Серия {episode_num} успешно добавлена!\n"
                f"Ссылка: {video_url}"
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ Номер серии должен быть числом. Попробуйте еще раз:"
            )
        except Exception as e:
            logger.error(f"Error adding episode: {e}")
            await update.message.reply_text(
                "⚠️ Произошла ошибка при добавлении серии. Попробуйте позже."
            )

    async def cancel_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.states[user.id] = {'step': None}
        
        await update.message.reply_text(
            "❌ Действие отменено"
        )
        await self.show_admin_panel(update, context)

def main():
    bot = AnimeBot()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Основные команды
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("menu", bot.menu))
    app.add_handler(CommandHandler("auth", bot.admin_auth))
    app.add_handler(CommandHandler("cancel", bot.cancel_action))
    
    # Обработчики callback-запросов
    app.add_handler(CallbackQueryHandler(bot.anime_details, pattern="^anime_"))
    app.add_handler(CallbackQueryHandler(bot.watch_episode, pattern="^episode_"))
    app.add_handler(CallbackQueryHandler(bot.back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(bot.show_admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(bot.add_anime_handler, pattern="^admin_add_anime$"))
    app.add_handler(CallbackQueryHandler(bot.add_episodes_handler, pattern="^admin_add_episodes$"))
    app.add_handler(CallbackQueryHandler(bot.select_anime_for_episodes, pattern="^select_anime_"))
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_anime_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_episode_data))
    app.add_handler(MessageHandler(filters.VIDEO, bot.process_episode_data))
    
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == '__main__':
    import psycopg2
    main()
