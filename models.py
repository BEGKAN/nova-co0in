from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
import random
import string
from typing import Optional, Dict, List, Any
from config import Config
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import random
import string

class Database:
    def __init__(self):
        self.client = AsyncIOMotorClient(Config.MONGO_URI)
        self.db = self.client[Config.MONGO_DB_NAME]
        
        # Коллекции
        self.users = self.db.users
        self.lottery = self.db.lottery
        self.team_lottery = self.db.team_lottery
        self.checks = self.db.checks
        self.promocodes = self.db.promocodes
        self.rep_cooldowns = self.db.rep_cooldowns
        
    # ========== ПОЛЬЗОВАТЕЛИ ==========
    
    async def get_or_create_user(self, user_id: int, username: str = None, first_name: str = None) -> Dict:
        """Получить пользователя или создать нового"""
        user = await self.users.find_one({"_id": user_id})
        
        if not user:
            user = {
                "_id": user_id,
                "username": username,
                "first_name": first_name or f"User{user_id}",
                "balance": 10000.0,
                "reputation": 0,
                "user_tag": "",
                "banned": False,
                "bonus_games": 0,
                "last_game_time": 0,
                
                # Кликер данные
                "per_click": 0.05,
                "per_sec": 0.05,
                "click_multiplier": 1.0,
                "crit_chance": 0.1,
                "total_clicks": 0,
                "total_earned": 0.0,
                "today_earned": 0.0,
                "last_reset": datetime.now().date().isoformat(),
                "upgrades": [],
                "name_color": None,
                
                "created_at": datetime.utcnow(),
                "last_active": datetime.utcnow()
            }
            await self.users.insert_one(user)
        else:
            # Обновляем username/first_name если изменились
            update = {"last_active": datetime.utcnow()}
            if username:
                update["username"] = username
            if first_name:
                update["first_name"] = first_name
            await self.users.update_one({"_id": user_id}, {"$set": update})
            user.update(update)
        
        # Сброс today_earned если новый день
        today = datetime.now().date().isoformat()
        if user.get("last_reset") != today:
            await self.users.update_one(
                {"_id": user_id},
                {"$set": {"today_earned": 0.0, "last_reset": today}}
            )
            user["today_earned"] = 0.0
            user["last_reset"] = today
            
        return user
    
    async def update_user(self, user_id: int, data: Dict) -> None:
        """Обновить данные пользователя"""
        data["last_active"] = datetime.utcnow()
        await self.users.update_one({"_id": user_id}, {"$set": data})
    
    async def inc_balance(self, user_id: int, amount: float) -> float:
        """Увеличить баланс (атомарно)"""
        result = await self.users.find_one_and_update(
            {"_id": user_id},
            {"$inc": {"balance": amount}},
            return_document=True
        )
        return result["balance"] if result else 0
    
    async def get_user_tag(self, user_id: int) -> str:
        """Получить метку пользователя"""
        user = await self.users.find_one({"_id": user_id})
        if not user:
            return ""
        
        rep = user.get("reputation", 0)
        if rep <= Config.SCAM_THRESHOLD:
            return "⛔️"
        elif rep >= Config.TRUSTED_THRESHOLD:
            return "👑"
        else:
            return user.get("user_tag", "")
    
    async def update_user_tag_by_reputation(self, user_id: int) -> None:
        """Обновить метку на основе репутации"""
        user = await self.users.find_one({"_id": user_id})
        if not user:
            return
        
        rep = user.get("reputation", 0)
        current_tag = user.get("user_tag", "")
        
        if rep <= Config.SCAM_THRESHOLD:
            if current_tag != "⛔️":
                await self.users.update_one({"_id": user_id}, {"$set": {"user_tag": "⛔️"}})
        elif rep >= Config.TRUSTED_THRESHOLD:
            if current_tag != "👑":
                await self.users.update_one({"_id": user_id}, {"$set": {"user_tag": "👑"}})
        else:
            if current_tag in ["⛔️", "👑"]:
                await self.users.update_one({"_id": user_id}, {"$set": {"user_tag": ""}})
    
    async def is_banned(self, user_id: int) -> bool:
        """Проверить, забанен ли пользователь"""
        user = await self.users.find_one({"_id": user_id})
        return user.get("banned", False) if user else False
    
    async def get_top_users(self, sort_by: str = "balance", limit: int = 50) -> List[Dict]:
        """Получить топ пользователей"""
        sort_field = {
            "balance": "balance",
            "income": "per_sec",
            "click": "per_click"
        }.get(sort_by, "balance")
        
        cursor = self.users.find({"banned": False}).sort(sort_field, -1).limit(limit)
        return await cursor.to_list(length=limit)
    
    # ========== РЕПУТАЦИЯ ==========
    
    async def check_rep_cooldown(self, giver_id: int, receiver_id: int) -> tuple[bool, int]:
        """Проверить кулдаун репутации"""
        cooldown = await self.rep_cooldowns.find_one({
            "giver_id": giver_id,
            "receiver_id": receiver_id
        })
        
        if not cooldown:
            return True, 0
        
        time_passed = (datetime.utcnow() - cooldown["created_at"]).total_seconds()
        if time_passed < Config.REP_COOLDOWN:
            return False, int(Config.REP_COOLDOWN - time_passed)
        
        return True, 0
    
    async def set_rep_cooldown(self, giver_id: int, receiver_id: int) -> None:
        """Установить кулдаун репутации"""
        await self.rep_cooldowns.update_one(
            {"giver_id": giver_id, "receiver_id": receiver_id},
            {"$set": {"created_at": datetime.utcnow()}},
            upsert=True
        )
    
    async def change_reputation(self, giver_id: int, receiver_id: int, is_positive: bool) -> int:
        """Изменить репутацию"""
        delta = 1 if is_positive else -1
        
        result = await self.users.find_one_and_update(
            {"_id": receiver_id},
            {"$inc": {"reputation": delta}},
            return_document=True
        )
        
        if result:
            await self.update_user_tag_by_reputation(receiver_id)
            return result["reputation"]
        
        return 0
    
    # ========== ЛОТЕРЕЯ ==========
    
    async def get_lottery(self) -> Dict:
        """Получить состояние обычной лотереи"""
        lottery = await self.lottery.find_one({"_id": "regular"})
        if not lottery:
            lottery = {
                "_id": "regular",
                "pool": {},  # user_id -> amount
                "total": 0,
                "is_active": True
            }
            await self.lottery.insert_one(lottery)
        return lottery
    
    async def place_lottery_bet(self, user_id: int, amount: float) -> Dict:
        """Сделать ставку в лотерею"""
        # Списываем баланс
        await self.inc_balance(user_id, -amount)
        
        # Добавляем в пул
        lottery = await self.lottery.find_one_and_update(
            {"_id": "regular"},
            {
                "$inc": {f"pool.{user_id}": amount, "total": amount},
                "$setOnInsert": {"is_active": True}
            },
            upsert=True,
            return_document=True
        )
        
        return lottery
    
    async def end_lottery(self) -> tuple[int, float]:
        """Завершить лотерею и выбрать победителя"""
        lottery = await self.lottery.find_one({"_id": "regular"})
        if not lottery or not lottery["pool"]:
            return None, 0
        
        participants = list(lottery["pool"].keys())
        weights = list(lottery["pool"].values())
        total = lottery["total"]
        
        winner_id = random.choices(participants, weights=weights)[0]
        winner_stake = lottery["pool"][winner_id]
        
        # Выдаем выигрыш
        await self.inc_balance(winner_id, total)
        
        # Очищаем лотерею
        await self.lottery.update_one(
            {"_id": "regular"},
            {"$set": {"pool": {}, "total": 0}}
        )
        
        return winner_id, total
    
    # ========== КОМАНДНАЯ ЛОТЕРЕЯ ==========
    
    async def get_team_lottery(self) -> Dict:
        """Получить состояние командной лотереи"""
        lottery = await self.team_lottery.find_one({"_id": "team"})
        if not lottery:
            lottery = {
                "_id": "team",
                "eagle": {},  # user_id -> amount
                "tails": {},  # user_id -> amount
                "eagle_total": 0,
                "tails_total": 0,
                "is_active": True
            }
            await self.team_lottery.insert_one(lottery)
        return lottery
    
    async def place_team_bet(self, user_id: int, team: str, amount: float) -> Dict:
        """Сделать ставку в командную лотерею"""
        if team not in ["eagle", "tails"]:
            raise ValueError("Invalid team")
        
        # Списываем баланс
        await self.inc_balance(user_id, -amount)
        
        # Добавляем в команду
        update_field = f"{team}.{user_id}"
        inc_total = f"{team}_total"
        
        lottery = await self.team_lottery.find_one_and_update(
            {"_id": "team"},
            {
                "$inc": {update_field: amount, inc_total: amount},
                "$setOnInsert": {"is_active": True}
            },
            upsert=True,
            return_document=True
        )
        
        return lottery
    
    async def end_team_lottery(self) -> tuple[str, List[int], Dict]:
        """Завершить командную лотерею"""
        lottery = await self.team_lottery.find_one({"_id": "team"})
        if not lottery:
            return None, [], {}
        
        # Бросаем монетку
        winner_team = random.choice(["eagle", "tails"])
        loser_team = "tails" if winner_team == "eagle" else "eagle"
        
        winner_pool = lottery[winner_team]
        loser_pool = lottery[loser_team]
        
        if not winner_pool:
            return None, [], {}
        
        total_winner = lottery[f"{winner_team}_total"]
        total_loser = lottery[f"{loser_team}_total"]
        
        total_pool = total_winner + total_loser
        
        # Распределяем выигрыш пропорционально ставкам
        winner_ids = list(winner_pool.keys())
        for uid in winner_ids:
            stake = winner_pool[uid]
            win_amount = total_pool * (stake / total_winner)
            await self.inc_balance(uid, win_amount)
        
        # Очищаем лотерею
        await self.team_lottery.update_one(
            {"_id": "team"},
            {"$set": {"eagle": {}, "tails": {}, "eagle_total": 0, "tails_total": 0}}
        )
        
        return winner_team, winner_ids, winner_pool
    
    # ========== ЧЕКИ ==========
    
    async def create_check(self, creator_id: int, amount: float, activations: int) -> str:
        """Создать чек"""
        # Списываем сумму
        total_cost = amount * activations
        await self.inc_balance(creator_id, -total_cost)
        
        # Генерируем код
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        check = {
            "_id": code,
            "creator_id": creator_id,
            "amount": amount,
            "activation_count": activations,
            "activated_count": 0,
            "activated_by": [],
            "created_at": datetime.utcnow()
        }
        
        await self.checks.insert_one(check)
        return code
    
    async def activate_check(self, code: str, user_id: int) -> Optional[float]:
        """Активировать чек"""
        check = await self.checks.find_one({"_id": code})
        if not check:
            return None
        
        if user_id in check["activated_by"]:
            return None
        
        if check["activated_count"] >= check["activation_count"]:
            await self.checks.delete_one({"_id": code})
            return None
        
        if user_id == check["creator_id"]:
            return None
        
        # Начисляем
        await self.inc_balance(user_id, check["amount"])
        
        # Обновляем чек
        await self.checks.update_one(
            {"_id": code},
            {
                "$inc": {"activated_count": 1},
                "$push": {"activated_by": user_id}
            }
        )
        
        # Проверяем, не исчерпан ли лимит
        check = await self.checks.find_one({"_id": code})
        if check["activated_count"] >= check["activation_count"]:
            await self.checks.delete_one({"_id": code})
        
        return check["amount"]
    
    async def get_user_checks(self, user_id: int) -> List[Dict]:
        """Получить чеки пользователя"""
        cursor = self.checks.find({"creator_id": user_id})
        return await cursor.to_list(length=100)
    
    async def delete_check(self, code: str, user_id: int) -> bool:
        """Удалить чек и вернуть средства"""
        check = await self.checks.find_one({"_id": code})
        if not check or check["creator_id"] != user_id:
            return False
        
        remaining = check["amount"] * (check["activation_count"] - check["activated_count"])
        await self.inc_balance(user_id, remaining)
        await self.checks.delete_one({"_id": code})
        
        return True
    
    # ========== ПРОМОКОДЫ ==========
    
    async def create_promocode(self, code: str, amount: float, activations: int) -> bool:
        """Создать промокод"""
        try:
            await self.promocodes.insert_one({
                "_id": code.upper(),
                "amount": amount,
                "activations_left": activations,
                "created_at": datetime.utcnow()
            })
            return True
        except:
            return False
    
    async def activate_promocode(self, code: str, user_id: int) -> Optional[float]:
        """Активировать промокод"""
        promo = await self.promocodes.find_one({"_id": code.upper()})
        if not promo or promo["activations_left"] <= 0:
            return None
        
        # Проверяем, не активировал ли уже
        used = await self.users.find_one({
            "_id": user_id,
            "used_promocodes": code.upper()
        })
        if used:
            return None
        
        await self.inc_balance(user_id, promo["amount"])
        
        await self.promocodes.update_one(
            {"_id": code.upper()},
            {"$inc": {"activations_left": -1}}
        )
        
        await self.users.update_one(
            {"_id": user_id},
            {"$push": {"used_promocodes": code.upper()}}
        )
        
        return promo["amount"]