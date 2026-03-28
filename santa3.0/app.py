import os
import io
import base64
import math
import wave
import struct
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from voice_to_text import ensure_sr, ensure_pydub, convert_to_wav, recognize_audio
from dotenv import load_dotenv
import httpx
import logging

load_dotenv()

logger = logging.getLogger("uvicorn.error")

class TextIn(BaseModel):
    text: str

class AudioOut(BaseModel):
    input_text: str
    detected_lang: str
    reply_text: str
    reply_audio_base64: str
    reply_audio_mime: str

class AudioJsonIn(BaseModel):
    audio_url: Optional[str] = None
    audio_base64: Optional[str] = None
    speaker: Optional[str] = "santa"

def _resolve_speaker(s: Optional[str]) -> str:
    v = (s or "santa").strip().lower()
    if v == "santa":
        return "4e2c8f38-4a95-11f0-a003-00163e0e1a44"
    return s or "4e2c8f38-4a95-11f0-a003-00163e0e1a44"


def santa_prompt() -> str:
    return (
        "You are a kind and wise Santa Claus. Reply warmly, festively, "
        "encouraging and friendly. Keep the holiday spirit but be practical "
        "and helpful. Always reply in English regardless of the user's language. "
        "Avoid long lectures; answer to the point."
    )


def generate_santa_reply(text: str) -> str:
    token = os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_TOKEN")
    if not token:
        return "Токен LLM не установлен (переменная окружения OPENAI_API_KEY или CHATGPT_TOKEN)."
    try:
        from openai import OpenAI
        client = OpenAI(api_key=token)
        sys_prompt = santa_prompt()
        user_prompt = f"Сообщение пользователя: {text}"
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка генерации ответа: {e}"


def _guess_lang_from_text(text: str) -> str:
    total_alpha = 0
    cyrillic_alpha = 0
    for ch in text:
        if ch.isalpha():
            total_alpha += 1
            if "а" <= ch.lower() <= "я" or ch in "ёЁ":
                cyrillic_alpha += 1
    if total_alpha > 0 and (cyrillic_alpha / total_alpha) > 0.2:
        return "ru"
    return "en"


def stt_from_file(path: Path, engine: Optional[str] = None) -> Tuple[str, str]:
    try:
        wav = convert_to_wav(path)
        eng = "whisper"
        try:
            if eng == "openai":
                try:
                    from openai import OpenAI
                    token = os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_TOKEN")
                    if not token:
                        raise RuntimeError("Нет ключа OPENAI_API_KEY/CHATGPT_TOKEN")
                    client = OpenAI(api_key=token)
                    with open(str(path), "rb") as f:
                        resp = client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=f)
                    text = getattr(resp, "text", "") or ""
                    lang = _guess_lang_from_text(text)
                    return text, lang
                except Exception as e:
                    raise RuntimeError(f"OpenAI STT ошибка: {e}")
            if eng == "whisper":
                try:
                    from faster_whisper import WhisperModel
                    model = WhisperModel("base", device="cpu", compute_type="int8")
                    segments, info = model.transcribe(str(wav), task="transcribe", vad_filter=True, beam_size=5)
                    text = " ".join(s.text.strip() for s in segments)
                    if not text.strip():
                        segments2, info2 = model.transcribe(str(wav), task="transcribe", language="en", vad_filter=True, beam_size=5)
                        text = " ".join(s.text.strip() for s in segments2)
                        info = info2 if info2 else info
                    if text.strip():
                        lang = info.language if hasattr(info, "language") and info.language else _guess_lang_from_text(text)
                        return text, lang
                    # fallback to OpenAI STT if Whisper returned empty
                    try:
                        from openai import OpenAI
                        token = os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_TOKEN")
                        if token:
                            client = OpenAI(api_key=token)
                            with open(str(path), "rb") as f:
                                resp = client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=f)
                            text2 = getattr(resp, "text", "") or ""
                            lang2 = _guess_lang_from_text(text2)
                            if text2.strip():
                                return text2, lang2
                    except Exception:
                        pass
                except Exception:
                    # Whisper импорт недоступен: пробуем OpenAI STT, затем Google
                    try:
                        from openai import OpenAI
                        token = os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_TOKEN")
                        if token:
                            client = OpenAI(api_key=token)
                            with open(str(path), "rb") as f:
                                resp = client.audio.transcriptions.create(model="gpt-4o-mini-transcribe", file=f)
                            text2 = getattr(resp, "text", "") or ""
                            lang2 = _guess_lang_from_text(text2)
                            if text2.strip():
                                return text2, lang2
                    except Exception:
                        pass
                    eng = "google"
            if eng == "google":
                text_ru = ""
                text_en = ""
                try:
                    text_ru = recognize_audio(wav, "google", "ru-RU")
                except Exception:
                    pass
                try:
                    text_en = recognize_audio(wav, "google", "en-US")
                except Exception:
                    pass
                if not text_ru and not text_en:
                    try:
                        from faster_whisper import WhisperModel
                        model = WhisperModel("base", device="cpu", compute_type="int8")
                        segments, info = model.transcribe(str(wav), task="transcribe")
                        text = " ".join(s.text.strip() for s in segments)
                        lang = info.language if hasattr(info, "language") and info.language else _guess_lang_from_text(text)
                        return text, lang
                    except Exception:
                        return "", "en"
                candidates = [(text_ru, "ru"), (text_en, "en")]
                best = max(candidates, key=lambda t: (len(t[0]), 1 if _guess_lang_from_text(t[0]) == t[1] else 0))
                return best
            try:
                text_any = recognize_audio(wav, "sphinx", "ru-RU")
                lang = _guess_lang_from_text(text_any)
                return text_any, lang
            except Exception:
                text_any = recognize_audio(wav, "sphinx", "en-US")
                lang = _guess_lang_from_text(text_any)
                return text_any, lang
        finally:
            if wav != path and wav.exists():
                try:
                    wav.unlink()
                except Exception:
                    pass
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка STT: {e}")

def _synthesize_beep_wav(seconds: float = 0.7, freq: float = 440.0, sr: int = 16000) -> bytes:
    frames = int(seconds * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(frames):
            t = i / sr
            s = int(32767 * 0.2 * math.sin(2 * math.pi * freq * t))
            w.writeframes(struct.pack("<h", s))
    return buf.getvalue()

def _detect_mime(b: bytes, default: str = "audio/mpeg") -> str:
    if len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "audio/wav"
    if len(b) >= 3 and b[:3] == b"ID3":
        return "audio/mpeg"
    if len(b) >= 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0:
        return "audio/mpeg"
    return default


app = FastAPI(title="Santa API", description="API Санты: текст и аудио", version="1.0.0", root_path="/santa")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_vpn_proc = None
_vpn_cfg = None
_socks_port = None


@app.on_event("startup")
def _start_vpn():
    global _vpn_proc, _vpn_cfg, _socks_port
    url = os.getenv("VLESS_URL")
    xray = os.getenv("XRAY_PATH")
    _socks_port = int(os.getenv("XRAY_SOCKS_PORT", "1080"))
    if url and xray and Path(xray).exists():
        from vpn import start_vpn
        _vpn_proc, _vpn_cfg = start_vpn(url, xray, _socks_port)
        os.environ["HTTP_PROXY"] = f"socks5://127.0.0.1:{_socks_port}"
        os.environ["HTTPS_PROXY"] = f"socks5://127.0.0.1:{_socks_port}"


@app.on_event("shutdown")
def _stop_vpn():
    global _vpn_proc, _vpn_cfg
    try:
        if _vpn_proc:
            _vpn_proc.terminate()
    except Exception:
        pass
    try:
        if _vpn_cfg and Path(_vpn_cfg).exists():
            Path(_vpn_cfg).unlink()
    except Exception:
        pass

@app.post("/api/santa/text")
def santa_text(body: TextIn):
    reply = generate_santa_reply(body.text)
    return {"reply_text": reply}


@app.post(
    "/api/santa/audio",
    summary="Аудио → текст → ответ Санты (с озвучкой)",
    description=(
        "Принимает аудиофайл, выполняет транскрипцию, генерирует ответ Санты и возвращает озвученный ответ. "
        "Поле reply_audio_base64 содержит готовый к проигрыванию аудиопоток (WAV/MP3, base64). "
        "Распознавание: Whisper (фиксировано). "
        "Параметр speaker по умолчанию: santa. "
        "Примечание: время подготовки реальной озвучки может быть до 2–3 минут; "
        "до интеграции внешнего TTS используется краткий звуковой заглушка."
    ),
    response_model=AudioOut,
)
async def santa_audio(
    file: UploadFile = File(...),
    speaker: str = Form(
        "santa",
        description="Идентификатор голоса. По умолчанию: santa",
    ),
):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix or ".wav") as tmp:
            data = await file.read()
            tmp.write(data)
            temp_path = Path(tmp.name)
        text, lang = stt_from_file(temp_path, engine=None)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
    reply = generate_santa_reply(text)
    async def _tts_external() -> Optional[Tuple[bytes, str]]:
        base = os.getenv("TOPMEDIA_BASE_URL") or "https://fastapi.kreaai.inc"
        user_id = "test"
        app_id = "com.test.test"
        url = f"{base}/topmedia/api/v1/text2speech"
        params = {"user_id": user_id, "app_bundle_id": app_id}
        spk = _resolve_speaker(speaker)
        body = {
            "text": reply,
            "speaker": spk,
            "emotion_name": "Default",
            "speed": 1,
            "stability": 50,
            "similarity": 95,
            "exaggeration": 0,
            "volume": 50,
        }
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                logger.info(f"TTS request url={url} params={params} speaker={spk} text_len={len(reply)}")
                r = await client.post(url, params=params, json=body, headers={"Accept": "application/json"})
                ct = r.headers.get("content-type", "")
                logger.info(f"TTS response status={r.status_code} content_type={ct} content_len={len(r.content)}")
                if "application/json" in ct:
                    try:
                        data = r.json()
                    except Exception:
                        logger.warning("TTS response JSON parse failed")
                        return None
                    b64 = data.get("audio_base64") or data.get("wav_base64") or data.get("mp3_base64")
                    if b64:
                        try:
                            raw = base64.b64decode(b64)
                            mime = "audio/wav" if data.get("wav_base64") else "audio/mpeg"
                            logger.info(f"TTS JSON audio_base64 found mime={mime} bytes={len(raw)}")
                            return raw, mime
                        except Exception:
                            logger.warning("TTS base64 decode failed")
                            return None
                    url2 = data.get("url") or data.get("file_url") or data.get("audio_url")
                    try:
                        nested = data.get("data", {})
                        inner = nested.get("data", {}) if isinstance(nested, dict) else {}
                        if isinstance(inner, dict) and inner.get("oss_url"):
                            url2 = inner.get("oss_url")
                    except Exception:
                        pass
                    if url2:
                        rr = await client.get(url2)
                        mime = rr.headers.get("content-type") or ("audio/mpeg" if str(url2).lower().endswith(".mp3") else "audio/wav")
                        logger.info(f"TTS fetched url2={url2} status={rr.status_code} mime={mime} bytes={len(rr.content)}")
                        return rr.content, mime
                    logger.warning(f"TTS JSON without audio fields keys={list(data.keys())}")
                    return None
                mime = ct or _detect_mime(r.content)
                logger.info(f"TTS non-JSON returned mime={mime} bytes={len(r.content)}")
                return (r.content, mime)
        except Exception as e:
            logger.exception(f"TTS external error: {e}")
            return None
    ext = await _tts_external()
    if ext is None:
        logger.warning("TTS failed, using beep fallback")
        wav_bytes = _synthesize_beep_wav()
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        audio_mime = "audio/wav"
    else:
        raw, audio_mime = ext
        audio_b64 = base64.b64encode(raw).decode("ascii")
    return {
        "input_text": text,
        "detected_lang": lang,
        "reply_text": reply,
        "reply_audio_base64": audio_b64,
        "reply_audio_mime": audio_mime,
    }

@app.post(
    "/api/santa/audio.json",
    summary="Аудио (JSON) → текст → ответ Санты (с озвучкой)",
    description=(
        "Для внешних клиентов. Принимает JSON с audio_url или audio_base64 и speaker. "
        "Распознавание: Whisper (фиксировано). Возвращает транскрипт, ответ и озвучку в base64 с MIME. "
        "Параметр speaker по умолчанию: santa. "
        "Поддерживает CORS. Примечание: реальная озвучка может готовиться до 2–3 минут."
    ),
    response_model=AudioOut,
)
async def santa_audio_json(body: AudioJsonIn):
    temp_path = None
    try:
        if body.audio_url:
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.get(body.audio_url)
                data = r.content
            suffix = ".mp3"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                temp_path = Path(tmp.name)
        elif body.audio_base64:
            raw = base64.b64decode(body.audio_base64)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(raw)
                temp_path = Path(tmp.name)
        else:
            raise HTTPException(status_code=400, detail="Требуется audio_url или audio_base64")
        text, lang = stt_from_file(temp_path, engine=None)
    finally:
        try:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        except Exception:
            pass
    reply = generate_santa_reply(text)
    async def _tts_external2() -> Optional[Tuple[bytes, str]]:
        base = os.getenv("TOPMEDIA_BASE_URL") or "https://fastapi.kreaai.inc"
        user_id = "com.test.test"
        app_id = "test"
        url = f"{base}/topmedia/api/v1/text2speech"
        params = {"user_id": user_id, "app_bundle_id": app_id}
        body_json = {
            "text": reply,
            "speaker": _resolve_speaker(body.speaker),
            "emotion_name": "Default",
            "speed": 1,
            "stability": 50,
            "similarity": 95,
            "exaggeration": 0,
            "volume": 50,
        }
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                logger.info(f"TTS request url={url} params={params} speaker={body_json['speaker']} text_len={len(reply)}")
                r = await client.post(url, params=params, json=body_json, headers={"Accept": "application/json"})
                ct = r.headers.get("content-type", "")
                logger.info(f"TTS response status={r.status_code} content_type={ct} content_len={len(r.content)}")
                if "application/json" in ct:
                    try:
                        data = r.json()
                    except Exception:
                        logger.warning("TTS response JSON parse failed")
                        return None
                    b64 = data.get("audio_base64") or data.get("wav_base64") or data.get("mp3_base64")
                    if b64:
                        try:
                            raw = base64.b64decode(b64)
                        except Exception:
                            logger.warning("TTS base64 decode failed")
                            return None
                        mime = "audio/wav" if data.get("wav_base64") else "audio/mpeg"
                        logger.info(f"TTS JSON audio_base64 found mime={mime} bytes={len(raw)}")
                        return raw, mime
                    url2 = data.get("url") or data.get("file_url") or data.get("audio_url")
                    try:
                        nested = data.get("data", {})
                        inner = nested.get("data", {}) if isinstance(nested, dict) else {}
                        if isinstance(inner, dict) and inner.get("oss_url"):
                            url2 = inner.get("oss_url")
                    except Exception:
                        pass
                    if url2:
                        rr = await client.get(url2)
                        mime = rr.headers.get("content-type") or ("audio/mpeg" if str(url2).lower().endswith(".mp3") else "audio/wav")
                        logger.info(f"TTS fetched url2={url2} status={rr.status_code} mime={mime} bytes={len(rr.content)}")
                        return rr.content, mime
                    logger.warning(f"TTS JSON without audio fields keys={list(data.keys())}")
                    return None
                mime = ct or _detect_mime(r.content)
                logger.info(f"TTS non-JSON returned mime={mime} bytes={len(r.content)}")
                return (r.content, mime)
        except Exception as e:
            logger.exception(f"TTS external error: {e}")
            return None
    ext = await _tts_external2()
    if ext is None:
        logger.warning("TTS failed, using beep fallback")
        wav_bytes = _synthesize_beep_wav()
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
        audio_mime = "audio/wav"
    else:
        raw, audio_mime = ext
        audio_b64 = base64.b64encode(raw).decode("ascii")
    return {
        "input_text": text,
        "detected_lang": lang,
        "reply_text": reply,
        "reply_audio_base64": audio_b64,
        "reply_audio_mime": audio_mime,
    }

@app.get("/api/vpn/status")
def vpn_status():
    vless = os.getenv("VLESS_URL")
    xray = os.getenv("XRAY_PATH")
    exists = bool(xray and Path(xray).exists())
    missing = []
    if not vless:
        missing.append("VLESS_URL")
    if not xray:
        missing.append("XRAY_PATH")
    elif not exists:
        missing.append("XRAY_PATH_file_missing")
    return {
        "enabled": bool(vless and xray and exists),
        "running": _vpn_proc is not None,
        "socks_port": _socks_port,
        "missing": missing,
    }

ADMIN_HTML = """
<!doctype html>
<html lang="ру">
  <head>
    <meta charset="utf-8">
    <title>Santa Admin</title>
    <style>
      :root {
        --bg: #0f172a;
        --panel: #0b1222;
        --card: #111827;
        --accent: #ef4444;
        --accent-2: #f59e0b;
        --text: #e5e7eb;
        --muted: #94a3b8;
        --ok: #22c55e;
      }
      * { box-sizing: border-box }
      body {
        margin: 0;
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
        color: var(--text);
        background:
          radial-gradient(1200px 600px at 0% 0%, rgba(245, 158, 11, .15), transparent 60%),
          radial-gradient(1200px 600px at 100% 0%, rgba(239, 68, 68, .18), transparent 60%),
          linear-gradient(180deg, #0b1222 0%, #0f172a 60%, #0b1222 100%);
        min-height: 100vh;
      }
      .container { max-width: 1080px; margin: 0 auto; padding: 32px 24px; }
      .header {
        display: flex; align-items: center; gap: 14px; margin-bottom: 24px;
      }
      .logo {
        width: 48px; height: 48px; border-radius: 12px;
        background: linear-gradient(135deg, var(--accent), var(--accent-2));
        display: grid; place-items: center; font-size: 24px; color: #fff;
        box-shadow: 0 10px 30px rgba(239, 68, 68, .35);
      }
      .title { font-size: 24px; font-weight: 700; letter-spacing: .2px }
      .subtitle { color: var(--muted); font-size: 14px }
      .nav {
        display: flex; gap: 10px; margin: 24px 0;
        background: rgba(255,255,255,.04); padding: 6px; border-radius: 12px;
      }
      .tab {
        padding: 10px 14px; border-radius: 8px; cursor: pointer; color: var(--muted);
      }
      .tab.active { background: rgba(255,255,255,.08); color: var(--text) }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px }
      .card {
        background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.08);
        border-radius: 14px; padding: 16px;
      }
      .card h2 { margin: 0 0 8px; font-size: 18px }
      .card p { margin: 0 0 12px; color: var(--muted); font-size: 13px }
      label { display:block; margin: 10px 0 6px; font-size: 13px; color: var(--muted) }
      input[type=text], select, textarea {
        width: 100%; background: var(--card); border: 1px solid rgba(255,255,255,.08);
        color: var(--text); border-radius: 10px; padding: 10px 12px; outline: none;
      }
      textarea { min-height: 120px }
      button {
        display: inline-flex; align-items: center; gap: 8px;
        margin-top: 12px; padding: 10px 14px; border-radius: 10px; border: none; cursor: pointer;
        background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; font-weight: 600;
        box-shadow: 0 6px 18px rgba(239, 68, 68, .35);
      }
      .danger { background: linear-gradient(135deg, #ef4444, #dc2626) }
      .output { background: var(--card); border: 1px dashed rgba(255,255,255,.12); border-radius: 10px; padding: 12px; white-space: pre-wrap; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px }
      .footer { margin-top: 20px; color: var(--muted); font-size: 12px }
      @media (max-width: 920px) { .grid, .row { grid-template-columns: 1fr } }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="header">
        <div class="logo">🎅</div>
        <div>
          <div class="title">Santa Admin</div>
          <div class="subtitle">Тестирование: текст, аудио, VPN</div>
        </div>
      </div>

      <div class="nav">
        <div class="tab active" data-tab="text">Текст</div>
        <div class="tab" data-tab="audio">Аудио</div>
        <div class="tab" data-tab="vpn">VPN</div>
      </div>

      <div id="panel-text" class="grid">
        <div class="card">
          <h2>Текст → ответ Санты</h2>
          <p>Напишите сообщение. Санта ответит на том же языке.</p>
          <label>Текст</label>
          <textarea id="txt" placeholder="Например: Привет, Санта!"></textarea>
          <div class="row">
            <button onclick="sendText()">Отправить</button>
            <button class="danger" onclick="clearOut('out1')">Очистить</button>
          </div>
        </div>
        <div class="card">
          <h2>Ответ</h2>
          <div id="out1" class="output"></div>
        </div>
      </div>

      <div id="panel-audio" class="grid" style="display:none">
        <div class="card">
          <h2>Аудио → текст → ответ Санты</h2>
          <p>Загрузите аудиофайл.</p>
          <label>Файл аудио</label>
          <input id="file" type="file" accept="audio/*">
          <label>Голос</label>
          <select id="voice">
            <option value="santa" selected>santa</option>
          </select>
          <div class="row">
            <button onclick="sendAudio()">Отправить</button>
            <button class="danger" onclick="clearOut('out2')">Очистить</button>
          </div>
        </div>
        <div class="card">
          <h2>Результат</h2>
          <div id="out2" class="output"></div>
          <label>Озвучка</label>
          <audio id="aud2" controls></audio>
        </div>
      </div>

      <div id="panel-vpn" class="grid" style="display:none">
        <div class="card">
          <h2>Статус VPN</h2>
          <p>Проверка автозапуска VLESS/Xray.</p>
          <div class="row">
            <button onclick="checkVPN()">Проверить</button>
            <button class="danger" onclick="clearOut('out3')">Очистить</button>
          </div>
        </div>
        <div class="card">
          <h2>Детали</h2>
          <div id="out3" class="output"></div>
        </div>
      </div>

      <div class="footer">
        © Santa API · Используются переменные окружения OPENAI_API_KEY/CHATGPT_TOKEN
      </div>
    </div>
    <script>
      const tabs = document.querySelectorAll('.tab');
      const panels = {
        text: document.getElementById('panel-text'),
        audio: document.getElementById('panel-audio'),
        vpn: document.getElementById('panel-vpn'),
      };
      tabs.forEach(t => {
        t.addEventListener('click', () => {
          tabs.forEach(x => x.classList.remove('active'));
          t.classList.add('active');
          const id = t.getAttribute('data-tab');
          Object.keys(panels).forEach(k => panels[k].style.display = k === id ? '' : 'none');
        })
      });
      function clearOut(id){ const el = document.getElementById(id); if (el) el.textContent = ''; }

      async function sendText() {
        const text = document.getElementById('txt').value;
        const res = await fetch('/api/santa/text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text })
        });
        const txt = await res.text();
        document.getElementById('out1').textContent = txt;
      }
      async function sendAudio() {
        const f = document.getElementById('file').files[0];
        const speaker = document.getElementById('voice').value;
        const fd = new FormData();
        fd.append('file', f);
        fd.append('speaker', speaker);
        const res = await fetch('/api/santa/audio', { method: 'POST', body: fd });
        const data = await res.json();
        const out = [
          'Транскрипция:', data.input_text,
          '',
          'Ответ Санты:', data.reply_text,
          '',
          'Язык:', data.detected_lang
        ].join('\\n');
        document.getElementById('out2').textContent = out;
        if (data.reply_audio_base64) {
          const mime = data.reply_audio_mime || 'audio/wav';
          document.getElementById('aud2').src = 'data:' + mime + ';base64,' + data.reply_audio_base64;
        }
      }
      async function checkVPN(){
        try {
          const res = await fetch('/api/vpn/status');
          const data = await res.json();
          document.getElementById('out3').textContent = JSON.stringify(data, null, 2);
        } catch(e) {
          document.getElementById('out3').textContent = String(e);
        }
      }
    </script>
  </body>
</html>
"""


@app.get("/admin", response_class=HTMLResponse)
def admin():
    return HTMLResponse(ADMIN_HTML)
