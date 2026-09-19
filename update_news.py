import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

# Konfiguracja Pexels
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "N9lZEHVVxzeo70Ool0sBLSnzpZAvgUxeRk7niJKr5pQdMRkQyIouz2QQ")
FALLBACK_IMG = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=800&auto=format&fit=crop"

RSS_URLS = [
    # --- GLOBALNE / GEOPOLITYKA / OBRONNOŚĆ ---
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=world+news+geopolitics+military&hl=en-US&gl=US&ceid=US:en",
    "https://defence24.pl/rss",
    
    # --- BIZNES / RYNKI / GOSPODARKA ---
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=markets&sort=date",
    
    # --- TECHNOLOGIA / AI / CYBER ---
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://arstechnica.com/feed/",
    
    # --- POLSKA ---
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:7]:
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
sorted_sessions = sorted(archive_data.keys(), reverse=True)[:8]
for session_key in sorted_sessions:
    session_content = archive_data[session_key]
    if isinstance(session_content, dict) and "items" in session_content:
        for item in session_content.get("items", []):
            if "title" in item:
                clean_title = "".join([c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
                previous_topics.append(clean_title)

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

if len(filtered_raw_articles) < 5:
    filtered_raw_articles = raw_articles

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz profesjonalny, dynamiczny przegląd najważniejszych wiadomości ze świata (przetłumacz i sformatuj na język polski).

PROFIL I RESTRYKCJE PROPORCJI (12-16 elementów):
1. MINIMUM 80% CAŁOŚCI MUSZĄ STANOWIĆ:
   - GEOPOLITYKA, WOJNA, OBRONNOŚĆ, RYNKI FINANSOWE, SUROWCE, DECYZJE RZĄDÓW ORAZ POLSKA.
2. TWARDE LIMITY DLA TECHNOLOGII I NAUKI:
   - MAKSYMALNIE 2 pozycje z kategorii "TECHNOLOGIE / AI".
   - MAKSYMALNIE 1 pozycja z kategorii "NAUKA / KOSMOS" (lub 0, jeśli nie ma przełomowego wydarzenia).
   - Bezwzględny zakaz dominacji tematów o modelach LLM czy misjach satelitarnych.
3. Całkowity zakaz ciekawostek, lifestyle'u i memów.

Każdy obiekt na liście musi zawierać dokładnie następujące klucze:
- "category": Kategoria pisana WIELKIMI LITERAMI (np. "GEOPOLITYKA", "RYNKI I GOSPODARKA", "OBRONNOŚĆ", "POLSKA", "TECHNOLOGIE / AI", "NAUKA").
- "title": Krótki, merytoryczny i chwytliwy nagłówek z dopasowaną emotikoną na początku (np. "📉 Rynki w dół: Nowe decyzje Fed...", "🛢️ Ropa drożeje po napięciach na Bliskim Wschodzie").
- "summary": Rzeczowy opis w 1-2 zdaniach, wyjaśniający sedno wydarzenia.
- "comment": Celny, analityczny komentarz biznesowy, polityczny lub strategiczny.
- "image_query": 2-3 precyzyjne słowa kluczowe w języku ANGIELSKIM do wyszukiwania zdjęcia stockowego (np. "stock market board", "cargo container ship", "diplomacy meeting", "military aircraft").
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
        "image_query": "world news global press",
        "link": art['link']
    } for art in raw_articles[:15]]


# --- POBIERANIE ZDJĘĆ Z PEXELS PO STRONIE PYTHON ---
def fetch_pexels_image_url(query):
    if not PEXELS_API_KEY:
        return FALLBACK_IMG
    
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
    req = urllib.request.Request(url, headers={
        "Authorization": PEXELS_API_KEY,
        "User-Agent": "SwiatWMinute-Bot/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                photos = data.get("photos", [])
                if photos:
                    src = photos[0].get("src", {})
                    return src.get("large") or src.get("medium") or FALLBACK_IMG
    except Exception as ex:
        print(f"Błąd Pexels dla zapytania '{query}': {ex}")
    return FALLBACK_IMG

print("Pobieranie linków do zdjęć z Pexels...")
for item in items:
    q = item.get("image_query", "world news")
    item["image_url"] = fetch_pexels_image_url(q)


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

raw_feed_output = {
    "date": date_pretty,
    "time": time_pretty,
    "count": len(filtered_raw_articles),
    "items": filtered_raw_articles
}
with open("raw_feed.json", "w", encoding="utf-8") as f:
    json.dump(raw_feed_output, f, ensure_ascii=False, indent=2)

print(f"Zakończono pomyślnie. Zapisano {len(items)} newsów z gotowymi zdjęciami.")
