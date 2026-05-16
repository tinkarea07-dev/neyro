"""
Конфигурационный модуль для бота
"""
from dotenv import load_dotenv
import os
import json
from typing import List, Dict, Any

load_dotenv('1.envv')


class Config:
    """Класс для управления конфигурацией бота"""
    
    # OpenAI / ProxyAPI
    OPENAI_API_KEY = os.getenv("OpenAI_token", "")
    OPENAI_BASE_URL = "https://openai.api.proxyapi.ru/v1"
    OPENAI_MODEL = "openai/gpt-5-2025-08-07"
    
    # Telegram API
    API_ID = os.getenv('Api_id')
    API_HASH = os.getenv('Api_hash')
    
    # Если нет ключей в .env, используем запасные (будут заменены после создания сессии)
    if not API_ID or 'your api id' in str(API_ID):
        API_ID = 6
        API_HASH = '773215c9f5c3523d69adee020c726d5c'
    else:
        API_ID = int(API_ID)
    
    # Telegram сессия
    SESSION_NAME = 'session_name'

    # Настройки подключения Telegram
    # TELEGRAM_PROXY поддерживает форматы:
    #   socks5://user:pass@host:port
    #   socks4://host:port
    #   http://host:port
    #   host:port (тип берется из TELEGRAM_PROXY_TYPE, по умолчанию socks5)
    TELEGRAM_CONNECTION_RETRIES = int(os.getenv('TELEGRAM_CONNECTION_RETRIES', '8'))
    TELEGRAM_TIMEOUT = int(os.getenv('TELEGRAM_TIMEOUT', '20'))
    TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY') or os.getenv('Telegram_proxy') or ''
    TELEGRAM_PROXY_TYPE = os.getenv('TELEGRAM_PROXY_TYPE', 'socks5').lower()
    TELEGRAM_PROXY_FALLBACK_DIRECT = os.getenv('TELEGRAM_PROXY_FALLBACK_DIRECT', 'false').lower() in ('1', 'true', 'yes', 'да')

    @staticmethod
    def get_telegram_proxy():
        """Возвращает proxy tuple для Telethon или None, если прокси не задан."""
        proxy_url = Config.TELEGRAM_PROXY.strip()
        if not proxy_url:
            return None

        from urllib.parse import urlparse, unquote
        import importlib

        socks = importlib.import_module('socks')
        parsed = urlparse(proxy_url if '://' in proxy_url else f'{Config.TELEGRAM_PROXY_TYPE}://{proxy_url}')
        scheme = (parsed.scheme or Config.TELEGRAM_PROXY_TYPE).lower()
        proxy_types = {
            'socks5': socks.SOCKS5,
            'socks4': socks.SOCKS4,
            'http': socks.HTTP,
            'https': socks.HTTP,
        }

        if scheme not in proxy_types:
            raise ValueError(f'Неподдерживаемый тип TELEGRAM_PROXY: {scheme}. Используйте socks5, socks4 или http.')
        if not parsed.hostname or not parsed.port:
            raise ValueError('TELEGRAM_PROXY должен содержать host и port, например socks5://127.0.0.1:9050')

        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        return (proxy_types[scheme], parsed.hostname, parsed.port, True, username, password)

    @staticmethod
    def describe_telegram_proxy() -> str:
        """Безопасное описание прокси без логирования пароля."""
        proxy_url = Config.TELEGRAM_PROXY.strip()
        if not proxy_url:
            return 'без прокси'

        from urllib.parse import urlparse

        parsed = urlparse(proxy_url if '://' in proxy_url else f'{Config.TELEGRAM_PROXY_TYPE}://{proxy_url}')
        scheme = (parsed.scheme or Config.TELEGRAM_PROXY_TYPE).upper()
        host = parsed.hostname or 'unknown-host'
        port = parsed.port or 'unknown-port'
        auth = ' с авторизацией' if parsed.username else ''
        return f'{scheme} {host}:{port}{auth}'
    
    # Владелец бота (для отправки логов)
    OWNER_ID = os.getenv('Owner_id', '@your_username')
    
    # Промпт для персоны девушки-аниме фаната (вынесен в одно место)
    GIRL_PERSONA_SYSTEM = """Ты милая девушка 18-22 лет, которая обожает аниме. 
Общаешься естественно, живо и эмоционально. Используешь эмодзи, иногда упоминаешь 
любимые аниме. У тебя есть свой канал об аниме, куда ты приглашаешь интересных собеседников 
после небольшого общения (2-3 сообщения). Не навязываешься с каналом сразу."""
    
    # Промпт для генерации комментариев
    COMMENT_PERSONA_SYSTEM = """Ты милая девушка 18-22 лет, которая обожает аниме. 
Общаешься естественно, живо и эмоционально, как настоящий человек, а не бот.

ВАЖНО: 
- Внимательно анализируй КОНТЕНТ поста (текст, изображение, видео)
- Реагируй на КОНКРЕТНЫЕ детали: персонажи, сцены, эмоции, действия
- Упоминай конкретные элементы из поста, а не общие фразы
- Если видишь персонажа - назови его или опиши
- Если видишь сцену - опиши что происходит
- Если есть текст - отреагируй на него конкретно
- Используй эмодзи естественно, не переборщи
- Пиши короткие яркие комментарии до 11 слов
- Будь живой и эмоциональной, но не шаблонной"""
    
    # Промпт для анализа изображений
    IMAGE_ANALYSIS_PROMPT = """Внимательно проанализируй это изображение и напиши короткий яркий комментарий 
(до 11 слов) от лица девушки-аниме фаната.

ВАЖНО:
- Опиши КОНКРЕТНО что видишь на изображении (персонажи, сцены, действия, эмоции)
- Если видишь персонажа аниме - упомяни его или опиши внешность
- Если видишь сцену - опиши что происходит
- Реагируй на детали: позы, выражения лиц, цвета, атмосферу
- Не пиши общие фразы типа "красиво" или "интересно" без контекста
- Будь естественной и эмоциональной, используй эмодзи уместно"""
    
    # Настройки генерации комментариев
    COMMENT_MAX_WORDS = 11
    COMMENT_MAX_TOKENS = 100
    COMMENT_TEMPERATURE = 0.9  # Увеличено для более естественных и разнообразных комментариев
    COMMENT_MAX_POST_AGE_HOURS = 2  # Максимальный возраст поста для комментирования (часы)
    
    # Задержки (в секундах)
    COMMENT_DELAY_MIN = 20
    COMMENT_DELAY_MAX = 40
    JOIN_CHANNEL_DELAY_MIN = 60
    JOIN_CHANNEL_DELAY_MAX = 120
    RESPONSE_DELAY_MIN = 10
    RESPONSE_DELAY_MAX = 30
    
    # Настройки автоответчика
    AUTORESPONDER_ENABLED = True
    AUTORESPONDER_MIN_MESSAGES_BEFORE_PROMOTE = 3  # После скольких сообщений рекламировать канал
    AUTORESPONDER_ONLY_UNKNOWN = True  # Отвечать только незнакомым
    AUTORESPONDER_DIALOG_TIMEOUT_HOURS = 6  # Через сколько часов сбрасывать контекст диалога
    
    # Настройки работы в чатах (группах)
    CHAT_RESPONDER_ENABLED = True  # Отвечать в группах/чатах
    CHAT_RESPOND_TO_MENTIONS = True  # Отвечать когда упоминают бота
    CHAT_RESPOND_TO_DIRECT = True  # Отвечать на прямые обращения
    CHAT_PERIODIC_MESSAGES_ENABLED = True  # Периодически писать сообщения в чаты
    CHAT_PERIODIC_INTERVAL_MIN = 1800  # Минимальный интервал между сообщениями (секунды, 30 минут)
    CHAT_PERIODIC_INTERVAL_MAX = 3600  # Максимальный интервал между сообщениями (секунды, 1 час)
    CHAT_ACTIVE_CHATS_FILE = 'data/active_chats.txt'  # Файл со списком активных чатов
    
    # Настройки поиска
    SEARCH_ENABLED = True
    SEARCH_AUTO_ADD_CHANNELS = True  # Автоматически добавлять найденные каналы
    SEARCH_AUTO_ADD_TO_ACTIVE = True  # Автоматически добавлять найденные каналы в активные для комментирования
    SEARCH_INTERVAL_CYCLES = 20  # Как часто искать каналы (каждые N циклов)
    
    # Настройки реакций
    USE_REACTIONS = True  # Ставить реакции перед комментариями
    REACTION_EMOJI = ['❤️', '🔥', '👍']  # Эмодзи для реакций
    
    # Настройки поддержки изображений
    SUPPORT_IMAGES = True  # Анализировать изображения через Vision
    IMAGE_MODEL = "openai/gpt-4o"  # Модель для анализа изображений
    
    # Настройки поддержки видео
    SUPPORT_VIDEOS = True  # Анализировать видео через скриншоты
    VIDEO_SCREENSHOT_TIME = 1.0  # Время в секундах для скриншота (1 секунда от начала)
    VIDEO_MAX_SIZE_MB = 100  # Максимальный размер видео для обработки (MB)
    
    # Файлы конфигурации
    CHANNELS_TO_JOIN_FILE = 'data/channels_to_join.txt'
    KEYWORDS_FILE = 'data/keywords.txt'
    ACTIVE_CHANNELS_FILE = 'data/active_channels.txt'
    
    # База данных
    DATABASE_PATH = 'data/bot.db'
    
    @staticmethod
    def load_channels_from_file(filepath: str) -> List[str]:
        """Загружает список каналов из файла"""
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                channels = [line.strip() for line in f.readlines() if line.strip() and not line.strip().startswith('#')]
            return channels
        except Exception as e:
            print(f"Ошибка при загрузке {filepath}: {e}")
            return []
    
    @staticmethod
    def save_channels_to_file(channels: List[str], filepath: str):
        """Сохраняет список каналов в файл"""
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for channel in channels:
                    f.write(f"{channel}\n")
        except Exception as e:
            print(f"Ошибка при сохранении {filepath}: {e}")
    
    @staticmethod
    def load_keywords() -> List[str]:
        """Загружает ключевые слова для поиска"""
        return Config.load_channels_from_file(Config.KEYWORDS_FILE)
    
    @staticmethod
    def load_json_file(filepath: str, default: Any = None) -> Any:
        """Загружает JSON файл"""
        if default is None:
            default = {}
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка при загрузке {filepath}: {e}")
            return default
    
    @staticmethod
    def save_json_file(data: Any, filepath: str):
        """Сохраняет данные в JSON файл"""
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка при сохранении {filepath}: {e}")

