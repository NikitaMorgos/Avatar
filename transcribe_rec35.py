import requests, time

API_KEY = "3a111e5c070d48c8b0b9924a23fb17e6"
AUDIO_PATH = r"C:\Users\user\Dropbox\Public\Cursor\Avatar\content\darina\audio\notes_rec35.m4a"
OUT_PATH    = r"C:\Users\user\Dropbox\Public\Cursor\Avatar\content\darina\audio\notes_rec35_transcript.txt"
HEADERS = {"authorization": API_KEY, "content-type": "application/json"}

print("Uploading audio...")
with open(AUDIO_PATH, "rb") as f:
    up = requests.post("https://api.assemblyai.com/v2/upload",
                       headers={"authorization": API_KEY}, data=f, timeout=300)
up.raise_for_status()
audio_url = up.json()["upload_url"]
print(f"Uploaded: {audio_url}")

print("Submitting transcription...")
resp = requests.post(
    "https://api.assemblyai.com/v2/transcript",
    json={"audio_url": audio_url, "speech_models": ["universal-2"],
          "language_code": "ru", "punctuate": True, "format_text": True},
    headers=HEADERS, timeout=30,
)
resp.raise_for_status()
tid = resp.json()["id"]
print(f"Job ID: {tid}")

print("Waiting", end="", flush=True)
while True:
    r = requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers=HEADERS, timeout=30)
    status = r.json()["status"]
    if status == "completed": break
    elif status == "error": print(f"\nError: {r.json().get('error')}"); exit(1)
    print(".", end="", flush=True)
    time.sleep(5)

text = r.json()["text"]
print(f"\nDone! {len(text)} chars")
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(text)
print(f"Saved: {OUT_PATH}\n\n--- TRANSCRIPT ---\n")
print(text)
