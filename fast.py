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
from pydantic import BaseModel, Field

import feedparser
from google import genai
from google.genai import types

pl_tz = ZoneInfo("Europe/Warsaw")

# Konfiguracja obrazów
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "N9lZEHVVxzeo70Ool0sBLSnzpZAvgUxeRk7niJKr5pQdMRkQyIouz2QQ")
FALLBACK_IMG = "https://images.unsplash.com/photo-1579912437766-7896dfc2d008?q=80&w=1200&auto=format&fit=crop"

RSS_URLS = [
    "https://defence24.pl/rss",
    "https://news.google.com/rss/search?q=wojsko+bezpiecze%C5%84stwo+granica+obronno%C5%9B%C4%87&hl=pl&gl=PL&ceid=PL:pl",
    "https://www.twz.com/feed",
    "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
    "https://news.usni.org/feed",
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=military+strike+missile+war+tensions&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=nato+russia+china+taiwan+defense&hl=en-US&gl=US&ceid=US:en"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 12
TARGET_ITEMS = 3

# --- STRUKTURA DANYCH DLA AI (PYDANTIC) ---
class NewsItem(BaseModel):
    category: str = Field(description="Kategoria artykułu: np. OBRONNOŚĆ, KONFLIKTY, GEOPOLITYKA.")
    title: str = Field(description="Krótki, merytoryczny i chwytliwy nagłówek z emotikoną na początku (np. 🚨, 🛡️, ⚔️, 🚀).")
    summary: str = Field(description="Zwięzły opis sedna wydarzenia w 1-2 krótkich zdaniach.")
    comment: str = Field(description="Bardzo krótki, chłodny komentarz strategiczny - DOKŁADNIE 1 ZWIĘZŁE ZDANIE (pointa).")
    image_query: str = Field(description="2-3 precyzyjne angielskie słowa kluczowe do bazy zdjęć Pexels np. 'stealth fighter military'.")
    link: str = Field(description="Dokładnie ten sam URL wejściowy przypisany do artykułu.")

class NewsOutput(BaseModel):
    items: list[NewsItem]


def clean_link(url: str) -> str:
    if not url or url == "#": return "#"
    try:
        tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "at_medium", "at_campaign", "fbclid", "gclid"}
        parsed = urlparse(url)
        if parsed.query:
            qs = parse_qs(parsed.query)
            clean_qs = {k: v[0] for k, v in qs.items() if k not in tracking_params}
            if clean_qs:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urllib.parse.urlencode(clean_qs)}"
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return url
    except Exception:
        return url

def is_recent(entry) -> bool:
    published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not published: return True
    try:
        pub_dt = datetime.fromtimestamp(mktime(published), tz=pl_tz)
        age = datetime.now(pl_tz) - pub_dt
        return age <= timedelta(hours=MAX_AGE_HOURS)
    except Exception:
        return True

def fetch_article_image(url: str) -> str | None:
    """Krok 1: Próba pobrania oryginalnego zdjęcia ze strony artykułu (og:image / twitter:image)."""
    if not url or url == "#" or "news.google.com" in url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "pl,en-US;q=0.9,en;q=0.8"
            }
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']'
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                img = m.group(1).strip()
                if img.startswith("//"): img = "https:" + img
                if img.startswith("http") and not img.endswith(".svg"):
                    return img
    except Exception as ex:
        print(f"  [Foto-Scraper] Brak og:image dla {url[:45]}... ({ex})")
    return None

def fetch_pexels_image_url(query: str) -> str | None:
    """Krok 2: Fallback do Pexels API, gdy strona artykułu nie ma og:image."""
    if not PEXELS_API_KEY:
        return None
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
                    return src.get("large") or src.get("medium")
    except Exception as ex:
        print(f"  [Pexels] Błąd dla '{query}': {ex}")
    return None


# --- ZBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:4]:
            if not is_recent(entry): continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 6:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

if len(raw_articles) < TARGET_ITEMS:
    print("Zbyt mało nowości z 6h. Pobieram starsze by zapewnić wydanie...")
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                title = getattr(entry, "title", "").strip()
                link = clean_link(getattr(entry, "link", "#"))
                if title and len(title) > 6:
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
            for session_key in sorted(archive_data.keys(), reverse=True)[:5]:
                session_content = archive_data.get(session_key)
                if isinstance(session_content, dict) and "items" in session_content:
                    for item in session_content.get("items", []):
                        if "title" in item:
                            clean = "".join(c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
                            excluded_topics.append(clean)
    except: pass

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
    except: pass

# --- DEDUPLIKACJA ---
filtered_raw_articles = []
seen_titles = set()
for art in raw_articles:
    t = "".join(c for c in art["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
    
    is_duplicate = False
    art_words = set(t.split())
    if len(art_words) > 2:
        for prev in excluded_topics:
            prev_words = set(prev.split())
            if len(prev_words) > 2:
                common = art_words.intersection(prev_words)
                if len(common) / min(len(art_words), len(prev_words)) > 0.35:
                    is_duplicate = True
                    break

    if not is_duplicate and t not in seen_titles:
        filtered_raw_articles.append(art)
        seen_titles.add(t)

if len(filtered_raw_articles) < TARGET_ITEMS:
    filtered_raw_articles = raw_articles

articles_for_ai = filtered_raw_articles[:15]

# --- PROMPT AI Z OPTYMALIZACJĄ DŁUGOŚCI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś analitykiem militarnym przygotowującym zwięzły format FLASH REPORT.
Wybierz i przetłumacz na język polski DOKŁADNIE {TARGET_ITEMS} NAJWAŻNIEJSZE tematy z listy.

ZASADY FORMATOWANIA:
- Tytuł: mocny, zwięzły, z pojedynczą emotikoną (🚨, 🛡️, ⚔️, 🚀).
- Summary: 1-2 zwięzłe zdania faktograficzne.
- Comment: MAKSYMALNIE 1 KRÓTKIE, CHŁODNE ZDANIE STRATEGICZNE. Bezwzględny zakaz długich wywodów. Pointa w jednym zdaniu.
- image_query: 2-3 słowa po angielsku.
- link: dokładnie URL z danego artykułu.

Unikaj tematów podobnych do: {json.dumps(excluded_topics[:10], ensure_ascii=False)}

Dane wejściowe:
{json.dumps(articles_for_ai, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=NewsOutput,
            temperature=0.2,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            ]
        ),
    )
    
    raw_data = json.loads(response.text)
    items = raw_data.get("items", [])
    
except Exception as e:
    print(f"Błąd AI: {e}")
    traceback.print_exc()

# Blok awaryjny (uzupełnienie, jeśli model zwrócił za mało)
while len(items) < TARGET_ITEMS:
    existing_links = {i.get('link') for i in items if isinstance(i, dict)}
    added = False
    for art in articles_for_ai:
        if art['link'] not in existing_links and art['link'] != "#":
            items.append({
                "category": "PILNE",
                "title": f"🚨 {art.get('title', 'Wiadomość z agencji prasowych')}",
                "summary": "Najnowsze doniesienia wskazują na dynamiczny rozwój wydarzeń w tym rejonie.",
                "comment": "Sytuacja wymaga dalszego monitorowania.",
                "image_query": "military conflict",
                "link": art.get("link", "#")
            })
            existing_links.add(art['link'])
            added = True
            if len(items) >= TARGET_ITEMS: break
    if not added:
        break

items = items[:TARGET_ITEMS]

# --- KASKADOWE POBIERANIE ZDJĘĆ ---
print("Dobieranie zdjęć (Artykuł -> Pexels -> Fallback)...")
for item in items:
    url = item.get("link", "")
    q = item.get("image_query", "military")
    
    # 1. Zdjęcie z oryginalnego artykułu
    selected_img = fetch_article_image(url)
    
    # 2. Jeśli brak, zapytanie do Pexels
    if not selected_img:
        selected_img = fetch_pexels_image_url(q)
        
    # 3. Jeśli Pexels zawiedzie, fallback
    if not selected_img:
        selected_img = FALLBACK_IMG
        
    item["image_url"] = selected_img
    item["source_image_url"] = selected_img

# --- ZAPIS ---
now_pl = datetime.now(pl_tz)
output_data = {
    "date": f"{now_pl.day} {POLISH_MONTHS[now_pl.month]} {now_pl.year}",
    "time": now_pl.strftime("%H:%M"),
    "timestamp": now_pl.strftime("%Y-%m-%d_%H:%M"),
    "items": items
}

with open("fast.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print(f"Zakończono. Pomyślnie zapisano {len(items)} pozycje w fast.json.")
