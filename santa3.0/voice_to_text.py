import argparse
import sys
from pathlib import Path
import tempfile
import shutil
import subprocess


def ensure_sr():
    try:
        import speech_recognition as sr  # noqa: F401
        return True
    except Exception:
        return False


def ensure_pydub():
    try:
        import pydub  # noqa: F401
        return True
    except Exception:
        return False


def convert_to_wav(input_path: Path) -> Path:
    ext = input_path.suffix.lower()
    if ext in {".wav", ".aiff", ".aif", ".aifc"}:
        return input_path
    if ensure_pydub():
        from pydub import AudioSegment
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            out = Path(f.name)
        audio = AudioSegment.from_file(str(input_path))
        audio.export(str(out), format="wav")
        return out
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            out = Path(f.name)
        subprocess.run([ffmpeg, "-y", "-i", str(input_path), str(out)], check=True)
        return out
    raise RuntimeError("Не удалось конвертировать файл в WAV. Установите pydub+ffmpeg или предоставьте WAV/AIFF.")


def recognize_audio(wav_path: Path, engine: str, language: str) -> str:
    import speech_recognition as sr
    import wave
    r = sr.Recognizer()
    if engine == "google":
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
        total_sec = frames / float(rate)
        chunk_sec = 25.0
        parts = []
        offset = 0.0
        while offset < total_sec:
            dur = min(chunk_sec, total_sec - offset)
            try:
                with sr.AudioFile(str(wav_path)) as source:
                    audio = r.record(source, offset=offset, duration=dur)
                if audio and len(audio.get_raw_data()) > 0:
                    parts.append(r.recognize_google(audio, language=language))
            except Exception:
                pass
            offset += dur
        return " ".join(parts).strip()
    if engine == "sphinx":
        try:
            with sr.AudioFile(str(wav_path)) as source:
                audio = r.record(source)
            return r.recognize_sphinx(audio, language=language)
        except Exception:
            with sr.AudioFile(str(wav_path)) as source:
                audio = r.record(source)
            return r.recognize_sphinx(audio)
    raise ValueError("Неизвестный движок распознавания")


def main():
    parser = argparse.ArgumentParser(prog="voice_to_text", description="Конвертация аудио-файла в текст")
    parser.add_argument("input", type=str, help="Путь к аудио-файлу (wav/mp3/ogg и т.д.)")
    parser.add_argument("-o", "--out", type=str, help="Путь для сохранения результата .txt")
    parser.add_argument("-e", "--engine", type=str, default="google", choices=["google", "sphinx", "whisper"], help="Движок распознавания")
    parser.add_argument("-l", "--language", type=str, default="ru-RU", help="Язык распознавания (напр. ru-RU, en-US)")
    args = parser.parse_args()

    if not ensure_sr():
        print("Требуется библиотека SpeechRecognition. Установите: pip install SpeechRecognition", file=sys.stderr)
        sys.exit(1)
    inp = Path(args.input)
    if not inp.exists():
        print("Файл не найден: " + str(inp), file=sys.stderr)
        sys.exit(1)
    tmp_wav = None
    error_msg = None
    try:
        wav_path = convert_to_wav(inp)
        if wav_path != inp:
            tmp_wav = wav_path
        if args.engine == "whisper":
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("base", device="cpu", compute_type="int8")
                segments, _ = model.transcribe(str(wav_path), language=args.language.split("-")[0], task="transcribe")
                text = " ".join(s.text.strip() for s in segments)
            except Exception as e:
                error_msg = "Whisper offline ошибка: " + str(e)
                text = ""
        else:
            try:
                text = recognize_audio(wav_path, args.engine, args.language)
            except Exception as e:
                error_msg = "Ошибка распознавания: " + str(e)
                text = ""
    except Exception as e:
        error_msg = "Ошибка распознавания: " + str(e)
        text = ""
    finally:
        if tmp_wav and tmp_wav.exists():
            try:
                tmp_wav.unlink()
            except Exception:
                pass
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = inp.with_suffix(".txt")
    try:
        if error_msg:
            out_path.write_text(error_msg + ("\n\n" + text if text else ""), encoding="utf-8")
            print(error_msg, file=sys.stderr)
        else:
            out_path.write_text(text, encoding="utf-8")
            print(text)
    except Exception as e:
        print("Не удалось сохранить результат: " + str(e), file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
