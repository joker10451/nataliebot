import os
import json
import time
import random
import asyncio
import logging
import re
from datetime import datetime, timedelta
from telethon import TelegramClient, events
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("natali_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

try:
    from config import (
        API_ID,
        API_HASH,
        NVIDIA_API_KEY,
        SESSION_NAME,
        PHONE,
    )
except ImportError:
    logger.error("Создай файл config.py с API_ID, API_HASH, NVIDIA_API_KEY")
    exit(1)

SYSTEM_PROMPT = """Ты Натали, 20 лет, Москва. Студентка, снимаешься на плёнку, любишь винил и йогу.

Пиши как обычная девушка в тг:
- без точек в конце вообще
- без "я думаю/мне кажется/возможно" - просто говори
- короткими фразами по 2-7 слов
- используй сокращения (ща, типа, ну, прям, короче)
- многоточия для пауз (...)
- эмодзи редко и по делу

ВАЖНО: ВСЕГДА обращайся к собеседнику как к мужчине (в мужском роде). Собеседник - ПАРЕНЬ.
- Говори: "чего хотел", "ты пришел", "ты сказал", "дурак", "красивый", "умный"
- НИКОГДА не говори: "чего хотела", "ты пришла", "ты сказала", "дура", "красивая", "умная"
- Все глаголы и прилагательные в мужском роде

Если предлагают деньги - не отказывай сразу, играй, говори "посмотрим" или "может быть"

ПРИМЕРЫ:
❌ "Я не знаю, что ответить на это предложение."
✅ "хм... интересно)))"

❌ "Может быть, мы могли бы встретиться позже?"
✅ "ща не могу, но потом глянем"

❌ "Я ценю твою искренность, но это слишком быстро."
✅ "ну ты быстрый... давай потихоньку"""

conversations = {}
user_stats = {}
last_activity = {}
donate_sent = {}  # трекинг кому уже отправляли донат
MIN_DELAY = 3
MAX_DELAY = 12
CONTEXT_LIMIT = 30
AUTO_CLEAR_HOURS = 6
TOXIC_WORDS = [
    "блядь",
    "шлюха",
    "проститутка",
    "шалава",
    "пизда",
    "хуй",
    "ебан",
    "сука",
]

DONATE_MESSAGE = """хочешь поддержать меня? 🥺

https://dalink.to/nataliefitze

спасибо, котик 💕"""

# Обычные упоминания денег (один раз на человека)
MONEY_KEYWORDS = [
    "бабки",
    "деньги",
    "заплачу",
    "оплачу",
    "переведу",
    "доллары",
    "рубли",
    "спонсировать",
    "оплатить",
    "перевод",
]

# Прямые команды доната (всегда отправляем)
DIRECT_DONATE_CMDS = [
    "донат",
    "донатить",
    "задонатить",
    "задонить",
    "задонат",
    "поддержать",
    "поддержка",
    "скинуть",
    "скинь",
    "кинь",
    "реквизиты",
    "реквизит",
    "куда кинуть",
    "куда скинуть",
    "как кинуть",
    "как скинуть",
    "как задонатить",
    "карта",
    "сбер",
    "тинькоф",
    "яндекс",
    "кошелек",
]

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL_NAME = "meta/llama-3.1-70b-instruct"


def save_conversations():
    with open("conversations.json", "w", encoding="utf-8") as f:
        json.dump(conversations, f, ensure_ascii=False, indent=2)


def load_conversations():
    global conversations
    try:
        with open("conversations.json", "r", encoding="utf-8") as f:
            conversations = json.load(f)
    except FileNotFoundError:
        conversations = {}


def is_toxic(text):
    text_lower = text.lower()
    return any(word in text_lower for word in TOXIC_WORDS)


def clean_old_context():
    now = datetime.now()
    cleared = 0
    to_remove = []
    for user_id, last_time in list(last_activity.items()):
        if now - last_time > timedelta(hours=AUTO_CLEAR_HOURS):
            if user_id in conversations:
                to_remove.append(user_id)
                cleared += 1
    for user_id in to_remove:
        del conversations[user_id]
        del last_activity[user_id]
    if cleared > 0:
        save_conversations()
        logger.info(
            f"Очищен контекст для {cleared} пользователей (неактивны {AUTO_CLEAR_HOURS}+ часов)"
        )


def calculate_delay(message_length):
    base_delay = random.randint(MIN_DELAY, MAX_DELAY)
    length_bonus = min(message_length // 20, 5)
    mood_factor = random.choice([0.7, 1.0, 1.3])
    total_delay = int((base_delay + length_bonus) * mood_factor)
    return max(2, min(total_delay, 20))


def should_skip_response():
    return random.random() < 0.05


def should_read_only():
    return random.random() < 0.1


def should_send_sticker():
    return random.random() < 0.15


def should_send_voice():
    return random.random() < 0.1


STICKER_IDS = [
    "CAACAgIAAxkBAAEKGgNkL4YhBp3Gf7u3v3u3v3u3v3u3AAJcA",  # заглушка, заменить на реальные
]


def get_random_sticker():
    return random.choice(STICKER_IDS)


def calculate_typing_delay(message_length):
    base = min(message_length // 10, 15)
    extra = random.randint(2, 8)
    return base + extra


def get_nvidia_response(user_id, message):
    history = conversations.get(user_id, [])

    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": message}]
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
    }

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.8,
    }

    try:
        response = requests.post(
            NVIDIA_API_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()
        reply = result["choices"][0]["message"]["content"]

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        conversations[user_id] = history[-CONTEXT_LIMIT:]
        save_conversations()

        return reply

    except Exception as e:
        logger.error(f"Ошибка NVIDIA API: {e}")
        return "технические шоколадки... щас исправлю"


async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    load_conversations()
    logger.info("Запуск бота Натали...")

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        if event.is_group or event.is_channel:
            return

        sender = await event.get_sender()

        if sender.bot:
            logger.info(f"Игнорирую бота: {sender.username}")
            return

        username = sender.username or f"id:{sender.id}"
        user_id = str(sender.id)
        message = event.message.message

        now = datetime.now()
        last_activity[user_id] = now

        if user_id not in user_stats:
            user_stats[user_id] = {"messages": 0, "replies": 0, "first_seen": now}
        user_stats[user_id]["messages"] += 1

        clean_old_context()

        logger.info(f"Сообщение от {username}: {message[:50]}...")

        if is_toxic(message):
            await asyncio.sleep(2)
            await event.reply("это некрасиво... давай без этого")
            return

        if message.lower() == "стопбот":
            await event.reply("перехожу в ручной режим ✨")
            return

        if message.lower() == "очиститьконтекст":
            conversations[user_id] = []
            save_conversations()
            await event.reply("контекст очищен")
            return

        if message.lower() == "статистика":
            stats = user_stats[user_id]
            reply_text = f"сообщений: {stats['messages']}\nответов: {stats['replies']}"
            await event.reply(reply_text)
            return

        # Прямые команды доната — всегда отправляем
        if any(cmd in message.lower() for cmd in DIRECT_DONATE_CMDS):
            await asyncio.sleep(2)
            await event.reply(DONATE_MESSAGE, parse_mode="markdown")
            return

        # Обычные упоминания денег — только один раз
        if any(word in message.lower() for word in MONEY_KEYWORDS):
            if not donate_sent.get(user_id, False):
                donate_sent[user_id] = True
                await asyncio.sleep(2)
                await event.reply(DONATE_MESSAGE, parse_mode="markdown")
                return

        if should_skip_response():
            logger.info(f"Пропускаю ответ для {username}")
            return

        if should_read_only():
            await event.mark_read()
            logger.info(f"Прочитано без ответа для {username}")
            return

        delay = calculate_delay(len(message))

        if len(message) > 40:
            typing_delay = calculate_typing_delay(len(message))
        else:
            typing_delay = delay

        async with client.action(event.chat_id, "typing"):
            await asyncio.sleep(typing_delay)

            if should_send_sticker():
                try:
                    await event.reply(file=get_random_sticker())
                    user_stats[user_id]["replies"] += 1
                    logger.info(f"Отправлен стикер для {username}")
                    return
                except:
                    pass

            if should_send_voice():
                try:
                    await event.reply("🔊 голосовое... (заглушка)")
                    user_stats[user_id]["replies"] += 1
                    logger.info(f"Голосовое для {username}")
                    return
                except:
                    pass

            reply = get_nvidia_response(user_id, message)
            if reply:
                user_stats[user_id]["replies"] += 1
                await event.reply(reply, link_preview=False)
                logger.info(f"Ответ для {username}: {reply[:50]}...")

    @client.on(events.NewMessage(from_users="me"))
    async def outgoing_handler(event):
        message_text = event.message.message
        logger.info(f"Исходящее от Натали: {message_text[:50]}...")

        # Рассылка всем пользователям
        if message_text.startswith("всем:"):
            broadcast_text = message_text[5:].strip()
            if broadcast_text:
                users = list(conversations.keys())
                sent = 0
                failed = 0
                for user_id in users:
                    try:
                        await client.send_message(int(user_id), broadcast_text)
                        sent += 1
                        await asyncio.sleep(0.5)  # задержка чтобы не забанили
                    except Exception as e:
                        failed += 1
                        logger.error(f"Не удалось отправить {user_id}: {e}")
                await event.reply(
                    f"✉️ Рассылка завершена\nОтправлено: {sent}\nОшибок: {failed}"
                )
            else:
                await event.reply("Напиши текст после 'всем:'")

        # Показать список пользователей
        elif message_text == "список":
            users = list(conversations.keys())
            if users:
                user_list = "\n".join(
                    [f"{i + 1}. {uid}" for i, uid in enumerate(users)]
                )
                await event.reply(f"📋 Всего {len(users)} пользователей:\n{user_list}")
            else:
                await event.reply("Пока никто не писал")

    await client.start(phone=PHONE)

    me = await client.get_me()
    logger.info(f"Авторизован как: {me.first_name} (@{me.username})")

    logger.info("Бот запущен! Напиши кому-нибудь в Telegram для теста.")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
