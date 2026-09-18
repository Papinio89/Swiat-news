import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

# Źródła ukierunkowane na politykę, obronność, geopolitykę i rynki
RSS_URLS = [
    # --- GLOBALNE / GEOPOLITYKA / POLITYKA ---
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=world+news+geopolitics+defense&hl=en-US&gl=US&ceid=US:en",
    
    # --- BIZNES / GOSPODARKA / RYNKI ---
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=markets&sort=date",
    
    # --- POLSKA / BEZPIECZEŃSTWO ---
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
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

# Zbieramy tematy do wykluczenia z archive.json ORAZ news.json
excluded_topics = []

# 1. Z archive.json (ostatnie sesje)
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

# 2. Z aktualnego news.json
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

# Wstępna filtracja duplikatów po stronie Pythona
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

prompt = f"""Przeanalizuj poniższe surowe nagłówki i wybierz DOKŁADNIE 3 NAJWAŻNIEJSZE i NAJCIEKAWSZE wiadomości uzupełniające.

KRYTERIA SELEKCJI:
- Wybierz wyłącznie tematy z obszarów: POLITYKA, BEZPIECZEŃSTWO / OBRONNOŚĆ, GEOPOLITYKA lub GOSPODARKA / RYNKI.
- Zero ciekawostek, lifestyle'u czy tematów pobocznych.
- Wybierz tematy świeże i istotne, które stanowią mocne uzupełnienie dnia.

Zwróć DOKŁADNIE 3 obiekty w czystej tablicy JSON. Każdy obiekt musi zawierać:
- "category": Kategoria pisana WIELKIMI LITERAMI (np. "GEOPOLITYKA", "BEZPIECZEŃSTWO", "GOSPODARKA", "POLITYKA").
- "title": Krótki, chwytliwy nagłówek w języku polskim z dopasowaną emotikoną na początku (np. "🛡️ Nowy pakt obronny...", "🏛️ Napięcia dyplomatyczne...").
- "summary": Rzeczowe podsumowanie w 1-2 zdaniach wyjaśniające sedno sprawy.
- "comment": Krótki, analityczny komentarz pokazujący znaczenie tego faktu.
- "image_query": 2-3 profesjonalne słowa kluczowe po ANGIELSKU pod zdjęcie stockowe (np. "nato military summit", "central bank building", "defense radar system").
- "link": Dokładny adres URL z wejścia przypisany do tej wiadomości.

BEZWZGLĘDNY ZAKAZ POWIELANIA TEMATÓW Z TEJ LISTY (to już opublikowane wiadomości):
{json.dumps(excluded_topics[:40], ensure_ascii=False)}

Zwróć WYŁĄCZNIE poprawną tablicę JSON (bez ```json ani ```).

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
    items = items[:3]  # Gwarancja dokładnie 3 newsów
except Exception as e:
    print(f"Błąd AI: {e}")
    items = [{
        "category": "FAST NEWS",
        "title": f"📌 {art['title']}",
        "summary": "Szybki news pobrany bezpośrednio z agencji prasowych.",
        "comment": "Wydarzenie z ostatnich godzin.",
        "image_query": "breaking news world politics",
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

# Zapis do fast.json
with open("fast.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"Pomyślnie wygenerowano fast.json z {len(items)} newsami o {time_pretty}.")
