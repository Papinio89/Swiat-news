import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

# Źródła wyspecjalizowane w obronności, konfliktach i twardej geopolityce
RSS_URLS = [
    # --- POLSKIE / REGIONALNE BEZPIECZEŃSTWO ---
    "https://defence24.pl/rss",
    "https://news.google.com/rss/search?q=wojsko+bezpiecze%C5%84stwo+granica+obronno%C5%9B%C4%87&hl=pl&gl=PL&ceid=PL:pl",
    
    # --- GLOBALNY SEKTOR OBRONNY / KONFLIKTY ZBROJNE ---
    "https://www.twz.com/feed",                           # The War Zone (taktyka, uzbrojenie, wywiad satelitarny)
    "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",  # Defense News
    "https://news.usni.org/feed",                         # US Naval Institute (incydenty morskie, marynarki wojenne)
    
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
        for entry in feed.entries[:8]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

# Zbieramy tematy do wykluczenia z archive.json oraz news.json
excluded_topics = []

# 1. Z archive.json
archive_file = "archive.json"
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            for session_key in sorted(archive_data.keys(), reverse=True)[:10]:
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

# Wstępny filtr podobieństwa słów
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

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe surowe nagłówki i wyselekcjonuj DOKŁADNIE 3 NAJMOCNIEJSZE tematy o najwyższym ładunku geopolitycznym i militarnym.

KRYTERIUM WYBORU:
- Bezwzględny priorytet: WOJNA, OBRONNOŚĆ, ATAKI, STARCIOM ZBROJNYM, TESTY RAKIETOWE, TWARDA POLITYKA MIĘDZYNARODOWA, RUCHY WOJSK, BEZPIECZEŃSTWO NARODOWE.
- Zero lifestyle'u, ciekawostek, luźnego IT czy tematów pobocznych.
- Wybierz tematy, które budzą największe zaangażowanie i dyskusję w mediach społecznościowych.

Zwróć DOKŁADNIE 3 obiekty w czystej tablicy JSON. Każdy obiekt musi zawierać:
- "category": Kategoria pisana WIELKIMI LITERAMI (wyłącznie: "OBRONNOŚĆ", "KONFLIKTY", "GEOPOLITYKA", "BEZPIECZEŃSTWO").
- "title": Krótki, mocny nagłówek po polsku z adekwatną emotikoną (np. 🚨, 🚀, 🛡️, ⚔️, 🪖, 🛑).
- "summary": Rzeczowy, twardy opis w 1-2 zdaniach przedstawiający bezpośredni fakt i skalę wydarzenia.
- "comment": Chłodna, strategiczna puenta analizująca bezpośrednie konsekwencje militarne, polityczne lub bezpieczeństwa.
- "image_query": 2-3 konkretne słowa kluczowe po ANGIELSKU pod zdjęcie stockowe (np. "military missile launch", "war zone destruction", "soldier combat gear", "warship naval patrol").
- "link": Dokładny adres URL z wejścia przypisany do tego artykułu.

ZAKAZ POWIELANIA TEMATÓW Z TEJ LISTY:
{json.dumps(excluded_topics[:40], ensure_ascii=False)}

Zwróć WYŁĄCZNIE poprawną tablicę JSON (bez formatowania markdown ```json ani ```).

Dane wejściowe:
{json.dumps(filtered_raw_articles, ensure_ascii=False)}
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
