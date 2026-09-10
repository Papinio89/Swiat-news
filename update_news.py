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
        for entry in feed.entries[:15]:
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

# Pobieramy tytuły z ostatnich 8 sesji w archiwum (ok. 4 dni wstecz) dla lepszej filtracji
previous_topics = []
sorted_sessions = sorted(archive_data.keys(), reverse=True)[:8]
for session_key in sorted_sessions:
    session_content = archive_data[session_key]
    if isinstance(session_content, dict) and "items" in session_content:
        for item in session_content.get("items", []):
            if "title" in item:
                clean_title = "".join([c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()]).strip().lower()
                previous_topics.append(clean_title)

# Zaostrzona wstępna filtracja duplikatów w Pythonie (próg 35% pokrycia słów)
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

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz dynamiczny przegląd globalny (przetłumacz i sformatuj na język polski).

WYMAGANA STRUKTURA (12-16 elementów):
Podziel wiadomości na dwie wyraźne grupy:
1. FAKTY I GOSPODARKA (ok. 75% treści): Ważne wiadomości ze świata, geopolityka, rynki (waluty, surowce, konflikty, decyzje rządowe).
2. CIEKAWOSTKI I LUŹNE TEMATY (ok. 25% treści, minimum 3-4 pozycje): Obowiązkowo dodaj zaskakujące, nietypowe lub lżejsze ciekawostki, anegdoty ze świata nauki, technologii lub codzienne smaczki (z unikalnymi emoji typu 🐝, 🤖, 🧠, 🚀).

Każdy obiekt na liście musi zawierać dokładnie następujące klucze:
- "category": Kategoria pisana wielkimi literami (np. "ŚWIAT / GOSPODARKA", "TECHNOLOGIE", "CIEKAWOSTKA / LIFE").
- "title": Krótki, chwytliwy nagłówek z dopasowaną emotikoną na początku (np. "🐝 Dzień Pszczół: Niezwykłe odkrycia...").
- "summary": Konkretny, krótki opis w 1-2 zdaniach.
- "comment": Trafny, lekki lub wnikliwy komentarz analityczny (odpowiednik idei żarówki).
- "link": Dokładnie ten sam URL z wejścia dla danej wiadomości (jeśli to luźna ciekawostka bez linku, przypisz pierwszy lepszy URL z listy).

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
