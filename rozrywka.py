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

pl_tz = ZoneInfo("Europe/Warsaw")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "N9lZEHVVxzeo70Ool0sBLSnzpZAvgUxeRk7niJKr5pQdMRkQyIouz2QQ")
FALLBACK_IMG = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=800&auto=format&fit=crop"

RSS_URLS = [
    "https://news.google.com/rss/search?q=weird+animal+facts+quirky+funny+history+bizarre&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=dziwne+fakty+śmieszne+ciekawostki+absurdalne+zwierzęta&hl=pl&gl=PL&ceid=PL:pl",
    "https://news.google.com/rss/search?q=dziwna+historia+nietypowe+rekordy+humor&hl=pl&gl=PL&ceid=PL:pl",
    "https://www.huffpost.com/section/weird-news/feed",
    "https://www.sciencenews.org/topic/weird-science/feed",
    "https://www.mentalfloss.com/rss.xml"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 24
MIN_ITEMS = 6


def sanitize_text(text: str) -> str:
    """Usuwa problematyczne znaki Unicode (tag characters, bidi, ukryte kontrolne)."""
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
        category = sanitize_text(str(item.get("category", "ABSRUDY ŚWIATA"))).upper()
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


raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:6]:
            if not is_recent(entry):
                continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 12:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

print(f"Pobrano {len(raw_articles)} świeżych artykułów rozrywkowych (max {MAX_AGE_HOURS}h)")

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
                if ratio > 0.35:
                    is_duplicate = True
                    break
    if not is_duplicate:
        filtered_raw_articles.append(art)

if len(filtered_raw_articles) < 5:
    filtered_raw_articles = raw_articles

print(f"Po deduplikacji: {len(filtered_raw_articles)} artykułów")

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz czysto rozrywkową, lekką i ekstremalnie zabawną listę 8-10 ciekawostek (przetłumacz i sformatuj na język polski).

WYMAGANA STRUKTURA:
- Skup się WYŁĄCZNIE na: absurdalnych faktach, dziwnych zachowaniach zwierząt, szalonej historii, dziwnym jedzeniu/piciu oraz zakręconych rekordach świata.
- Kategoryczny zakaz: poważne badania naukowe, psychologia, socjologia, sztuka, recenzje książek, rocznice miast/architektury.
- Ma być luźno, śmiesznie i czysto rozrywkowo.

Każdy obiekt musi zawierać dokładnie te klucze:
- "category": WIELKIMI LITERAMI (np. "ZWIERZAKI", "ABSRUDY ŚWIATA", "SZALONA HISTORIA", "BEKA Z NAUKI")
- "title": krótki, chwytliwy i zabawny nagłówek z jedną prostą emotikoną na początku (unikaj flag państwowych i regionalnych)
- "summary": konkretny, zabawny opis w 1-2 zdaniach
- "comment": dowcipny, sarkastyczny lub ironiczny komentarz
- "image_query": 2-4 słowa kluczowe po angielsku
- "link": dokładnie ten sam URL z wejścia

Unikaj tematów podobnych do archiwum:
{json.dumps(previous_topics[:25], ensure_ascii=False)}

Zwróć WYŁĄCZNIE czystą tablicę JSON. Żadnego markdown, żadnych ```.

Dane wejściowe:
{json.dumps(filtered_raw_articles, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
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
        "category": "ZWIERZAKI",
        "title": f"🦦 {art['title']}",
        "summary": "Nietypowy i szalony fakt z życia przyrody.",
        "comment": "Natura naprawdę ma poczucie humoru!",
        "image_query": "funny cute animal",
        "link": art["link"]
    } for art in filtered_raw_articles[:10]]

if items:
    cats = Counter([item["category"] for item in items])
    print("Rozkład kategorii (rozrywka):")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

if len(items) < MIN_ITEMS:
    print(f"UWAGA: Tylko {len(items)} pozycji rozrywkowych (minimum {MIN_ITEMS}).")
else:
    print(f"Wygenerowano {len(items)} pozycji rozrywkowych – OK")

print("Pobieranie linków do zdjęć z Pexels...")
for item in items:
    q = item.get("image_query", "funny weird fact")
    item["image_url"] = fetch_pexels_image_url(q)

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

archive_data[session_fixed_key] = output_data
with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"Zakończono pomyślnie. Zapisano {len(items)} ciekawostek rozrywkowych.")
