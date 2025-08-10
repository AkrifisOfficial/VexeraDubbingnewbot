import os
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
        self.states = {}  # Хранение состояний пользователей

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        self.states[user.id] = {'step': None}
        
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n"
            "Я помогу тебе смотреть аниме с озвучкой VexeraDubbing.\n\n"
            "📌 Доступные команды:\n"
            "/menu - Показать список аниме\n"
            "/auth - Вход для администраторов"
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать меню с аниме"""
        # Здесь должна быть логика получения списка аниме из БД
        anime_list = [
            (1, "Наруто"),
            (2, "Блич"),
            (3, "Ван Пис")
        ]
        
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
        """Показать детали аниме"""
        query = update.callback_query
        await query.answer()
        
        anime_id = int(query.data.split('_')[1])
        # Здесь должна быть логика получения информации об аниме из БД
        anime = {
            'title': "Наруто",
            'description': "История о юном ниндзя, который мечтает стать Хокаге",
            'cover_url': "https://example.com/naruto.jpg"
        }
        
        # Получаем список серий (заглушка)
        episodes = [(1, "https://example.com/ep1.mp4"), (2, "https://example.com/ep2.mp4")]
        
        # Формируем клавиатуру с сериями
        episodes_buttons = [
            [InlineKeyboardButton(f"▶️ Серия {num}", callback_data=f"episode_{anime_id}_{num}")]
            for num, _ in episodes
        ]
        
        # Добавляем кнопки управления
        control_buttons = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
            [InlineKeyboardButton("📥 Добавить серию", callback_data=f"add_episode_{anime_id}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(episodes_buttons + control_buttons)
        
        await query.edit_message_text(
            f"📺 <b>{anime['title']}</b>\n\n"
            f"{anime['description']}\n\n"
            f"🔢 Доступно серий: {len(episodes)}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        
        if anime.get('cover_url'):
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=anime['cover_url'],
                reply_to_message_id=query.message.message_id
            )

    async def watch_episode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать серию"""
        query = update.callback_query
        await query.answer()
        
        _, anime_id, episode_num = query.data.split('_')
        # Здесь должна быть логика получения ссылки на серию из БД
        video_url = "https://example.com/ep1.mp4"
        
        await context.bot.send_video(
            chat_id=query.message.chat_id,
            video=video_url,
            caption=f"🎥 Серия {episode_num}",
            supports_streaming=True
        )

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вернуться в меню"""
        await self.menu(update.callback_query.message, context)

    async def admin_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Аутентификация администратора"""
        user = update.effective_user
        args = context.args
        
        if not args:
            await update.message.reply_text(
                "🔒 Для входа введите:\n"
                f"/auth <пароль>\n\n"
                "Например: /auth MySecretPassword"
            )
            return
        
        if args[0] == ADMIN_PASSWORD:
            self.states[user.id] = {'is_admin': True}
            await update.message.reply_text(
                "✅ Вы успешно авторизованы как администратор!\n"
                "Теперь вам доступны дополнительные команды."
            )
            await self.show_admin_panel(update, context)
        else:
            await update.message.reply_text("❌ Неверный пароль")

    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать панель администратора"""
        user = update.effective_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await update.message.reply_text("🚫 Доступ запрещен")
            return
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить аниме", callback_data="admin_add_anime")],
            [InlineKeyboardButton("📤 Добавить серии", callback_data="admin_add_episodes")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚙️ <b>Панель администратора</b>",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    async def add_anime_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик добавления аниме"""
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
            "<code>Наруто | История о ниндзя | https://example.com/naruto.jpg</code>",
            parse_mode="HTML"
        )

    async def process_anime_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка данных нового аниме"""
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
            
            # Здесь должна быть логика сохранения в БД
            # add_anime_to_db(title, description, cover_url)
            
            self.states[user.id]['step'] = None
            await update.message.reply_text(
                f"✅ Аниме <b>{title}</b> успешно добавлено!",
                parse_mode="HTML"
            )
            await self.show_admin_panel(update, context)
            
        except Exception as e:
            logger.error(f"Error adding anime: {e}")
            await update.message.reply_text(
                "⚠️ Произошла ошибка при добавлении аниме. Попробуйте позже."
            )

    async def add_episodes_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик добавления серий"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        # Здесь должна быть логика получения списка аниме из БД
        anime_list = [(1, "Наруто"), (2, "Блич")]
        
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
        """Выбор аниме для добавления серий"""
        query = update.callback_query
        await query.answer()
        
        anime_id = int(query.data.split('_')[2])
        user = query.from_user
        
        self.states[user.id]['step'] = 'awaiting_episodes'
        self.states[user.id]['selected_anime'] = anime_id
        
        await query.edit_message_text(
            "📤 <b>Добавление серий</b>\n\n"
            "Отправьте номер серии и ссылку на видео в формате:\n"
            "<code>Номер | URL</code>\n\n"
            "Пример:\n"
            "<code>1 | https://example.com/ep1.mp4</code>\n\n"
            "Или отправьте видеофайл с подписью в формате:\n"
            "<code>Номер</code>\n\n"
            "Для отмены введите /cancel",
            parse_mode="HTML"
        )

    async def process_episode_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка данных новой серии"""
        user = update.effective_user
        if self.states.get(user.id, {}).get('step') != 'awaiting_episodes':
            return
        
        try:
            anime_id = self.states[user.id]['selected_anime']
            
            if update.message.video:
                # Если прислали видеофайл
                if not update.message.caption:
                    await update.message.reply_text("ℹ️ Укажите номер серии в подписи к видео")
                    return
                
                episode_num = int(update.message.caption)
                video_file = await update.message.video.get_file()
                video_url = video_file.file_path
            else:
                # Если прислали текст
                data = update.message.text.split('|')
                if len(data) < 2:
                    await update.message.reply_text(
                        "❌ Неверный формат. Нужно: Номер | URL\n"
                        "Попробуйте еще раз:"
                    )
                    return
                
                episode_num = int(data[0].strip())
                video_url = data[1].strip()
            
            # Здесь должна быть логика сохранения в БД
            # add_episode_to_db(anime_id, episode_num, video_url)
            
            await update.message.reply_text(
                f"✅ Серия {episode_num} успешно добавлена!"
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
        """Отмена текущего действия"""
        user = update.effective_user
        self.states[user.id] = {'step': None}
        
        await update.message.reply_text(
            "❌ Действие отменено",
            reply_markup=ReplyKeyboardRemove()
        )
        await self.show_admin_panel(update, context)

def main():
    """Запуск бота"""
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
    main()
