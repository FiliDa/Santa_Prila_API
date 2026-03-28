import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app import stt_from_file
from deep_translator import GoogleTranslator

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/transcribe_translate_via_app.py <audio_path>")
        sys.exit(2)
    p = Path(sys.argv[1])
    if not p.exists():
        print("File not found: " + str(p))
        sys.exit(2)
    text, lang = stt_from_file(p, engine=None)
    try:
        translated = GoogleTranslator(source="auto", target="en").translate(text) if text else ""
    except Exception:
        translated = ""
    print({"detected_lang": lang, "text": text, "translated": translated})

if __name__ == "__main__":
    main()
