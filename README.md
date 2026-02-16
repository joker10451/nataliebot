# Natalie Bot
Telegram бот Натали на Telethon + NVIDIA API

## Установка

1. Установи зависимости:
```bash
pip install -r requirements.txt
```

2. Создай файл `config.py`:
```python
API_ID = твой_api_id
API_HASH = "твой_api_hash"
NVIDIA_API_KEY = "твой_nvidia_key"
SESSION_NAME = "natali_session"
PHONE = "+79001234567"
```

3. Запусти:
```bash
python natali_bot.py
```

## Деплой на Render

1. Подключи этот репозиторий к Render
2. Выбери "Background Worker"
3. Start Command: `python natali_bot.py`
4. Добавь Environment Variables вместо config.py
