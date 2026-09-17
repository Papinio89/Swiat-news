import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

RSS_URLS = [
    # --- GLOBALNE / GEOPOLITYKA ---
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=world+news+geopolitics&hl=en-US&gl=US&ceid=US:en",
    
    # --- BIZNES / RYNKI / GOSPODARKA ---
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=markets&sort=date",
    
    # --- TECHNOLOGIA / AI / CYBER ---
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://arstechnica.com/feed/",
    
    # --- NAUKA / KOSMOS ---
    "https://www.sciencedaily.com/rss/top/science.xml",
    "https://phys.org/rss-feed/",
    "https://www.nasa.gov/feed/",
    
    # --- POLSKA ---
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:7]:  # 7 najświeższych wpisów z każdego feeda
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

# Pobieramy tytuły z ostatnich 8 sesji w archiwum (ok. 4 dni wstecz) dla filtracji duplikatów
previous_topics = []
sorted_sessions = sorted(archive_data.keys(), reverse=True)[:8]
for session_key in sorted_sessions:
    session_content = archive_data[session_key]
    if isinstance(session_content, dict) and "items" in session_content:
        for item in session_content.get("items", []):
            if "title" in item:
                clean_title = "".join([c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
                previous_topics.append(clean_title)

# Wstępna filtracja duplikatów w Pythonie (próg 35% pokrycia słów)
filtered_raw_articles = []
for art in raw_articles:
    art_clean = "".join([c for c in art["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
    is_duplicate = False
    
    art_words = set(art_clean.split())
    if len(art_words) > 2:
        for prev in previous_topics:
            prev_words = set(prev.split())
            if len(prev_words) > 2:
                common = art_words.intersection(prev_words)
                if len(common) / min(len(art_words), len(prev_words)) > 0.35:
                    is_duplicate = True
                    break
                    
    if not is_duplicate:
        filtered_raw_articles.append(art)

# Zabezpieczenie przed nadmiernym odfiltrowaniem
if len(filtered_raw_articles) < 5:
    filtered_raw_articles = raw_articles

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz profesjonalny, dynamiczny przegląd najważniejszych wiadomości ze świata (przetłumacz i sformatuj na język polski).

PROFIL WYDANIA:
- 100% TWARDE FAKTY I GOSPODARKA (12-16 elementów).
- Skup się WYŁĄCZNIE na istotnych wydarzeniach: geopolityka, rynki finansowe, surowce, decyzje rządowe/banków centralnych, obronność, kluczowe technologie oraz ważne wydarzenia z Polski i świata.
- Całkowicie pomijaj luźne ciekawostki, śmieszne anegdoty czy tematy lifestylowe (od tego jest osobny serwis rozrywkowy).

Każdy obiekt na liście musi zawierać dokładnie następujące klucze:
- "category": Kategoria pisana WIELKIMI LITERAMI (np. "GEOPOLITYKA", "RYNKI I GOSPODARKA", "TECHNOLOGIE / AI", "POLSKA", "OBRONNOŚĆ", "NAUKA").
- "title": Krótki, merytoryczny i chwytliwy nagłówek z dopasowaną emotikoną na początku (np. "📉 Rynki w dół: Nowe decyzje Fed...", "🛢️ Ropa drożeje po napięciach na Bliskim Wschodzie").
- "summary": Rzeczowy, konkretny opis w 1-2 zdaniach, wyjaśniający sedno wydarzenia.
- "comment": Celny, analityczny komentarz biznesowy, polityczny lub rynkowy (wyjaśniający konsekwencje lub szerszy kontekst).
- "image_query": 2-3 precyzyjne, profesjonalne słowa kluczowe w języku ANGIELSKIM do wyszukiwania zdjęcia stockowego (np. "stock market board", "cargo container ship", "diplomacy meeting", "military aircraft", "server room datacenter").
- "link": Dokładnie ten sam URL z wejścia dla danego artykułu.

ZASADY:
- BEZWZGLĘDNIE unikaj tematów powtarzających się z ostatniej historii archiwum: {json.dumps(previous_topics[:30], ensure_ascii=False)}
- Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów z powyższymi kluczami.
- Żadnego formatowania markdown (żadnego ```json ani ```).

Dane wejściowe:
{json.dumps(filtered_raw_articles, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-2.5-flash-lite',
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
        "image_query": "world news global press",
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

# 1. Zapis głównego wydania newsów
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# 2. Zapis do archiwum wydań
archive_data[session_fixed_key] = output_data
with open("archive.json", "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

# 3. Zapis surowych tytułów z RSS pod szybkie wrzutki na Threads
raw_feed_output = {
    "date": date_pretty,
    "time": time_pretty,
    "count": len(filtered_raw_articles),
    "items": filtered_raw_articles
}
with open("raw_feed.json", "w", encoding="utf-8") as f:
    json.dump(raw_feed_output, f, ensure_ascii=False, indent=2)
