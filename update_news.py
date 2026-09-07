import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

RSS_URLS = [
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
    "https://www.reuters.com/world/"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

now_pl = datetime.now(pl_tz)
today_date_key = now_pl.strftime("%Y-%m-%d")
current_hour = now_pl.hour

# Definiujemy, czy to sesja poranna (< 12:00) czy wieczorna (>= 12:00)
is_morning = current_hour < 12
session_type_str = "poranne" if is_morning else "wieczorne"

# Szukamy, czy w archiwum dla dzisiejszego dnia istnieje już sesja tego samego typu
existing_session_key = None
for k in archive_data.keys():
    if k.startswith(today_date_key):
        # Sprawdzamy godzinę zapisaną w kluczu archiwum (np. "2026-09-07_06:30" -> godzina 6)
        try:
            h = int(k.split("_")[1].split(":")[0])
            if (is_morning and h < 12) or (not is_morning and h >= 12):
                existing_session_key = k
                break
        except Exception:
            pass

# Pobieramy poprzednie tematy tylko jeśli to sesja wieczorna i nie nadpisujemy tej samej sesji
previous_topics = []
if not is_morning:
    for k, v in archive_data.items():
        if k.startswith(today_date_key) and k != existing_session_key:
            for item in v.get("items", []):
                if "text" in item:
                    previous_topics.append(item["text"])

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz minimalistyczny przegląd w stylu platformy X.
STRUKTURA WYMAGANA:
1. Około 15-18 najważniejszych, poważnych wiadomości (geopolityka, finanse, gospodarka, konflikty). Każda musi zaczynać się od ODPOWIEDNIEJ flagi państwa lub tematycznej ikony (np. 🇺🇸, 🇪🇺, 📈, ⚖️, ⚡), NIGDY nie używaj wszędzie tej samej ikony globu (🌍).
2. Dodatkowo obowiązkowo 5-7 luźniejszych, ciekawych lub zaskakujących ciekawostek ze świata (nauka, kultura, technologia, lifestyle) z dedykowanymi emoji (np. 🚀, 🤖, 🧠, 🦖, ☕).
3. Unikaj powtarzania tematów z poranka: {json.dumps(previous_topics, ensure_ascii=False)}
4. Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów z kluczami: "text" oraz "link" (dokładnie ten sam URL z wejścia).
5. Żadnego formatowania markdown (żadnego ```json ani ```).

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
    )
    text_res = response.text.strip()
    if text_res.startswith("```json"):
        text_res = text_res[7:-3].strip()
    elif text_res.startswith("```"):
        text_res = text_res[3:-3].strip()
    
    items = json.loads(text_res)
except Exception as e:
    print(f"Błąd AI: {e}")
    items = [{"text": f"📌 {art['title']}", "link": art['link']} for art in raw_articles[:15]]

timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")
date_pretty = now_pl.strftime("%d %B %Y")
time_pretty = now_pl.strftime("%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

# Zapis bieżących newsów
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# Jeśli sesja danego typu już dzisiaj istniała, usuwamy stary wpis z archiwum, żeby nie robić duplikatów
if existing_session_key and existing_session_key in archive_data:
    del archive_data[existing_session_key]

# Zapisujemy pod nowym/aktualnym kluczem czasu tej sesji
archive_data[timestamp_key] = output_data

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
