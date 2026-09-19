import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
import traceback
from datetime import datetime, timedelta
from time import mktime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

import feedparser
from google import genai

pl_tz = ZoneInfo("Europe/Warsaw")

# Konfiguracja obrazów
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "N9lZEHVVxzeo70Ool0sBLSnzpZAvgUxeRk7niJKr5pQdMRkQyIouz2QQ")
FALLBACK_IMG = "[https://images.unsplash.com/photo-1579912437766-7896dfc2d008?q=80&w=1200&auto=format&fit=crop](https://images.unsplash.com/photo-1579912437766-7896dfc2d008?q=80&w=1200&auto=format&fit=crop)"

RSS_URLS = [
    # --- POLSKIE / REGIONALNE BEZPIECZEŃSTWO ---
    "[https://defence24.pl/rss](https://defence24.pl/rss)",
    "[https://news.google.com/rss/search?q=wojsko+bezpiecze%C5%84stwo+granica+obronno%C5%9B%C4%87&hl=pl&gl=PL&ceid=PL:pl](https://news.google.com/rss/search?q=wojsko+bezpiecze%C5%84stwo+granica+obronno%C5%9B%C4%87&hl=pl&gl=PL&ceid=PL:pl)",

    # --- GLOBALNY SEKTOR OBRONNY / KONFLIKTY ZBROJNE ---
    "[https://www.twz.com/feed](https://www.twz.com/feed)",
    "[https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml](https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml)",
    "[https://news.usni.org/feed](https://news.usni.org/feed)",

    # --- GEOPOLITYKA / KONFLIKTY ŚWIATOWE ---
    "[https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best](https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best)",
    "[https://feeds.bbci.co.uk/news/world/rss.xml](https://feeds.bbci.co.uk/news/world/rss.xml)",
    "[https://news.google.com/rss/search?q=military+strike+missile+war+tensions&hl=en-US&gl=US&ceid=US:en](https://news.google.com/rss/search?q=military+strike+missile+war+tensions&hl=en-US&gl=US&ceid=US:en)",
    "[https://news.google.com/rss/search?q=nato+russia+china+taiwan+defense&hl=en-US&gl=US&ceid=US:en](https://news.google.com/rss/search?q=nato+russia+china+taiwan+defense&hl=en-US&gl=US&ceid=US:en)"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 12
TARGET_ITEMS = 3


def clean_link(url: str) -> str:
    """Czyści parametry śledzące z linków."""
    if not url or url == "#":
        return "#"
    try:
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
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return url
    except Exception:
        return url


def is_recent(entry) -> bool:
    """Odrzuca wpisy starsze niż MAX_AGE_HOURS (12h)."""
    published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not published:
        return True
    try:
        pub_dt = datetime.fromtimestamp(mktime(published), tz=pl_tz)
        age = datetime.now(pl_tz) - pub_dt
        return age <= timedelta(hours=MAX_AGE_HOURS)
    except Exception:
        return True


def fetch_article_image(url: str) -> str | None:
    """Pobiera og:image / twitter:image ze strony artykułu."""
    if not url or url == "#" or "news.google.com" in url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                img = m.group(1).strip()
                if img.startswith("//"): img = "https:" + img
                if img.startswith("http"): return img
    except Exception:
        pass
    return None


def fetch_pexels_image_url(query):
    """Pobiera zdjęcie z Pexels na podstawie słów kluczowych."""
    if not PEXELS_API_KEY:
        return FALLBACK_IMG
    
    url = f"[https://api.pexels.com/v1/search?query=](https://api.pexels.com/v1/search?query=){urllib.parse.quote(query)}&per_page=1&orientation=landscape"
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


# --- ZBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:4]:
            if not is_recent(entry):
                continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 12:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

# Tryb ratunkowy - jeśli jest ekstremalnie mało newsów
if len(raw_articles) < TARGET_ITEMS:
    print("Zbyt mało nowości z 12h. Pobieram starsze by zapewnić wydanie...")
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                title = getattr(entry, "title", "").strip()
                link = clean_link(getattr(entry, "link", "#"))
                if title and len(title) > 12:
                    raw_articles.append({"title": title, "link": link})
        except: pass

print(f"Pobrano {len(raw_articles)} artykułów wejściowych.")

# --- WYKLUCZENIA Z ARCHIWUM ---
excluded_topics = []
archive_file = "archive.json"
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
            for session_key in sorted(archive_data.keys(), reverse=True)[:6]:
                session_content = archive_data.get(session_key)
                if isinstance(session_content, dict) and "items" in session_content:
                    for item in session_content.get("items", []):
                        if "title" in item:
                            clean = "".join(c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
                            excluded_topics.append(clean)
    except Exception:
        pass

news_file = "news.json"
if os.path.exists(news_file):
    try:
        with open(news_file, "r", encoding="utf-8") as f:
            news_data = json.load(f)
            if isinstance(news_data, dict) and "items" in news_data:
                for item in news_data.get("items", []):
                    if "title" in item:
                        clean = "".join(c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
                        excluded_topics.append(clean)
    except Exception:
        pass

# --- DEDUPLIKACJA ---
filtered_raw_articles = []
for art in raw_articles:
    art_clean = "".join(c for c in art["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
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

# Tryb ratunkowy deduplikacji
if len(filtered_raw_articles) < TARGET_ITEMS:
    print("Zbyt mało unikalnych newsów po odrzuceniu duplikatów. Wyłączam filtrację...")
    seen_links = {a['link'] for a in filtered_raw_articles}
    for art in raw_articles:
        if art['link'] not in seen_links:
            filtered_raw_articles.append(art)
            seen_links.add(art['link'])
        if len(filtered_raw_articles) >= 10:
            break

articles_for_ai = filtered_raw_articles[:15]

# --- PROMPT I WYSYŁKA DO AI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Wybierz DOKŁADNIE {TARGET_ITEMS} NAJMOCNIEJSZYCH tematów militarnych, obronnych lub geopolitycznych z poniższej listy.

Zasady:
- Tytuł: zwięzły, mocny, z jedną prostą emotikoną na początku (🚨 🛡️ ⚔️ 🚀). Bez flag.
- Summary: 1-2 zdania, konkretny fakt i co to oznacza.
- Comment: chłodna puenta strategiczna (1 zdanie).
- Category: WIELKIE LITERY (OBRONNOŚĆ, KONFLIKTY, GEOPOLITYKA, BEZPIECZEŃSTWO).
- image_query: 2-3 angielskie słowa kluczowe.
- link: dokładnie ten sam URL z wejścia.

Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów. Żadnego formatowania markdown (żadnego ```json ani ```).

Unikaj tematów podobnych do:
{json.dumps(excluded_topics[:12], ensure_ascii=False)}

Dane wejściowe:
{json.dumps(articles_for_ai, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
    )
    
    text_res = response.text.strip()
    
    # Ręczne czyszczenie, dokładnie tak samo jak działa w głównym news.json
    if text_res.startswith("```json"):
        text_res = text_res[7:-3].strip()
    elif text_res.startswith("```"):
        text_res = text_res[3:-3].strip()
        
    items = json.loads(text_res)
    
except Exception as e:
    print(f"Błąd AI (Tryb awaryjny): {e}")
    traceback.print_exc()

# Gwarancja powrotu 3 elementów
if len(items) < TARGET_ITEMS:
    print(f"Ostrzeżenie: Model zwrócił {len(items)} elementów. Uzupełniam braki systemowo.")
    existing_links = {i.get('link') for i in items if isinstance(i, dict)}
    
    for art in articles_for_ai:
        if art['link'] not in existing_links:
            items.append({
                "category": "PILNE",
                "title": f"🚨 {art['title']}",
                "summary": "Najnowsze raporty agencji prasowych informują o rozwoju sytuacji w tym obszarze.",
                "comment": "Trwa analizowanie konsekwencji strategicznych.",
                "image_query": "breaking news military",
                "link": art["link"]
            })
            existing_links.add(art['link'])
        if len(items) >= TARGET_ITEMS:
            break

# Przycinamy tablicę do dokładnie TARGET_ITEMS
items = items[:TARGET_ITEMS]

print(f"Wybrano {len(items)} pozycji flash – OK")

# --- ZDJĘCIA ZE ŹRÓDEŁ ---
print("Pobieranie linków do zdjęć...")
for item in items:
    # 1. Próbujemy pobrać zdjęcie oryginalne z serwisu (najbardziej wiarygodne dla newsów militarnych)
    img_url = fetch_article_image(item.get("link", ""))
    
    # 2. Jeśli nie ma, pobieramy stockowe z Pexels na bazie zapytania AI
    if not img_url:
        q = item.get("image_query", "military conflict")
        img_url = fetch_pexels_image_url(q)
        
    item["image_url"] = img_url

# --- ZAPIS ---
now_pl = datetime.now(pl_tz)
date_pretty = f"{now_pl.day} {POLISH_MONTHS[now_pl.month]} {now_pl.year}"
time_pretty = now_pl.strftime("%H:%M")
timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

with open("fast.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"Zapisano {len(items)} twarde newsy do fast.json o {time_pretty}.")
