"""
Главный файл бота для нейрокомментинга
Объединяет все модули: комментирование, автоответчик, поиск, вступление в каналы
"""
from telethon.sync import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    UsernameInvalidError,
    MessageIdInvalidError
)
from telethon.errors.rpcerrorlist import MsgIdInvalidError
from openai import OpenAI
import time
import random
import threading
import base64
import io
import os
import tempfile
from datetime import datetime, timezone
from config import Config
from modules.channel_joiner import ChannelJoiner
from modules.comment_checker import CommentChecker
from modules.autoresponder import AutoResponder
from modules.keyword_search import KeywordSearch
from modules.comment_generator import CommentGenerator
from modules.reactions import ReactionManager
from utils.logger import Logger
from utils.database import Database


class TelegramCommentator:
    """Главный класс бота"""
    
    def __init__(self):
        # Инициализация OpenAI клиента
        self.openai_client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL
        )
        
        # Инициализация Telegram клиента
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        self.client = None
        
        # Инициализация базы данных
        self.db = Database(Config.DATABASE_PATH)
        
        # Инициализация модулей
        self.channel_joiner = None
        self.comment_checker = None
        self.autoresponder = None
        self.keyword_search = None
        self.comment_generator = CommentGenerator(self.openai_client)
        self.reaction_manager = None
        
        # Логирование
        self.logger = Logger()
        
        # Загружаем список каналов для комментирования
        self.active_channels = Config.load_channels_from_file(Config.ACTIVE_CHANNELS_FILE)
        if not self.active_channels:
            # Если нет активных каналов, создаем пустой список
            self.active_channels = []
            self.logger.warning("⚠️ Список активных каналов пуст! Добавьте каналы в data/active_channels.txt")
    
    def _extract_video_screenshot(self, media) -> bytes:
        """
        Извлекает скриншот из видео
        
        Args:
            media: Media объект из Telegram
        
        Returns:
            bytes: JPEG байты скриншота или None при ошибке
        """
        temp_video_path = None
        try:
            # Пробуем использовать OpenCV для извлечения кадра
            try:
                import cv2
            except ImportError:
                self.logger.warning("⚠️ OpenCV не установлен. Установите: pip install opencv-python")
                return None
            
            # Создаем временный файл для видео
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                temp_video_path = temp_file.name
            
            # Скачиваем видео во временный файл
            self.logger.info(f"📥 Скачивание видео для извлечения скриншота...")
            self.client.download_media(media, file=temp_video_path)
            
            # Открываем видео через OpenCV
            cap = cv2.VideoCapture(temp_video_path)
            
            if not cap.isOpened():
                self.logger.warning("⚠️ Не удалось открыть видео файл")
                return None
            
            # Получаем FPS и общее количество кадров
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if total_frames == 0:
                self.logger.warning("⚠️ Видео не содержит кадров")
                cap.release()
                return None
            
            # Вычисляем номер кадра для скриншота (по умолчанию 1 секунда от начала)
            target_frame = int(Config.VIDEO_SCREENSHOT_TIME * fps)
            if target_frame >= total_frames:
                target_frame = total_frames - 1
            if target_frame < 0:
                target_frame = 0
            
            # Переходим к нужному кадру
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            
            # Читаем кадр
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                self.logger.warning("⚠️ Не удалось извлечь кадр из видео")
                return None
            
            # Конвертируем BGR в RGB (OpenCV использует BGR)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Кодируем в JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
            result, encoded_img = cv2.imencode('.jpg', frame_rgb, encode_param)
            
            if not result:
                self.logger.warning("⚠️ Не удалось закодировать кадр в JPEG")
                return None
            
            # Конвертируем numpy array в bytes
            screenshot_bytes = encoded_img.tobytes()
            
            self.logger.info(f"✅ Скриншот извлечен (размер: {len(screenshot_bytes) / 1024:.1f}KB)")
            return screenshot_bytes
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка при извлечении скриншота из видео: {e}")
            return None
        finally:
            # Удаляем временный файл
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.unlink(temp_video_path)
                except Exception as e:
                    self.logger.warning(f"⚠️ Не удалось удалить временный файл: {e}")
    
    def start_telegram_client(self):
        """Запускает клиент Telegram"""
        self.logger.info("🔌 Подключение к Telegram...")
        self.client = TelegramClient(Config.SESSION_NAME, self.api_id, self.api_hash)
        self.client.start()
        
        me = self.client.get_me()
        self.logger.info(f"✅ Подключен как: {me.first_name} (@{me.username or 'нет'})")
        
        # Инициализируем модули после подключения (передаем БД)
        self.channel_joiner = ChannelJoiner(self.client)
        self.comment_checker = CommentChecker(self.client, self.db)
        self.autoresponder = AutoResponder(self.client, self.openai_client, self.db)
        self.keyword_search = KeywordSearch(self.client, self.db)
        self.reaction_manager = ReactionManager(self.client)
    
    def join_channels_task(self):
        """Задача автоматического вступления в каналы"""
        self.logger.info("📥 Запуск задачи вступления в каналы...")
        if self.channel_joiner:
            results = self.channel_joiner.join_all_channels(Config.OWNER_ID)
            self.logger.info(f"✅ Вступление завершено. Успешно: {sum(1 for s, _ in results.values() if s)}")
    
    def check_channels_task(self):
        """Задача проверки каналов на возможность комментирования"""
        self.logger.info("🔍 Проверка каналов на возможность комментирования...")
        if self.comment_checker:
            # Проверяем все каналы
            all_channels = list(set(
                self.active_channels + 
                Config.load_channels_from_file(Config.CHANNELS_TO_JOIN_FILE)
            ))
            
            results = self.comment_checker.check_channels(all_channels)
            
            # Фильтруем только те, где можно комментировать
            self.active_channels = self.comment_checker.filter_active_channels(all_channels)
            
            self.logger.info(f"✅ Проверка завершена. Активных каналов: {len(self.active_channels)}")
    
    def search_task(self):
        """Задача поиска аниме каналов"""
        if not Config.SEARCH_ENABLED:
            return
        
        self.logger.info("🎌 Запуск поиска аниме каналов...")
        if self.keyword_search:
            # Ищем аниме каналы с автоматическим добавлением
            results = self.keyword_search.search_all(auto_add_to_active=Config.SEARCH_AUTO_ADD_TO_ACTIVE)
            
            # Обновляем список активных каналов если были добавлены новые
            if results.get('added_channels'):
                self.active_channels = Config.load_channels_from_file(Config.ACTIVE_CHANNELS_FILE)
                self.logger.info(f"📺 Обновлен список активных каналов. Всего: {len(self.active_channels)}")
            
            # Отправляем отчет владельцу
            if Config.OWNER_ID:
                report = f"🎌 Результаты поиска аниме каналов:\n\n"
                report += f"📺 Найдено каналов: {len(results['channels'])}\n"
                report += f"➕ Добавлено новых: {len(results.get('added_channels', []))}\n"
                report += f"📝 Найдено постов: {len(results['posts'])}\n"
                
                if results.get('added_channels'):
                    report += "\n📺 Новые аниме каналы добавлены:\n"
                    for ch in results['added_channels'][:10]:  # Первые 10
                        report += f"  • {ch}\n"
                elif results['channels']:
                    report += "\n📺 Найденные каналы:\n"
                    for ch in results['channels'][:10]:  # Первые 10
                        report += f"  • {ch.get('username', ch.get('title', 'Неизвестно'))}\n"
                
                self.client.send_message(Config.OWNER_ID, report)
            
            self.logger.info(f"✅ Поиск завершен. Добавлено {len(results.get('added_channels', []))} новых аниме каналов")
    
    def write_comments_in_telegram(self):
        """Основной цикл комментирования постов"""
        if not self.active_channels:
            self.logger.warning("⚠️ Нет активных каналов для комментирования")
            return
        
        # Создаем копию списка для безопасной итерации (на случай удаления элементов)
        channels_to_process = self.active_channels.copy()
        
        for name in channels_to_process:
            try:
                channel_entity = self.client.get_entity(name)
            except Exception as e:
                self.logger.error(f"Ошибка при получении канала '{name}': {e}")
                # Удаляем недоступный канал из активных
                if name in self.active_channels:
                    self.active_channels.remove(name)
                    Config.save_channels_to_file(self.active_channels, Config.ACTIVE_CHANNELS_FILE)
                    self.logger.warning(f"🗑️ Канал '{name}' удален (недоступен)")
                if Config.OWNER_ID:
                    self.client.send_message(
                        Config.OWNER_ID, 
                        f"🗑️ Канал '{name}' удален из активных (недоступен: {e})"
                    )
                continue
            
            try:
                # Пробуем проверить, поддерживает ли канал комментарии, пытаясь получить информацию о посте
                messages = self.client.get_messages(channel_entity, limit=1)
                if messages:
                    for post in messages:
                        # ИСПРАВЛЕНО: Проверяем в БД, был ли пост уже обработан
                        if self.db.is_post_processed(name, post.id):
                            continue  # Пропускаем уже обработанные посты
                        
                        # Получаем текст поста
                        post_text = post.raw_text or ""
                        
                        # Получаем изображение или скриншот из видео если есть
                        image_data = None
                        if (Config.SUPPORT_IMAGES or Config.SUPPORT_VIDEOS) and post.media:
                            try:
                                from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
                                
                                image_type = None
                                mime_type = None
                                is_video = False
                                image_bytes = None
                                
                                # Проверяем тип медиа
                                if isinstance(post.media, MessageMediaPhoto):
                                    # Это фото - по умолчанию JPEG
                                    image_type = 'jpeg'
                                elif isinstance(post.media, MessageMediaDocument):
                                    # Это документ - проверяем mime_type
                                    if hasattr(post.media.document, 'mime_type') and post.media.document.mime_type:
                                        mime_type = post.media.document.mime_type
                                        
                                        # Проверяем, это видео?
                                        if Config.SUPPORT_VIDEOS and mime_type.startswith('video/'):
                                            is_video = True
                                            self.logger.info(f"🎬 Обнаружено видео в посте {post.id} (тип: {mime_type})")
                                            
                                            # Проверяем размер видео
                                            video_size = 0
                                            if hasattr(post.media.document, 'size'):
                                                video_size = post.media.document.size
                                            
                                            if video_size > Config.VIDEO_MAX_SIZE_MB * 1024 * 1024:
                                                self.logger.warning(f"⚠️ Видео слишком большое ({video_size / 1024 / 1024:.2f}MB), пропускаю")
                                                image_data = None
                                            else:
                                                # Извлекаем скриншот из видео
                                                try:
                                                    screenshot_bytes = self._extract_video_screenshot(post.media)
                                                    if screenshot_bytes:
                                                        image_bytes = screenshot_bytes
                                                        image_type = 'jpeg'  # Скриншоты всегда JPEG
                                                        self.logger.info(f"📸 Скриншот извлечен из видео в посте {post.id}")
                                                    else:
                                                        image_type = None
                                                        image_data = None
                                                except Exception as video_e:
                                                    self.logger.warning(f"⚠️ Ошибка при извлечении скриншота из видео: {video_e}")
                                                    image_type = None
                                                    image_data = None
                                        
                                        # Если не видео, проверяем форматы изображений
                                        elif mime_type.lower().startswith('image/'):
                                            # Поддерживаемые форматы: png, jpeg, gif, webp
                                            supported_formats = {
                                                'image/png': 'png',
                                                'image/jpeg': 'jpeg',
                                                'image/jpg': 'jpeg',
                                                'image/gif': 'gif',
                                                'image/webp': 'webp'
                                            }
                                            
                                            if mime_type.lower() in supported_formats:
                                                image_type = supported_formats[mime_type.lower()]
                                            else:
                                                # Неподдерживаемый формат
                                                self.logger.warning(f"⚠️ Неподдерживаемый формат изображения: {mime_type}, пропускаю изображение")
                                                image_data = None
                                        else:
                                            # Неизвестный тип медиа
                                            image_data = None
                                    else:
                                        # Нет mime_type - пропускаем
                                        image_data = None
                                else:
                                    # Неизвестный тип медиа
                                    image_data = None
                                
                                if image_type:
                                    # Если это не видео (скриншот уже извлечен), скачиваем файл
                                    if not is_video:
                                        image_bytes = self.client.download_media(post.media, file=io.BytesIO())
                                    # Для видео image_bytes уже содержит скриншот
                                    
                                    if image_bytes:
                                        # Если это BytesIO, получаем байты
                                        if isinstance(image_bytes, io.BytesIO):
                                            image_bytes = image_bytes.getvalue()
                                        
                                        # Проверяем реальный формат по магическим байтам
                                        def detect_image_format(bytes_data):
                                            """Определяет формат изображения по магическим байтам"""
                                            if len(bytes_data) < 4:
                                                return None
                                            
                                            # PNG: 89 50 4E 47
                                            if bytes_data[:4] == b'\x89PNG':
                                                return 'png'
                                            # JPEG: FF D8 FF
                                            elif bytes_data[:3] == b'\xFF\xD8\xFF':
                                                return 'jpeg'
                                            # GIF: 47 49 46 38
                                            elif bytes_data[:4] == b'GIF8':
                                                return 'gif'
                                            # WebP: RIFF...WEBP
                                            elif bytes_data[:4] == b'RIFF' and len(bytes_data) > 8 and bytes_data[8:12] == b'WEBP':
                                                return 'webp'
                                            return None
                                        
                                        # Определяем реальный формат
                                        detected_format = detect_image_format(image_bytes)
                                        if detected_format:
                                            image_type = detected_format
                                            self.logger.debug(f"🔍 Определен формат изображения по магическим байтам: {image_type}")
                                        
                                        # Проверяем размер (не более 20MB для Vision API)
                                        if len(image_bytes) > 20 * 1024 * 1024:
                                            self.logger.warning(f"⚠️ Изображение слишком большое ({len(image_bytes) / 1024 / 1024:.2f}MB), пропускаю")
                                            image_data = None
                                        else:
                                            # Конвертируем в base64 для Vision API
                                            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                                            # Формируем data URL для OpenAI Vision API (используем правильный формат)
                                            image_data = f"data:image/{image_type};base64,{image_base64}"
                                            self.logger.info(f"📷 Обнаружено изображение в посте {post.id} (тип: {image_type}, размер: {len(image_bytes) / 1024:.1f}KB)")
                                    
                            except Exception as e:
                                self.logger.warning(f"⚠️ Ошибка при обработке изображения: {e}")
                                image_data = None
                        
                        # Если нет текста и нет изображения - пропускаем
                        if not post_text.strip() and not image_data:
                            continue
                        
                        # КРИТИЧНО: Проверяем возможность комментирования ДО генерации комментария
                        # Это экономит время и ресурсы API
                        can_comment = False
                        try:
                            from telethon.tl.functions.messages import GetDiscussionMessageRequest
                            
                            # Пытаемся получить discussion message - если это работает, значит комментарии поддерживаются
                            try:
                                self.client(GetDiscussionMessageRequest(
                                    peer=channel_entity,
                                    msg_id=post.id
                                ))
                                can_comment = True
                                self.logger.debug(f"✅ Канал {name} поддерживает комментарии")
                            except (MessageIdInvalidError, MsgIdInvalidError) as e:
                                # Комментарии не поддерживаются или пост не существует в обсуждении
                                error_str = str(e)
                                if "message ID used in the peer was invalid" in error_str.lower():
                                    self.logger.warning(f"⚠️ Канал {name} не поддерживает комментарии (проверка до генерации)")
                                    # Отмечаем пост как обработанный и удаляем канал
                                    self.db.mark_post_processed(name, post.id)
                                    
                                    if name in self.active_channels:
                                        self.active_channels.remove(name)
                                        Config.save_channels_to_file(self.active_channels, Config.ACTIVE_CHANNELS_FILE)
                                        self.logger.warning(f"🗑️ Канал {name} удален из активных (комментарии закрыты)")
                                        
                                        if Config.OWNER_ID:
                                            try:
                                                self.client.send_message(
                                                    Config.OWNER_ID, 
                                                    f"🗑️ Канал {name} удален из активных каналов.\n"
                                                    f"Причина: комментарии в канале закрыты или не поддерживаются."
                                                )
                                            except Exception:
                                                pass
                                    continue  # Пропускаем этот пост
                            except Exception as check_e:
                                # Другие ошибки - возможно, нужно вступить в группу
                                error_str = str(check_e)
                                if "join the discussion group" in error_str.lower() or "requiring-users-to-join-the-group" in error_str.lower():
                                    # Нужно вступить в группу - попробуем
                                    try:
                                        from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
                                        
                                        channel_full_info = self.client(GetFullChannelRequest(channel_entity))
                                        if hasattr(channel_full_info, 'linked_chat') and channel_full_info.linked_chat:
                                            discussion_group = channel_full_info.linked_chat
                                            self.client(JoinChannelRequest(discussion_group))
                                            self.logger.info(f"✅ Вступил в группу обсуждения для {name} (проверка)")
                                            time.sleep(2)
                                            can_comment = True
                                        else:
                                            # Группа обсуждения не найдена - комментарии не поддерживаются
                                            can_comment = False
                                            self.logger.warning(f"⚠️ Группа обсуждения не найдена для {name}, комментарии не поддерживаются")
                                    except Exception as join_err:
                                        # Не удалось вступить в группу - комментарии не поддерживаются
                                        can_comment = False
                                        self.logger.warning(f"⚠️ Не удалось вступить в группу для {name}: {join_err}")
                                else:
                                    # Неизвестная ошибка - предполагаем, что можно комментировать
                                    can_comment = True
                        except Exception as e:
                            # Если не удалось проверить - предполагаем, что можно комментировать
                            self.logger.debug(f"Не удалось проверить возможность комментирования для {name}: {e}")
                            can_comment = True
                        
                        # Если комментарии не поддерживаются - пропускаем и удаляем канал
                        if not can_comment:
                            self.logger.warning(f"⚠️ Комментарии не поддерживаются в {name}, пропускаю пост и удаляю канал")
                            # Отмечаем пост как обработанный
                            self.db.mark_post_processed(name, post.id)
                            
                            # Удаляем канал из активных
                            if name in self.active_channels:
                                self.active_channels.remove(name)
                                Config.save_channels_to_file(self.active_channels, Config.ACTIVE_CHANNELS_FILE)
                                self.logger.warning(f"🗑️ Канал {name} удален из активных (комментарии не поддерживаются)")
                                
                                if Config.OWNER_ID:
                                    try:
                                        self.client.send_message(
                                            Config.OWNER_ID, 
                                            f"🗑️ Канал {name} удален из активных каналов.\n"
                                            f"Причина: комментарии в канале закрыты или не поддерживаются."
                                        )
                                    except Exception:
                                        pass
                            continue
                        
                        self.logger.info(f"📝 Генерация комментария к посту {post.id} в {name}...")
                        
                        # Проверяем и вступаем в группу обсуждения если нужно (дополнительная проверка)
                        try:
                            from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
                            
                            # Получаем полную информацию о канале
                            channel_full_info = self.client(GetFullChannelRequest(channel_entity))
                            
                            # Проверяем, есть ли связанная группа обсуждения
                            if hasattr(channel_full_info, 'linked_chat') and channel_full_info.linked_chat:
                                discussion_group = channel_full_info.linked_chat
                                
                                # Проверяем, вступили ли мы в группу
                                try:
                                    # Пытаемся получить информацию о группе
                                    self.client.get_entity(discussion_group)
                                    self.logger.debug(f"✅ Уже в группе обсуждения для {name}")
                                except Exception:
                                    # Не в группе - вступаем
                                    try:
                                        self.client(JoinChannelRequest(discussion_group))
                                        self.logger.info(f"✅ Вступил в группу обсуждения для {name}")
                                        time.sleep(2)  # Небольшая задержка после вступления
                                    except Exception as join_e:
                                        self.logger.warning(f"⚠️ Не удалось вступить в группу обсуждения для {name}: {join_e}")
                        except Exception as e:
                            # Если не удалось получить информацию о канале или группы нет - продолжаем
                            self.logger.debug(f"Группа обсуждения не найдена или недоступна для {name}: {e}")
                        
                        # Ставим реакцию перед комментарием (если включено)
                        if Config.USE_REACTIONS and self.reaction_manager:
                            self.reaction_manager.send_reaction(channel_entity, post.id)
                            time.sleep(2)  # Небольшая задержка после реакции
                        
                        # Генерируем комментарий (передаем image_data вместо image_url)
                        comment = self.comment_generator.generate_comment(post_text, image_data)
                        
                        # Задержка перед отправкой
                        delay = random.randint(Config.COMMENT_DELAY_MIN, Config.COMMENT_DELAY_MAX)
                        time.sleep(delay)
                        
                        try:
                            # Отправляем комментарий
                            self.client.send_message(
                                entity=name, 
                                message=comment, 
                                comment_to=post.id
                            )
                            
                            # КРИТИЧНО: СРАЗУ отмечаем пост как обработанный ДО отправки отчета
                            # Это предотвратит повторную отправку при следующей итерации
                            self.db.mark_post_processed(name, post.id)
                            self.logger.info(f"✅ Пост {post.id} в {name} отмечен как обработанный в БД")
                            
                            # Отправляем отчет владельцу
                            if Config.OWNER_ID:
                                report = (
                                    f'✅ Комментарий отправлен!\n\n'
                                    f'📺 Канал: {name}\n'
                                    f'🔗 Ссылка: https://t.me/{name}/{post.id}\n\n'
                                    f'📝 Пост: {post_text[:100]}...\n\n'
                                    f'💬 Комментарий: {comment}'
                                )
                                self.client.send_message(Config.OWNER_ID, report)
                            
                            self.logger.info(f'✅ Комментарий отправлен в {name}')
                            
                        except (MessageIdInvalidError, MsgIdInvalidError) as e:
                            # Обрабатываем ошибку невалидного ID сообщения отдельно
                            error_str = str(e)
                            self.logger.warning(f"⚠️ Ошибка MessageIdInvalidError для поста {post.id} в {name}: {error_str}")
                            
                            # Отмечаем пост как обработанный и удаляем канал из активных
                            self.db.mark_post_processed(name, post.id)
                            
                            if name in self.active_channels:
                                self.active_channels.remove(name)
                                Config.save_channels_to_file(self.active_channels, Config.ACTIVE_CHANNELS_FILE)
                                self.logger.warning(f"🗑️ Канал {name} удален из активных (комментарии закрыты или не поддерживаются)")
                                
                                if Config.OWNER_ID:
                                    try:
                                        self.client.send_message(
                                            Config.OWNER_ID, 
                                            f"🗑️ Канал {name} удален из активных каналов.\n"
                                            f"Причина: комментарии в канале закрыты или не поддерживаются."
                                        )
                                    except Exception:
                                        pass  # Игнорируем ошибки при отправке уведомления
                            continue  # Пропускаем этот канал
                            
                        except Exception as e:
                            error_str = str(e)
                            
                            # Проверяем, что это ошибка "нужно вступить в группу"
                            if ("join the discussion group" in error_str.lower() or
                                "requiring-users-to-join-the-group" in error_str.lower()):
                                # Пытаемся вступить в группу обсуждения и повторить попытку
                                try:
                                    from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
                                    
                                    # Получаем полную информацию о канале
                                    channel_full_info = self.client(GetFullChannelRequest(channel_entity))
                                    
                                    if hasattr(channel_full_info, 'linked_chat') and channel_full_info.linked_chat:
                                        discussion_group = channel_full_info.linked_chat
                                        
                                        # Вступаем в группу
                                        self.client(JoinChannelRequest(discussion_group))
                                        self.logger.info(f"✅ Вступил в группу обсуждения для {name} после ошибки")
                                        time.sleep(3)  # Задержка после вступления
                                        
                                        # Повторяем попытку отправки комментария
                                        try:
                                            self.client.send_message(
                                                entity=name, 
                                                message=comment, 
                                                comment_to=post.id
                                            )
                                            
                                            # Успешно отправили после вступления
                                            self.db.mark_post_processed(name, post.id)
                                            self.logger.info(f"✅ Комментарий отправлен в {name} после вступления в группу")
                                            
                                            if Config.OWNER_ID:
                                                report = (
                                                    f'✅ Комментарий отправлен!\n\n'
                                                    f'📺 Канал: {name}\n'
                                                    f'🔗 Ссылка: https://t.me/{name}/{post.id}\n\n'
                                                    f'📝 Пост: {post_text[:100]}...\n\n'
                                                    f'💬 Комментарий: {comment}'
                                                )
                                                self.client.send_message(Config.OWNER_ID, report)
                                            
                                            continue  # Успешно, переходим к следующему посту
                                        except Exception as retry_e:
                                            # Не удалось даже после вступления
                                            self.logger.error(f"❌ Не удалось отправить комментарий в {name} даже после вступления в группу: {retry_e}")
                                            self.db.mark_post_processed(name, post.id)  # Отмечаем как обработанный, чтобы не спамить
                                            continue
                                    else:
                                        # Группа обсуждения не найдена
                                        self.logger.warning(f"⚠️ Группа обсуждения не найдена для {name}")
                                        self.db.mark_post_processed(name, post.id)
                                        continue
                                except Exception as join_error:
                                    # Не удалось вступить в группу
                                    self.logger.error(f"❌ Не удалось вступить в группу обсуждения для {name}: {join_error}")
                                    self.db.mark_post_processed(name, post.id)  # Отмечаем как обработанный
                                    continue
                            
                            # Проверяем, что это ошибка "комментарии не поддерживаются" (если не обработано выше)
                            if ("GetDiscussionMessageRequest" in error_str or 
                                "message ID used in the peer was invalid" in error_str.lower()):
                                # Канал не поддерживает комментарии - отмечаем пост как обработанный
                                # и удаляем канал из активных, так как он нам не нужен
                                self.db.mark_post_processed(name, post.id)
                                
                                # Удаляем канал из активных
                                if name in self.active_channels:
                                    self.active_channels.remove(name)
                                    Config.save_channels_to_file(self.active_channels, Config.ACTIVE_CHANNELS_FILE)
                                    self.logger.warning(f"🗑️ Канал {name} удален из активных (комментарии закрыты)")
                                    
                                    if Config.OWNER_ID:
                                        try:
                                            self.client.send_message(
                                                Config.OWNER_ID, 
                                                f"🗑️ Канал {name} удален из активных каналов.\n"
                                                f"Причина: комментарии в канале закрыты или не поддерживаются."
                                            )
                                        except Exception:
                                            pass  # Игнорируем ошибки при отправке уведомления
                                continue  # Пропускаем этот канал дальше
                            
                            # Для других ошибок - логируем как обычно и отмечаем пост как обработанный
                            self.db.mark_post_processed(name, post.id)  # Отмечаем, чтобы не спамить
                            error_msg = f"Ошибка при отправке комментария в '{name}': {e}"
                            self.logger.error(error_msg)
                            if Config.OWNER_ID:
                                self.client.send_message(Config.OWNER_ID, f"❌ {error_msg}")
                        
                        # Дополнительная задержка после комментария
                        time.sleep(random.randint(Config.COMMENT_DELAY_MIN, Config.COMMENT_DELAY_MAX))
                            
            except Exception as e:
                self.logger.error(f"Ошибка при обработке канала '{name}': {e}")
    
    def start_autoresponder(self):
        """Запускает автоответчик"""
        if Config.AUTORESPONDER_ENABLED and self.autoresponder:
            self.logger.info("💬 Запуск автоответчика...")
            self.autoresponder.start_listening()
    
    def run(self):
        """Главный цикл работы бота"""
        # Запускаем клиент
        self.start_telegram_client()
        
        # Запускаем автоответчик
        self.start_autoresponder()
        
        # Первичные задачи при старте
        self.logger.info("🚀 Выполнение первичных задач...")
        
        # Вступление в каналы (один раз при старте)
        # self.join_channels_task()  # Раскомментируйте, если нужно вступать при каждом запуске
        
        # Проверка каналов (один раз при старте)
        # self.check_channels_task()  # Раскомментируйте, если нужно проверять при каждом запуске
        
        # Поиск по ключевым словам (периодически)
        # self.search_task()  # Раскомментируйте, если нужно искать при каждом запуске
        
        self.logger.info("✅ Бот запущен и готов к работе!")
        self.logger.info(f"📺 Отслеживается {len(self.active_channels)} каналов")
        
        # Основной цикл комментирования
        cycle_count = 0
        while True:
            try:
                cycle_count += 1
                self.logger.info(f"🔄 Цикл #{cycle_count}")
                
                # Комментирование
                self.write_comments_in_telegram()
                
                # Периодически выполняем другие задачи
                if cycle_count % 10 == 0:  # Каждые 10 циклов
                    self.check_channels_task()
                
                if cycle_count % 20 == 0:  # Каждые 20 циклов
                    self.search_task()
                
                # Задержка перед следующим циклом
                time.sleep(60)  # 1 минута между циклами
                
            except KeyboardInterrupt:
                self.logger.info("🛑 Получен сигнал остановки")
                break
            except Exception as e:
                self.logger.error(f"❌ Критическая ошибка: {e}")
                time.sleep(60)  # Ждем перед повтором


if __name__ == "__main__":
    bot = TelegramCommentator()
    bot.run()

