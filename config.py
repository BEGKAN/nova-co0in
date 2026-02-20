import os
from dotenv import load_dotenv
from typing import Dict, Any, Optional, List, Tuple

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "nova_coin")
    WEBAPP_URL = os.getenv("WEBAPP_URL", "https://yourdomain.com")
    SECRET_KEY = os.getenv("SECRET_KEY", "default-secret-key-change-it")
    
    # Пороги для меток
    SCAM_THRESHOLD = -200
    TRUSTED_THRESHOLD = 200
    
    # Время между репутациями (24 часа)
    REP_COOLDOWN = 24 * 60 * 60
    
    # Время между играми
    GAME_COOLDOWN = 4
    
    # Коэффициенты игр
    GAME_MULTIPLIERS = {
        'dice': 1.9,
        'basketball_perfect': 2.5,
        'basketball_regular': 1.5,
        'football_perfect': 2.0,
        'football_regular': 1.25,
        'bowling_strike': 2.2,
        'bowling_five': 1.8,
        'bowling_four': 1.5,
        'darts_bullseye': 2.5,
        'darts_outer': 1.3,
        'slot_777': 10.0,
        'slot_bar3': 7.0,
        'slot_lemon3': 3.0,
        'slot_grape3': 4.0,
    }
    
    CURRENCY = "NC"