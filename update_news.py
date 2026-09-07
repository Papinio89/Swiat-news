import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

# Polska strefa czasowa
pl_tz = ZoneInfo("Europe/Warsaw")

# Ograniczone źródła i liczba pobieranych pozycji dla oszczędności tokenów
RSS_URLS = [
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
    "https://www.reuters.com/world/"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        # Zmniejszamy do 10 wpisów na źródło (oszczędność danych wejściowych)
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

# Pobieramy tylko same teksty wcześniejszych nagłówków z dzisiaj (oszczędność tokenów historii)
previous_topics = []
for k, v in archive_data.items():
    if k.startswith(today_date_key):
        for item in v.get("items", []):
            if "text" in item:
                previous_topics.append(item["text"])

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Bardziej zwięzły prompt (mniejsze zużycie tokenów)
prompt = f"""Wybierz z poniższej listy 15-20 najważniejszych wiadomości (geopolityka, finanse, gospodarka) oraz 5 ciekawostek.
Stwórz minimalistyczny przegląd w stylu platformy X (krótkie fakty z flagami i emoji).

ZASADY:
1. UNIKAJ TYCH TEMATÓW (były wcześniej): {json.dumps(previous_topics, ensure_ascii=False)}
2. Zwróć WYŁĄCZNIE tablicę JSON obiektów z kluczami: "text" (nagłówek) oraz "link" (ten sam URL).
3. Żadnego markdown (żadnego ```json).

Dane:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-2.5-flash',  # Ekonomiczny i szybki model
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
    items = [{"text": f"📌 {art['title'][:60]}...", "link": art['link']} for art in raw_articles[:15]]

timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")
date_pretty = now_pl.strftime("%d %B %Y")
time_pretty = now_pl.strftime("%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

archive_data[timestamp_key] = output_data

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
