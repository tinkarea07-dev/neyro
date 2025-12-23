"""
Модуль для работы с реакциями на посты
"""
import random
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from config import Config


class ReactionManager:
    """Класс для управления реакциями на посты"""
    
    def __init__(self, client: TelegramClient):
        self.client = client
    
    def send_reaction(self, entity, message_id: int, emoji: str = None) -> bool:
        """
        Ставит реакцию на пост
        
        Args:
            entity: Entity канала/чата
            message_id: ID сообщения
            emoji: Эмодзи для реакции (если None - случайный из списка)
        
        Returns:
            bool: Успешно ли поставлена реакция
        """
        if not Config.USE_REACTIONS:
            return False
        
        try:
            if emoji is None:
                emoji = random.choice(Config.REACTION_EMOJI)
            
            # Валидация эмодзи - проверяем, что это действительно эмодзи
            # Удаляем пробелы и проверяем длину
            emoji = emoji.strip()
            
            # Проверяем, что эмодзи не пустой и содержит только эмодзи символы
            if not emoji:
                return False
            
            # Проверяем, что эмодзи из списка разрешенных (безопасность)
            if emoji not in Config.REACTION_EMOJI:
                # Если эмодзи не из списка, используем случайный из списка
                emoji = random.choice(Config.REACTION_EMOJI)
            
            # Создаем реакцию
            reaction = ReactionEmoji(emoticon=emoji)
            
            # Отправляем реакцию
            self.client(SendReactionRequest(
                peer=entity,
                msg_id=message_id,
                reaction=[reaction]
            ))
            
            return True
            
        except Exception as e:
            error_str = str(e)
            # Игнорируем ошибки, которые не критичны:
            # - Invalid reaction / only emoji - невалидное эмодзи
            # - reactions_uniq_max - уже достигнуто максимальное количество реакций
            # - message already has exactly reactions_uniq_max - пост уже имеет максимальное количество реакций
            ignore_errors = [
                "Invalid reaction",
                "only emoji",
                "reactions_uniq_max",
                "message already has exactly"
            ]
            
            should_ignore = any(ignore in error_str for ignore in ignore_errors)
            
            if not should_ignore:
                print(f"Ошибка при установке реакции: {e}")
            return False

