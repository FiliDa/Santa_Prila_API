# Santa API — текст и аудио, авто‑язык, VPN, TTS

Проект предоставляет веб‑API на FastAPI и админ‑панель для работы с текстом и аудио:

- `POST /api/santa/text` — текст → ответ Санты (на языке запроса)
- `POST /api/santa/audio` — аудио → транскрипция → ответ → озвучка (через внешний TTS)
- Авто‑языковая адаптация, интеграция VLESS/Xray VPN и Swagger‑документация

Админ‑панель: `http://127.0.0.1:8000/admin`  
Swagger: `http://127.0.0.1:8000/docs`

---

## Возможности

- Текстовый диалог: генерация ответов в стиле Санта‑Клауса
- Обработка аудио: транскрипция с выбором движка (`google|openai|whisper|sphinx`)
- Внешний TTS: генерация озвучки, выбор Голоса (несколько вариантов Санты)
- Авто‑VPN: поднимает Xray по VLESS URL и проксирует исходящие HTTP(S)
- Админ‑панель: тестирование текста/аудио, выбор движка и голоса, аудиоплеер

---

## Требования

- Windows, Python 3.10+ и `pip`
- `ffmpeg` (для конвертации аудио):
  - Скачайте с `https://ffmpeg.org/download.html`
  - Добавьте путь к `ffmpeg.exe` в `PATH`
- `xray.exe` (Xray‑core):
  - Поместите рядом с проектом, либо укажите абсолютный путь в `.env`

---

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install fastapi uvicorn httpx[socks] socksio python-dotenv
pip install SpeechRecognition pydub
pip install faster-whisper
```

Убедитесь, что `ffmpeg` доступен в `PATH`.

---

## Конфигурация

Создайте файл `.env` в корне проекта и укажите переменные:

```env
# Ключи LLM (любой один из)
OPENAI_API_KEY=sk-...
CHATGPT_TOKEN=sk-...

# VPN (VLESS/Xray)
VLESS_URL=vless://<uuid>@<host>:443?type=tcp&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F#Name
XRAY_PATH=C:\Path\To\xray.exe
XRAY_SOCKS_PORT=1080

# Внешний TTS (TopMedia)
TOPMEDIA_USER_ID=...
TOPMEDIA_APP_BUNDLE_ID=...
TOPMEDIA_BASE_URL=http://96.9.225.42:8000
```

> Не храните секреты в репозитории. `.gitignore` уже игнорирует `.env`.

---

## Запуск

```powershell
.\.venv\Scripts\activate
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

- При старте (если `VLESS_URL` и `XRAY_PATH` валидны) Xray поднимется автоматически, а исходящие HTTP(S) будут идти через SOCKS5 `127.0.0.1:XRAY_SOCKS_PORT`.
- Проверка VPN: `http://127.0.0.1:8000/api/vpn/status`
- Админ‑панель: `http://127.0.0.1:8000/admin`
- Swagger: `http://127.0.0.1:8000/docs`

---

## Использование (Админ‑панель)

- Вкладка «Текст»: введите сообщение → «Отправить» → получите ответ Санты
- Вкладка «Аудио»:
  - Загрузите аудиофайл (`wav/mp3/ogg/...`)
  - Выберите движок распознавания (`google|openai|whisper|sphinx`)
  - Выберите Голос TTS (варианты Санты)
  - Нажмите «Отправить» — увидите:
    - «Транскрипция» — текст из аудио
    - «Ответ Санты» — сгенерированный текст
    - «Озвучка» — встроенный аудиоплеер

---

## API

### `POST /api/santa/text`

- Body (JSON):

```json
{ "text": "Привет, Санта!" }
```

- Response:

```json
{ "reply_text": "..." }
```

### `POST /api/santa/audio`

- Form‑Data:
  - `file`: аудиофайл
  - `engine`: `google|openai|whisper|sphinx`
  - `speaker`: UUID голоса (например, `0793a86c-c1cf-11ef-b247-00163e022d5e`)

- Response:

```json
{
  "input_text": "текст транскрипции",
  "detected_lang": "ru|en",
  "reply_text": "ответ Санты",
  "reply_audio_base64": "<base64>",
  "reply_audio_mime": "audio/mpeg|audio/wav"
}
```

> Примечание: подготовка озвучки внешним TTS может занимать 2–3 минуты. Клиенту следует закладывать увеличенный таймаут. До конфигурации `TOPMEDIA_USER_ID` и `TOPMEDIA_APP_BUNDLE_ID` вернётся краткая WAV‑заглушка.

---

## Внешний TTS (TopMedia)

- Эндпоинт: `POST {TOPMEDIA_BASE_URL}/topmedia/api/v1/topmedia/text2speech`
- Query:
  - `user_id`
  - `app_bundle_id`
- Body:

```json
{
  "text": "string",
  "speaker": "uuid",
  "emotion_name": "Default",
  "speed": 0,
  "stability": 0,
  "similarity": 0,
  "exaggeration": 0,
  "volume": 0
}
```

- Идеальный ответ (пример):

```json
{
  "message": "Speech",
  "data": {
    "status": 0,
    "message": "Success",
    "data": {
      "type": 0,
      "name": "string",
      "speaker": "string",
      "oss_url": "https://.../audio.mp3"
    }
  }
}
```

- Клиент скачивает `oss_url` или принимает аудио в base64, конвертирует в `reply_audio_base64`/`reply_audio_mime`.

---

## VPN (VLESS/Xray)

- Авто‑запуск при старте приложения, SOCKS5 на `127.0.0.1:XRAY_SOCKS_PORT`
- Статус: `GET /api/vpn/status` → поля `enabled`, `running`, `socks_port`, `missing`
- Отключение: удалите `VLESS_URL` или `XRAY_PATH` из `.env` и перезапустите сервер

---

## Диагностика и устранение

- LLM 401: проверьте `OPENAI_API_KEY` или `CHATGPT_TOKEN`
- TTS не приходит: заполните `TOPMEDIA_USER_ID`, `TOPMEDIA_APP_BUNDLE_ID`; проверьте доступность `TOPMEDIA_BASE_URL`
- VPN missing: проверьте путь к `xray.exe` (`XRAY_PATH`) и валидность `VLESS_URL`
- Конвертация аудио: установите `ffmpeg` и `pydub`

---

## Безопасность

- Не публикуйте `.env` и секреты
- При необходимости защитите `/admin` (ключ/HTTP‑Basic) в прод‑среде

---

## Структура

```
app.py          # FastAPI, эндпоинты, админ‑панель, интеграция VPN/TTS
vpn.py          # Парсинг VLESS, генерация конфигурации Xray, запуск процесса
voice_to_text.py# Конвертация аудио → WAV, распознавание (Google/Sphinx/Whisper)
.gitignore      # Игнорирует .env и производные
README.md       # Этот файл
```

---

## Разработка

- Запуск локально: `python -m uvicorn app:app --host 127.0.0.1 --port 8000`
- Рекомендуется добавить линтер/типизацию и команды в проект (например, `ruff`, `mypy`), а также интеграционные тесты.

