import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

# Źródła RSS o szerszej tematyce lifestyle, nauka, ciekawostki, kultura i świat
RSS_URLS = [
    "https://news.google.com/rss/search?q=science+nature+culture+quirky+fun+facts&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=ciekawostki+nauka+technologia+kultura+świat&hl=pl&gl=PL&ceid=PL:pl",
    "https://www.reutersagency.com/feed/?best-topics=lifestyle&post_type=best"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:15]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

archive_file = "archive_rozrywka.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

now_pl = datetime.now(pl_tz)
today_date_key = now_pl.strftime("%Y-%m-%d")
session_fixed_key = f"{today_date_key}_rozrywka"

# Pobieramy tytuły z historii rozrywkowej, aby unikać duplikatów
previous_topics = []
sorted_sessions = sorted(archive_data.keys(), reverse=True)[:10]
for session_key in sorted_sessions:
    session_content = archive_data[session_key]
    if isinstance(session_content, dict) and "items" in session_content:
        for item in session_content.get("items", []):
            if "title" in item:
                clean_title = "".join([c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
                previous_topics.append(clean_title)

# Wstępna filtracja duplikatów w Pythonie
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

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz lekką, rozrywkową listę 10 ciekawostek (przetłumacz i sformatuj na język polski).

WYMAGANA STRUKTURA (dokładnie 10 elementów):
- Skup się wyłącznie na luźnych tematach, ciekawostkach ze świata przyrody, nauki, nietypowych rekordach, nietypowych świętach (np. dzień kota, dzień wieloryba) oraz fascynujących smaczkach kulturowych. 
- Zero ciężkiej polityki czy giełdy.

Każdy obiekt na liście musi zawierać dokładnie następujące klucze:
- "category": Kategoria pisana wielkimi literami (np. "CIEKAWOSTKA", "PRZYRODA", "NAUKA / LIFE", "REKORDY").
- "title": Krótki, chwytliwy nagłówek z unikalną, dopasowaną emotikoną na początku (np. "🐋 Wielki dzień wielorybów: Gdzie je spotkać?").
- "summary": Konkretny, ciekawy opis w 1-2 zdaniach przybliżający fakt.
- "comment": Lekki, zabawny lub intrygujący komentarz, anegdotka lub żart (odpowiednik luźnej porady lub humoru).
- "link": Dokładnie ten sam URL z wejścia dla danej wiadomości (jeśli ciekawostka nie ma bezpośredniego linku, przypisz pierwszy lepszy URL z listy).

ZASADY:
- BEZWZGLĘDNIE unikaj tematów powtarzających się z historii archiwum: {json.dumps(previous_topics[:30], ensure_ascii=False)}
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
        "category": "CIEKAWOSTKA",
        "title": f"💡 {art['title']}",
        "summary": "Fascynujący fakt ze świata.",
        "comment": "Kto by pomyślał!",
        "link": art['link']
    } for art in raw_articles[:10]]

timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")
date_pretty = now_pl.strftime("%d %B %Y")
time_pretty = now_pl.strftime("%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

with open("rozrywka.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

archive_data[session_fixed_key] = output_data

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
