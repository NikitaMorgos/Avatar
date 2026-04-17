"""
Транскрибация аудио через AssemblyAI (русский язык)
Запускать из папки проекта: python transcribe.py

Результаты сохраняются в transcripts/<имя>_raw.txt
"""
import requests
import time
import sys
from pathlib import Path

API_KEY = "3a111e5c070d48c8b0b9924a23fb17e6"
HEADERS = {"authorization": API_KEY}

BASE = Path(__file__).parent
audio_dir = BASE / "audio"
output_dir = BASE / "transcripts"
output_dir.mkdir(exist_ok=True)


def upload_file(path):
    with open(path, "rb") as f:
        r = requests.post("https://api.assemblyai.com/v2/upload", headers=HEADERS, data=f)
    return r.json()["upload_url"]


def transcribe(upload_url):
    r = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers=HEADERS,
        json={"audio_url": upload_url, "language_code": "ru", "speech_models": ["universal-2"]}
    )
    data = r.json()
    if "id" not in data:
        raise Exception(f"API error: {data}")
    return data["id"]


def poll(tid):
    while True:
        r = requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers=HEADERS)
        d = r.json()
        if d["status"] == "completed":
            return d["text"]
        if d["status"] == "error":
            raise Exception(d["error"])
        time.sleep(3)


files = sorted(audio_dir.glob("*.m4a"))
print(f"Найдено файлов: {len(files)}")

for audio_file in files:
    out = output_dir / (audio_file.stem + "_raw.txt")
    if out.exists():
        print(f"[SKIP] {audio_file.name} — уже есть")
        continue
    print(f"[UP]   Загружаю {audio_file.name}...")
    url = upload_file(audio_file)
    print(f"[TR]   Транскрибирую...")
    tid = transcribe(url)
    text = poll(tid)
    out.write_text(text, encoding="utf-8")
    print(f"[OK]   → {out.name} ({len(text)} симв.)")

print("\nГотово!")
