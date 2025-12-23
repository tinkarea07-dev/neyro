from telethon.sync import TelegramClient
from openai import OpenAI
from dotenv import load_dotenv
import os
import time

# Загружаем переменные из файла 1.envv
load_dotenv('1.envv')


class Telegram_Commentator:
    def __init__(self):
        # замените список тегов каналов на свой список
        self.channels: list = ['energynewz', 'militaryZmediaa', 'novosti_ru_24', 'voenacher']
        # Инициализация OpenAI клиента с ProxyAPI
        self.openai_client = OpenAI(
            api_key=os.getenv("OpenAI_token"),
            base_url="https://openai.api.proxyapi.ru/v1"
        )
        
        # Используем данные из .env или официальные ключи Telegram Android
        self.api_id = os.getenv('Api_id')
        if not self.api_id or 'your api id' in self.api_id:
            self.api_id = 6
            self.api_hash = '773215c9f5c3523d69adee020c726d5c'
        else:
            self.api_id = int(self.api_id)
            self.api_hash = os.getenv('Api_hash')
            
        self.owner_ID: str = os.getenv('Owner_id')
        self.client = None

    def start_telegram_client(self):
        # запуск сессии телеграмма
        self.client = TelegramClient('session_name', self.api_id, self.api_hash)
        self.client.start()

    def write_comments_in_telegram(self):
        """
			Чтобы не было бесконечного
			спама под одним и тем же постом,
			сделано сохранение айди поста
			"""
        last_message_ids = {name: 0 for name in self.channels}
        # перебираем каналы по списку
        for name in self.channels:
            try:
                channel_entity = self.client.get_entity(name)
            except ValueError as e:
                self.client.send_message(f'{self.owner_ID}', f"Ошибка при получении информации о канале '{name}': {e}")
                print("Ошибка, проверьте личные сообщения!")
                continue
            messages = self.client.get_messages(channel_entity, limit=1)
            if messages:
                for post in messages:
                    # сохраняем айди поста
                    if post.id != last_message_ids[name]:
                        last_message_ids[name] = post.id
                        """
                        генерируем коммент через GPT-5,
			            промпт адаптирован под персону девушки-аниме фаната
			            """
                        try:
                            # GPT-5 требует max_completion_tokens вместо max_tokens
                            # GPT-5 поддерживает только temperature=1 (по умолчанию), поэтому не передаем этот параметр
                            response = self.openai_client.chat.completions.create(
                                model="openai/gpt-5-2025-08-07",
                                messages=[
                                    {
                                        "role": "system",
                                        "content": "Ты милая девушка 18-22 лет, которая обожает аниме. Общаешься естественно, живо и эмоционально. Пиши короткие яркие комментарии до 11 слов, можешь использовать эмодзи."
                                    },
                                    {
                                        "role": "user",
                                        "content": f"Напиши короткий яркий комментарий к этому посту: {post.raw_text}"
                                    }
                                ],
                                max_completion_tokens=100
                                # temperature не передаем - GPT-5 поддерживает только значение по умолчанию (1)
                            )
                            output = response.choices[0].message.content.strip()
                            # проверка на пустой ответ
                            if output == "":
                                output = "Даже не знаю, что тут сказать... 🤔"
                        except Exception as e:
                            print(f"Ошибка при генерации комментария: {e}")
                            output = "Интересно! 😊"
                        try:
                            # задержка для избежания бана модерами канала
                            time.sleep(25)
                            self.client.send_message(entity=name, message=output, comment_to=post.id)
                            self.client.send_message(f'{self.owner_ID}',
                                                     f'Комментарий отправлен!\nСсылка на пост: <a href="https://t.me/{name}/{post.id}">{name}</a>\nСам пост: {post.raw_text[:90]}\nНаш коммент: {output}',
                                                     parse_mode="html")
                            print('Успешно отправлен коммент, проверьте личные сообщения')
                        except Exception as e:
                            self.client.send_message(f'{self.owner_ID}',
                                                     f"Ошибка при отправке комментария в канал '{name}': {e}")
                            print('Ошибка, проверьте личные сообщения')
                        finally:
                            # сделано для избежания чрезмерного спама
                            time.sleep(25)

    def run(self):
        # запуск и цикл вынесены отдельно для удобства
        self.start_telegram_client()
        while True:
            self.write_comments_in_telegram()


# запускаем наше чудо
AI_commentator = Telegram_Commentator()
AI_commentator.run()