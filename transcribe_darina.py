import requests, time, json

API_KEY = "3a111e5c070d48c8b0b9924a23fb17e6"
AUDIO_PATH = r"C:\Users\user\Downloads\Новая запись 13.m4a"
OUT_PATH = r"C:\Users\user\Dropbox\Public\Cursor\Avatar\darina_interview_transcript.txt"
HEADERS = {"authorization": API_KEY, "content-type": "application/json"}

# 1. Upload
print("Загружаю файл...")
with open(AUDIO_PATH, "rb") as f:
    up = requests.post(
        "https://api.assemblyai.com/v2/upload",
        headers={"authorization": API_KEY},
        data=f,
        timeout=300,
    )
up.raise_for_status()
audio_url = up.json()["upload_url"]
print(f"Загружено: {audio_url[:60]}...")

# 2. Submit transcription
print("Отправляю на транскрипцию...")
resp = requests.post(
    "https://api.assemblyai.com/v2/transcript",
    json={
        "audio_url": audio_url,
        "speech_models": ["universal-2"],
        "language_code": "ru",
        "punctuate": True,
        "format_text": True,
    },
    headers=HEADERS,
    timeout=30,
)
resp.raise_for_status()
tid = resp.json()["id"]
print(f"ID задачи: {tid}")

# 3. Poll
print("Жду результата", end="", flush=True)
while True:
    r = requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers=HEADERS, timeout=30)
    status = r.json()["status"]
    if status == "completed":
        print(" готово!")
        break
    elif status == "error":
        print(f"\nОшибка: {r.json()['error']}")
        exit(1)
    print(".", end="", flush=True)
    time.sleep(5)

text = r.json()["text"]
print("\n=== ТРАНСКРИПТ ===\n")
print(text)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(text)
print(f"\n=== Сохранено: {OUT_PATH} ===")


if transcript.status == aai.TranscriptStatus.error:
    print(f"Ошибка: {transcript.error}")
else:
    print("\n=== ТРАНСКРИПТ ===\n")
    print(transcript.text)
    
    # Save to file
    out_path = r"C:\Users\user\Dropbox\Public\Cursor\Avatar\darina_interview_transcript.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(transcript.text)
    print(f"\n=== Сохранено в {out_path} ===")
