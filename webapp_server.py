import json
import hmac
import hashlib
import random
from datetime import datetime
from urllib.parse import parse_qsl

from aiohttp import web
from models import Database
from config import Config
from utils import verify_telegram_data, format_with_currency

db = Database()
routes = web.RouteTableDef()

# ================== МИДЛВАР ДЛЯ ПРОВЕРКИ ==================

@web.middleware
async def auth_middleware(request, handler):
    """Проверяет подпись Telegram данных"""
    # Пропускаем опционы и статику
    if request.method == "OPTIONS" or request.path.startswith("/static/"):
        return await handler(request)
    
    init_data = request.headers.get("X-Init-Data")
    if not init_data:
        return web.json_response({"error": "Missing init data"}, status=401)
    
    # Получаем user_id из тела запроса
    try:
        body = await request.json()
        user_id = body.get("user_id")
    except:
        return web.json_response({"error": "Invalid request"}, status=400)
    
    if not verify_telegram_data(init_data, user_id):
        return web.json_response({"error": "Invalid signature"}, status=401)
    
    request["user_id"] = user_id
    return await handler(request)

# ================== API ЭНДПОИНТЫ ==================

@routes.post("/api/init")
async def init_user(request):
    """Инициализация пользователя для Mini App"""
    data = await request.json()
    user_id = data.get("user_id")
    init_data = request.headers.get("X-Init-Data")
    
    if not verify_telegram_data(init_data, user_id):
        return web.json_response({"error": "Unauthorized"}, status=401)
    
    # Получаем данные пользователя из init_data
    parsed = dict(parse_qsl(init_data))
    user_data = json.loads(parsed.get('user', '{}'))
    
    # Получаем или создаем пользователя в БД
    user = await db.get_or_create_user(
        user_id,
        user_data.get('username'),
        user_data.get('first_name')
    )
    
    # Сбрасываем today_earned если новый день
    today = datetime.now().date().isoformat()
    if user.get('last_reset') != today:
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"today_earned": 0.0, "last_reset": today}}
        )
        user['today_earned'] = 0.0
    
    return web.json_response({
        "balance": user['balance'],
        "per_click": user['per_click'],
        "per_sec": user['per_sec'],
        "click_multiplier": user['click_multiplier'],
        "crit_chance": user['crit_chance'],
        "total_clicks": user['total_clicks'],
        "total_earned": user['total_earned'],
        "today_earned": user['today_earned'],
        "upgrades": user['upgrades'],
        "name_color": user.get('name_color'),
        "first_name": user['first_name'],
        "bonus_games": user['bonus_games'],
        "reputation": user['reputation'],
        "tag": await db.get_user_tag(user_id)
    })

@routes.post("/api/click")
async def handle_click(request):
    """Обработка клика"""
    data = await request.json()
    user_id = data.get("user_id")
    
    user = await db.get_user(user_id)
    if not user:
        return web.json_response({"error": "User not found"}, status=404)
    
    # Рассчитываем награду
    gain = user['per_click'] * user['click_multiplier']
    
    # Крит
    if random.random() < user['crit_chance']:
        gain *= 2
    
    # Обновляем баланс и статистику
    await db.inc_balance(user_id, gain)
    await db.users.update_one(
        {"_id": user_id},
        {
            "$inc": {
                "total_clicks": 1,
                "total_earned": gain,
                "today_earned": gain
            }
        }
    )
    
    return web.json_response({
        "success": True,
        "gain": gain,
        "new_balance": user['balance'] + gain
    })

@routes.post("/api/update_passive")
async def update_passive(request):
    """Обновление пассивного дохода (вызывается каждую секунду с фронта)"""
    data = await request.json()
    user_id = data.get("user_id")
    
    user = await db.get_user(user_id)
    if not user:
        return web.json_response({"error": "User not found"}, status=404)
    
    gain = user['per_sec']
    
    await db.inc_balance(user_id, gain)
    await db.users.update_one(
        {"_id": user_id},
        {"$inc": {"total_earned": gain, "today_earned": gain}}
    )
    
    return web.json_response({
        "success": True,
        "gain": gain
    })

@routes.post("/api/buy")
async def buy_upgrade(request):
    """Покупка улучшения"""
    data = await request.json()
    user_id = data.get("user_id")
    upgrade_index = data.get("upgrade_index")
    
    # Список улучшений (должен совпадать с фронтом)
    shop_items = [
        {"name": "👆 Усиление клика +0.01", "price": 100, "type": "perClick", "value": 0.01},
        {"name": "⚡ Авто-майнер +0.01/с", "price": 150, "type": "perSec", "value": 0.01},
        {"name": "💥 Критический клик +5%", "price": 200, "type": "crit", "value": 0.05},
        {"name": "🚀 Множитель клика x1.5", "price": 300, "type": "multiplier", "value": 0.5},
        {"name": "🔋 Батарейка +0.03/с", "price": 400, "type": "perSec", "value": 0.03},
        {"name": "🎯 Меткий глаз +0.02", "price": 500, "type": "perClick", "value": 0.02},
        {"name": "✨ Удача +10% крита", "price": 600, "type": "crit", "value": 0.1},
        {"name": "👑 Королевский множитель x2", "price": 1000, "type": "multiplier", "value": 1.0},
    ]
    
    if upgrade_index < 0 or upgrade_index >= len(shop_items):
        return web.json_response({"error": "Invalid item"}, status=400)
    
    item = shop_items[upgrade_index]
    
    user = await db.get_user(user_id)
    if user['balance'] < item['price']:
        return web.json_response({"error": "Insufficient funds"}, status=400)
    
    # Списываем деньги
    await db.inc_balance(user_id, -item['price'])
    
    # Применяем улучшение
    update = {}
    if item['type'] == "perClick":
        update = {"per_click": user['per_click'] + item['value']}
    elif item['type'] == "perSec":
        update = {"per_sec": user['per_sec'] + item['value']}
    elif item['type'] == "multiplier":
        update = {"click_multiplier": user['click_multiplier'] + item['value']}
    elif item['type'] == "crit":
        update = {"crit_chance": user['crit_chance'] + item['value']}
    
    update["$push"] = {"upgrades": item['name']}
    
    await db.users.update_one({"_id": user_id}, {"$set": update})
    
    return web.json_response({
        "success": True,
        "new_balance": user['balance'] - item['price']
    })

@routes.get("/api/rating")
async def get_rating(request):
    """Получить топ пользователей"""
    sort_by = request.query.get("type", "balance")
    users = await db.get_top_users(sort_by, 50)
    
    result = []
    for user in users:
        result.append({
            "id": user['_id'],
            "name": user['first_name'],
            "username": user.get('username'),
            "balance": user['balance'],
            "per_sec": user['per_sec'],
            "per_click": user['per_click'] * user['click_multiplier'],
            "tag": await db.get_user_tag(user['_id']),
            "name_color": user.get('name_color')
        })
    
    return web.json_response(result)

@routes.post("/api/profile/change_name")
async def change_name(request):
    """Смена имени"""
    data = await request.json()
    user_id = data.get("user_id")
    new_name = data.get("name", "").strip()
    
    if not new_name or len(new_name) > 32:
        return web.json_response({"error": "Invalid name"}, status=400)
    
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"first_name": new_name}}
    )
    
    return web.json_response({"success": True})

@routes.post("/api/profile/buy_color")
async def buy_color(request):
    """Покупка цвета ника"""
    data = await request.json()
    user_id = data.get("user_id")
    color = data.get("color")
    
    user = await db.get_user(user_id)
    price = 100
    
    if user['balance'] < price:
        return web.json_response({"error": "Insufficient funds"}, status=400)
    
    await db.inc_balance(user_id, -price)
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"name_color": color}}
    )
    
    return web.json_response({"success": True})

@routes.post("/api/promo/activate")
async def activate_promo(request):
    """Активация промокода"""
    data = await request.json()
    user_id = data.get("user_id")
    code = data.get("code", "").upper()
    
    amount = await db.activate_promocode(code, user_id)
    
    if amount:
        return web.json_response({"success": True, "amount": amount})
    else:
        return web.json_response({"error": "Invalid promo code"}, status=400)

@routes.post("/api/promo/create")
async def create_promo(request):
    """Создание промокода (только админ)"""
    data = await request.json()
    user_id = data.get("user_id")
    
    if user_id != Config.ADMIN_ID:
        return web.json_response({"error": "Unauthorized"}, status=403)
    
    code = data.get("code", "").upper()
    amount = float(data.get("amount", 0))
    activations = int(data.get("activations", 1))
    
    if not code or amount <= 0 or activations <= 0:
        return web.json_response({"error": "Invalid data"}, status=400)
    
    success = await db.create_promocode(code, amount, activations)
    
    if success:
        return web.json_response({"success": True})
    else:
        return web.json_response({"error": "Code already exists"}, status=400)

# ================== ЛОТЕРЕЯ ==================

@routes.get("/api/lottery/regular")
async def get_regular_lottery(request):
    """Получить состояние обычной лотереи"""
    lottery = await db.get_lottery()
    
    # Получаем имена игроков
    players = {}
    for uid in lottery['pool']:
        user = await db.get_user(uid)
        if user:
            players[str(uid)] = {
                "name": user.get('username') or f"ID{uid}",
                "bet": lottery['pool'][uid]
            }
    
    return web.json_response({
        "total": lottery['total'],
        "players": players
    })

@routes.post("/api/lottery/regular/bet")
async def place_regular_bet(request):
    """Сделать ставку в обычную лотерею"""
    data = await request.json()
    user_id = data.get("user_id")
    amount = float(data.get("amount", 0))
    
    if amount <= 0:
        return web.json_response({"error": "Invalid amount"}, status=400)
    
    user = await db.get_user(user_id)
    if user['balance'] < amount:
        return web.json_response({"error": "Insufficient funds"}, status=400)
    
    lottery = await db.place_lottery_bet(user_id, amount)
    
    return web.json_response({
        "success": True,
        "total": lottery['total']
    })

@routes.post("/api/lottery/regular/end")
async def end_regular_lottery(request):
    """Завершить обычную лотерею"""
    data = await request.json()
    user_id = data.get("user_id")
    
    lottery = await db.get_lottery()
    
    if len(lottery['pool']) < 2:
        return web.json_response({"error": "Not enough players"}, status=400)
    
    if user_id not in lottery['pool']:
        return web.json_response({"error": "Only participants can end"}, status=400)
    
    winner_id, amount = await db.end_lottery()
    
    return web.json_response({
        "success": True,
        "winner_id": winner_id,
        "amount": amount
    })

@routes.get("/api/lottery/team")
async def get_team_lottery(request):
    """Получить состояние командной лотереи"""
    lottery = await db.get_team_lottery()
    
    # Получаем имена игроков
    eagle_players = {}
    tails_players = {}
    
    for uid in lottery['eagle']:
        user = await db.get_user(uid)
        if user:
            eagle_players[str(uid)] = {
                "name": user.get('username') or f"ID{uid}",
                "bet": lottery['eagle'][uid]
            }
    
    for uid in lottery['tails']:
        user = await db.get_user(uid)
        if user:
            tails_players[str(uid)] = {
                "name": user.get('username') or f"ID{uid}",
                "bet": lottery['tails'][uid]
            }
    
    return web.json_response({
        "eagle_total": lottery['eagle_total'],
        "tails_total": lottery['tails_total'],
        "eagle_players": eagle_players,
        "tails_players": tails_players
    })

@routes.post("/api/lottery/team/bet")
async def place_team_bet(request):
    """Сделать ставку в командную лотерею"""
    data = await request.json()
    user_id = data.get("user_id")
    team = data.get("team")  # "eagle" или "tails"
    amount = float(data.get("amount", 0))
    
    if team not in ["eagle", "tails"]:
        return web.json_response({"error": "Invalid team"}, status=400)
    
    if amount <= 0:
        return web.json_response({"error": "Invalid amount"}, status=400)
    
    user = await db.get_user(user_id)
    if user['balance'] < amount:
        return web.json_response({"error": "Insufficient funds"}, status=400)
    
    lottery = await db.place_team_bet(user_id, team, amount)
    
    return web.json_response({
        "success": True,
        "eagle_total": lottery['eagle_total'],
        "tails_total": lottery['tails_total']
    })

@routes.post("/api/lottery/team/end")
async def end_team_lottery(request):
    """Завершить командную лотерею"""
    data = await request.json()
    user_id = data.get("user_id")
    
    lottery = await db.get_team_lottery()
    
    if not lottery['eagle'] or not lottery['tails']:
        return web.json_response({"error": "Both teams need players"}, status=400)
    
    winner_team, winners, _ = await db.end_team_lottery()
    
    return web.json_response({
        "success": True,
        "winner_team": winner_team
    })

# ================== ЗАПУСК СЕРВЕРА ==================

app = web.Application(middlewares=[auth_middleware])
app.add_routes(routes)

# Раздача статических файлов
app.router.add_static('/static/', path='./static/', name='static')

async def start_server():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("🌐 WebApp server started on http://0.0.0.0:8080")

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_server())