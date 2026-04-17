# Истории сыну — фреймворк проекта

## Что это

Папа рассказывает сыну (6 лет) истории про своё детство перед сном.
Цель: сохранить истории → книга + ТГ-канал + педагогический инструмент.

---

## Структура папок

```
audio/           — исходные m4a-записи
transcripts/     — транскрипты (raw + clean)
processed/       — финальные обработки каждой истории
_framework.md    — этот файл
```

---

## Рабочий поток (на каждую порцию ~10 историй/неделю)

```
1. Записать аудио (Plaud или телефон)
2. Положить m4a в audio/
3. Запустить транскрипцию через AssemblyAI (скрипт ниже)
4. Сохранить raw-транскрипт в transcripts/ИМЯ_raw.txt
5. Почистить транскрипт вручную или попросить Клода → transcripts/ИМЯ_clean.txt
6. Клод делает обработку → processed/ИМЯ.md
```

### Скрипт транскрипции

```python
# transcribe.py — запускать из папки audio/
# API_KEY = "3a111e5c070d48c8b0b9924a23fb17e6"
import requests, time, sys
from pathlib import Path

API_KEY = "3a111e5c070d48c8b0b9924a23fb17e6"
HEADERS = {"authorization": API_KEY}
audio_dir = Path(__file__).parent / "audio"
output_dir = Path(__file__).parent / "transcripts"
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
    return r.json()["id"]

def poll(tid):
    while True:
        r = requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers=HEADERS)
        d = r.json()
        if d["status"] == "completed": return d["text"]
        if d["status"] == "error": raise Exception(d["error"])
        time.sleep(3)

for f in sorted(audio_dir.glob("*.m4a")):
    out = output_dir / (f.stem + "_raw.txt")
    if out.exists():
        print(f"[SKIP] {f.name}")
        continue
    print(f"[...] {f.name}")
    text = poll(transcribe(upload_file(f)))
    out.write_text(text, encoding="utf-8")
    print(f"[OK]  {out.name}")
```

---

## Формат clean-транскрипта

Что убираем:
- вступление (угадай с одного слова, бытовые реплики до истории)
- технические реплики («подожди, я записываю», «нажимай»)
- явный шум и повторы

Что оставляем:
- саму историю целиком
- реплики сына по ходу — это живая фактура
- оговорки и самоисправления рассказчика — это голос

---

## Формат обработки каждой истории

Каждый файл в `processed/` содержит три блока:

### 1. 📖 Текст для книги / ТГ-канала
- Авторский голос — минимальная обработка
- Прямые цитаты из транскрипта (курсив или кавычки)
- Реплики сына — в тексте, как диалог
- Никакой «литературщины» — слышен живой рассказчик

### 2. 🎓 Педагогическая рамка
- Какая ценность / урок в истории
- Что проговорить с сыном (возраст 6 лет)
- Конкретный вопрос для следующего раза

### 3. 💬 Что делать дальше
- Игра или активность по мотивам
- Вопрос на засыпание
- Идея для следующей истории (если есть связь)

---

## Педагогические темы, которые уже прошли

| История | Тема |
|---------|------|
| Гномик Гоша | Магия выдумки, забота о младших |
| Крутобол | Изобретение, командная игра, проигрывать достойно |
| Ожог | Чужая безответственность, последствия |
| Пудра | Любопытство, нечаянная красота |
| Трансформатор | Ответственность старшего, коммуникация в трудной ситуации |

---

## Темы, которые стоит развивать дальше

- Дружба и предательство
- Страх и смелость
- Честность и маленькая ложь
- Деньги и желания
- Отношения с родителями / бабушками
- Первый раз что-то сделал сам
