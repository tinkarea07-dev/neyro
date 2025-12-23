"""
Модуль работы с SQLite базой данных
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import contextmanager


class Database:
    """Класс для работы с SQLite базой данных"""
    
    def __init__(self, db_path: str = 'data/bot.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для получения соединения с БД"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        """Инициализация таблиц базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица статусов каналов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_status (
                    channel TEXT PRIMARY KEY,
                    can_comment INTEGER DEFAULT 0,
                    is_public INTEGER DEFAULT 0,
                    has_discussion INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    error TEXT,
                    channel_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица истории диалогов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS dialog_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица обработанных постов (для избежания дублей)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    post_id INTEGER NOT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel, post_id)
                )
            ''')
            
            # Таблица счетчиков сообщений для автоответчика
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_counters (
                    user_id INTEGER PRIMARY KEY,
                    message_count INTEGER DEFAULT 0,
                    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица найденных каналов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS found_channels (
                    channel TEXT PRIMARY KEY,
                    title TEXT,
                    keyword TEXT,
                    found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Индексы для быстрого поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dialog_user_id ON dialog_history(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_dialog_timestamp ON dialog_history(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processed_channel ON processed_posts(channel)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_processed_channel_post ON processed_posts(channel, post_id)')
    
    # Методы для работы со статусами каналов
    def save_channel_status(self, channel: str, status: Dict[str, Any]):
        """Сохраняет статус канала"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO channel_status 
                (channel, can_comment, is_public, has_discussion, is_banned, error, channel_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (
                channel,
                1 if status.get('can_comment') else 0,
                1 if status.get('is_public') else 0,
                1 if status.get('has_discussion') else 0,
                1 if status.get('is_banned') else 0,
                status.get('error'),
                status.get('channel_id')
            ))
    
    def get_channel_status(self, channel: str) -> Optional[Dict[str, Any]]:
        """Получает статус канала"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM channel_status WHERE channel = ?', (channel,))
            row = cursor.fetchone()
            if row:
                return {
                    'can_comment': bool(row['can_comment']),
                    'is_public': bool(row['is_public']),
                    'has_discussion': bool(row['has_discussion']),
                    'is_banned': bool(row['is_banned']),
                    'error': row['error'],
                    'channel_id': row['channel_id']
                }
            return None
    
    # Методы для работы с историей диалогов
    def save_message(self, user_id: int, role: str, content: str, timestamp: float = None):
        """Сохраняет сообщение в историю диалога"""
        if timestamp is None:
            import time
            timestamp = time.time()
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO dialog_history (user_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, role, content, timestamp))
    
    def get_dialog_history(self, user_id: int, limit: int = 10, max_age_hours: float = 6) -> List[Dict[str, Any]]:
        """Получает историю диалога с пользователем"""
        import time
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT role, content, timestamp 
                FROM dialog_history 
                WHERE user_id = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (user_id, cutoff_time, limit))
            
            rows = cursor.fetchall()
            # Возвращаем в хронологическом порядке
            return [{'role': row['role'], 'content': row['content'], 'timestamp': row['timestamp']} 
                    for row in reversed(rows)]
    
    def clear_old_dialogs(self, max_age_hours: float = 24):
        """Очищает старые диалоги"""
        import time
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM dialog_history WHERE timestamp < ?', (cutoff_time,))
    
    # Методы для работы с обработанными постами
    def is_post_processed(self, channel: str, post_id: int) -> bool:
        """
        Проверяет, был ли пост уже обработан
        
        Args:
            channel: Имя канала (может быть с @ или без)
            post_id: ID поста
        
        Returns:
            bool: True если пост уже был обработан
        """
        # Нормализуем имя канала (убираем @ если есть)
        normalized_channel = channel.lstrip('@')
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Проверяем с @ и без @
            cursor.execute('''
                SELECT 1 FROM processed_posts 
                WHERE (channel = ? OR channel = ?) AND post_id = ?
            ''', (normalized_channel, f"@{normalized_channel}", post_id))
            return cursor.fetchone() is not None
    
    def mark_post_processed(self, channel: str, post_id: int):
        """
        Отмечает пост как обработанный
        
        Args:
            channel: Имя канала (может быть с @ или без)
            post_id: ID поста
        """
        # Нормализуем имя канала (убираем @ для единообразия)
        normalized_channel = channel.lstrip('@')
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Сохраняем без @ для единообразия
            cursor.execute('''
                INSERT OR IGNORE INTO processed_posts (channel, post_id)
                VALUES (?, ?)
            ''', (normalized_channel, post_id))
    
    def get_last_post_id(self, channel: str) -> Optional[int]:
        """Получает ID последнего обработанного поста в канале"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT post_id FROM processed_posts 
                WHERE channel = ? 
                ORDER BY processed_at DESC 
                LIMIT 1
            ''', (channel,))
            row = cursor.fetchone()
            return row['post_id'] if row else None
    
    # Методы для работы со счетчиками сообщений
    def increment_message_count(self, user_id: int) -> int:
        """Увеличивает счетчик сообщений пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO message_counters (user_id, message_count, last_message_at)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    message_count = message_count + 1,
                    last_message_at = CURRENT_TIMESTAMP
            ''', (user_id,))
            cursor.execute('SELECT message_count FROM message_counters WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row['message_count'] if row else 1
    
    def get_message_count(self, user_id: int) -> int:
        """Получает счетчик сообщений пользователя"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT message_count FROM message_counters WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row['message_count'] if row else 0
    
    # Методы для работы с найденными каналами
    def add_found_channel(self, channel: str, title: str = None, keyword: str = None):
        """Добавляет найденный канал"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO found_channels (channel, title, keyword, found_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (channel, title, keyword))
    
    def get_found_channels(self) -> List[str]:
        """Получает список найденных каналов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT channel FROM found_channels ORDER BY found_at DESC')
            return [row['channel'] for row in cursor.fetchall()]

