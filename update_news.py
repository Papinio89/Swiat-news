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

# Zrównoważone źródła: Polska, biznes, rynki + sekcja zdarzeń nietypowych/szokujących
RSS_URLS = [
    # --- POLSKA: GOSPODARKA, BIZNES, PRZEMYSŁ I KRAJ ---
    "https://www.money.pl/rss/",
    "https://businessinsider.com.pl/.rss",
    "https://www.bankier.pl/rss/wiadomosci.xml",
    "https://www.wnp.pl/rss/artykuly.xml",
    "https://archiwum.rp.pl/rss/ekonomia",
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",

    # --- ŚWIAT: RYNKI, FINANSE, SUROWCE ---
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=markets&sort=date",

    # --- GEOPOLITYKA I WYDARZENIA GLOBALNE ---
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://news.google.com/rss/search?q=world+news+geopolitics&hl=en-US&gl=US&ceid=US:en",

    # --- OBRONNOŚĆ ---
    "https://defence24.pl/rss",

    # --- CIEKAWOSTKI / ABSURDY / SZOKUJĄCE TEMATY DNIA ---
    "https://news.google.com/rss/search?q=weird+bizarre+shocking+investigation+scandal&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

MAX_AGE_HOURS = 24
MIN_ITEMS = 12


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


def normalize_category(cat: str) -> str:
    c = str(cat or "").upper().strip()
    if "POLSK" in c:
        return "POLSKA"
    if "OBRON" in c or "WOJSK" in c:
        return "OBRONNOŚĆ"
    if "TECH" in c or "AI" in c:
        return "TECHNOLOGIE"
    if "GEOPOLITYK" in c or "ŚWIAT" in c:
        return "GEOPOLITYKA"
    if "BIZNES" in c or "SPÓŁK" in c or "FIRM" in c:
        return "BIZNES"
    if "GOSPODARK" in c or "RYNK" in c or "FINANS" in c or "SUROWC" in c:
        return "GOSPODARKA"
    return "GOSPODARKA"


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
        category = normalize_category(item.get("category", "GOSPODARKA"))
        image_query = str(item.get("image_query", "world news")).strip()
        link = clean_link(str(item.get("link", "#")))

        # Pilnujemy, aby post Threads nie był skrócony (min. 400 znaków dla 2 postów)
        if len(title) < 10 or len(summary) < 20 or len(comment) < 10 or len(threads_post) < 400:
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
                import html as html_lib
                img = html_lib.unescape(m.group(1).strip()).replace("&amp;", "&")
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
            summary = getattr(entry, "summary", "").strip()
            clean_summary = re.sub(r'<[^>]+>', '', summary)[:250]
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 15:
                raw_articles.append({
                    "title": title,
                    "snippet": clean_summary,
                    "link": link
                })
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

print(f"Pobrano {len(raw_articles)} świeżych artykułów (max {MAX_AGE_HOURS}h)")

# --- ROZSZERZONE ARCHIWUM (14 SESJI WSTECZ) I WYKRYWANIE TEMATÓW KLUCZOWYCH ---
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

previous_titles = []
banned_entities = set()

sorted_sessions = sorted(archive_data.keys(), reverse=True)[:14]
for session_key in sorted_sessions:
    session_content = archive_data.get(session_key)
    if isinstance(session_content, dict) and "items" in session_content:
        for item in session_content.get("items", []):
            t = item.get("title", "")
            if t:
                previous_titles.append(t)
                words = re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{4,}', t.lower())
                for w in words:
                    if w not in {"polsce", "polski", "polaków", "nowy", "nowa", "nowe", "roku", "swiat", "przez", "tylko", "rzad", "rząd"}:
                        banned_entities.add(w)

# Ścisła deduplikacja wejściowa
filtered_raw_articles = []
for art in raw_articles:
    art_title = art["title"].lower()
    art_clean_words = set(re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{4,}', art_title))
    
    is_duplicate = False
    for prev_t in previous_titles:
        prev_clean_words = set(re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{4,}', prev_t.lower()))
        common = art_clean_words.intersection(prev_clean_words)
        if len(common) >= 2:
            is_duplicate = True
            break
            
    if not is_duplicate:
        filtered_raw_articles.append(art)

if len(filtered_raw_articles) < 10:
    filtered_raw_articles = raw_articles

print(f"Po ścisłej deduplikacji: {len(filtered_raw_articles)} unikalnych artykułów")

# --- PROMPT AI Z ROZSZERZONYM FORMATEM THREADS (DWUPAK: POST + ODPOWIEDŹ) ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

recent_titles_sample = previous_titles[:35]

prompt = f"""Jesteś autorem i redaktorem naczelnym czołowego formatu informacyjno-analitycznego w social mediach („Świat w Minucie” na Instagramie i Threads). 
Twoje posty generują potężne zasięgi, ponieważ tworzysz rozbudowane wątki – post główny intryguje, a odpowiedź pod nim dopina historię i wywołuje dyskusję.

Zadanie: Na podstawie poniższych artykułów stwórz DOKŁADNIE 14-15 NAJWAŻNIEJSZYCH I NAJCIEKAWSZYCH wiadomości w języku polskim w formacie JSON.

ZASADA 1: BEZWZGLĘDNY ZAKAZ POWTÓREK Z POPRZEDNICH DNI:
{json.dumps(recent_titles_sample, ensure_ascii=False)}

ZASADA 2: GWARANTOWANE MINIMUM 2 POZYCJE SZOKUJĄCE / ABSURDALNE / NIECODZIENNE.

ZASADA 3: ŚCISŁA DYSTRYBUCJA POJEDYNCZYCH KATEGORII:
Pole "category" to DOKŁADNIE JEDNO słowo:
- "POLSKA" (min. 4 pozycje)
- "GOSPODARKA" (min. 4 pozycje)
- "BIZNES" (2-3 pozycje)
- "GEOPOLITYKA" (2 pozycje)
- "OBRONNOŚĆ" (max 2 pozycje)
- "TECHNOLOGIE" (max 1-2 pozycje)

ZASADA 4: FORMAT THREADS (DWA POSTY: POST GŁÓWNY + ODPOWIEDŹ POD SPODEM):
Pole "threads_post" MUSI mieć łącznie 600-800 ZNAKÓW i być sformatowane dokładnie w 2 częściach oddzielonych znacznikiem "---ODPOWIEDŹ---":

CZĘŚĆ 1 (Post główny na Threads – ok. 300-380 znaków):
[Nagłówek z trafną emotikoną]
[Dynamiczny, podwójny hook z flagami i wykrzyknikiem]
[1-2 zdania wprowadzające w sedno kryzysu/sporu, kończące się zachętą do przeczytania szczegółów: (Szczegóły i tło w odpowiedzi 👇🧵)]

---ODPOWIEDŹ---

CZĘŚĆ 2 (Pierwsza odpowiedź pod postem – ok. 350-450 znaków):
[Pogłębione rozwinięcie z konkretnymi liczbami, kulisami i tłem, którego NIE MA na slajdzie graficznym]
[Cięta, bezkompromisowa pointa obnażająca hipokryzję lub koszty]
[Konkretne pytanie prowokujące czytelników do dyskusji kończące się '👇💬']

STRUKTURA JSON:
[
  {{
    "category": "POLSKA" lub "GOSPODARKA" lub "BIZNES" lub "GEOPOLITYKA" lub "OBRONNOŚĆ" lub "TECHNOLOGIE",
    "title": "[Emotikona] [Nagłówek do 60 znaków]",
    "hook": "1 zdanie uderzające w sedno.",
    "summary": "2 zwięzłe zdania faktów na slajd.",
    "comment": "1 dosadne zdanie z puentą (14-22 słowa, krótsze niż summary).",
    "threads_post": "Treść części 1\\n\\n---ODPOWIEDŹ---\\n\\nTreść części 2",
    "question": "1 pytanie do dyskusji kończące się '👇💬'.",
    "image_query": "2-3 konkretne słowa kluczowe po angielsku do Pexels",
    "link": "dokładnie URL artykułu"
  }}
]

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
            temperature=0.55,
            safety_settings=[
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
            ]
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

# Fallback awaryjny
if len(items) < MIN_ITEMS:
    existing_links = {i.get("link") for i in items}
    for art in filtered_raw_articles:
        if art["link"] not in existing_links and art["link"] != "#":
            clean_t = art.get("title", "Wydarzenie na arenie międzynarodowej")
            items.append({
                "category": "GOSPODARKA",
                "title": f"📈 {clean_t[:55]}",
                "hook": f"Kluczowe doniesienia agencyjne w sprawie: {clean_t[:40]}.",
                "summary": "Najnowsze ustalenia wskazują na istotną zmianę sytuacji rynkowej. Przedstawiciele branży i rządy analizują potencjalne konsekwencje.",
                "comment": "Urzędnicy znowu zapewniają o pełnej kontroli, choć rachunek za ich błędy jak zwykle zapłacą obywatele przy kasach.",
                "threads_post": f"📈 {clean_t[:55]}\n\nKluczowy zwrot na rynkach: nowe ustalenia zmieniają dotychczasowe reguły gry! 📊🚨\n\nNajnowsze raporty agencji prasowych wskazują na dynamiczny rozwój wydarzeń. Decydenci w pośpiechu przeliczają koszty scenariuszy.\n(Szczegóły i tło w odpowiedzi 👇🧵)\n\n---ODPOWIEDŹ---\n\nKulisy tej decyzji pokazują rosnącą presję na płynność finansową całego sektora. Kiedy gasną flesze kamer, twarda kalkulacja wymusza rewizję wielomiliardowych kontraktów.\n\nTo kolejny dowód, że deklaracje polityczne natychmiast zderzają się z rzeczywistością budżetową. 💼⏳\n\nJak oceniacie ten ruch z perspektywy kolejnych miesięcy? 📈👇💬",
                "question": "Jak ta decyzja wpłynie bezpośrednio na Twoje finanse lub portfel? 👇💬",
                "image_query": "financial market economy",
                "link": art["link"]
            })
            existing_links.add(art["link"])
            if len(items) >= 14:
                break

if items:
    cats = Counter([item["category"] for item in items])
    print("Rozkład pojedynczych kategorii:")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

print(f"Wygenerowano {len(items)} pozycji – OK")

# --- ZDJĘCIA: Pexels (karuzela) + og:image (Threads / IG Top 3) ---
print("Pobieranie zdjęć: Pexels + źródła artykułów...")
source_ok = 0
for item in items:
    q = item.get("image_query", "business economy news")
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

print(f"Zakończono pomyślnie. Zapisano {len(items)} unikalnych newsów z dwupakiem na Threads.")
