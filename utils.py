import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from config import Config

def verify_telegram_data(init_data: str, expected_user_id: int) -> bool:
    """
    Проверяет подпись данных инициализации Telegram WebApp
    Возвращает True, если данные валидны и user_id совпадает
    """
    try:
        # Парсим данные
        parsed_data = dict(parse_qsl(init_data))
        
        if 'hash' not in parsed_data:
            return False
        
        received_hash = parsed_data['hash']
        parsed_data.pop('hash')
        
        # Сортируем ключи и создаем строку для проверки
        data_check_string = '\n'.join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        
        # Создаем secret key из токена бота
        secret_key = hmac.new(
            b"WebAppData",
            Config.BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # Вычисляем хеш
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Проверяем хеш
        if not hmac.compare_digest(computed_hash, received_hash):
            return False
        
        # Проверяем user_id
        user_data = json.loads(parsed_data.get('user', '{}'))
        return user_data.get('id') == expected_user_id
        
    except Exception as e:
        print(f"Verification error: {e}")
        return False

def parse_amount(text: str) -> float | None:
    """Парсит сумму из текста (1к, 1.5кк и т.д.)"""
    import re
    
    text = text.lower().replace(" ", "")
    
    match = re.match(r'^(\d+(?:[.,]\d+)?)(к{1,3})?$', text)
    if not match:
        return None
    
    num_part = float(match.group(1).replace(',', '.'))
    suffix = match.group(2)
    
    if not suffix:
        return num_part
    
    multipliers = {
        'к': 1000,
        'кк': 1_000_000,
        'ккк': 1_000_000_000
    }
    return num_part * multipliers.get(suffix, 1)

def format_number(num: float) -> str:
    """Форматирует число с пробелами"""
    return f"{num:,.0f}".replace(",", " ")

def format_with_currency(num: float) -> str:
    """Форматирует с валютой"""
    return f"{format_number(num)} {Config.CURRENCY}"

def get_user_tag(user: dict) -> str:
    """Возвращает метку пользователя"""
    rep = user.get('reputation', 0)
    
    if rep <= Config.SCAM_THRESHOLD:
        return "⛔️"
    elif rep >= Config.TRUSTED_THRESHOLD:
        return "👑"
    else:
        return user.get('user_tag', '')

def get_user_mention(user: dict) -> str:
    """Создает ссылку на пользователя"""
    tag = get_user_tag(user)
    user_id = user['_id']
    username = user.get('username')
    
    if username:
        return f"{tag} @{username}".strip()
    else:
        return f"{tag} <a href='tg://user?id={user_id}'>ID{user_id}</a>".strip()