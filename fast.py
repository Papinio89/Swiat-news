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

FALLBACK_IMG = "https://images.unsplash.com/photo-1579912437766-7896dfc2d008?q=80&w=1200&auto=format&fit=crop"

RSS_URLS = [
    # --- POLSKIE / REGIONALNE BEZPIECZEŃSTWO ---
    "https://defence24.pl/rss",
    "https://news.google.com/rss/search?q=wojsko+bezpiecze%C5%84stwo+granica+obronno%C5%9B%C4%87&hl=pl&gl=PL&ceid=PL:pl",

    # --- GLOBALNY SEKTOR OBRONNY / KONFLIKTY ZBROJNE ---
    "https://www.twz.com/feed",
    "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
    "https://news.usni.org/feed",

    # --- GEOPOLITYKA / KONFLIKTY ŚWIATOWE ---
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

def validate_items(items: list) -> list:
    required = {"category", "title", "summary", "comment", "image_query", "link"}
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        
        title = sanitize_text(str(item.get("title", "")))
        summary = sanitize_text(str(item.get("summary", "")))
        comment = sanitize_text(str(item.get("comment", "")))
        category = sanitize_text(str(item.get("category", "PILNE"))).upper()
        image_query = sanitize_text(str(item.get("image_query", "military defense")))
        link = clean_link(str(item.get("link", "#")))

        # Bardzo łagodna walidacja, aby nie odrzucać dobrych tekstów AI
        if len(title) < 5 or len(summary) < 10:
            continue

        valid.append({
            "category": category,
            "title": title,
            "summary": summary,
            "comment": comment,
            "image_query": image_query,
            "link": link
        })
        if len(valid) >= TARGET_ITEMS:
            break
    return valid

def fetch_article_image(url: str) -> str | None:
    if not url or url == "#" or "news.google.com" in url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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

# Mechanizm ratunkowy: jeśli wyjątkowo nic nie ma z ostatnich 12h, dobieramy niezależnie od czasu
if len(raw_articles) < TARGET_ITEMS:
    print("Brak wystarczającej liczby newsów z ostatnich 12h. Pobieram najświeższe bez limitu czasu...")
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                title = getattr(entry, "title", "").strip()
                link = clean_link(getattr(entry, "link", "#"))
                if title and len(title) > 12:
                    raw_articles.append({"title": title, "link": link})
        except: pass

print(f"Pobrano {len(raw_articles)} artykułów wejściowych.")

# --- WYKLUCZENIA Z ARCHIWUM I NEWS.JSON ---
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

# Mechanizm ratunkowy dla deduplikacji
if len(filtered_raw_articles) < TARGET_ITEMS:
    print("Zbyt mało unikalnych newsów. Dobieram pomijając duplikaty, aby wygenerować pełne wydanie.")
    seen_links = {a['link'] for a in filtered_raw_articles}
    for art in raw_articles:
        if art['link'] not in seen_links:
            filtered_raw_articles.append(art)
            seen_links.add(art['link'])
        if len(filtered_raw_articles) >= 10:
            break

articles_for_ai = filtered_raw_articles[:15]

# --- PROMPT ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Twoim zadaniem jest wybranie DOKŁADNIE {TARGET_ITEMS} najważniejszych, najgorętszych tematów militarnych, obronnych lub geopolitycznych.

Zasady bezwzględne:
- Tytuł ("title"): zwięzły, chwytliwy nagłówek z jedną prostą emotikoną na początku (np. 🚨, 🛡️, ⚔️, 🚀, 🛑). Ma przyciągać wzrok.
- Opis ("summary"): 1-2 pełne zdania wyjaśniające najważniejsze fakty.
- Komentarz ("comment"): 1 analityczne, chłodne zdanie oceniające sytuację.
- Kategoria ("category"): np. OBRONNOŚĆ, KONFLIKTY, GEOPOLITYKA, BEZPIECZEŃSTWO.
- Obraz ("image_query"): 2-3 słowa po angielsku dla bazy zdjęć.
- Link ("link"): dokładnie ten sam z wejścia.

Zwróć DOKŁADNIE {TARGET_ITEMS} wpisów w formacie tablicy JSON.
Dane wejściowe:
{json.dumps(articles_for_ai, ensure_ascii=False)}
"""

# --- GENEROWANIE ---
items = []
try:
    # KLUCZOWE: Wymuszenie czystego JSON (aby nie generowało pustych opisów i błędów parsowania)
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "max_output_tokens": 2048,
            "temperature": 0.3,
        }
    )
    text_res = response.text.strip()
    
    raw_items = json.loads(text_res)
    items = validate_items(raw_items)

except Exception as e:
    print(f"Błąd AI: {e}")
    traceback.print_exc()

# Gwarancja posiadania 3 elementów, nawet jeśli AI padnie (co nie powinno się już zdarzyć)
if len(items) < TARGET_ITEMS:
    print("Ostrzeżenie: Model zwrócił za mało elementów. Uzupełniam do 3 pozycji.")
    existing_links = {i['link'] for i in items}
    for art in articles_for_ai:
        if art['link'] not in existing_links:
            items.append({
                "category": "PILNE",
                "title": f"🚨 {art['title']}",
                "summary": "Najnowsze raporty agencji prasowych informują o rozwoju sytuacji w tym obszarze.",
                "comment": "Trwa gromadzenie szczegółowych informacji.",
                "image_query": "breaking news military",
                "link": art["link"]
            })
        if len(items) >= TARGET_ITEMS:
            break

# --- ZDJĘCIA ZE ŹRÓDEŁ ---
print("Pobieranie zdjęć ze źródeł artykułów...")
source_ok = 0
for item in items:
    article_img = fetch_article_image(item.get("link", ""))
    if article_img:
        item["source_image_url"] = article_img
        item["image_url"] = article_img
        source_ok += 1
    else:
        item["source_image_url"] = FALLBACK_IMG
        item["image_url"] = FALLBACK_IMG

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

print(f"Zapisano dokładnie {len(items)} newsów do fast.json o {time_pretty}.")
