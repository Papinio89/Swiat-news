import json
import os
import re
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
FALLBACK_IMG = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=800&auto=format&fit=crop"

RSS_URLS = [
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=world+news+geopolitics+military&hl=en-US&gl=US&ceid=US:en",
    "https://defence24.pl/rss",
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=markets&sort=date",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://arstechnica.com/feed/",
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 24
MIN_ITEMS = 8


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


def validate_items(items: list) -> list:
    required = {"category", "title", "hook", "summary", "comment", "question", "image_query", "link"}
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not required.issubset(item.keys()):
            continue

        title = str(item.get("title", "")).strip()
        hook = str(item.get("hook", "")).strip()
        summary = str(item.get("summary", "")).strip()
        comment = str(item.get("comment", "")).strip()
        question = str(item.get("question", "")).strip()
        category = str(item.get("category", "AKTUALNOŚCI")).strip().upper()
        image_query = str(item.get("image_query", "world news")).strip()
        link = clean_link(str(item.get("link", "#")))

        if len(title) < 10 or len(summary) < 25:
            continue

        valid.append({
            "category": category,
            "title": title,
            "hook": hook,
            "summary": summary,
            "comment": comment,
            "question": question,
            "image_query": image_query,
            "link": link
        })
    return valid


def fetch_pexels_image_url(query: str, retries: int = 2) -> str:
    if not PEXELS_API_KEY:
        return FALLBACK_IMG
    for attempt in range(retries + 1):
        try:
            url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
            req = urllib.request.Request(url, headers={
                "Authorization": PEXELS_API_KEY,
                "User-Agent": "SwiatWMinute-Bot/1.0"
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    photos = data.get("photos", [])
                    if photos:
                        src = photos[0].get("src", {})
                        return src.get("large") or src.get("medium") or FALLBACK_IMG
        except Exception as ex:
            if attempt == retries:
                print(f"Błąd Pexels dla '{query}': {ex}")
            else:
                import time
                time.sleep(1)
    return FALLBACK_IMG


def fetch_article_image(url: str) -> str | None:
    """Pobiera og:image / twitter:image ze strony artykułu (do Threads / IG Top 3)."""
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
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
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
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http"):
                    return img
    except Exception as ex:
        print(f"  brak og:image ({url[:55]}…): {ex}")
    return None


# --- ZBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:6]:
            if not is_recent(entry):
                continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 15:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

print(f"Pobrano {len(raw_articles)} świeżych artykułów (max {MAX_AGE_HOURS}h)")

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
                if ratio > 0.40:
                    is_duplicate = True
                    break
    if not is_duplicate:
        filtered_raw_articles.append(art)

if len(filtered_raw_articles) < 6:
    filtered_raw_articles = raw_articles

print(f"Po deduplikacji: {len(filtered_raw_articles)} artykułów")

# --- PROMPT WIRALOWY ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś redaktorem naczelnym topowego formatu informacyjnego w social mediach (Instagram/Threads). 
Twoje posty zdobywają dziesiątki tysięcy odsłon, ponieważ piszesz obrazowo, unikasz nudnego żargonu i natychmiast pokazujesz czytelnikowi realną stawkę wydarzenia.

Zadanie: Na podstawie poniższych artykułów stwórz 10-14 NAJWAŻNIEJSZYCH wiadomości w języku polskim w formacie JSON.

ZASADY WIRALOWEGO COPYWRITINGU:
1. ZAKAZ KORPO-MOWY I OGÓLNIKÓW:
   - Zamiast „kwestie instytucjonalne”, „dynamika makroekonomiczna”, „weryfikacja struktur” -> pisz o portfelach, cenach paliw, blackoutach, rakietach, granicach, czołgach i paraliżu lotnisk.
   - Każdy wpis MUSI odnosić się dokładnie do faktów z danego nagłówka. Zakaz powtarzania tych samych formułek.
2. ZASADA BEZPOŚREDNIEJ STAWKI:
   - Pokaż, co to oznacza: czy wzrosną ceny, czy grozi nam eskalacja, czy Polska zyskuje przewagę, czy to tylko polityczny teatr.
3. AUTORYTET I KONTRAST:
   - Wskazuj konkret: „Piloci ostrzegają”, „Pentagon naciska”, „Główny ekonomista banku bije na alarm”.
   - Stosuj obalanie mitów: „Wszyscy patrzyli na X, podczas gdy realne zagrożenie uderzyło w Y”.
4. INDYWIDUALNE PYTANIE:
   - Każdy news musi mieć inne, precyzyjne pytanie do dyskusji pod dany temat (do komentarzy).

PROPORCJE (twarde reguły):
- Minimum 80% = Bezpieczeństwo, obronność, Polska, surowce, rynki finansowe, twarda geopolityka
- Maksymalnie 2 pozycje TECHNOLOGIE / AI (tylko przełomy militarne, wielkie pieniądze lub realne zagrożenia)
- ZERO plotek, celebrytów i nudnych komunikatów bez wpływu na rzeczywistość

STRUKTURA JSON (Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów):
[
  {{
    "category": "GEOPOLITYKA / OBRONNOŚĆ / RYNKI I GOSPODARKA / POLSKA / TECHNOLOGIE / AI",
    "title": "[Emotikona] [Konkretny, chwytliwy nagłówek do 60 znaków]",
    "hook": "1 zdanie uderzające w sedno – kontrast lub obalenie mitu.",
    "summary": "2 zwięzłe zdania faktów operujące obrazowymi rzeczownikami.",
    "comment": "1 mocne, chłodne zdanie wniosku strategicznego (pointa).",
    "question": "1 unikalne, prowokujące do dyskusji pytanie pod dany temat.",
    "image_query": "2-3 konkretne słowa kluczowe po angielsku do Pexels (np. 'tank field maneuver', 'oil refinery fire night')",
    "link": "dokładnie URL artykułu"
  }}
]

Unikaj tematów z archiwum:
{json.dumps(previous_topics[:25], ensure_ascii=False)}

Dane wejściowe:
{json.dumps(filtered_raw_articles, ensure_ascii=False)}
"""

# --- GENEROWANIE ---
items = []
try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.35,
        ),
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
    else:
        raw_items = []
        
    items = validate_items(raw_items)
except Exception as e:
    print(f"Błąd AI: {e}")
    items = []

# Fallback awaryjny – bez powtarzania sztampowych szablonów
if len(items) < MIN_ITEMS:
    existing_links = {i.get("link") for i in items}
    for art in filtered_raw_articles:
        if art["link"] not in existing_links and art["link"] != "#":
            clean_t = art.get("title", "Wydarzenie na arenie międzynarodowej")
            items.append({
                "category": "AKTUALNOŚCI",
                "title": f"📌 {clean_t[:55]}",
                "hook": f"Kluczowe doniesienia agencyjne w sprawie: {clean_t[:40]}.",
                "summary": "Najnowsze ustalenia wskazują na istotną zmianę sytuacji w tym obszarze. Przedstawiciele branży i rządy analizują potencjalne konsekwencje.",
                "comment": "Decyzje podejmowane w tym segmencie bezpośrednio przełożą się na równowagę sił w kolejnych miesiącach.",
                "question": "Jak oceniasz potencjalne skutki tych doniesień?",
                "image_query": "world news global politics",
                "link": art["link"]
            })
            existing_links.add(art["link"])
            if len(items) >= 12:
                break

if items:
    cats = Counter([item["category"] for item in items])
    print("Rozkład kategorii:")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

print(f"Wygenerowano {len(items)} pozycji – OK")

# --- ZDJĘCIA: Pexels (karuzela) + og:image (Threads / IG Top 3) ---
print("Pobieranie zdjęć: Pexels + źródła artykułów...")
source_ok = 0
for item in items:
    q = item.get("image_query", "world news")
    item["image_url"] = fetch_pexels_image_url(q)

    article_img = fetch_article_image(item.get("link", ""))
    if article_img:
        item["source_image_url"] = article_img
        source_ok += 1
    else:
        item["source_image_url"] = item["image_url"]

print(f"Zdjęcia ze źródeł artykułów: {source_ok}/{len(items)} (reszta = Pexels fallback)")

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
with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

raw_feed_output = {
    "date": date_pretty,
    "time": time_pretty,
    "count": len(filtered_raw_articles),
    "items": filtered_raw_articles
}
with open("raw_feed.json", "w", encoding="utf-8") as f:
    json.dump(raw_feed_output, f, ensure_ascii=False, indent=2)

print(f"Zakończono pomyślnie. Zapisano {len(items)} newsów.")
