import html as html_lib
import json
import os
import re
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from time import mktime, sleep
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs
from collections import Counter

import feedparser
from google import genai
from google.genai import types

pl_tz = ZoneInfo("Europe/Warsaw")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
FALLBACK_IMG = "https://images.unsplash.com/photo-1534447677768-be436bb09401?q=80&w=1000&auto=format&fit=crop"

RSS_URLS = [
    "https://news.google.com/rss/search?q=ciekawostki+zwierz%C4%99ta+rekord+zoo&hl=pl&gl=PL&ceid=PL:pl",
    "https://news.google.com/rss/search?q=kuriozum+absurd+wpadka&hl=pl&gl=PL&ceid=PL:pl",
    "https://www.upi.com/rss/Odd_News/",
    "https://news.google.com/rss/search?q=when:2d+topic:weird+news&hl=en-US&gl=US&ceid=US:en",
    "https://www.mentalfloss.com/rss.xml",
    "https://www.sciencenews.org/topic/weird-science/feed",
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia",
}

MAX_AGE_HOURS = 72
MIN_ITEMS = 6


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[\U000E0020-\U000E007F]", "", text)
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("Cf", "Cc", "Cn") or ch in "\n\t"
    )
    text = re.sub(r"U\+[0-9A-Fa-f]{4,6}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_polish_text(text: str) -> bool:
    if not text or len(text.strip()) < 5:
        return False
    if re.search(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", text):
        return True
    common_pl = r"\b(i|w|na|z|do|o|nie|się|jak|to|co|że|jest|ten|ta|to|dla|po|od|przez|ze|oraz|ale|za)\b"
    if re.search(common_pl, text.lower()):
        return True
    common_en = r"\b(the|why|how|what|when|where|who|this|that|these|with|from|and|for|are|was|were)\b"
    if re.search(common_en, text.lower()):
        return False
    return True


def clean_link(url: str) -> str:
    if not url or url == "#":
        return "#"
    try:
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "at_medium", "at_campaign", "fbclid", "gclid", "mc_cid", "mc_eid",
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
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "pl,en-US;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
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
                img = html_lib.unescape(m.group(1).strip()).replace("&amp;", "&")
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http") and not img.endswith(".svg"):
                    return img
    except Exception:
        pass
    return None


def fetch_pexels_image_url(query: str, seen: set | None = None) -> str | None:
    if not PEXELS_API_KEY:
        return None

    seen = seen or set()
    queries = [query]
    parts = query.split()
    if len(parts) > 1:
        queries.append(parts[0])

    for q in queries:
        try:
            url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(q)}&per_page=5&orientation=landscape"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": PEXELS_API_KEY,
                    "User-Agent": "SwiatWMinute-Bot/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    photos = data.get("photos") or []
                    for photo in photos:
                        src = photo.get("src") or {}
                        raw = src.get("large") or src.get("medium")
                        if raw:
                            raw = html_lib.unescape(raw).replace("&amp;", "&")
                            if raw not in seen:
                                return raw
        except Exception:
            continue
    return None


def pick_image_for_item(item: dict, seen_image_urls: set) -> str:
    url = item.get("link", "")
    q = str(item.get("image_query") or "curiosity nature").strip()

    # 1. Sprawdzenie czy zdjęcie z artykułu jest dostępne
    article_img = fetch_article_image(url)
    if article_img and article_img not in seen_image_urls:
        seen_image_urls.add(article_img)
        return article_img

    # 2. Pexels po query z AI
    stock = fetch_pexels_image_url(q, seen=seen_image_urls)
    if stock and stock not in seen_image_urls:
        seen_image_urls.add(stock)
        return stock

    seen_image_urls.add(FALLBACK_IMG)
    return FALLBACK_IMG


def embed_all_image_keys(item: dict, img_url: str) -> dict:
    """Wstrzykuje wszystkie klucze, jakich frontend mógłby szukać."""
    item["image_url"] = img_url
    item["source_image_url"] = img_url
    item["image"] = img_url
    item["img"] = img_url
    item["photo"] = img_url
    return item


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

        if not is_polish_text(title) or not is_polish_text(summary):
            continue

        valid.append({
            "category": category,
            "title": title,
            "summary": summary,
            "comment": comment,
            "image_query": image_query,
            "link": link,
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
            if re.search(r"\b(nsfw|porn|sex|naked|erotic)\b", title, re.I):
                continue
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 12:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

print(f"Pobrano {len(raw_articles)} surowych artykułów.")

archive_file = "archive_rozrywka.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

now_pl = datetime.now(pl_tz)
session_fixed_key = f"{now_pl.strftime('%Y-%m-%d')}_rozrywka"

previous_topics = []
sorted_sessions = sorted(archive_data.keys(), reverse=True)[:15]
for s_key in sorted_sessions:
    s_content = archive_data.get(s_key, {})
    if isinstance(s_content, dict) and "items" in s_content:
        for it in s_content.get("items", []):
            if isinstance(it, dict) and "title" in it:
                clean = "".join(
                    c for c in it["title"] if ord(c) > 127 or c.isalnum() or c.isspace()
                ).strip().lower()
                previous_topics.append(clean)

filtered_raw_articles = []
for art in raw_articles:
    art_clean = "".join(
        c for c in art["title"] if ord(c) > 127 or c.isalnum() or c.isspace()
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

api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

prompt = f"""Jesteś polskim redaktorem formatu rozrywkowego „Świat w Minucie” (Instagram/Threads). 
Stwórz 8-10 absolutnie fascynujących, wiralowych ciekawostek po polsku.

KATEGORYCZNY NAKAZ JĘZYKOWY (100% POLSKI):
- Nawet jeśli artykuł w „Danych wejściowych” ma tytuł po angielsku (np. z Mental Floss lub UPI), MASZ BEZWZGLĘDNY OBOWIĄZEK PRZETŁUMACZYĆ I NAPISAĆ TYTUŁ, PODSUMOWANIE ORAZ KOMENTARZ W JĘZYKU POLSKIM!
- ZAKAZ pozostawiania angielskich słów w polach "title", "summary" oraz "comment".

PODZIAŁ TEMATYCZNY:
1. 50% MUSI dotyczyć BIEŻĄCYCH ODDITIES (wpadki ludzi, ucieczki zwierzaków, dziwne rekordy, kurioza).
   - Kategoria: BIEŻĄCE ABSURDY lub ZWIERZAKI.
2. 50% to szalona historia, sekrety popkultury, dziwna nauka.
   - Kategoria: SZALONA HISTORIA, BEKA Z NAUKI lub POPKULTURA.

STRUKTURA JSON:
[
  {{
    "category": "BIEŻĄCE ABSURDY" lub "ZWIERZAKI" lub "SZALONA HISTORIA" lub "BEKA Z NAUKI" lub "POPKULTURA",
    "title": "[Emotikona] [Chwytliwy polski nagłówek do 60 znaków]",
    "summary": "2-3 zdania pełne komicznych faktów i liczb po polsku.",
    "comment": "1 ostre, przezabawne zdanie puenty w stylu ciętego stand-upu po polsku.",
    "image_query": "1-2 słowa kluczowe po angielsku do Pexels (np. 'raccoon', 'pirate ship')",
    "link": "Dokładny URL artykułu"
  }}
]

Unikaj tematów z archiwum:
{json.dumps(previous_topics[:30], ensure_ascii=False)}

Dane wejściowe:
{json.dumps(filtered_raw_articles[:30], ensure_ascii=False)}
"""

models_to_try = ["gemini-3.6-flash", "gemini-2.5-flash"]
items = []

for model_name in models_to_try:
    if len(items) >= MIN_ITEMS:
        break
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.45,
                safety_settings=[
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                ],
            ),
        )

        raw_text = response.text or ""
        text_clean = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        text_clean = re.sub(r"\s*```$", "", text_clean)

        parsed = json.loads(text_clean)
        if isinstance(parsed, list):
            raw_items = parsed
        elif isinstance(parsed, dict) and "items" in parsed:
            raw_items = parsed["items"]
        elif isinstance(parsed, dict):
            raw_items = list(parsed.values())[0] if parsed else []
        else:
            raw_items = []

        items = validate_items(raw_items)
        if len(items) >= MIN_ITEMS:
            break
    except Exception as e:
        print(f"Błąd modelu {model_name}: {e}")
        sleep(1)

# Awaryjny fallback
POLISH_FALLBACK_TITLES = [
    "🐾 Niezwykłe odkrycie przyrodników zaskoczyło naukowców",
    "🎩 Zapomniany sekret historii, o którym nie uczą w szkołach",
    "🍕 Najdziwniejszy kulinarny eksperyment, który podbił sieć",
    "🚀 Genialny patent z przeszłości, który wyprzedził swoją epokę",
    "🦜 Zwierzęcy geniusz: Niewiarygodna ucieczka z miejskiego zoo",
    "🎬 Kulisy kultowego filmu, które całkowicie zmieniają fabułę",
]

if len(items) < MIN_ITEMS:
    existing_links = {i.get("link") for i in items}
    for idx, art in enumerate(filtered_raw_articles):
        if len(items) >= MIN_ITEMS:
            break
        if art["link"] in existing_links:
            continue

        pl_title = POLISH_FALLBACK_TITLES[idx % len(POLISH_FALLBACK_TITLES)]
        items.append({
            "category": "BIEŻĄCE ABSURDY" if idx % 2 == 0 else "SZALONA HISTORIA",
            "title": pl_title,
            "summary": "Nietypowe i zaskakujące doniesienia z ostatnich godzin, które wzbudziły ogromne poruszenie.",
            "comment": "Rzeczywistość po raz kolejny udowadnia, że najdziwniejsze scenariusze pisze samo życie.",
            "image_query": "weird animal mystery",
            "link": art["link"],
        })
        existing_links.add(art["link"])

# --- DOBIERANIE ZDJĘĆ Z ZAPISYWANIEM WSZYSTKICH ALIASÓW KLUCZY ---
print("Dobieranie unikalnych zdjęć...")
source_ok = 0
seen_image_urls = set()

for item in items:
    img = pick_image_for_item(item, seen_image_urls)
    embed_all_image_keys(item, img)
    if "pexels.com" not in img and "unsplash.com" not in img:
        source_ok += 1

print(f"Zdjęcia z artykułów: {source_ok}/{len(items)}")

# --- ZAPIS ---
date_pretty = f"{now_pl.day} {POLISH_MONTHS[now_pl.month]} {now_pl.year}"
time_pretty = now_pl.strftime("%H:%M")
timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items,
}

# 1. Bieżące wydanie
with open("rozrywka.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# 2. Archiwum: dopisujemy dzisiejsze wydanie z pełnymi kluczami
archive_data[session_fixed_key] = output_data

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"Zapisano {len(items)} pozycji do rozrywka.json oraz sesji {session_fixed_key} w {archive_file}.")
