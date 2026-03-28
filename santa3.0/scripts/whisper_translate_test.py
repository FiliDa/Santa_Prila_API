import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from voice_to_text import convert_to_wav

def detect_lang(text: str) -> str:
    total = 0
    cyr = 0
    for ch in text:
        if ch.isalpha():
            total += 1
            if "а" <= ch.lower() <= "я" or ch in "ёЁ":
                cyr += 1
    if total > 0 and (cyr / total) > 0.2:
        return "ru"
    return "en"

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/whisper_translate_test.py <audio_path>")
        sys.exit(2)
    inp = Path(sys.argv[1])
    if not inp.exists():
        print("File not found: " + str(inp))
        sys.exit(2)
    wav = convert_to_wav(inp)
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(wav), task="transcribe", vad_filter=True, beam_size=5)
        text = " ".join(s.text.strip() for s in segments)
    finally:
        if wav != inp and wav.exists():
            try:
                wav.unlink()
            except Exception:
                pass
    lang = detect_lang(text)
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(source="auto", target="en").translate(text) if text else ""
    except Exception as e:
        translated = ""
    print({"lang": lang, "text": text, "translated": translated})

if __name__ == "__main__":
    main()
