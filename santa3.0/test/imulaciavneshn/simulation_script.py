import json
import base64
import sys
import time
from pathlib import Path

import requests


def _resolve_speaker(s: str) -> str:
    v = (s or "santa").strip().lower()
    if v == "santa":
        return "4e2c8f38-4a95-11f0-a003-00163e0e1a44"
    return s or "4e2c8f38-4a95-11f0-a003-00163e0e1a44"


def _save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _save_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def pick_base_url():
    candidates = [
        "http://127.0.0.1:8005",
        "http://127.0.0.1:8004",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8000",
    ]
    for base in candidates:
        try:
            r = requests.get(base + "/admin", timeout=5)
            if r.status_code in (200, 404):
                return base
        except Exception:
            pass
    return candidates[0]


def main():
    out_dir = Path("c:/Users/xeon/Desktop/santa2.0/test/imulaciavneshn")
    audio_file = Path("c:/Users/xeon/Desktop/santa2.0/test/testaudio/52a19964cc807d899e98bcfeb89042c9.mp3")
    if not audio_file.exists():
        print("missing audio file", file=sys.stderr)
        sys.exit(1)

    base = pick_base_url()
    speaker = "santa"

    files = {
        "file": (audio_file.name, open(audio_file, "rb"), "audio/mpeg"),
    }
    data = {"speaker": speaker}
    req_form = {
        "method": "POST",
        "url": base + "/api/santa/audio",
        "headers": {},
        "form": {"speaker": speaker},
        "files": [{"field": "file", "filename": audio_file.name, "content_type": "audio/mpeg"}],
    }
    _save_json(out_dir / "request_form.json", req_form)
    try:
        res = requests.post(req_form["url"], files=files, data=data, timeout=300)
        res.raise_for_status()
        resp_json = res.json()
    except Exception as e:
        resp_json = {"error": str(e), "status_code": getattr(e, "response", None).status_code if hasattr(e, "response") and e.response else None}
    _save_json(out_dir / "response_form.json", resp_json)

    reply_text = resp_json.get("reply_text", "")
    reply_audio_b64 = resp_json.get("reply_audio_base64", "")
    reply_mime = resp_json.get("reply_audio_mime", "audio/wav")
    if reply_audio_b64:
        raw = base64.b64decode(reply_audio_b64)
        ext = ".wav" if reply_mime == "audio/wav" else ".mp3"
        _save_bytes(out_dir / ("reply_audio_form" + ext), raw)

    b64 = base64.b64encode(audio_file.read_bytes()).decode("ascii")
    req_json = {
        "method": "POST",
        "url": base + "/api/santa/audio.json",
        "headers": {"Content-Type": "application/json"},
        "json": {"audio_base64": b64, "speaker": speaker},
    }
    _save_json(out_dir / "request_json.json", req_json)
    try:
        res2 = requests.post(req_json["url"], json=req_json["json"], timeout=300)
        res2.raise_for_status()
        resp_json2 = res2.json()
    except Exception as e:
        resp_json2 = {"error": str(e), "status_code": getattr(e, "response", None).status_code if hasattr(e, "response") and e.response else None}
    _save_json(out_dir / "response_json.json", resp_json2)

    reply_text2 = resp_json2.get("reply_text", reply_text)
    reply_audio_b64_2 = resp_json2.get("reply_audio_base64", "")
    reply_mime_2 = resp_json2.get("reply_audio_mime", "audio/wav")
    if reply_audio_b64_2:
        raw2 = base64.b64decode(reply_audio_b64_2)
        ext2 = ".wav" if reply_mime_2 == "audio/wav" else ".mp3"
        _save_bytes(out_dir / ("reply_audio_json" + ext2), raw2)

    tts_req = {
        "method": "POST",
        "url": "https://fastapi.kreaai.inc/topmedia/api/v1/text2speech",
        "params": {"user_id": "com.test.test", "app_bundle_id": "test"},
        "headers": {"accept": "application/json", "Content-Type": "application/json"},
        "json": {
            "text": reply_text2 or reply_text or "Ho ho ho! Santa’s working on it, just a moment!",
            "speaker": _resolve_speaker(speaker),
            "emotion_name": "Default",
            "speed": 1,
            "stability": 50,
            "similarity": 95,
            "exaggeration": 0,
            "volume": 50,
        },
    }
    _save_json(out_dir / "tts_request.json", tts_req)

    summary = {
        "base_url": base,
        "reply_text_from_form": reply_text,
        "reply_text_from_json": reply_text2,
        "form_audio_saved": bool(reply_audio_b64),
        "json_audio_saved": bool(reply_audio_b64_2),
        "timestamp": int(time.time()),
    }
    _save_json(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

