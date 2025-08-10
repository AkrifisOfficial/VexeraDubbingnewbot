import os
import logging
import re
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

        
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n"
            "Я помогу тебе смотреть аниме с озвучкой VexeraDubbing.\n\n"
            "📌 Доступные команды:\n"
            "/menu - Показать список аниме\n"
            "/auth - Вход для администраторов"
        )

    async def menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.anime_list:
            await update.message.reply_text("📭 Список аниме пока пуст")
            return
        
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"anime_{id}")]
            for id, title in self.anime_list
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
        anime = next((a for a in self.anime_list if a[0] == anime_id), None)
        
        if not anime:
            await query.edit_message_text("❌ Аниме не найдено")
            return
        
        episodes = self.episodes.get(anime_id, [])
        
        episodes_buttons = [
            [InlineKeyboardButton(f"▶️ Серия {num}", callback_data=f"episode_{anime_id}_{num}")]
            for num, _ in episodes
        ]
        
        control_buttons = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        
        if self.states.get(query.from_user.id, {}).get('is_admin'):
            control_buttons.append(
                [InlineKeyboardButton("📥 Добавить серию", callback_data=f"add_episode_{anime_id}")]
            )
        
        reply_markup = InlineKeyboardMarkup(episodes_buttons + control_buttons)
        
        await query.edit_message_text(
            f"📺 <b>{anime[1]}</b>\n\n"
            f"🔢 Доступно серий: {len(episodes)}",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    async def watch_episode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        _, anime_id, episode_num = query.data.split('_')
        anime_id = int(anime_id)
        episode_num = int(episode_num)
        
        episode = next((ep for ep in self.episodes.get(anime_id, []) if ep[0] == episode_num), None)
        
        if not episode:
            await query.edit_message_text("❌ Серия не найдена")
            return
        
        video_url = episode[1]
        
        # Проверяем, является ли ссылка VK видео
        if "vk.com/video" in video_url:
            # Извлекаем video_id из ссылки
            match = re.search(r'vk\.com\/video(-?\d+_\d+)', video_url)
            if match:
                video_id = match.group(1)
                # Формируем ссылку для просмотра в Telegram
                vk_play_url = f"https://vk.com/video{video_id}?embed"
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"🎥 Серия {episode_num}\n\n"
                         f"Ссылка для просмотра: {vk_play_url}\n\n"
                         "⚠️ Для просмотра нажмите на ссылку и выберите 'Открыть в приложении'"
                )
                return
        
        # Для обычных ссылок
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🎥 Серия {episode_num}\n\n{video_url}"
        )

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await self.menu(query.message, context)

    async def admin_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "Отправьте название аниме\n\n"
            "Для отмены введите /cancel",
            parse_mode="HTML"
        )

    async def process_anime_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if self.states.get(user.id, {}).get('step') != 'awaiting_anime_data':
            return
        
        title = update.message.text.strip()
        new_id = max([a[0] for a in self.anime_list], default=0) + 1
        self.anime_list.append((new_id, title))
        self.episodes[new_id] = []
        
        self.states[user.id]['step'] = None
        await update.message.reply_text(
            f"✅ Аниме <b>{title}</b> успешно добавлено!",
            parse_mode="HTML"
        )
        await self.show_admin_panel(update, context)

    async def add_episodes_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        if not self.states.get(user.id, {}).get('is_admin'):
            await query.edit_message_text("🚫 Недостаточно прав")
            return
        
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"select_anime_{id}")]
            for id, title in self.anime_list
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
            "Отправьте ссылку на видео ВКонтакте в формате:\n"
            "<code>https://vk.com/video-12345678_456239017</code>\n\n"
            "Для отмены введите /cancel",
            parse_mode="HTML"
        )

    async def process_episode_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if self.states.get(user.id, {}).get('step') != 'awaiting_episodes':
            return
        
        try:
            anime_id = self.states[user.id]['selected_anime']
            video_url = update.message.text.strip()
            
            # Проверяем, что это ссылка VK
            if "vk.com/video" not in video_url:
                await update.message.reply_text(
                    "❌ Это не ссылка на видео ВКонтакте. Попробуйте еще раз:"
                )
                return
            
            # Добавляем серию
            new_episode_num = len(self.episodes.get(anime_id, [])) + 1
            self.episodes.setdefault(anime_id, []).append((new_episode_num, video_url))
            
            await update.message.reply_text(
                f"✅ Серия {new_episode_num} успешно добавлена!"
            )
            
            self.states[user.id]['step'] = None
            
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
    
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == '__main__':
    main()
