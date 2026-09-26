import json
import os
import re
import urllib.parse
import urllib.request
import traceback
from datetime import datetime, timedelta
from time import mktime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

import feedparser
from google import genai
from google.genai import types

pl_tz = ZoneInfo("Europe/Warsaw")

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


def clean_link(url: str) -> str:
    if not url or url == "#":
        return "#"
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
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http") and not img.endswith(".svg"):
                    return img
    except Exception as ex:
        print(f"  [Foto-Scraper] Brak og:image dla {url[:45]}... ({ex})")
    return None


def fetch_pexels_image_url(query: str) -> str | None:
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


def validate_items(items: list) -> list:
    required = {"category", "title", "hook", "summary", "comment", "threads_post", "question", "image_query", "link"}
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
        threads_post = str(item.get("threads_post", "")).strip()
        question = str(item.get("question", "")).strip()
        category = str(item.get("category", "OBRONNOŚĆ")).strip().upper()
        image_query = str(item.get("image_query", "military")).strip()
        link = clean_link(str(item.get("link", "#")))

        if len(title) < 10 or len(summary) < 20 or len(threads_post) < 80:
            continue

        valid.append({
            "category": category,
            "title": title,
            "hook": hook,
            "summary": summary,
            "comment": comment,
            "threads_post": threads_post,
            "question": question,
            "image_query": image_query,
            "link": link
        })
    return valid


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
            if title and len(title) > 6:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

if len(raw_articles) < TARGET_ITEMS:
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                title = getattr(entry, "title", "").strip()
                link = clean_link(getattr(entry, "link", "#"))
                if title and len(title) > 6:
                    raw_articles.append({"title": title, "link": link})
        except:
            pass

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
    except:
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
    except:
        pass

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

# --- PROMPT AI Z PODZIAŁEM NA SLAJD I PUBLICYSTYCZNY POST THREADS ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś autorem czołowego konta analityczno-militarnego w mediach społecznościowych („Świat w Minucie”). 
Twoje posty na Threads generują ogromne organiczne zasięgi (dziesiątki tysięcy wyświetleń i setki komentarzy), ponieważ piszesz w sposób żywy, publicystyczny, z trafnym tłem strategicznym i bezkompromisową pointą.

Zadanie: Wybierz DOKŁADNIE {TARGET_ITEMS} RÓŻNE, NAJCIEKAWSZE tematy z podanej listy i stwórz dla każdego unikalny wpis w formacie JSON.

ZASADA ROZDZIELENIA TREŚCI SLAJD VS THREADS:
- Na karuzelę Instagrama ("summary" i "comment"): pisz krótko, syntetycznie i merytorycznie. Summary to 2 zdania faktów o konkretnym sprzęcie/wydarzeniu, comment to 1 zdanie wniosku strategicznego.
- Na Threads ("threads_post"): BEZWZGLĘDNY ZAKAZ przepisania 1:1 słów ze slajdu!
  Napisz wciągający, bogaty post publicystyczny (dokładnie 3-4 naturalne akapity).
  Wzoruj się na poniższym schemacie:
  Akapit 1: Tytuł z trafną emotikoną (np. 🛡️, 🚀, ⚔️, ⚠️).
  Akapit 2: Krzykliwy podwójny hook z flagami i wykrzyknikiem (np. "302 dni na oceanie: Historyczny i wyczerpujący dyżur USS Abraham Lincoln! 🚀🇺🇸").
  Akapit 3: Pogłębione rozwinięcie sytuacji, którego NIE MA na grafice (szersze tło strategiczne, zmęczenie załóg, zużycie sprzętu, realna presja logistyczna).
  Akapit 4: Cięta pointa z dedykowanymi emotikonami (np. 🌊⚓, 🛸🪖, ❄️🛡️).
  Akapit 5: Konkretne pytanie prowokujące do dyskusji pod dany temat (np. "Czy US Navy nie nadwyręża zbytnio wytrzymałości swoich załóg? 🚢👇💬").

STRUKTURA JSON (zwróć WYŁĄCZNIE czysty JSON):
[
  {{
    "category": "OBRONNOŚĆ / POLSKA / GEOPOLITYKA",
    "title": "[Emotikona] [Konkretny, intrygujący nagłówek do 60 znaków]",
    "hook": "1 zdanie uderzające w sedno.",
    "summary": "2 zwięzłe zdania konkretów na slajd.",
    "comment": "1 mocne, chłodne zdanie wniosku strategicznego.",
    "threads_post": "Pełna treść wiralowego posta na Threads (rozdzielona podwójnymi enterami \\n\\n, bogata w kontekst i unikalna względem summary).",
    "question": "1 angażujące, unikalne pytanie skierowane do czytelników w tym konkretnym temacie.",
    "image_query": "2-3 precyzyjne angielskie słowa kluczowe do Pexels (np. 'aircraft carrier ocean', 'military drone flight')",
    "link": "dokładnie URL artykułu"
  }}
]

Unikaj tematów z archiwum: {json.dumps(excluded_topics[:8], ensure_ascii=False)}

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
            temperature=0.4,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            ]
        ),
    )
    
    text = response.text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    parsed = json.loads(text)
    if isinstance(parsed, list):
        raw_items = parsed
    elif isinstance(parsed, dict) and "items" in parsed:
        raw_items = parsed["items"]
    else:
        raw_items = []

    items = validate_items(raw_items)

except Exception as e:
    print(f"Błąd AI: {e}")
    traceback.print_exc()
    items = []

# Awaryjne uzupełnienie
while len(items) < TARGET_ITEMS:
    existing_links = {i.get('link') for i in items if isinstance(i, dict)}
    added = False
    for art in articles_for_ai:
        if art['link'] not in existing_links and art['link'] != "#":
            clean_t = art.get('title', 'Nowe doniesienia')
            items.append({
                "category": "OBRONNOŚĆ",
                "title": f"🚨 {clean_t[:55]}",
                "hook": f"Kluczowe doniesienia dotyczące projektu: {clean_t[:40]}.",
                "summary": f"Trwają dyskusje wokół wdrożenia i zabezpieczenia kontraktu w tym obszarze. Przedstawiciele branży analizują szczegóły techniczne.",
                "comment": "Decyzje w tym sektorze bezpośrednio zdefiniują potencjał operacyjny na kolejne lata.",
                "threads_post": f"🚨 {clean_t[:55]}\n\nKluczowy zwrot na wschodniej flance: zapadają strategiczne decyzje! 🛡️⚡\n\nPrzedstawiciele resortów obrony i sztabów analizują najnowsze dane operacyjne. Presja czasu i wyzwania logistyczne zmuszają do weryfikacji dotychczasowych planów zaopatrzeniowych.\n\nTo wyraźny sygnał, że deklaracje polityczne muszą natychmiast znaleźć odzwierciedlenie w realnych mocach produkcyjnych przemysłu. 🪖⏳\n\nKrajowy i sojuszniczy przemysł zbrojeniowy sprosta wyzwaniom nowej ery? 🏭👇💬",
                "question": "Jak oceniacie ten ruch z perspektywy modernizacji armii?",
                "image_query": "military defense technology",
                "link": art.get("link", "#")
            })
            existing_links.add(art['link'])
            added = True
            if len(items) >= TARGET_ITEMS:
                break
    if not added:
        break

items = items[:TARGET_ITEMS]

# --- KASKADOWE POBIERANIE ZDJĘĆ ---
print("Dobieranie zdjęć (Artykuł -> Pexels -> Fallback)...")
source_ok = 0
for item in items:
    url = item.get("link", "")
    q = item.get("image_query", "military")
    
    selected_img = fetch_article_image(url)
    if selected_img:
        source_ok += 1
    else:
        selected_img = fetch_pexels_image_url(q)
    if not selected_img:
        selected_img = FALLBACK_IMG
        
    item["image_url"] = selected_img
    item["source_image_url"] = selected_img

print(f"Zdjęcia ze źródeł pobrane: {source_ok}/{len(items)}")

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

print(f"Zakończono. Pomyślnie zapisano {len(items)} unikalnych pozycji w fast.json.")
