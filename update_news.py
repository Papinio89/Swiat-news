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
        # Pobieramy 18 elementów ze źródła – idealny balans między bogatą treścią a niskim kosztem
        for entry in feed.entries[:18]:
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

session_name = "poranne" if current_hour < 12 else "wieczorne"
session_fixed_key = f"{today_date_key}_{session_name}"

previous_topics = []
if session_name == "wieczorne":
    morning_key = f"{today_date_key}_poranne"
    if morning_key in archive_data:
        for item in archive_data[morning_key].get("items", []):
            if "text" in item:
                previous_topics.append(item["text"])

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Zbalansowany prompt: precyzyjnie wymusza obecność ciekawostek i solidną paczkę newsów
prompt = f"""Przeanalizuj poniższe nagłówki i stwórz atrakcyjny przegląd w stylu platformy X.
WYMAGANE MINIMUM:
1. Przygotuj 12-15 ważnych wiadomości (geopolityka, finanse, gospodarka). Każda musi zaczynać się od odpowiedniej flagi lub ikony tematycznej (np. 🇺🇸, 🇪🇺, 📈, ⚖️). NIGDY nie używaj ikony globu (🌍).
2. Przygotuj dodatkowo 3-5 luźniejszych ciekawostek ze świata (nauka, technologia, lifestyle) z dedykowanymi emoji (np. 🚀, 🤖, 🧠, ☕).
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

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

archive_data[session_fixed_key] = output_data

with open("archive.json", "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
