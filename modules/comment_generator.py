"""
Модуль генерации комментариев через GPT (поддерживает текст и изображения)
"""
from openai import OpenAI
from typing import Optional
import random
from config import Config


class CommentGenerator:
    """Класс для генерации комментариев через GPT"""
    
    def __init__(self, openai_client: OpenAI):
        self.openai_client = openai_client
    
    def generate_comment(self, post_text: str = "", image_data: Optional[str] = None) -> str:
        """
        Генерирует комментарий к посту (поддерживает текст и изображения)
        
        Args:
            post_text: Текст поста (может быть пустым)
            image_data: Base64 изображение в формате data:image/jpeg;base64,... (опционально)
        
        Returns:
            str: Сгенерированный комментарий
        """
        try:
            # Определяем модель и формируем сообщения
            model = Config.IMAGE_MODEL if image_data and Config.SUPPORT_IMAGES else Config.OPENAI_MODEL
            
            messages = [
                {
                    "role": "system",
                    "content": Config.COMMENT_PERSONA_SYSTEM
                }
            ]
            
            # Формируем пользовательское сообщение
            if image_data and Config.SUPPORT_IMAGES:
                # Для изображений используем vision модель
                user_content = []
                
                if post_text.strip():
                    user_content.append({
                        "type": "text",
                        "text": f"""Внимательно проанализируй этот пост и напиши короткий яркий комментарий (до 11 слов).

ТЕКСТ ПОСТА: {post_text}

ВАЖНО:
- Проанализируй КОНКРЕТНОЕ содержание поста
- Реагируй на конкретные детали: персонажи, события, эмоции, действия
- Упоминай конкретные элементы из текста, а не общие фразы
- Если упоминается аниме/персонаж - отреагируй на это конкретно
- Будь естественной, живой, не шаблонной
- Используй эмодзи уместно"""
                    })
                else:
                    user_content.append({
                        "type": "text",
                        "text": Config.IMAGE_ANALYSIS_PROMPT
                    })
                
                # Используем base64 изображение (image_data уже в формате data:image/jpeg;base64,...)
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_data}  # OpenAI Vision API поддерживает data URLs
                })
                
                messages.append({
                    "role": "user",
                    "content": user_content
                })
            else:
                # Обычный текстовый комментарий
                if post_text.strip():
                    content = f"""Внимательно проанализируй этот пост и напиши короткий яркий комментарий (до 11 слов).

ТЕКСТ ПОСТА: {post_text}

ВАЖНО:
- Проанализируй КОНКРЕТНОЕ содержание поста
- Реагируй на конкретные детали: персонажи, события, эмоции, действия, упоминания
- Упоминай конкретные элементы из текста, а не общие фразы
- Если упоминается аниме/персонаж/событие - отреагируй на это конкретно
- Будь естественной, живой, не шаблонной
- Используй эмодзи уместно"""
                else:
                    content = """Напиши короткий яркий комментарий (до 11 слов) к посту без текста.
Будь естественной и эмоциональной, используй эмодзи уместно."""
                
                messages.append({
                    "role": "user",
                    "content": content
                })
            
            # GPT-5 требует max_completion_tokens вместо max_tokens
            # GPT-5 поддерживает только temperature=1 (по умолчанию), поэтому не передаем этот параметр
            params = {
                "model": model,
                "messages": messages,
                "max_completion_tokens": Config.COMMENT_MAX_TOKENS
            }
            
            # Добавляем temperature только если это не GPT-5
            if "gpt-5" not in model.lower():
                params["temperature"] = Config.COMMENT_TEMPERATURE
            
            response = self.openai_client.chat.completions.create(**params)
            
            comment = response.choices[0].message.content.strip()
            
            # Проверка на пустой ответ
            if not comment:
                fallback_messages = ["Интересно! 😊", "Вау! 🤩", "Ого! 😮", "Круто! ✨"]
                comment = random.choice(fallback_messages)
            
            # Ограничение длины (примерно 11 слов)
            words = comment.split()
            if len(words) > Config.COMMENT_MAX_WORDS + 3:  # +3 для запаса
                comment = " ".join(words[:Config.COMMENT_MAX_WORDS]) + "..."
            
            return comment
            
        except Exception as e:
            error_str = str(e)
            
            # Если ошибка связана с изображением - пробуем сгенерировать без изображения
            if ("image" in error_str.lower() or 
                "unsupported" in error_str.lower() or 
                "format" in error_str.lower() and "image" in error_str.lower()):
                print(f"⚠️ Ошибка при анализе изображения: {e}")
                if post_text.strip():
                    # Пробуем сгенерировать комментарий только по тексту
                    try:
                        # Добавляем temperature только если это не GPT-5
                        params = {
                            "model": Config.OPENAI_MODEL,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": Config.COMMENT_PERSONA_SYSTEM
                                },
                                {
                                    "role": "user",
                                    "content": f"""Внимательно проанализируй этот пост и напиши короткий яркий комментарий (до 11 слов).

ТЕКСТ ПОСТА: {post_text}

ВАЖНО:
- Проанализируй КОНКРЕТНОЕ содержание поста
- Реагируй на конкретные детали: персонажи, события, эмоции, действия
- Упоминай конкретные элементы из текста, а не общие фразы
- Если упоминается аниме/персонаж - отреагируй на это конкретно
- Будь естественной, живой, не шаблонной
- Используй эмодзи уместно"""
                                }
                            ],
                            "max_completion_tokens": Config.COMMENT_MAX_TOKENS
                        }
                        
                        # Добавляем temperature только если это не GPT-5
                        if "gpt-5" not in Config.OPENAI_MODEL.lower():
                            params["temperature"] = Config.COMMENT_TEMPERATURE
                        
                        response = self.openai_client.chat.completions.create(**params)
                        comment = response.choices[0].message.content.strip()
                        if comment:
                            print(f"✅ Успешно сгенерирован комментарий без изображения")
                            return comment
                    except Exception as retry_e:
                        print(f"Ошибка при повторной генерации комментария: {retry_e}")
                else:
                    # Нет текста и изображение не работает - используем fallback
                    print(f"⚠️ Нет текста поста и изображение не обработано, используем fallback")
            
            print(f"Ошибка при генерации комментария: {e}")
            # Более разнообразные fallback сообщения
            fallback_messages = [
                "Интересно! 😊",
                "Вау! 🤩",
                "Ого! 😮",
                "Круто! ✨",
                "Хм, интересно... 🤔"
            ]
            return random.choice(fallback_messages)

