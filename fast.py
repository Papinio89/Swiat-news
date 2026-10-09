import html
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

# Źródła standardowe (Militaria, Geopolityka, Obronność)
RSS_URLS_STANDARD = [
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

# Źródła zdarzeń krytycznych (Breaking: ataki nożowników, strzelaniny, incydenty kryzysowe)
RSS_URLS_BREAKING = [
    "https://news.google.com/rss/search?q=strzelanina+atak+no%C5%BCownik+zamach+ranni+policja+ob%C5%82awa&hl=pl&gl=PL&ceid=PL:pl",
    "https://news.google.com/rss/search?q=stabbing+shooting+attack+police+suspect+dead+injured&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bbci.co.uk/news/world/rss.xml"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 12
TARGET_ITEMS = 5


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


def normalize_category(cat: str) -> str:
    c = str(cat or "").upper().strip()
    if "PILNE" in c or "ATAK" in c or "KRYZYS" in c or "STRZEL" in c:
        return "PILNE"
    if "POLSK" in c:
        return "POLSKA"
    if "GEOPOLITYK" in c or "ŚWIAT" in c:
        return "GEOPOLITYKA"
    return "OBRONNOŚĆ"


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
                "Accept-Language": "pl,en-US;q=0.9,en;q=0.8"
            }
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            html_raw = resp.read().decode("utf-8", errors="ignore")
            
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']'
        ]
        for pat in patterns:
            m = re.search(pat, html_raw, re.I)
            if m:
                img = html.unescape(m.group(1).strip()).replace("&amp;", "&")
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
                    raw_src = src.get("large") or src.get("medium")
                    if raw_src:
                        return html.unescape(raw_src).replace("&amp;", "&")
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
        category = normalize_category(item.get("category", "OBRONNOŚĆ"))
        image_query = str(item.get("image_query", "police emergency")).strip()
        link = clean_link(str(item.get("link", "#")))

        # Wymóg rozbudowanego porannego wątku Threads (minimum 350 znaków)
        if len(title) < 10 or len(summary) < 20 or len(comment) < 10 or len(threads_post) < 350:
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


def parse_feed_list(urls, max_entries=4):
    articles = []
    for u in urls:
        try:
            feed = feedparser.parse(u)
            for entry in feed.entries[:max_entries]:
                if not is_recent(entry):
                    continue
                title = getattr(entry, "title", "").strip()
                summary = getattr(entry, "summary", "").strip()
                clean_snippet = re.sub(r'<[^>]+>', '', summary)[:250]
                link = clean_link(getattr(entry, "link", "#"))
                if title and len(title) > 8:
                    articles.append({
                        "title": title,
                        "snippet": clean_snippet,
                        "link": link
                    })
        except Exception as e:
            print(f"Błąd RSS z {u}: {e}")
    return articles


# --- ZBIERANIE RSS (Z PODZIAŁEM NA STANDARD I BREAKING) ---
raw_standard = parse_feed_list(RSS_URLS_STANDARD, max_entries=4)
raw_breaking = parse_feed_list(RSS_URLS_BREAKING, max_entries=5)

print(f"Pobrano: {len(raw_standard)} standardowych oraz {len(raw_breaking)} pilnych artykułów.")

# --- WYKLUCZENIA Z ARCHIWUM ---
excluded_topics = []
for fname in ["archive.json", "news.json", "fast.json"]:
    if os.path.exists(fname):
        try:
            with open(fname, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    # Obsługa formatu archiwalnego z kluczami sesji
                    items_pool = []
                    if "items" in d:
                        items_pool = d["items"]
                    else:
                        for sk in sorted(d.keys(), reverse=True)[:5]:
                            sub = d.get(sk)
                            if isinstance(sub, dict) and "items" in sub:
                                items_pool.extend(sub["items"])
                    for item in items_pool:
                        if isinstance(item, dict) and "title" in item:
                            clean = "".join(c for c in item["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
                            excluded_topics.append(clean)
        except:
            pass

def deduplicate(article_list):
    filtered = []
    seen = set()
    for art in article_list:
        t = "".join(c for c in art["title"] if ord(c) > 127 or c.isalnum() or c.isspace()).strip().lower()
        words = set(t.split())
        is_dup = False
        if len(words) > 2:
            for prev in excluded_topics:
                p_words = set(prev.split())
                if len(p_words) > 2:
                    common = words.intersection(p_words)
                    if len(common) / min(len(words), len(p_words)) > 0.40:
                        is_dup = True
                        break
        if not is_dup and t not in seen:
            filtered.append(art)
            seen.add(t)
    return filtered if filtered else article_list

clean_standard = deduplicate(raw_standard)[:12]
clean_breaking = deduplicate(raw_breaking)[:8]

# --- PROMPT AI Z GWARANCJĄ PORANNEJ JAKOŚCI I 2 PILNYCH NEWSÓW ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś autorem i redaktorem naczelnym czołowego formatu informacyjno-analitycznego w social mediach („Świat w Minucie”). 
Twoje treści zdobywają gigantyczne zasięgi, ponieważ łączysz 100% rzetelność agencyjną z bezkompromisowym, ciętym językiem i formą dopracowanych dwuczęściowych wątków.

ZADANIE:
Przygotuj DOKŁADNIE 5 NAJWAŻNIEJSZYCH I NAJBARDZIEJ ELEKTRYZUJĄCYCH WIADOMOŚCI w formacie JSON:
1. DOKŁADNIE 2 POZYCJE PILNE (Kategoria: "PILNE"):
   - Wybierz je z puli [ARTYKUŁY PILNE / KRYTYCZNE].
   - Muszą to być nagłe zdarzenia kryzysowe: atak nożownika, strzelanina, obława, ewakuacja, incydent bezpieczeństwa publicznego lub zamach.
2. DOKŁADNIE 3 POZYCJE STRATEGICZNE (Kategoria: "OBRONNOŚĆ", "POLSKA" lub "GEOPOLITYKA"):
   - Wybierz je z puli [ARTYKUŁY STRATEGICZNE].
   - Sprawy wschodniej flanki, zakupy zbrojeniowe, traktaty, sojusze, napięcia mocarstw.

ZASADA POJEDYNCZEJ KATEGORII:
Pole "category" to DOKŁADNIE JEDNO słowo: "PILNE", "OBRONNOŚĆ", "POLSKA" lub "GEOPOLITYKA".

ZASADA PORANNEGO FORMATOWANIA THREADS (DWA POSTY W JEDNYM WĄTKU):
Pole "threads_post" MUSI mieć łącznie 600-800 ZNAKÓW i być rozdzielone znacznikiem "---ODPOWIEDŹ---":
CZĘŚĆ 1 (Post główny – ok. 300-380 znaków):
- [Mocny tytuł z emotikoną 🚨, ⚠️, ⚔️ lub 🛡️]
- [Dramatyczny, podwójny hook z flagami i wykrzyknikiem]
- [1-2 zdania wprowadzające w sedno kryzysu, zakończone wezwaniem: (Szczegóły i tło w odpowiedzi 👇🧵)]

---ODPOWIEDŹ---

CZĘŚĆ 2 (Pierwsza odpowiedź pod postem – ok. 350-450 znaków):
- [Pogłębione rozwinięcie z konkretnymi faktami, liczbami i kulisami, których NIE MA na slajdzie]
- [Cięta pointa bez taryfy ulgowej obnażająca realia]
- [Pytanie prowokujące dyskusję kończące się '👇💬']

ZASADY DLA SLAJDU:
- "title": [Emotikona] [Konkretny, intrygujący nagłówek do 60 znaków].
- "hook": 1 dynamiczne zdanie uderzające w sedno.
- "summary": Dokładnie 2 zwięzłe zdania czystych faktów na slajd. Zakaz zmyślania!
- "comment": DOKŁADNIE 1 CIĘTE, BŁYSKOTLIWE ZDANIE (14-22 słowa, krótsze niż summary).
- "question": 1 pytanie do dyskusji kończące się '👇💬'.
- "image_query": 2-3 precyzyjne słowa kluczowe po angielsku do Pexels (np. 'police emergency sirens', 'fighter jet missile', 'military border patrol').

STRUKTURA JSON (Zwróć CZYSTĄ tablicę 5 obiektów):
[
  {{
    "category": "PILNE" lub "OBRONNOŚĆ" lub "POLSKA" lub "GEOPOLITYKA",
    "title": "[Emotikona] [Nagłówek]",
    "hook": "1 zdanie w sedno.",
    "summary": "2 zwięzłe zdania faktów.",
    "comment": "1 cięte zdanie z puentą (14-22 słowa).",
    "threads_post": "Część 1\\n\\n---ODPOWIEDŹ---\\n\\nCzęść 2",
    "question": "Pytanie do dyskusji 👇💬",
    "image_query": "słowa kluczowe Pexels",
    "link": "URL artykułu źródłowego"
  }}
]

Unikaj tematów: {json.dumps(excluded_topics[:15], ensure_ascii=False)}

DANE WEJŚCIOWE:
[ARTYKUŁY PILNE / KRYTYCZNE]:
{json.dumps(clean_breaking, ensure_ascii=False)}

[ARTYKUŁY STRATEGICZNE]:
{json.dumps(clean_standard, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.5,
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
pool = clean_breaking + clean_standard
while len(items) < TARGET_ITEMS:
    existing_links = {i.get('link') for i in items if isinstance(i, dict)}
    added = False
    for art in pool:
        if art['link'] not in existing_links and art['link'] != "#":
            clean_t = art.get('title', 'Pilne wydarzenie')
            is_breaking_item = len(items) < 2
            cat = "PILNE" if is_breaking_item else "OBRONNOŚĆ"
            icon = "🚨" if is_breaking_item else "🛡️"
            
            items.append({
                "category": cat,
                "title": f"{icon} {clean_t[:55]}",
                "hook": f"Kluczowe doniesienia agencyjne: {clean_t[:40]}.",
                "summary": "Służby i przedstawiciele władz analizują najnowszy rozwój sytuacji na miejscu zdarzenia. Trwa weryfikacja bezpośrednich następstw incydentu.",
                "comment": "Deklaracje o bezpieczeństwie natychmiast zderzają się z realną zdolnością reagowania w warunkach kryzysowych.",
                "threads_post": f"{icon} {clean_t[:55]}\n\nKluczowy zwrot akcji: sytuacja rozwija się błyskawicznie! 🚨⚡\n\nNajnowsze raporty wskazują na dynamiczny rozwój wydarzeń. Służby postawiono w stan najwyższej gotowości.\n(Szczegóły i tło w odpowiedzi 👇🧵)\n\n---ODPOWIEDŹ---\n\nKulisy tego incydentu obnażają słabe punkty dotychczasowych procedur reagowania. Kiedy opadną emocje, konieczna będzie natychmiastowa rewizja założeń operacyjnych.\n\nTo kolejny dowód, że spokój bywa pozorny, a realna próba następuje bez ostrzeżenia. ⏳🛡️\n\nJak oceniacie reakcję służb w tym kryzysowym momencie? 👇💬",
                "question": "Jak oceniacie przygotowanie systemów bezpieczeństwa na takie sytuacje? 👇💬",
                "image_query": "police siren emergency" if is_breaking_item else "military army patrol",
                "link": art.get("link", "#")
            })
            existing_links.add(art['link'])
            added = True
            if len(items) >= TARGET_ITEMS:
                break
    if not added:
        break

items = items[:TARGET_ITEMS]

# --- KASKADOWE POBIERANIE ZDJĘĆ Z POTRÓJNYM KLUCZEM DLA FRONTENDU ---
print("Dobieranie zdjęć (Artykuł -> Pexels -> Fallback)...")
source_ok = 0
seen_image_urls = set()

for item in items:
    url = item.get("link", "")
    q = item.get("image_query", "police emergency")
    
    selected_img = fetch_article_image(url)
    if selected_img and selected_img not in seen_image_urls:
        source_ok += 1
    else:
        selected_img = fetch_pexels_image_url(q)
        if not selected_img or selected_img in seen_image_urls:
            selected_img = FALLBACK_IMG
        
    clean_img = html.unescape(selected_img).replace("&amp;", "&")
    seen_image_urls.add(clean_img)
    
    # Potrójny klucz (pełna kompatybilność z każdym widokiem)
    item["image_url"] = clean_img
    item["source_image_url"] = clean_img
    item["image"] = clean_img

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

print(f"Zakończono. Pomyślnie zapisano {len(items)} pozycji (2 pilne + 3 strategiczne) w fast.json.")
