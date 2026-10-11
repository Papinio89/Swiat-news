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

# Różne fallbacki – nie ten sam statek/kosmos dla wszystkich starych wpisów
FALLBACK_POOL = [
    "https://images.unsplash.com/photo-1534447677768-be436bb09401?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1469474968028-56623f02e42e?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1519681393784-d120267933ba?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1426604966848-d7adac402bff?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1472214103451-9374bd1c798e?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1501854140801-50d01698950b?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1518837695005-2083093ee35b?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1475924156734-496f6cac6ec1?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1518173946687-a0cabc1caa1d?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1501785888041-af3ef285b470?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1439066615861-d1af74d74000?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1518495973542-4542c06a5843?q=80&w=1000&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1540206395-68808572332f?q=80&w=1000&auto=format&fit=crop",
]
FALLBACK_IMG = FALLBACK_POOL[0]


def stable_hash(text: str) -> int:
    h = 0
    for ch in str(text or ""):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def fallback_for(seed: str) -> str:
    return FALLBACK_POOL[stable_hash(seed) % len(FALLBACK_POOL)]


# Tytuł PL → query EN pod stock
KEYWORD_MAP = [
    (r"szop|raccoon", "raccoon"),
    (r"kot|cat|kotek", "cat"),
    (r"pies|dog|szczen", "dog"),
    (r"ptak|bird|papug", "parrot bird"),
    (r"jaszczur|lizard|gecko", "lizard"),
    (r"wąż|snake", "snake"),
    (r"ryba|fish|rekin", "fish ocean"),
    (r"niedźwied|bear", "bear"),
    (r"słoń|elephant", "elephant"),
    (r"panda", "panda"),
    (r"pingwin|penguin", "penguin"),
    (r"flaming", "flamingo"),
    (r"jeż|hedgehog", "hedgehog"),
    (r"słońce|kosmos|gwiazd|galaktyk|space", "galaxy stars night"),
    (r"morze|ocean|żagl|statek|boat", "sailboat ocean"),
    (r"las|drzew|natura", "forest nature"),
    (r"gór|mountain", "mountain landscape"),
    (r"miasto|city|wieżow", "city skyline"),
    (r"samoch|car|auto", "vintage car"),
    (r"rower|bike", "bicycle"),
    (r"książ|book|biblio", "old books"),
    (r"muzeum|historia|vintage|starożyt", "museum history"),
    (r"nauka|science|laborat", "science laboratory"),
    (r"robot|ai|komput", "robot technology"),
    (r"jedzen|pizza|banan|kuchn", "food colorful"),
    (r"muzyk|gitara|koncert", "music concert"),
    (r"film|kino|aktor", "cinema film"),
    (r"sport|piłk|mecz", "stadium sport"),
    (r"deszcz|storm|burz", "storm clouds"),
    (r"śnieg|zim[aą]|winter", "winter snow"),
    (r"kwiat|flower|róż", "flowers"),
]

RSS_URLS = [
    # 1. POLSKIE BIEŻĄCE CIEKAWOSTKI
    "https://news.google.com/rss/search?q=ciekawostki+zwierz%C4%99ta+rekord+zoo&hl=pl&gl=PL&ceid=PL:pl",
    "https://news.google.com/rss/search?q=kuriozum+absurd+wpadka&hl=pl&gl=PL&ceid=PL:pl",

    # 2. GLOBALNE BIEŻĄCE ODD NEWS
    "https://www.upi.com/rss/Odd_News/",
    "https://news.google.com/rss/search?q=when:2d+topic:weird+news&hl=en-US&gl=US&ceid=US:en",

    # 3. NAUKA / HISTORIA
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

# Pola obrazka wymagane przez frontend (ciekawostki / karty)
IMAGE_FIELDS = ("image_url", "image", "source_image_url")


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


def query_from_title(title: str, image_query: str = "") -> str:
    """Buduje zróżnicowane query EN z image_query lub tytułu PL."""
    if image_query and re.search(r"[A-Za-z]{3,}", image_query):
        return image_query.strip()

    t = str(title or "").lower()
    for pat, eng in KEYWORD_MAP:
        if re.search(pat, t, re.I):
            return eng

    words = re.findall(r"[A-Za-z]{4,}", title or "")
    if words:
        return " ".join(words[:2])
    # ostatnia deska: hash → kilka ogólnych, ale różnych zapytań
    generic = [
        "curious animal", "vintage object", "science experiment",
        "funny moment", "historic place", "colorful nature",
        "street photography", "night sky", "ocean wave", "forest path",
    ]
    return generic[stable_hash(title) % len(generic)]


def fetch_pexels_image_url(query: str, seed: str = "", seen: set | None = None) -> str | None:
    """
    Pexels z wyborem RÓŻNEGO zdjęcia (nie zawsze photos[0]).
    page + index zależą od hasha tytułu → mniej duplikatów.
    Przy 429 / błędzie zwraca None (caller użyje fallback_for).
    """
    if not PEXELS_API_KEY:
        return None

    seen = seen or set()
    h = stable_hash(seed or query)
    page = (h % 3) + 1  # strony 1–3
    prefer_idx = h % 12

    queries = [query]
    parts = query.split()
    if len(parts) > 1:
        queries.append(parts[0])

    for q in queries:
        try:
            url = (
                f"https://api.pexels.com/v1/search?"
                f"query={urllib.parse.quote(q)}"
                f"&per_page=15&orientation=landscape&page={page}"
            )
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": PEXELS_API_KEY,
                    "User-Agent": "SwiatWMinute-Bot/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 429:
                    print("  Pexels rate limit (429) – przechodzę na fallbacki")
                    return None
                if resp.status != 200:
                    continue
                data = json.loads(resp.read().decode("utf-8"))
                photos = data.get("photos") or []
                if not photos:
                    continue
                # spróbuj preferowany index, potem kolejne, pomijając already seen
                order = list(range(len(photos)))
                order = order[prefer_idx:] + order[:prefer_idx]
                for i in order:
                    src = photos[i].get("src") or {}
                    raw = src.get("large") or src.get("medium") or src.get("original")
                    if not raw:
                        continue
                    raw = html_lib.unescape(raw).replace("&amp;", "&")
                    if raw not in seen:
                        return raw
                # wszystkie widziane – i tak weź pierwszy z tej strony
                src = photos[0].get("src") or {}
                raw = src.get("large") or src.get("medium")
                if raw:
                    return html_lib.unescape(raw).replace("&amp;", "&")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("  Pexels HTTP 429 – limit, fallbacki")
                return None
            continue
        except Exception:
            continue
        sleep(0.35)  # delikatny throttle między query
    return None


def pick_image_for_item(item: dict, seen_image_urls: set) -> str:
    """Unikalna grafika: OG artykułu → Pexels (różne zdjęcia) → unikalny fallback."""
    title = str(item.get("title") or "")
    url = item.get("link", "")
    q = query_from_title(title, str(item.get("image_query") or ""))

    article_img = fetch_article_image(url)
    if article_img and article_img not in seen_image_urls:
        seen_image_urls.add(article_img)
        return article_img

    stock = fetch_pexels_image_url(q, seed=title, seen=seen_image_urls)
    if stock and stock not in seen_image_urls:
        seen_image_urls.add(stock)
        return stock

    # drugi strzał z innym query
    alt_q = q.split()[0] if q else "nature"
    stock2 = fetch_pexels_image_url(alt_q, seed=title + "|alt", seen=seen_image_urls)
    if stock2 and stock2 not in seen_image_urls:
        seen_image_urls.add(stock2)
        return stock2

    fb = fallback_for(title)
    # jeśli ten fallback już był – przewiń pool
    if fb in seen_image_urls:
        for i in range(len(FALLBACK_POOL)):
            cand = FALLBACK_POOL[(stable_hash(title) + i) % len(FALLBACK_POOL)]
            if cand not in seen_image_urls:
                fb = cand
                break
    seen_image_urls.add(fb)
    return fb


def apply_image_fields(item: dict, img_url: str) -> dict:
    """Ustawia wszystkie aliasy obrazka używane przez frontend."""
    item["image_url"] = img_url
    item["source_image_url"] = img_url
    item["image"] = img_url
    return item


def normalize_archive_item(item: dict) -> dict:
    """
    Kanoniczna struktura wpisu w archive_rozrywka.json.
    Frontend (imageOf) czyta: image, image_url, source_image_url, img, photo, thumbnail…
    """
    if not isinstance(item, dict):
        return item

    img = (
        item.get("image_url")
        or item.get("image")
        or item.get("source_image_url")
        or item.get("img")
        or item.get("photo")
        or item.get("thumbnail")
        or ""
    )
    img = str(img).strip() if img else ""

    out = {
        "category": sanitize_text(str(item.get("category", "ABSURDY ŚWIATA"))).upper(),
        "title": sanitize_text(str(item.get("title", ""))),
        "summary": sanitize_text(str(item.get("summary", ""))),
        "comment": sanitize_text(str(item.get("comment", ""))),
        "link": clean_link(str(item.get("link", "#"))),
        "image_query": sanitize_text(str(item.get("image_query", ""))),
        # zawsze te same 3 klucze – także w archiwum
        "image_url": img or FALLBACK_IMG,
        "image": img or FALLBACK_IMG,
        "source_image_url": img or FALLBACK_IMG,
    }
    return out


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
            "link": link,
        })
    return valid


def migrate_archive_images(archive_data: dict, max_backfill: int = 60) -> dict:
    """
    1) Uzupełnia wpisy BEZ grafiki.
    2) Podmienia masowe duplikaty (ten sam URL > 2 razy) na dedykowane zdjęcia.
    Throttle Pexels, żeby nie wpaść w 429.
    """
    seen: set[str] = set()
    url_counts: dict[str, int] = {}
    filled = 0
    replaced_dupes = 0

    def note_url(u: str):
        if not u:
            return
        url_counts[u] = url_counts.get(u, 0) + 1

    # zlicz użycia
    for session in archive_data.values():
        if not isinstance(session, dict):
            continue
        for it in session.get("items") or []:
            if isinstance(it, dict):
                u = it.get("image_url") or it.get("image") or it.get("source_image_url") or ""
                note_url(u)

    # URL-e użyte > 2 razy uznajemy za „złe” (limit Pexels / jeden fallback)
    overused = {u for u, c in url_counts.items() if c > 2 and u}
    print(f"  nadużywane grafiki (>{2}×): {len(overused)}")

    for key, session in list(archive_data.items()):
        if not isinstance(session, dict):
            continue
        items = session.get("items")
        if not isinstance(items, list):
            continue

        new_items = []
        for it in items:
            if not isinstance(it, dict):
                continue

            current = (
                it.get("image_url")
                or it.get("image")
                or it.get("source_image_url")
                or ""
            )
            needs = (not current) or (current in overused)

            if needs and filled < max_backfill:
                try:
                    # nie dodawaj current do seen zanim nie znajdziemy lepszego
                    img = pick_image_for_item(it, seen)
                    if img and img != current:
                        if current in overused:
                            replaced_dupes += 1
                        it = apply_image_fields(dict(it), img)
                        filled += 1
                        print(f"  fix [{filled}]: {str(it.get('title', ''))[:48]}…")
                        sleep(0.4)  # throttle Pexels
                except Exception as e:
                    print(f"  backfill fail: {e}")
                    it = apply_image_fields(dict(it), fallback_for(it.get("title", key)))
            elif current:
                seen.add(current)

            new_items.append(normalize_archive_item(it))

        session["items"] = new_items
        archive_data[key] = session

    print(f"Uzupełniono/podmieniono grafik: {filled} (w tym duplikaty: {replaced_dupes})")
    return archive_data


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

print(f"Pobrano {len(raw_articles)} surowych artykułów rozrywkowych.")

# --- ODCZYT ARCHIWUM SESYJNEGO ---
archive_file = "archive_rozrywka.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

now_pl = datetime.now(pl_tz)
# stabilniejszy klucz dnia + godzina (bez minut – mniej fragmentacji)
session_fixed_key = now_pl.strftime("%Y-%m-%d_%H_rozrywka")

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

print(f"Po deduplikacji: {len(filtered_raw_articles)} artykułów przekazanych do AI")

api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

prompt = f"""Jesteś redaktorem rozrywkowym formatu „Świat w Minucie” (Instagram/Threads). 
Stwórz 8-10 absolutnie fascynujących, zabawnych i viralowych ciekawostek w formacie JSON.
BEZWZGLĘDNY WYMÓG: CAŁA TREŚĆ (tytuł, opis, komentarz) MUSI BYĆ W JĘZYKU POLSKIM. Przetłumacz angielskie zdarzenia na błyskotliwy, żywy polski język!

PODZIAŁ TEMATYCZNY:
1. 50% MUSI dotyczyć BIEŻĄCYCH ODDITIES (wpadki ludzi, ucieczki zwierzaków, dziwne rekordy, kurioza).
   - Kategoria: BIEŻĄCE ABSURDY lub ZWIERZAKI.
2. 50% to szalona historia, sekrety popkultury, dziwna nauka.
   - Kategoria: SZALONA HISTORIA, BEKA Z NAUKI lub POPKULTURA.

ZASADA UNIKALNOŚCI ŹRÓDEŁ:
- Każda wygenerowana ciekawostka MUSI mieć INNY link ("link") przypisany z listy "Dane wejściowe".
- KATEGORYCZNY ZAKAZ przypisywania tego samego linku do kilku wiadomości! 1 news = 1 unikalny link.

ZASADY PISANIA DLA PÓL:
- "category": Dokładnie jedna z kategorii: "BIEŻĄCE ABSURDY", "ZWIERZAKI", "SZALONA HISTORIA", "BEKA Z NAUKI", "POPKULTURA".
- "title": [Emotikona] + [Krótki, chwytliwy nagłówek po polsku do 60 znaków].
- "summary": 2-3 zdania pełne faktów, liczb i komicznego absurdu po polsku.
- "comment": 1 ostre, przezabawne zdanie puenty w stylu ciętego stand-upu po polsku.
- "image_query": Dokładnie 1-2 proste słowa kluczowe po angielsku pod Pexels oddające sedno (np. 'flamingo', 'vintage car', 'top hat', 'hedgehog', 'banana').
- "link": Dokładnie URL artykułu z wejścia (każdy news musi mieć inny!).

UNIKAJ TYCH TEMATÓW Z ARCHIWUM:
{json.dumps(previous_topics[:30], ensure_ascii=False)}

Zwróć CZYSTĄ tablicę JSON obiektów.

Dane wejściowe:
{json.dumps(filtered_raw_articles[:30], ensure_ascii=False)}
"""

models_to_try = ["gemini-3.6-flash", "gemini-2.5-flash"]
items = []

for model_name in models_to_try:
    if len(items) >= MIN_ITEMS:
        break
    try:
        print(f"Wysyłanie zapytania do modelu: {model_name}...")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.6,
                safety_settings=[
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
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
            print(f"Sukces! Wygenerowano {len(items)} unikalnych pozycji przy użyciu {model_name}.")
            break
        else:
            print(f"Model {model_name} zwrócił zbyt mało poprawnych elementów ({len(items)}/{MIN_ITEMS}).")
    except Exception as e:
        print(f"Błąd dla modelu {model_name}: {e}")
        traceback.print_exc()
        sleep(1)

# Awaryjne uzupełnienie
if len(items) < MIN_ITEMS:
    print("Aktywacja awaryjnego uzupełnienia pozycji...")
    existing_links = {i.get("link") for i in items}
    for idx, art in enumerate(filtered_raw_articles):
        if len(items) >= MIN_ITEMS:
            break
        if art["link"] in existing_links:
            continue

        raw_t = art["title"]
        clean_t = re.sub(r" - [^-]+$", "", raw_t)[:55]
        items.append({
            "category": "BIEŻĄCE ABSURDY" if idx % 2 == 0 else "SZALONA HISTORIA",
            "title": f"🐾 {clean_t}",
            "summary": (
                "Nietypowe i zaskakujące doniesienia z ostatnich godzin, "
                "które wzbudziły spore poruszenie i ciekawość w mediach."
            ),
            "comment": "Rzeczywistość po raz kolejny udowadnia, że najdziwniejsze scenariusze pisze samo życie.",
            "image_query": "weird animal funny mystery",
            "link": art["link"],
        })
        existing_links.add(art["link"])

if items:
    cats = Counter([item["category"] for item in items])
    print("Rozkład kategorii (rozrywka):")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

print(f"Łącznie gotowych pozycji rozrywkowych: {len(items)}")

# --- DOBIERANIE ZDJĘĆ (przed zapisem do rozrywka.json I archiwum) ---
print("Dobieranie zdjęć (blokada powtórzonych grafik i gwarancja URL)...")
source_ok = 0
seen_image_urls = set()

for item in items:
    before = len(seen_image_urls)
    img = pick_image_for_item(item, seen_image_urls)
    apply_image_fields(item, img)
    # jeśli weszło z artykułu (nie fallback / nie tylko pexels-heuristic) – zgrubnie
    if item.get("link") and img != FALLBACK_IMG and "pexels.com" not in img and "unsplash.com" not in img:
        source_ok += 1
    elif "pexels.com" not in img and img != FALLBACK_IMG and before < len(seen_image_urls):
        source_ok += 1

print(f"Zdjęcia ze źródeł: {source_ok}/{len(items)} (reszta = Pexels/Fallback)")

# Kanoniczna forma każdego itemu (te same pola co w archiwum)
items = [normalize_archive_item(it) for it in items]

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

# 2. Archiwum – pełne itemy ZE ZDJĘCIAMI (normalize gwarantuje pola)
archive_data[session_fixed_key] = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": [normalize_archive_item(it) for it in items],
}

# 3. Migracja starych sesji bez image_url (max 40, żeby nie walić w API)
print("Migracja starych wpisów archiwum bez grafik…")
archive_data = migrate_archive_images(archive_data, max_backfill=40)

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

# szybki self-check
missing = 0
for sess in archive_data.values():
    if not isinstance(sess, dict):
        continue
    for it in sess.get("items") or []:
        if not any(it.get(f) for f in IMAGE_FIELDS):
            missing += 1
print(f"Kontrola archiwum: wpisów bez grafiki = {missing}")

print(f"Zapisano {len(items)} ciekawostek do rozrywka.json.")
print(f"Zaktualizowano {archive_file} (łącznie sesji: {len(archive_data)}).")
print("Przykładowy item (pola obrazka):")
if items:
    sample = {k: items[0].get(k) for k in ("title", "image_url", "image", "source_image_url")}
    print(json.dumps(sample, ensure_ascii=False, indent=2))
