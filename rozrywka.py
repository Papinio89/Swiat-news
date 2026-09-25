import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from time import mktime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs
from collections import Counter

import feedparser
from google import genai
from google.genai import types

pl_tz = ZoneInfo("Europe/Warsaw")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "N9lZEHVVxzeo70Ool0sBLSnzpZAvgUxeRk7niJKr5pQdMRkQyIouz2QQ")
FALLBACK_IMG = "https://images.unsplash.com/photo-1534447677768-be436bb09401?q=80&w=1000&auto=format&fit=crop"

# --- ZWERYFIKOWANE I DZIAŁAJĄCE ŹRÓDŁA RSS ---
RSS_URLS = [
    # 1. POLSKIE BIEŻĄCE ODDITIES / CIEKAWOSTKI (Google News PL)
    "https://news.google.com/rss/search?q=ciekawostki+zwierz%C4%99ta+rekord+zoo&hl=pl&gl=PL&ceid=PL:pl",
    "https://news.google.com/rss/search?q=kuriozum+absurd+wpadka&hl=pl&gl=PL&ceid=PL:pl",
    
    # 2. GLOBALNE BIEŻĄCE ODD NEWS (bardzo świeże zdarzenia z ostatnich 24-48h)
    "https://www.upi.com/rss/Odd_News/",
    "https://news.google.com/rss/search?q=when:2d+topic:weird+news&hl=en-US&gl=US&ceid=US:en",
    "https://www.huffpost.com/section/weird-news/feed",
    
    # 3. NAUKA / HISTORIA (stałe smaczki)
    "https://www.mentalfloss.com/rss.xml",
    "https://www.sciencenews.org/topic/weird-science/feed"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 72
MIN_ITEMS = 6


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\U000E0020-\U000E007F]', '', text)
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("Cf", "Cc", "Cn") or ch in "\n\t"
    )
    text = re.sub(r'U\+[0-9A-Fa-f]{4,6}', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_link(url: str) -> str:
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
        with urllib.request.urlopen(req, timeout=5) as resp:
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
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http") and not img.endswith(".svg"):
                    return img
    except Exception:
        pass
    return None


def fetch_pexels_image_url(query: str, retries: int = 1) -> str:
    if not PEXELS_API_KEY:
        return FALLBACK_IMG
    for attempt in range(retries + 1):
        try:
            url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
            req = urllib.request.Request(url, headers={
                "Authorization": PEXELS_API_KEY,
                "User-Agent": "SwiatWMinute-Bot/1.0"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    photos = data.get("photos", [])
                    if photos:
                        src = photos[0].get("src", {})
                        return src.get("large") or src.get("medium") or FALLBACK_IMG
        except Exception:
            pass
    return FALLBACK_IMG


def validate_items(items: list) -> list:
    required = {"category", "title", "summary", "comment", "image_query", "link"}
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not required.issubset(item.keys()):
            continue

        title = sanitize_text(str(item.get("title", "")))
        summary = sanitize_text(str(item.get("summary", "")))
        comment = sanitize_text(str(item.get("comment", "")))
        category = sanitize_text(str(item.get("category", "ABSURDY ŚWIATA"))).upper()
        image_query = sanitize_text(str(item.get("image_query", "funny weird fact")))
        link = clean_link(str(item.get("link", "#")))

        if len(title) < 10 or len(summary) < 25:
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


# --- POBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:8]:
            if not is_recent(entry):
                continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 12:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

print(f"Pobrano {len(raw_articles)} surowych artykułów rozrywkowych.")

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

previous_topics = []
sorted_sessions = sorted(archive_data.keys(), reverse=True)[:10]
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
                if ratio > 0.40:
                    is_duplicate = True
                    break
    if not is_duplicate:
        filtered_raw_articles.append(art)

if len(filtered_raw_articles) < 6:
    filtered_raw_articles = raw_articles

print(f"Po deduplikacji: {len(filtered_raw_articles)} artykułów przekazanych do AI")

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś redaktorem rozrywkowym formatu „Świat w Minucie” (Instagram/Threads). Stwórz 8-10 absolutnie fascynujących, zabawnych i viralowych ciekawostek po polsku.

PODZIAŁ TEMATYCZNY (50/50):
1. DOKŁADNIE 50% MUSI dotyczyć BIEŻĄCYCH ODDITIES Z OSTATNICH DNI (wpadki ludzi, zoo, ucieczki zwierzaków, dziwne rekordy, kurioza lokalne).
   - Kategoria: BIEŻĄCE ABSURDY lub ZWIERZAKI.
2. POZOSTAŁE 50% to ponadczasowe smaczki: szalona historia, sekrety popkultury, dziwna nauka, literackie anomalie.
   - Kategoria: SZALONA HISTORIA, BEKA Z NAUKI lub POPKULTURA.

ZASADY PISANIA DLA PÓL:
- "title": [Emotikona] + [Krótki, chwytliwy nagłówek do 60 znaków].
- "summary": 2-3 zdania pełne mięsa, liczb i komicznego absurdu.
- "comment": 1 ostre, przezabawne zdanie puenty w stylu ciętego stand-upu (ZAKAZ powtarzania tego, co w summary!).
- "image_query": 2-3 konkretne słowa kluczowe po angielsku pod Pexels.
- "link": Dokładnie URL artykułu z wejścia.

UNIKAJ TYCH TEMATÓW Z ARCHIWUM:
{json.dumps(previous_topics[:30], ensure_ascii=False)}

Zwróć CZYSTĄ tablicę JSON obiektów.

Dane wejściowe:
{json.dumps(filtered_raw_articles[:30], ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.45,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            ]
        )
    )
    text_res = response.text.strip()
    if text_res.startswith("```json"):
        text_res = text_res[7:]
    if text_res.startswith("```"):
        text_res = text_res[3:]
    if text_res.endswith("```"):
        text_res = text_res[:-3]
    text_res = text_res.strip()

    parsed = json.loads(text_res)
    if isinstance(parsed, list):
        raw_items = parsed
    elif isinstance(parsed, dict) and "items" in parsed:
        raw_items = parsed["items"]
    elif isinstance(parsed, dict):
        raw_items = list(parsed.values())[0] if parsed else []
    else:
        raw_items = []

    items = validate_items(raw_items)
except Exception as e:
    print(f"Błąd AI podczas parsowania: {e}")
    items = []

# GWARANCJA: Jeśli AI zawiedzie, generujemy bezpieczny fallback z pobranych newsów
if len(items) < MIN_ITEMS:
    print(f"Aktywacja fallbacku – uzupełnianie do minimum {MIN_ITEMS} pozycji...")
    for art in filtered_raw_articles:
        if len(items) >= MIN_ITEMS:
            break
        items.append({
            "category": "BIEŻĄCE ABSURDY",
            "title": f"🐾 {art['title'][:55]}",
            "summary": "Nietypowe i zaskakujące zdarzenie z ostatnich godzin, które przyciągnęło uwagę mediów na całym świecie.",
            "comment": "Rzeczywistość po raz kolejny udowadnia, że najdziwniejsze scenariusze pisze samo życie.",
            "image_query": "weird funny news",
            "link": art["link"]
        })

if items:
    cats = Counter([item["category"] for item in items])
    print("Rozkład kategorii (rozrywka):")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

print(f"Łącznie gotowych pozycji rozrywkowych: {len(items)}")

# --- DOBIERANIE ZDJĘĆ ---
print("Dobieranie zdjęć...")
source_ok = 0
for item in items:
    url = item.get("link", "")
    q = item.get("image_query", "funny weird fact")
    
    article_img = fetch_article_image(url)
    if article_img:
        item["source_image_url"] = article_img
        item["image_url"] = article_img
        source_ok += 1
    else:
        stock_img = fetch_pexels_image_url(q)
        item["source_image_url"] = stock_img
        item["image_url"] = stock_img

print(f"Zdjęcia z oryginalnych artykułów: {source_ok}/{len(items)}")

date_pretty = f"{now_pl.day} {POLISH_MONTHS[now_pl.month]} {now_pl.year}"
time_pretty = now_pl.strftime("%H:%M")
timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

with open("rozrywka.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

if items:
    archive_data[session_fixed_key] = output_data
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"Zapisano {len(items)} ciekawostek do rozrywka.json.")
