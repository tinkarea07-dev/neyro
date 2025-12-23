"""
Модуль автоматического вступления в каналы
"""
import time
import random
from typing import List, Dict
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import (
    UsernameInvalidError, UsernameNotOccupiedError, PeerFloodError,
    ChannelPrivateError, FloodWaitError
)
from config import Config


class ChannelJoiner:
    """Класс для автоматического вступления в каналы"""
    
    def __init__(self, client: TelegramClient):
        self.client = client
        self.channels_to_join = Config.load_channels_from_file(Config.CHANNELS_TO_JOIN_FILE)
    
    def add_channel(self, channel: str):
        """Добавляет канал в список для вступления"""
        if channel not in self.channels_to_join:
            self.channels_to_join.append(channel)
            Config.save_channels_to_file(self.channels_to_join, Config.CHANNELS_TO_JOIN_FILE)
    
    def remove_channel(self, channel: str):
        """Удаляет канал из списка"""
        if channel in self.channels_to_join:
            self.channels_to_join.remove(channel)
            Config.save_channels_to_file(self.channels_to_join, Config.CHANNELS_TO_JOIN_FILE)
    
    def join_channel(self, channel: str) -> tuple[bool, str]:
        """
        Вступает в канал
        
        Returns:
            (success: bool, message: str)
        """
        try:
            # Получаем entity канала
            entity = self.client.get_entity(channel)
            
            # Пытаемся вступить
            self.client(JoinChannelRequest(entity))
            
            return True, f"Успешно вступил в канал {channel}"
            
        except FloodWaitError as e:
            # КРИТИЧНО: Правильная обработка FloodWait
            wait_seconds = e.seconds + 10  # Добавляем 10 секунд запаса
            print(f"⚠️ FloodWait: нужно подождать {wait_seconds} секунд")
            time.sleep(wait_seconds)
            # Пытаемся снова после ожидания
            try:
                self.client(JoinChannelRequest(entity))
                return True, f"Успешно вступил в канал {channel} после FloodWait"
            except Exception as retry_e:
                return False, f"Ошибка после FloodWait: {str(retry_e)}"
        except UsernameInvalidError:
            return False, f"Неверное имя канала: {channel}"
        except UsernameNotOccupiedError:
            return False, f"Канал не существует: {channel}"
        except PeerFloodError:
            # Старая ошибка, но на всякий случай обрабатываем
            return False, f"Слишком много действий. Нужна задержка перед вступлением в {channel}"
        except ChannelPrivateError:
            return False, f"Канал {channel} приватный или недоступен"
        except Exception as e:
            return False, f"Ошибка при вступлении в {channel}: {str(e)}"
    
    def join_all_channels(self, owner_id: str = None) -> Dict[str, tuple[bool, str]]:
        """
        Вступает во все каналы из списка с задержками
        
        Returns:
            Dict[channel: str, (success: bool, message: str)]
        """
        results = {}
        
        if not self.channels_to_join:
            if owner_id:
                self.client.send_message(owner_id, "📋 Список каналов для вступления пуст.")
            return results
        
        if owner_id:
            self.client.send_message(
                owner_id, 
                f"🔄 Начинаю вступление в {len(self.channels_to_join)} каналов..."
            )
        
        for i, channel in enumerate(self.channels_to_join, 1):
            print(f"[{i}/{len(self.channels_to_join)}] Вступаю в {channel}...")
            
            success, message = self.join_channel(channel)
            results[channel] = (success, message)
            
            if success:
                print(f"✅ {message}")
            else:
                print(f"❌ {message}")
            
            # Задержка между вступлениями (кроме последнего)
            if i < len(self.channels_to_join):
                delay = random.randint(
                    Config.JOIN_CHANNEL_DELAY_MIN, 
                    Config.JOIN_CHANNEL_DELAY_MAX
                )
                print(f"⏳ Задержка {delay} секунд...")
                time.sleep(delay)
        
        # Отправляем отчет владельцу
        if owner_id:
            success_count = sum(1 for success, _ in results.values() if success)
            report = f"📊 Отчет о вступлении в каналы:\n\n"
            report += f"✅ Успешно: {success_count}/{len(results)}\n"
            report += f"❌ Ошибок: {len(results) - success_count}/{len(results)}\n\n"
            
            for channel, (success, msg) in results.items():
                status = "✅" if success else "❌"
                report += f"{status} {channel}: {msg}\n"
            
            self.client.send_message(owner_id, report)
        
        return results
    
    def get_joined_channels(self) -> List[str]:
        """Получает список каналов, в которые уже вступил аккаунт"""
        try:
            dialogs = self.client.get_dialogs()
            channels = []
            for dialog in dialogs:
                if dialog.is_channel:
                    # Получаем username канала если есть
                    try:
                        if hasattr(dialog.entity, 'username') and dialog.entity.username:
                            channels.append(f"@{dialog.entity.username}")
                        else:
                            # Используем ID если нет username
                            channels.append(str(dialog.entity.id))
                    except:
                        continue
            return channels
        except Exception as e:
            print(f"Ошибка при получении списка каналов: {e}")
            return []

