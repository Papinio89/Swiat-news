import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

RSS_URLS = [
    # --- POLSKIE / REGIONALNE BEZPIECZEŃSTWO ---
    "https://defence24.pl/rss",
    "https://news.google.com/rss/search?q=wojsko+bezpiecze%C5%84stwo+granica+obronno%C5%9B%C4%87&hl=pl&gl=PL&ceid=PL:pl",
    
    # --- GLOBALNY SEKTOR OBRONNY / KONFLIKTY ZBROJNE ---
    "https://www.twz.com/feed",
    "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
    "https://news.usni.org/feed",
    
    # --- GEOPOLITYKA / KONFLIKTY ŚWIATOWE ---
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=military+strike+missile+war+tensions&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=nato+russia+china+taiwan+defense&hl=en-US&gl=US&ceid=US:en"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        # Pobieramy tylko 3 najświeższe z każdego feeda, aby nie pompować tokenów
        for entry in feed.entries[:3]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title.strip(), "link": link.strip()})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

excluded_topics = []

# 1. Z archive.json
archive_file = "archive.json"
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            for session_key in sorted(archive_data.keys(), reverse=True)[:6]:
                session_content = archive_data[session_key]
                if isinstance(session_content, dict) and "items" in session_content:
                    for item in session_content.get("items", []):
                        if "title" in item:
                            clean = "".join([c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
                            excluded_topics.append(clean)
    except Exception:
        pass

# 2. Z news.json
news_file = "news.json"
if os.path.exists(news_file):
    try:
        with open(news_file, "r", encoding="utf-8") as f:
            news_data = json.load(f)
            if isinstance(news_data, dict) and "items" in news_data:
                for item in news_data.get("items", []):
                    if "title" in item:
                        clean = "".join([c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
                        excluded_topics.append(clean)
    except Exception:
        pass

filtered_raw_articles = []
for art in raw_articles:
    art_clean = "".join([c for c in art["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
    is_duplicate = False
    
    art_words = set(art_clean.split())
    if len(art_words) > 2:
        for prev in excluded_topics:
            prev_words = set(prev.split())
            if len(prev_words) > 2:
                common = art_words.intersection(prev_words)
                if len(common) / min(len(art_words), len(prev_words)) > 0.35:
                    is_duplicate = True
                    break
                    
    if not is_duplicate:
        filtered_raw_articles.append(art)

if len(filtered_raw_articles) < 3:
    filtered_raw_articles = raw_articles

# Maksymalnie 15 pozycji przekazywanych do AI (oszczędność na prompt wejściowy)
articles_for_ai = filtered_raw_articles[:15]

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Wybierz DOKŁADNIE 3 NAJMOCNIEJSZE tematy militarne, obronne lub geopolityczne z poniższej listy.

Zwróć DOKŁADNIE 3 obiekty w czystej tablicy JSON:
- "category": Kategoria (WIELKIE LITERY, np. "OBRONNOŚĆ", "KONFLIKTY", "GEOPOLITYKA", "BEZPIECZEŃSTWO").
- "title": Zwięzły, mocny nagłówek z emoji (np. 🚨, 🚀, 🛡️, ⚔️).
- "summary": Konkretny opis faktu (1-2 zdania).
- "comment": Chłodna puenta strategiczna (1 zdanie).
- "image_query": 2-3 angielskie słowa kluczowe stock photo.
- "link": URL wejściowy dla danego newsa.

Unikaj tematów z tej listy: {json.dumps(excluded_topics[:10], ensure_ascii=False)}
Zwróć WYŁĄCZNIE poprawną tablicę JSON (bez markdown ```json ani ```).

Dane wejściowe:
{json.dumps(articles_for_ai, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.5-flash-lite',
        contents=prompt,
    )
    text_res = response.text.strip()
    if text_res.startswith("```json"):
        text_res = text_res[7:-3].strip()
    elif text_res.startswith("```"):
        text_res = text_res[3:-3].strip()
    
    items = json.loads(text_res)
    items = items[:3]
except Exception as e:
    print(f"Błąd AI: {e}")
    items = [{
        "category": "BEZPIECZEŃSTWO",
        "title": f"🚨 {art['title']}",
        "summary": "Wiadomość z agencji prasowych.",
        "comment": "Wydarzenie z sektora obronności.",
        "image_query": "military defense combat",
        "link": art['link']
    } for art in filtered_raw_articles[:3]]

now_pl = datetime.now(pl_tz)
timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")
date_pretty = now_pl.strftime("%d %B %Y")
time_pretty = now_pl.strftime("%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

with open("fast.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"Zapisano 3 twarde newsy do fast.json o {time_pretty}.")
