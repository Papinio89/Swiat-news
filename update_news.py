import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

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

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}


def clean_link(url: str) -> str:
    """Czyści linki (Google News + parametry śledzące)."""
    if not url or url == "#":
        return "#"

    try:
        # Google News – próba wyciągnięcia oryginalnego URL
        if "news.google.com" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "url" in qs and qs["url"]:
                return qs["url"][0]

        # Usuwanie typowych parametrów trackingowych
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "at_medium", "at_campaign", "fbclid", "gclid", "mc_cid", "mc_eid"
        }
        parsed = urlparse(url)
        if parsed.query:
            qs = parse_qs(parsed.query)
            clean_qs = {k: v[0] for k, v in qs.items() if k not in tracking_params}
            if clean_qs:
                new_query = urllib.parse.urlencode(clean_qs)
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}"
            else:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return url
    except Exception:
        return url


def validate_items(items: list) -> list:
    """Waliduje i czyści obiekty zwrócone przez AI."""
    required = {"category", "title", "summary", "comment", "image_query", "link"}
    valid = []

    for item in items:
        if not isinstance(item, dict):
            continue
        if not required.issubset(item.keys()):
            continue

        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        comment = str(item.get("comment", "")).strip()
        category = str(item.get("category", "AKTUALNOŚCI")).strip().upper()
        image_query = str(item.get("image_query", "world news")).strip()
        link = clean_link(str(item.get("link", "#")))

        # Minimalne wymagania jakościowe
        if len(title) < 12 or len(summary) < 30:
            continue

        valid.append({
            "category": category,
            "title": title,
            "summary": summary,
            "comment": comment,
            "image_query": image_query,
            "link": link
        })

    return valid


def fetch_pexels_image_url(query: str) -> str:
    if not PEXELS_API_KEY:
        return FALLBACK_IMG

    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
    req = urllib.request.Request(url, headers={
        "Authorization": PEXELS_API_KEY,
        "User-Agent": "SwiatWMinute-Bot/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                photos = data.get("photos", [])
                if photos:
                    src = photos[0].get("src", {})
                    return src.get("large") or src.get("medium") or FALLBACK_IMG
    except Exception as ex:
        print(f"Błąd Pexels dla zapytania '{query}': {ex}")
    return FALLBACK_IMG


# --- ZBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:  # mniej szumu
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 15:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

# --- ARCHIWUM I DEDUPLIKACJA ---
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
    session_content = archive_data.get(session_key)
    if isinstance(session_content, dict) and "items" in session_content:
        for item in session_content.get("items", []):
            if "title" in item:
                clean_title = "".join(
                    c for c in item["title"]
                    if ord(c) > 127 or c.isalnum() or c.isspace()
                ).strip().lower()
                previous_topics.append(clean_title)

filtered_raw_articles = []
for art in raw_articles:
    art_clean = "".join(
        c for c in art["title"]
        if ord(c) > 127 or c.isalnum() or c.isspace()
    ).strip().lower()

    is_duplicate = False
    art_words = set(art_clean.split())
    if len(art_words) > 2:
        for prev in previous_topics:
            prev_words = set(prev.split())
            if len(prev_words) > 2:
                common = art_words.intersection(prev_words)
                ratio = len(common) / min(len(art_words), len(prev_words))
                if ratio > 0.40:  # lekko ostrzejsza deduplikacja
                    is_duplicate = True
                    break

    if not is_duplicate:
        filtered_raw_articles.append(art)

if len(filtered_raw_articles) < 6:
    filtered_raw_articles = raw_articles

# --- PROMPT ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś redaktorem dynamicznego przeglądu prasy. Tworzysz treści pod szybkie czytanie rano.

Zadanie: Na podstawie nagłówków stwórz 12-15 najważniejszych wiadomości w języku polskim.

PROPORCJE (twarde limity):
- Minimum 80% = Geopolityka, obronność, rynki, surowce, decyzje rządów, Polska
- Maksymalnie 2 pozycje z kategorii TECHNOLOGIE / AI
- Maksymalnie 1 pozycja NAUKA / KOSMOS (tylko jeśli naprawdę istotna)
- Zero ciekawostek, lifestyle, memów i tematów rozrywkowych

STYL:
- Tytuł: krótki, konkretny, chwytliwy, z jedną emotikoną na początku. Może być mocniejszy i bardziej przyciągający uwagę.
- Summary: 1-2 zdania. Rzeczowe sedno wydarzenia.
- Comment: 1 konkretne, analityczne zdanie (konsekwencje, kontekst, znaczenie). Bez lania wody.
- Category: WIELKIMI LITERAMI (GEOPOLITYKA, RYNKI I GOSPODARKA, OBRONNOŚĆ, POLSKA, TECHNOLOGIE / AI, NAUKA)
- image_query: 2-4 słowa kluczowe po angielsku
- link: dokładnie ten sam URL, który otrzymałeś

Unikaj tematów podobnych do tych z archiwum:
{json.dumps(previous_topics[:25], ensure_ascii=False)}

Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów. Żadnego markdown, żadnych ```.

Dane wejściowe:
{json.dumps(filtered_raw_articles, ensure_ascii=False)}
"""

# --- GENEROWANIE ---
items = []
try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",  # poprawiona nazwa modelu (dostosuj jeśli używasz innej)
        contents=prompt,
    )
    text_res = response.text.strip()

    if text_res.startswith("```json"):
        text_res = text_res[7:]
    if text_res.startswith("```"):
        text_res = text_res[3:]
    if text_res.endswith("```"):
        text_res = text_res[:-3]
    text_res = text_res.strip()

    raw_items = json.loads(text_res)
    items = validate_items(raw_items)

except Exception as e:
    print(f"Błąd AI: {e}")
    items = [{
        "category": "AKTUALNOŚCI",
        "title": f"📌 {art['title']}",
        "summary": "Pobrano nagłówek bezpośrednio ze źródła.",
        "comment": "Brak dodatkowego komentarza.",
        "image_query": "world news global press",
        "link": art["link"]
    } for art in filtered_raw_articles[:12]]

# --- ZDJĘCIA ---
print("Pobieranie linków do zdjęć z Pexels...")
for item in items:
    q = item.get("image_query", "world news")
    item["image_url"] = fetch_pexels_image_url(q)

# --- ZAPIS ---
date_pretty = f"{now_pl.day} {POLISH_MONTHS[now_pl.month]} {now_pl.year}"
time_pretty = now_pl.strftime("%H:%M")
timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")

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
