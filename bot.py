import asyncio
import os
import random
import time
import logging
from typing import Dict, List, Optional, Tuple

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

from dotenv import load_dotenv
from models import Database
from utils import parse_amount, format_with_currency, get_user_tag, get_user_mention

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "nova_coin")
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourdomain.com")
    SECRET_KEY = os.getenv("SECRET_KEY", "default-secret-key-change-it")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация
bot = Bot(token=Config.BOT_TOKEN)  # ← Теперь Config определён
dp = Dispatcher()
db = Database()

# Временные хранилища для состояний
admin_temp: Dict[int, dict] = {}
transfer_temp: Dict[int, dict] = {}
games_enabled = True

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================

async def get_or_create_user(message: Message) -> dict:
    """Получить или создать пользователя"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    return await db.get_or_create_user(user_id, username, first_name)

def get_balance_text(user: dict) -> str:
    """Возвращает текст с балансом"""
    balance = user.get('balance', 0)
    tag = get_user_tag(user)
    bonus = user.get('bonus_games', 0)
    bonus_text = f" 🎮 {bonus}" if bonus > 0 else ""
    return f"{tag}Ваш Баланс: {format_with_currency(balance)}{bonus_text}".strip()

def get_reputation_text(user: dict) -> str:
    """Возвращает текст с репутацией"""
    rep = user.get('reputation', 0)
    return f"🌟 Репутация: {rep}"

# ================== ОБРАБОТЧИКИ КОМАНД ==================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    user_id = message.from_user.id
    user = await get_or_create_user(message)
    
    # Проверяем, не передан ли код чека
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('check_'):
        check_code = args[1].replace('check_', '').upper()
        amount = await db.activate_check(check_code, user_id)
        
        if amount:
            await message.answer(f"✅ Чек активирован! +{format_with_currency(amount)}")
            user = await db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        else:
            await message.answer("❌ Чек недействителен или уже использован")
    
    # Личное сообщение
    if message.chat.type == 'private':
        if user_id == Config.ADMIN_ID:
            await show_admin_panel(message, user)
        else:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📦 Мои чеки", callback_data="show_checks")],
                    [InlineKeyboardButton(text="🎮 Открыть Mini App", url=Config.WEBAPP_URL)]
                ]
            )
            
            await message.answer(
                f"🚀 Добро пожаловать в Nova Coin!\n\n"
                f"{get_balance_text(user)}\n"
                f"{get_reputation_text(user)}\n\n"
                f"🎮 Доступные игры:\n"
                f"• кубик [сумма]\n"
                f"• баскетбол [сумма]\n"
                f"• футбол [сумма]\n"
                f"• боулинг [сумма]\n"
                f"• дартс [сумма]\n"
                f"• слоты [сумма]\n\n"
                f"📱 Играй также в нашем Mini App!",
                reply_markup=keyboard
            )
    else:
        # В группе
        games_status = "🟢 ВКЛЮЧЕНЫ" if games_enabled else "🔴 ВЫКЛЮЧЕНЫ"
        await message.answer(
            f"🚀 Nova Coin\n\n"
            f"{get_balance_text(user)}\n"
            f"{get_reputation_text(user)}\n\n"
            f"🎮 Игры: {games_status}"
        )

@dp.message(F.text.lower().in_(['баланс', 'бал']))
async def show_balance(message: Message):
    """Показывает баланс"""
    if await db.is_banned(message.from_user.id):
        await message.answer("🔨 Вы забанены!")
        return
    
    user = await get_or_create_user(message)
    bonus = user.get('bonus_games', 0)
    
    text = f"{get_balance_text(user)}\n{get_reputation_text(user)}"
    
    if bonus > 0:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"🎮 Бонусные игры: {bonus}", callback_data="show_bonus_games")]
            ]
        )
        await message.answer(text, reply_markup=keyboard)
    else:
        await message.answer(text)

# ================== АДМИН-ПАНЕЛЬ ==================

async def show_admin_panel(message: Message, user: dict):
    """Показывает админ-панель"""
    global games_enabled
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Баланс", callback_data="admin_balance"),
                InlineKeyboardButton(text="🌟 Репутация", callback_data="admin_rep"),
                InlineKeyboardButton(text="🏷 Метки", callback_data="admin_tags")
            ],
            [
                InlineKeyboardButton(text="🔨 Бан", callback_data="admin_ban"),
                InlineKeyboardButton(text="✅ Разбан", callback_data="admin_unban"),
                InlineKeyboardButton(text="🎮 Бонусы", callback_data="admin_bonus")
            ],
            [
                InlineKeyboardButton(text="🎮 Игры", callback_data="admin_games"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
                InlineKeyboardButton(text="📦 Промокоды", callback_data="admin_promo")
            ]
        ]
    )
    
    status = "🟢 Включены" if games_enabled else "🔴 Выключены"
    
    await message.answer(
        f"👑 Админ панель\n\n"
        f"🎮 Статус игр: {status}\n"
        f"{get_balance_text(user)}\n"
        f"{get_reputation_text(user)}",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "admin_games")
async def admin_games_callback(callback: CallbackQuery):
    """Управление статусом игр"""
    if callback.from_user.id != Config.ADMIN_ID:
        await callback.answer("❌ Доступ запрещен")
        return
    
    global games_enabled
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 ВКЛЮЧИТЬ", callback_data="games_enable"),
                InlineKeyboardButton(text="🔴 ВЫКЛЮЧИТЬ", callback_data="games_disable")
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_main")]
        ]
    )
    
    await callback.message.edit_text(
        f"🎮 Управление играми\n\n"
        f"Текущий статус: {'🟢 Включены' if games_enabled else '🔴 Выключены'}\n\n"
        f"Выберите действие:",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["games_enable", "games_disable"])
async def games_toggle_callback(callback: CallbackQuery):
    """Включение/выключение игр"""
    if callback.from_user.id != Config.ADMIN_ID:
        await callback.answer("❌ Доступ запрещен")
        return
    
    global games_enabled
    games_enabled = (callback.data == "games_enable")
    
    await callback.message.answer(f"✅ Игры {'ВКЛЮЧЕНЫ' if games_enabled else 'ВЫКЛЮЧЕНЫ'}!")
    await admin_games_callback(callback)

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    """Статистика"""
    if callback.from_user.id != Config.ADMIN_ID:
        await callback.answer("❌ Доступ запрещен")
        return
    
    # Собираем статистику
    total_users = await db.users.count_documents({})
    banned = await db.users.count_documents({"banned": True})
    total_balance = 0
    async for user in db.users.find({}, {"balance": 1}):
        total_balance += user.get("balance", 0)
    
    lottery = await db.get_lottery()
    checks_count = await db.checks.count_documents({})
    
    text = (
        f"📊 Статистика:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🔨 Забанено: {banned}\n"
        f"💰 Общий баланс: {format_with_currency(total_balance)}\n"
        f"🎰 Участников лотереи: {len(lottery['pool'])}\n"
        f"💰 Банк лотереи: {format_with_currency(lottery['total'])}\n"
        f"📦 Активных чеков: {checks_count}"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_main")]]
    )
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ================== ИГРЫ ==================

@dp.message(F.text.lower().startswith(('кубик', 'кости')))
async def play_dice(message: Message):
    if not games_enabled:
        await message.answer("🎮 Игры временно отключены")
        return
    await handle_game_start(message, 'dice', '🎲')

# Аналогично для других игр...

async def handle_game_start(message: Message, game_type: str, emoji: str):
    """Обрабатывает начало игры"""
    user_id = message.from_user.id
    
    if await db.is_banned(user_id):
        await message.answer("🔨 Вы забанены!")
        return
    
    user = await get_or_create_user(message)
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажите сумму. Пример: кубик 1000")
        return
    
    amount_str = parts[1]
    bet_amount = parse_amount(amount_str)
    
    if bet_amount is None or bet_amount <= 0:
        await message.answer("❌ Неверный формат суммы")
        return
    
    bonus = user.get('bonus_games', 0)
    
    if bonus > 0:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=f"🎮 Использовать бонус ({bonus})", 
                                        callback_data=f"use_bonus_{game_type}_{amount_str}"),
                    InlineKeyboardButton(text="💰 Заплатить", 
                                        callback_data=f"pay_{game_type}_{amount_str}")
                ]
            ]
        )
        await message.answer(
            f"🎮 У вас есть {bonus} бонусных игр!\n\n"
            f"Хотите использовать бонус или заплатить {format_with_currency(bet_amount)}?",
            reply_markup=keyboard
        )
        return
    
    await play_regular_game(message, user, game_type, emoji, bet_amount, False)

async def play_regular_game(message: Message, user: dict, game_type: str, emoji: str, 
                           bet_amount: float, is_bonus: bool):
    """Обычная игра"""
    user_id = user['_id']
    
    # Проверка кулдауна
    current_time = time.time()
    last_time = user.get('last_game_time', 0)
    if current_time - last_time < Config.GAME_COOLDOWN:
        wait = Config.GAME_COOLDOWN - (current_time - last_time)
        await message.answer(f"⏳ Подождите {wait:.1f} секунд")
        return
    
    if not is_bonus and user['balance'] < bet_amount:
        await message.answer(f"❌ Недостаточно средств! {get_balance_text(user)}")
        return
    
    if not is_bonus:
        await db.inc_balance(user_id, -bet_amount)
    
    await db.users.update_one({"_id": user_id}, {"$set": {"last_game_time": current_time}})
    
    # Запускаем игру
    msg = await message.answer(f"🎮 Игра начинается...")
    await asyncio.sleep(2)
    await msg.delete()
    
    # Здесь логика конкретной игры...
    # Для примера - простой кубик
    if game_type == 'dice':
        await play_dice_game(message, user_id, bet_amount, is_bonus)

async def play_dice_game(message: Message, user_id: int, bet_amount: float, is_bonus: bool):
    """Игра в кубик"""
    player_dice = await message.answer_dice(emoji='🎲')
    await asyncio.sleep(2.5)
    bot_dice = await message.answer_dice(emoji='🎲')
    await asyncio.sleep(2.5)
    
    player_value = player_dice.dice.value
    bot_value = bot_dice.dice.value
    
    if player_value > bot_value:
        if not is_bonus:
            win_amount = int(bet_amount * Config.GAME_MULTIPLIERS['dice'])
        else:
            win_amount = int(10000 * Config.GAME_MULTIPLIERS['dice'])
        
        await db.inc_balance(user_id, win_amount)
        result = f"✅ ПОБЕДА! +{format_with_currency(win_amount)}"
        
    elif player_value < bot_value:
        result = f"❌ ПОРАЖЕНИЕ"
        if is_bonus:
            result += f"\n💸 Бонусная игра использована"
        else:
            result += f"\n💸 Проигрыш: {format_with_currency(bet_amount)}"
    else:
        if not is_bonus:
            await db.inc_balance(user_id, bet_amount)
            result = f"🤝 НИЧЬЯ! Ставка возвращена"
        else:
            await db.users.update_one({"_id": user_id}, {"$inc": {"bonus_games": 1}})
            result = f"🤝 НИЧЬЯ! Бонус возвращен"
    
    user = await db.get_user(user_id)
    await message.answer(
        f"🎲 КУБИК\n\n"
        f"Ваш: {player_value}\n"
        f"Бот: {bot_value}\n\n"
        f"{result}\n\n"
        f"{get_balance_text(user)}"
    )

# ================== ЛОТЕРЕЯ ==================

@dp.message(F.text.lower().startswith(('ставка', 'ставку')))
async def place_bet(message: Message):
    """Ставка в лотерею"""
    user_id = message.from_user.id
    
    if await db.is_banned(user_id):
        await message.answer("🔨 Вы забанены!")
        return
    
    user = await get_or_create_user(message)
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажите сумму. Пример: ставка 1000")
        return
    
    amount_str = parts[1]
    
    if amount_str.lower() == 'вб':
        bet_amount = user['balance']
    else:
        bet_amount = parse_amount(amount_str)
        if bet_amount is None or bet_amount <= 0:
            await message.answer("❌ Неверный формат суммы")
            return
    
    if bet_amount > user['balance']:
        await message.answer(f"❌ Недостаточно средств! {get_balance_text(user)}")
        return
    
    lottery = await db.place_lottery_bet(user_id, bet_amount)
    
    username = user.get('username') or f"ID{user_id}"
    
    await message.answer(
        f"💸 @{username} поставил {format_with_currency(bet_amount)}\n\n"
        f"💰 Общий банк: {format_with_currency(lottery['total'])}"
    )

@dp.message(F.text.lower() == 'вб')
async def bet_all(message: Message):
    """Ставка всё"""
    message.text = "ставка вб"
    await place_bet(message)

@dp.message(F.text.lower() == 'лотерея')
async def show_lottery(message: Message):
    """Показать состояние лотереи"""
    if await db.is_banned(message.from_user.id):
        await message.answer("🔨 Вы забанены!")
        return
    
    lottery = await db.get_lottery()
    
    if not lottery['pool']:
        await message.answer("🎰 Лотерея пуста")
        return
    
    text = "🎰 ЛОТЕРЕЯ\n\n"
    total = lottery['total']
    
    for uid, amount in lottery['pool'].items():
        user = await db.get_user(uid)
        if user:
            name = user.get('username') or f"ID{uid}"
            percent = (amount / total * 100)
            text += f"• @{name}: {format_with_currency(amount)} ({percent:.1f}%)\n"
    
    text += f"\n💰 Банк: {format_with_currency(total)}"
    
    await message.answer(text)

@dp.message(F.text.lower().in_(['кончить', 'закончить', 'закончить лотерею']))
async def end_lottery(message: Message):
    """Завершить лотерею"""
    user_id = message.from_user.id
    
    if await db.is_banned(user_id):
        await message.answer("🔨 Вы забанены!")
        return
    
    lottery = await db.get_lottery()
    
    if len(lottery['pool']) < 2:
        await message.answer("❌ Нужно минимум 2 участника")
        return
    
    if user_id not in lottery['pool']:
        await message.answer("❌ Только участники могут завершить лотерею")
        return
    
    winner_id, win_amount = await db.end_lottery()
    winner = await db.get_user(winner_id)
    
    if winner:
        winner_name = winner.get('username') or f"ID{winner_id}"
        await message.answer(
            f"🏆 Победитель: @{winner_name}\n"
            f"💰 Выигрыш: {format_with_currency(win_amount)}"
        )

# ================== ЧЕКИ ==================

@dp.message(F.text.startswith('!'))
async def handle_check(message: Message):
    """Создание/активация чека"""
    user_id = message.from_user.id
    
    if await db.is_banned(user_id):
        await message.answer("🔨 Вы забанены!")
        return
    
    text = message.text[1:]
    parts = text.split()
    
    if len(parts) == 2:
        # Создание
        amount_str, activation_str = parts
        amount = parse_amount(amount_str)
        activation = parse_amount(activation_str)
        
        if amount is None or activation is None:
            await message.answer("❌ Неверный формат")
            return
        
        user = await db.get_user(user_id)
        total_cost = amount * activation
        
        if user['balance'] < total_cost:
            await message.answer(f"❌ Нужно {format_with_currency(total_cost)}")
            return
        
        code = await db.create_check(user_id, amount, int(activation))
        bot_info = await bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=check_{code}"
        
        await message.answer(
            f"✅ Чек создан!\n"
            f"💰 {format_with_currency(amount)} × {activation}\n"
            f"🔗 {link}"
        )
        
    elif len(parts) == 1:
        # Активация
        if message.chat.type != 'private':
            await message.answer("❌ Активируйте в ЛС")
            return
        
        amount = await db.activate_check(parts[0].upper(), user_id)
        if amount:
            await message.answer(f"✅ +{format_with_currency(amount)}")
        else:
            await message.answer("❌ Чек недействителен")
    else:
        await message.answer("❌ Неверный формат")

@dp.callback_query(lambda c: c.data == "show_checks")
async def show_checks(callback: CallbackQuery):
    """Показать чеки пользователя"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    
    checks = await db.get_user_checks(user_id)
    
    if not checks:
        await callback.message.edit_text(
            f"📦 У вас нет активных чеков\n\n{get_balance_text(user)}"
        )
        await callback.answer()
        return
    
    keyboard = []
    for check in checks:
        code = check['_id']
        activated = check['activated_count']
        total = check['activation_count']
        amount = check['amount']
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"{format_with_currency(amount)} | {activated}/{total}",
                callback_data=f"check_info_{code}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    
    await callback.message.edit_text(
        f"📦 Ваши чеки\n\n{get_balance_text(user)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

# ================== РЕПУТАЦИЯ ==================

@dp.message(F.reply_to_message, F.text.lower().in_(['+реп', '-реп']))
async def change_reputation(message: Message):
    """Изменение репутации"""
    giver_id = message.from_user.id
    receiver_id = message.reply_to_message.from_user.id
    
    if giver_id == receiver_id:
        await message.answer("❌ Нельзя себе")
        return
    
    if await db.is_banned(giver_id) or await db.is_banned(receiver_id):
        await message.answer("❌ Один из пользователей забанен")
        return
    
    can, wait = await db.check_rep_cooldown(giver_id, receiver_id)
    if not can:
        hours = wait // 3600
        minutes = (wait % 3600) // 60
        await message.answer(f"⏳ Подождите {hours}ч {minutes}м")
        return
    
    is_positive = message.text.lower() == '+реп'
    
    new_rep = await db.change_reputation(giver_id, receiver_id, is_positive)
    await db.set_rep_cooldown(giver_id, receiver_id)
    
    receiver = await db.get_user(receiver_id)
    action = "повышена 📈" if is_positive else "понижена 📉"
    tag = get_user_tag(receiver)
    
    await message.answer(
        f"{'✅' if is_positive else '⚠️'} Репутация {action}\n\n"
        f"🌟 Новая репутация: {new_rep}{' ' + tag if tag else ''}"
    )

# ================== ПЕРЕВОДЫ ==================

@dp.message(F.reply_to_message, F.text.lower().startswith('перевод'))
async def transfer_money(message: Message):
    """Перевод денег"""
    sender_id = message.from_user.id
    receiver_id = message.reply_to_message.from_user.id
    
    if sender_id == receiver_id:
        await message.answer("❌ Нельзя себе")
        return
    
    if await db.is_banned(sender_id) or await db.is_banned(receiver_id):
        await message.answer("❌ Один из пользователей забанен")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажите сумму")
        return
    
    amount = parse_amount(parts[1])
    if amount is None or amount <= 0:
        await message.answer("❌ Неверная сумма")
        return
    
    sender = await db.get_user(sender_id)
    if sender['balance'] < amount:
        await message.answer(f"❌ Недостаточно средств")
        return
    
    receiver = await db.get_user(receiver_id)
    receiver_tag = get_user_tag(receiver)
    
    if receiver_tag == "⛔️" and sender_id != Config.ADMIN_ID:
        transfer_temp[sender_id] = {'receiver_id': receiver_id, 'amount': amount}
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да", callback_data="confirm_transfer"),
                    InlineKeyboardButton(text="❌ Нет", callback_data="cancel_transfer")
                ]
            ]
        )
        
        await message.answer(
            f"⚠️ У получателя метка СКАМ!\n"
            f"Перевести {format_with_currency(amount)}?",
            reply_markup=keyboard
        )
    else:
        await execute_transfer(sender_id, receiver_id, amount, message)

async def execute_transfer(sender_id: int, receiver_id: int, amount: float, message: Message):
    """Выполнить перевод"""
    await db.inc_balance(sender_id, -amount)
    await db.inc_balance(receiver_id, amount)
    
    sender = await db.get_user(sender_id)
    receiver = await db.get_user(receiver_id)
    
    await message.answer(
        f"💸 Перевод выполнен!\n\n"
        f"{get_user_mention(sender)} → {get_user_mention(receiver)}\n"
        f"Сумма: {format_with_currency(amount)}\n\n"
        f"{get_balance_text(sender)}",
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "confirm_transfer")
async def confirm_transfer(callback: CallbackQuery):
    """Подтверждение перевода"""
    sender_id = callback.from_user.id
    
    if sender_id not in transfer_temp:
        await callback.answer("❌ Время истекло")
        return
    
    data = transfer_temp[sender_id]
    await execute_transfer(sender_id, data['receiver_id'], data['amount'], callback.message)
    del transfer_temp[sender_id]
    await callback.answer()

@dp.callback_query(lambda c: c.data == "cancel_transfer")
async def cancel_transfer(callback: CallbackQuery):
    """Отмена перевода"""
    if callback.from_user.id in transfer_temp:
        del transfer_temp[callback.from_user.id]
    await callback.message.answer("❌ Перевод отменен")
    await callback.answer()

# ================== БОНУСНЫЕ ИГРЫ ==================

@dp.callback_query(lambda c: c.data == "show_bonus_games")
async def show_bonus_games(callback: CallbackQuery):
    """Показать бонусные игры"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    
    bonus = user.get('bonus_games', 0)
    if bonus <= 0:
        await callback.answer("❌ Нет бонусных игр")
        return
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 КУБИК", callback_data="bonus_dice"),
                InlineKeyboardButton(text="🏀 БАСКЕТБОЛ", callback_data="bonus_basketball")
            ],
            [
                InlineKeyboardButton(text="⚽ ФУТБОЛ", callback_data="bonus_football"),
                InlineKeyboardButton(text="🎳 БОУЛИНГ", callback_data="bonus_bowling")
            ],
            [
                InlineKeyboardButton(text="🎯 ДАРТС", callback_data="bonus_darts"),
                InlineKeyboardButton(text="🎰 СЛОТЫ", callback_data="bonus_slot")
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
        ]
    )
    
    await callback.message.edit_text(
        f"🎮 Бонусные игры: {bonus}\n"
        f"💰 Ставка: 10 000 NC (бесплатно)",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('bonus_'))
async def play_bonus_game(callback: CallbackQuery):
    """Запуск бонусной игры"""
    user_id = callback.from_user.id
    game_type = callback.data.replace('bonus_', '')
    
    user = await db.get_user(user_id)
    
    if user.get('bonus_games', 0) <= 0:
        await callback.answer("❌ Нет бонусных игр")
        return
    
    await db.users.update_one({"_id": user_id}, {"$inc": {"bonus_games": -1}})
    
    # Здесь логика игры...
    await callback.message.answer(f"🎮 Бонусная игра {game_type} запущена!")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    user = await db.get_user(callback.from_user.id)
    await show_admin_panel(callback.message, user)
    await callback.answer()

# ================== ЗАПУСК ==================

async def main():
    print("🚀 Бот запущен...")
    print(f"Админ ID: {Config.ADMIN_ID}")
    print(f"Подключение к MongoDB: {Config.MONGO_URI}")
    
    # Проверка подключения к БД
    try:
        await db.users.count_documents({})
        print("✅ Подключение к MongoDB успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения к MongoDB: {e}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())