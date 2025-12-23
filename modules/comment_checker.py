"""
Модуль проверки возможности комментирования в каналах
"""
from typing import Dict, List, Optional
from telethon.sync import TelegramClient
from telethon.errors import ChannelPrivateError, UsernameInvalidError
from config import Config
from utils.database import Database


class CommentChecker:
    """Класс для проверки возможности комментирования в каналах"""
    
    def __init__(self, client: TelegramClient, db: Database):
        self.client = client
        self.db = db
    
    def check_channel(self, channel: str) -> Dict[str, any]:
        """
        Проверяет возможность комментирования в канале
        
        Returns:
            {
                'can_comment': bool,
                'is_public': bool,
                'has_discussion': bool,
                'is_banned': bool,
                'error': str or None,
                'channel_id': int or None
            }
        """
        result = {
            'can_comment': False,
            'is_public': False,
            'has_discussion': False,
            'is_banned': False,
            'error': None,
            'channel_id': None
        }
        
        try:
            # Получаем entity канала
            entity = self.client.get_entity(channel)
            result['channel_id'] = entity.id
            
            # Проверяем, что это публичный канал
            if hasattr(entity, 'username') and entity.username:
                result['is_public'] = True
            else:
                result['error'] = "Канал приватный (нет username)"
                self.status_cache[channel] = result
                Config.save_json_file(self.status_cache, Config.CHANNEL_STATUS_FILE)
                return result
            
            # Получаем полную информацию о канале
            try:
                full_channel = self.client.get_entity(entity)
                
                # Проверяем наличие группы для комментариев
                if hasattr(full_channel, 'linked_chat_id') and full_channel.linked_chat_id:
                    result['has_discussion'] = True
                    result['can_comment'] = True
                else:
                    # Проверяем, есть ли у канала комментарии через сообщения
                    try:
                        messages = self.client.get_messages(entity, limit=1)
                        if messages:
                            # Пытаемся получить информацию о комментариях
                            result['can_comment'] = True  # Если можем получить сообщения, возможно можем комментировать
                    except:
                        pass
                
            except Exception as e:
                result['error'] = f"Ошибка при получении информации: {str(e)}"
            
            # Проверяем, не забанен ли аккаунт
            try:
                # Пытаемся получить информацию о канале - если забанен, будет ошибка
                self.client.get_permissions(entity, self.client.get_me())
            except Exception as e:
                if "banned" in str(e).lower() or "kicked" in str(e).lower():
                    result['is_banned'] = True
                    result['can_comment'] = False
                    result['error'] = "Аккаунт забанен в этом канале"
            
        except UsernameInvalidError:
            result['error'] = "Неверное имя канала"
        except ChannelPrivateError:
            result['error'] = "Канал приватный или недоступен"
        except Exception as e:
            result['error'] = f"Ошибка: {str(e)}"
        
        # Сохраняем статус в БД
        self.db.save_channel_status(channel, result)
        
        return result
    
    def check_channels(self, channels: List[str]) -> Dict[str, Dict]:
        """
        Проверяет список каналов
        
        Returns:
            Dict[channel: str, status: Dict]
        """
        results = {}
        for channel in channels:
            print(f"🔍 Проверяю канал: {channel}")
            status = self.check_channel(channel)
            results[channel] = status
            
            if status['can_comment']:
                print(f"  ✅ Можно комментировать")
            else:
                reason = status.get('error', 'Неизвестная причина')
                print(f"  ❌ Нельзя комментировать: {reason}")
        
        return results
    
    def get_commentable_channels(self, channels: List[str]) -> List[str]:
        """Возвращает список каналов, где можно комментировать"""
        commentable = []
        for channel in channels:
            status = self.check_channel(channel)
            if status['can_comment'] and not status['is_banned']:
                commentable.append(channel)
        return commentable
    
    def filter_active_channels(self, channels: List[str]) -> List[str]:
        """Фильтрует каналы, оставляя только те, где можно комментировать"""
        active = self.get_commentable_channels(channels)
        
        # Сохраняем активные каналы в файл
        Config.save_channels_to_file(active, Config.ACTIVE_CHANNELS_FILE)
        
        return active
    
    def get_status(self, channel: str) -> Optional[Dict]:
        """Получает сохраненный статус канала"""
        return self.db.get_channel_status(channel)

