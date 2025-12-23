"""
Модуль поиска каналов и постов по ключевым словам
"""
import time
from typing import List, Dict, Optional
from telethon.sync import TelegramClient
from telethon.tl.types import Channel, Chat
import time
from config import Config
from utils.database import Database
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import InputPeerEmpty


class KeywordSearch:
    """Класс для поиска каналов и постов по ключевым словам"""
    
    def __init__(self, client: TelegramClient, db: Database):
        self.client = client
        self.db = db
        self.keywords = Config.load_keywords()
    
    def search_channels_by_keywords(self, keywords: Optional[List[str]] = None) -> List[Dict]:
        """
        Ищет каналы по ключевым словам через ГЛОБАЛЬНЫЙ поиск Telegram
        
        Returns:
            List[Dict] - список найденных каналов с информацией
        """
        if keywords is None:
            keywords = self.keywords
        
        if not keywords:
            print("⚠️ Нет ключевых слов для поиска")
            return []
        
        found_channels = []
        
        for keyword in keywords:
            print(f"🔍 Ищу каналы по ключевому слову: {keyword}")
            
            try:
                # ИСПРАВЛЕНО: Используем глобальный поиск через contacts.Search
                result = self.client(SearchRequest(
                    q=keyword,
                    limit=20  # Ограничиваем количество результатов
                ))
                
                # Обрабатываем результаты поиска
                for peer in result.chats:
                    if hasattr(peer, 'username') and peer.username:
                        channel_username = f"@{peer.username}"
                        channel_title = getattr(peer, 'title', 'Без названия')
                        
                        channel_info = {
                            'username': channel_username,
                            'id': peer.id,
                            'title': channel_title,
                            'keyword': keyword
                        }
                        
                        # Проверяем, не добавлен ли уже
                        if channel_username not in [ch.get('username') for ch in found_channels]:
                            found_channels.append(channel_info)
                            print(f"  ✅ Найден канал: {channel_username} ({channel_title})")
                            # Сохраняем в БД
                            self.db.add_found_channel(channel_username, channel_title, keyword)
                
                # Небольшая задержка между поисками
                time.sleep(2)
                
            except Exception as e:
                print(f"  ❌ Ошибка при поиске по '{keyword}': {e}")
        
        return found_channels
    
    def search_posts_in_channels(self, channels: List[str], keywords: Optional[List[str]] = None, limit: int = 10) -> List[Dict]:
        """
        Ищет посты в каналах по ключевым словам
        
        Returns:
            List[Dict] - список найденных постов
        """
        if keywords is None:
            keywords = self.keywords
        
        if not keywords:
            return []
        
        found_posts = []
        
        for channel in channels:
            try:
                entity = self.client.get_entity(channel)
                messages = self.client.get_messages(entity, limit=limit)
                
                for message in messages:
                    if not message.text:
                        continue
                    
                    text_lower = message.text.lower()
                    
                    # Проверяем, содержит ли пост ключевые слова
                    for keyword in keywords:
                        if keyword.lower() in text_lower:
                            post_info = {
                                'channel': channel,
                                'post_id': message.id,
                                'text': message.text[:200],  # Первые 200 символов
                                'keyword': keyword,
                                'link': f"https://t.me/{channel.replace('@', '')}/{message.id}"
                            }
                            found_posts.append(post_info)
                            print(f"  ✅ Найден пост в {channel}: {message.id} (ключевое слово: {keyword})")
                            break  # Не добавляем один пост несколько раз
                
            except Exception as e:
                print(f"  ❌ Ошибка при поиске в {channel}: {e}")
        
        return found_posts
    
    def add_found_channels(self, channels: List[str]):
        """Добавляет найденные каналы в БД"""
        for channel in channels:
            self.db.add_found_channel(channel)
        print(f"📝 Добавлено {len(channels)} новых каналов в список найденных")
    
    def get_found_channels(self) -> List[str]:
        """Возвращает список найденных каналов из БД"""
        return self.db.get_found_channels()
    
    def search_all(self, auto_add_to_active: bool = True) -> Dict:
        """
        Выполняет полный поиск: каналы и посты
        Автоматически находит аниме каналы и добавляет их в список для комментирования
        
        Returns:
            {
                'channels': List[Dict],
                'posts': List[Dict],
                'added_channels': List[str]  # Новые добавленные каналы
            }
        """
        if not Config.SEARCH_ENABLED:
            return {'channels': [], 'posts': [], 'added_channels': []}
        
        print("🔍 Начинаю поиск аниме каналов...")
        
        # Поиск каналов
        channels = self.search_channels_by_keywords()
        
        # Автоматически добавляем найденные каналы в активные (если включено)
        added_channels = []
        if channels and (auto_add_to_active or Config.SEARCH_AUTO_ADD_TO_ACTIVE):
            active_channels = Config.load_channels_from_file(Config.ACTIVE_CHANNELS_FILE)
            
            for channel_info in channels:
                channel_username = channel_info.get('username')
                if channel_username and channel_username not in active_channels:
                    # Добавляем в активные каналы
                    active_channels.append(channel_username)
                    added_channels.append(channel_username)
                    print(f"  ➕ Добавлен новый аниме канал: {channel_username}")
            
            # Сохраняем обновленный список
            if added_channels:
                Config.save_channels_to_file(active_channels, Config.ACTIVE_CHANNELS_FILE)
                print(f"✅ Добавлено {len(added_channels)} новых аниме каналов в активные")
        
        # Поиск постов в существующих каналах
        active_channels = Config.load_channels_from_file(Config.ACTIVE_CHANNELS_FILE)
        posts = self.search_posts_in_channels(active_channels)
        
        print(f"✅ Поиск завершен. Найдено каналов: {len(channels)}, постов: {len(posts)}, добавлено новых: {len(added_channels)}")
        
        return {
            'channels': channels,
            'posts': posts,
            'added_channels': added_channels
        }
    
    def search_anime_channels_only(self) -> List[str]:
        """
        Специальный метод для поиска только аниме каналов
        Возвращает список username каналов
        """
        print("🎌 Ищу аниме каналы...")
        
        # Используем аниме-специфичные ключевые слова
        anime_keywords = [
            'аниме', 'anime', 'манга', 'manga', 
            'анимечат', 'анимеблог', 'animechannel'
        ]
        
        channels = self.search_channels_by_keywords(anime_keywords)
        
        # Возвращаем только username
        found_usernames = [ch['username'] for ch in channels if ch.get('username')]
        
        print(f"🎌 Найдено {len(found_usernames)} аниме каналов")
        
        return found_usernames

