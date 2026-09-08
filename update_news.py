import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

RSS_URLS = [
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://news.google.com/rss/search?q=world+news+finance+tech+science&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:12]:
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
            if "title" in item:
                previous_topics.append(item["title"])

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz zwięzły, dynamiczny przegląd globalny (przetłumacz i sformatuj na język polski).

WYMAGANA STRUKTURA (12-15 elementów):
Każdy obiekt na liście musi zawierać dokładnie następujące klucze:
- "category": Kategoria wiadomości pisana wielkimi literami (np. "ŚWIAT / GEOPOLITYKA", "RYNKI / GOSPODARKA", "NAUKA / TECHNOLOGIE").
- "title": Krótki, chwytliwy nagłówek z dopasowaną emotikoną na początku (np. "🇺🇸 Decyzja Fedu zaskoczyła rynki").
- "summary": Krótki opis w postaci 1 konkretnego zdania (maksymalnie dwa krótkie).
- "comment": Krótki, trafny komentarz analityczny (odpowiednik idei żarówki).
- "link": Dokładnie ten sam URL z wejścia dla danej wiadomości.

ZASADY:
- Unikaj powtarzania tematów z poranka: {json.dumps(previous_topics, ensure_ascii=False)}
- Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów z powyższymi kluczami.
- Żadnego formatowania markdown (żadnego ```json ani ```).

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
    items = [{
        "category": "AKTUALNOŚCI",
        "title": f"📌 {art['title']}",
        "summary": "Pobrano nagłówek bezpośrednio ze źródła.",
        "comment": "Brak dodatkowego komentarza.",
        "link": art['link']
    } for art in raw_articles[:15]]

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
