"""
Модуль автоответчика на личные сообщения и в чатах
"""
import time
import random
import threading
from typing import Dict, List, Optional
from telethon.sync import TelegramClient
from telethon import events
from telethon.tl.types import User, Chat, Channel
from openai import OpenAI
from config import Config
from utils.database import Database


class AutoResponder:
    """Класс для автоматических ответов на личные сообщения"""
    
    def __init__(self, client: TelegramClient, openai_client: OpenAI, db: Database):
        self.client = client
        self.openai_client = openai_client
        self.db = db
        self.channel_link = None  # Ссылка на канал из bio
        self._load_channel_link()
        self.bot_username = None  # Username бота для определения упоминаний
        self.active_chats = []  # Список активных чатов
        self.chat_last_message_time = {}  # Время последнего сообщения в чате
        self._load_bot_username()
        self._load_active_chats()
    
    def _load_channel_link(self):
        """Извлекает ссылку на канал из описания профиля"""
        try:
            me = self.client.get_me()
            # Получаем полную информацию о профиле
            full_me = self.client.get_entity(me)
            if hasattr(full_me, 'about') and full_me.about:
                # Ищем ссылку на канал в описании
                about = full_me.about
                # Ищем паттерны типа @channel, t.me/channel, https://t.me/channel
                import re
                patterns = [
                    r'@(\w+)',
                    r't\.me/(\w+)',
                    r'https?://t\.me/(\w+)',
                    r'https?://telegram\.me/(\w+)'
                ]
                for pattern in patterns:
                    match = re.search(pattern, about)
                    if match:
                        self.channel_link = f"@{match.group(1)}"
                        break
        except Exception as e:
            print(f"Ошибка при загрузке ссылки на канал: {e}")
            self.channel_link = "@your_anime_channel"  # Запасной вариант
    
    def _load_bot_username(self):
        """Загружает username бота для определения упоминаний"""
        try:
            me = self.client.get_me()
            if hasattr(me, 'username') and me.username:
                self.bot_username = me.username.lower()
        except Exception as e:
            print(f"Ошибка при загрузке username бота: {e}")
    
    def _load_active_chats(self):
        """Загружает список активных чатов из файла"""
        try:
            self.active_chats = Config.load_channels_from_file(Config.CHAT_ACTIVE_CHATS_FILE)
        except Exception as e:
            print(f"Ошибка при загрузке активных чатов: {e}")
            self.active_chats = []
    
    def _save_active_chats(self):
        """Сохраняет список активных чатов в файл"""
        try:
            Config.save_channels_to_file(self.active_chats, Config.CHAT_ACTIVE_CHATS_FILE)
        except Exception as e:
            print(f"Ошибка при сохранении активных чатов: {e}")
    
    def is_unknown_user(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь незнакомым"""
        if not Config.AUTORESPONDER_ONLY_UNKNOWN:
            return True  # Если отвечаем всем, считаем всех незнакомыми
        
        try:
            # Проверяем, есть ли пользователь в контактах
            entity = self.client.get_entity(user_id)
            if isinstance(entity, User):
                # Если это пользователь и не в контактах
                return not entity.contact
            return True
        except:
            return True
    
    def get_dialog_history(self, user_id: int) -> List[Dict]:
        """Получает историю диалога с пользователем (с учетом таймаута)"""
        return self.db.get_dialog_history(
            user_id, 
            limit=10, 
            max_age_hours=Config.AUTORESPONDER_DIALOG_TIMEOUT_HOURS
        )
    
    def save_message(self, user_id: int, role: str, content: str):
        """Сохраняет сообщение в историю диалога"""
        self.db.save_message(user_id, role, content)
    
    def generate_response(self, user_id: int, user_message: str) -> str:
        """Генерирует ответ через GPT"""
        try:
            # Получаем историю диалога
            history = self.get_dialog_history(user_id)
            
            # Формируем сообщения для GPT (используем промпт из config)
            messages = [
                {'role': 'system', 'content': Config.GIRL_PERSONA_SYSTEM}
            ]
            
            # Если прошло много времени, добавляем системное сообщение
            if history:
                import time as time_module
                oldest_msg_time = min([msg['timestamp'] for msg in history])
                hours_passed = (time_module.time() - oldest_msg_time) / 3600
                if hours_passed > Config.AUTORESPONDER_DIALOG_TIMEOUT_HOURS / 2:
                    messages.append({
                        'role': 'system',
                        'content': f'[Прошло много времени с прошлого сообщения - {int(hours_passed)} часов]'
                    })
            
            # Добавляем историю
            for msg in history[-5:]:  # Последние 5 сообщений для контекста
                messages.append({
                    'role': msg['role'],
                    'content': msg['content']
                })
            
            # Добавляем текущее сообщение пользователя
            messages.append({
                'role': 'user',
                'content': user_message
            })
            
            # Если пора рекламировать канал (после N сообщений)
            msg_count = self.db.get_message_count(user_id)
            if msg_count >= Config.AUTORESPONDER_MIN_MESSAGES_BEFORE_PROMOTE:
                # Добавляем промпт о необходимости пригласить на канал
                messages.append({
                    'role': 'system',
                    'content': f'В этом ответе естественно упомяни свой канал об аниме: {self.channel_link}. Не навязывайся, упомяни как бы между делом.'
                })
            
            # Генерируем ответ (используем промпт из config)
            # GPT-5 требует max_completion_tokens вместо max_tokens
            # GPT-5 поддерживает только temperature=1 (по умолчанию)
            params = {
                "model": Config.OPENAI_MODEL,
                "messages": messages,
                "max_completion_tokens": 200
            }
            
            # Добавляем temperature только если это не GPT-5
            if "gpt-5" not in Config.OPENAI_MODEL.lower():
                params["temperature"] = 0.8
            
            response = self.openai_client.chat.completions.create(**params)
            
            reply = response.choices[0].message.content.strip()
            
            # Сохраняем сообщения в историю
            self.save_message(user_id, 'user', user_message)
            self.save_message(user_id, 'assistant', reply)
            
            return reply
            
        except Exception as e:
            print(f"Ошибка при генерации ответа: {e}")
            return "Привет! 😊 Извини, сейчас не могу ответить подробно..."
    
    def is_bot_mentioned(self, message_text: str) -> bool:
        """Проверяет, упоминается ли бот в сообщении"""
        if not self.bot_username or not message_text:
            return False
        
        text_lower = message_text.lower()
        # Проверяем упоминание через @username
        if f"@{self.bot_username}" in text_lower:
            return True
        
        # Проверяем прямое обращение (можно расширить)
        me = self.client.get_me()
        if me and hasattr(me, 'first_name'):
            if me.first_name.lower() in text_lower:
                return True
        
        return False
    
    def analyze_chat_topic(self, chat_id: int) -> str:
        """Анализирует тему чата на основе последних сообщений"""
        try:
            # Получаем последние сообщения из чата
            messages = self.client.get_messages(chat_id, limit=20)
            if not messages:
                return "общий разговор"
            
            # Собираем текст последних сообщений
            recent_texts = []
            for msg in messages[:10]:
                if msg.text:
                    recent_texts.append(msg.text[:100])  # Первые 100 символов
            
            if not recent_texts:
                return "общий разговор"
            
            # Анализируем через GPT
            try:
                response = self.openai_client.chat.completions.create(
                    model=Config.OPENAI_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": "Ты анализируешь тему разговора в чате. Определи основную тему на основе последних сообщений. Ответь одним коротким предложением (до 10 слов)."
                        },
                        {
                            "role": "user",
                            "content": f"Последние сообщения в чате:\n" + "\n".join(recent_texts[:5])
                        }
                    ],
                    max_completion_tokens=50,
                    temperature=0.7
                )
                topic = response.choices[0].message.content.strip()
                return topic if topic else "общий разговор"
            except Exception:
                return "общий разговор"
        except Exception as e:
            print(f"Ошибка при анализе темы чата: {e}")
            return "общий разговор"
    
    def generate_chat_message(self, chat_id: int, context: str = "") -> str:
        """Генерирует сообщение для чата на основе темы"""
        try:
            # Анализируем тему чата
            topic = self.analyze_chat_topic(chat_id)
            
            messages = [
                {
                    "role": "system",
                    "content": Config.GIRL_PERSONA_SYSTEM + "\n\nТы в групповом чате. Пиши естественно, по теме разговора. Будь активной, но не навязчивой."
                },
                {
                    "role": "user",
                    "content": f"Тема разговора в чате: {topic}\n{context}\n\nНапиши короткое естественное сообщение (до 15 слов) по теме чата. Будь живой и эмоциональной."
                }
            ]
            
            params = {
                "model": Config.OPENAI_MODEL,
                "messages": messages,
                "max_completion_tokens": 100
            }
            
            if "gpt-5" not in Config.OPENAI_MODEL.lower():
                params["temperature"] = 0.9
            
            response = self.openai_client.chat.completions.create(**params)
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Ошибка при генерации сообщения для чата: {e}")
            return None
    
    def handle_chat_message(self, event: events.NewMessage.Event):
        """Обрабатывает сообщение в чате/группе"""
        if not Config.CHAT_RESPONDER_ENABLED:
            return
        
        message = event.message
        chat = event.chat
        
        # Проверяем, что это не от нас самих
        if message.out:
            return
        
        # Проверяем, что это группа/чат, а не канал
        if not isinstance(chat, (Chat, Channel)) or (isinstance(chat, Channel) and chat.broadcast):
            return
        
        chat_id = chat.id
        user_text = message.text or ""
        
        # Обновляем время последнего сообщения в чате
        self.chat_last_message_time[chat_id] = time.time()
        
        # Добавляем чат в активные, если его там нет
        chat_identifier = str(chat_id)
        if chat_identifier not in self.active_chats:
            try:
                chat_username = getattr(chat, 'username', None)
                if chat_username:
                    chat_identifier = f"@{chat_username}"
                else:
                    chat_identifier = str(chat_id)
                
                if chat_identifier not in self.active_chats:
                    self.active_chats.append(chat_identifier)
                    self._save_active_chats()
            except Exception as e:
                print(f"Ошибка при добавлении чата в активные: {e}")
        
        # Проверяем, нужно ли отвечать
        should_respond = False
        
        # Проверяем упоминание бота
        if Config.CHAT_RESPOND_TO_MENTIONS and self.is_bot_mentioned(user_text):
            should_respond = True
        
        # Проверяем прямое обращение (можно расширить логику)
        if Config.CHAT_RESPOND_TO_DIRECT and user_text.strip():
            # Простая проверка на вопросы или обращения
            if any(word in user_text.lower() for word in ['?', '!', 'привет', 'здравствуй', 'как дела']):
                should_respond = True
        
        if should_respond:
            # Генерируем ответ
            try:
                reply = self.generate_response(chat_id, user_text)
                if reply:
                    delay = random.randint(Config.RESPONSE_DELAY_MIN, Config.RESPONSE_DELAY_MAX)
                    time.sleep(delay)
                    self.client.send_message(chat_id, reply, reply_to=message.id)
                    print(f"💬 Ответ в чате {getattr(chat, 'title', chat_id)}: {reply[:50]}...")
            except Exception as e:
                print(f"❌ Ошибка при отправке ответа в чат: {e}")
    
    def handle_new_message(self, event: events.NewMessage.Event):
        """Обрабатывает новое входящее сообщение"""
        if not Config.AUTORESPONDER_ENABLED:
            return
        
        message = event.message
        sender = event.sender
        
        # Если это чат/группа - обрабатываем отдельно
        if not event.is_private:
            if Config.CHAT_RESPONDER_ENABLED:
                self.handle_chat_message(event)
            return
        
        # Проверяем, что это не от нас самих
        if message.out:
            return
        
        # Проверяем, незнакомый ли пользователь
        user_id = sender.id if sender else 0
        if not user_id or not self.is_unknown_user(user_id):
            return
        
        # Увеличиваем счетчик сообщений (в БД)
        msg_count = self.db.increment_message_count(user_id)
        
        # Генерируем ответ
        user_text = message.text or ""
        if not user_text.strip():
            return  # Игнорируем сообщения без текста
        
        sender_name = sender.first_name if sender else "Неизвестный"
        sender_username = getattr(sender, 'username', None) if sender else None
        print(f"💬 Новое сообщение от {sender_name} (@{sender_username or 'нет'}): {user_text[:50]}...")
        
        # Генерируем ответ
        reply = self.generate_response(user_id, user_text)
        
        # Задержка перед ответом для естественности
        delay = random.randint(Config.RESPONSE_DELAY_MIN, Config.RESPONSE_DELAY_MAX)
        time.sleep(delay)
        
        # Отправляем ответ (используем синхронный метод для синхронного клиента)
        try:
            # Для синхронного клиента используем обычный вызов
            self.client.send_message(user_id, reply, reply_to=message.id)
            print(f"✅ Ответ отправлен: {reply[:50]}...")
        except Exception as e:
            print(f"❌ Ошибка при отправке ответа: {e}")
    
    def periodic_chat_messages_task(self):
        """Периодически отправляет сообщения в активные чаты"""
        if not Config.CHAT_PERIODIC_MESSAGES_ENABLED:
            return
        
        while True:
            try:
                # Ждем случайный интервал
                interval = random.randint(
                    Config.CHAT_PERIODIC_INTERVAL_MIN,
                    Config.CHAT_PERIODIC_INTERVAL_MAX
                )
                time.sleep(interval)
                
                # Проверяем активные чаты
                if not self.active_chats:
                    continue
                
                # Выбираем случайный чат
                if not self.active_chats:
                    continue
                
                chat_identifier = random.choice(self.active_chats)
                
                # Пытаемся получить entity чата
                try:
                    chat_entity = self.client.get_entity(chat_identifier)
                    chat_id = chat_entity.id
                except Exception as e:
                    print(f"Ошибка при получении entity чата {chat_identifier}: {e}")
                    continue
                
                # Проверяем, было ли недавно сообщение в чате
                last_message_time = self.chat_last_message_time.get(chat_id, 0)
                time_since_last = time.time() - last_message_time
                
                # Если в чате не было активности более 10 минут, пропускаем
                if time_since_last < 600:  # 10 минут
                    continue
                
                # Генерируем и отправляем сообщение
                try:
                    message = self.generate_chat_message(chat_id)
                    if message:
                        self.client.send_message(chat_entity, message)
                        chat_title = getattr(chat_entity, 'title', chat_identifier)
                        print(f"📢 Периодическое сообщение в {chat_title}: {message[:50]}...")
                        # Обновляем время последнего сообщения
                        self.chat_last_message_time[chat_id] = time.time()
                except Exception as e:
                    print(f"❌ Ошибка при отправке периодического сообщения: {e}")
                    
            except Exception as e:
                print(f"❌ Ошибка в задаче периодических сообщений: {e}")
                time.sleep(60)  # Ждем минуту перед повтором
    
    def start_listening(self):
        """Запускает прослушивание новых сообщений"""
        if not Config.AUTORESPONDER_ENABLED:
            return
        
        # Для синхронного клиента Telethon все равно требует async обработчик
        # Но мы можем вызывать синхронные методы внутри через asyncio
        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event):
            # Используем asyncio для вызова синхронной функции в async контексте
            import asyncio
            try:
                # Запускаем синхронную функцию в отдельном потоке
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.handle_new_message, event)
            except Exception as e:
                print(f"❌ Ошибка в обработчике автоответчика: {e}")
        
        # Запускаем задачу периодических сообщений в отдельном потоке
        if Config.CHAT_PERIODIC_MESSAGES_ENABLED:
            periodic_thread = threading.Thread(target=self.periodic_chat_messages_task, daemon=True)
            periodic_thread.start()
            print("📢 Задача периодических сообщений в чаты запущена...")
        
        print("👂 Автоответчик запущен и слушает новые сообщения...")

