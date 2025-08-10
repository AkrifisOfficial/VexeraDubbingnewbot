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


    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        self.states[user.id] = {'step': None}
        
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n"
            "Я бот для просмотра аниме с озвучкой VexeraDubbing.\n\n"
            "Используй /menu для просмотра доступного аниме."
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать меню с аниме"""
        keyboard = [
            [InlineKeyboardButton(self.current_anime['title'], callback_data=f"anime_{self.current_anime['id']}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🎌 Доступное аниме:",
            reply_markup=reply_markup
        )

    async def anime_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать детали аниме"""
        query = update.callback_query
        await query.answer()
        
        # Заглушка для серий
        episodes = [
            (1, "https://vk.com/video-12345678_456239017"),
            (2, "https://vk.com/video-12345678_456239018")
        ]
        
        # Формируем клавиатуру с сериями
        episodes_buttons = [
            [InlineKeyboardButton(f"▶️ Серия {num}", callback_data=f"episode_{self.current_anime['id']}_{num}")]
            for num, _ in episodes
        ]
        
        # Добавляем кнопку назад
        control_buttons = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(episodes_buttons + control_buttons)
        
        await query.edit_message_text(
            f"📺 <b>{self.current_anime['title']}</b>\n\n"
            f"{self.current_anime['description']}\n\n"
            f"🔢 Доступно серий: {len(episodes)}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    async def watch_episode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать серию"""
        query = update.callback_query
        await query.answer()
        
        _, anime_id, episode_num = query.data.split('_')
        
        # Получаем ссылку на серию (заглушка)
        vk_url = "https://vk.com/video-12345678_456239017"
        
        # Отправляем ссылку как текст (будет открываться в TG)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🎥 Серия {episode_num}:\n{vk_url}"
        )

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Вернуться в меню"""
        query = update.callback_query
        await query.answer()
        await self.menu(query.message, context)

    async def admin_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Аутентификация администратора"""
        user = update.effective_user
        args = context.args
        
        if not args:
            await update.message.reply_text(
                "🔒 Для входа введите:\n"
                f"/auth <пароль>"
            )
            return
        
        if args[0] == ADMIN_PASSWORD:
            self.states[user.id] = {'is_admin': True}
            await update.message.reply_text("✅ Вы успешно авторизованы!")
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
            [InlineKeyboardButton("➕ Добавить серии", callback_data="admin_add_episodes")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "⚙️ Панель администратора:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "⚙️ Панель администратора:",
                reply_markup=reply_markup
            )

    async def add_episodes_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик добавления серий"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        self.states[user.id]['step'] = 'awaiting_episodes'
        
        await query.edit_message_text(
            "📤 Отправьте номер серии и ссылку на видео VK в формате:\n"
            "<code>Номер | URL</code>\n\n"
            "Пример:\n"
            "<code>1 | https://vk.com/video-12345678_456239017</code>\n\n"
            "Для отмены введите /cancel",
            parse_mode="HTML"
        )

    async def process_episode_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка данных новой серии"""
        user = update.effective_user
        if self.states.get(user.id, {}).get('step') != 'awaiting_episodes':
            return
        
        try:
            data = update.message.text.split('|')
            if len(data) < 2:
                await update.message.reply_text(
                    "❌ Неверный формат. Нужно: Номер | URL\n"
                    "Попробуйте еще раз:"
                )
                return
            
            episode_num = int(data[0].strip())
            vk_url = data[1].strip()
            
            if "vk.com/video" not in vk_url:
                await update.message.reply_text("❌ Поддерживаются только ссылки VK")
                return
            
            # Здесь должна быть логика сохранения в БД
            # add_episode_to_db(self.current_anime['id'], episode_num, vk_url)
            
            await update.message.reply_text(
                f"✅ Серия {episode_num} успешно добавлена!"
            )
            
            self.states[user.id]['step'] = None
            await self.show_admin_panel(update, context)
            
        except ValueError:
            await update.message.reply_text(
                "❌ Номер серии должен быть числом. Попробуйте еще раз:"
            )
        except Exception as e:
            logger.error(f"Error adding episode: {e}")
            await update.message.reply_text(
                "⚠️ Произошла ошибка. Попробуйте позже."
            )

    async def cancel_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущего действия"""
        user = update.effective_user
        self.states[user.id] = {'step': None}
        
        await update.message.reply_text("❌ Действие отменено")
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
    app.add_handler(CallbackQueryHandler(bot.add_episodes_handler, pattern="^admin_add_episodes$"))
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.process_episode_data))
    
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == '__main__':
    main()
