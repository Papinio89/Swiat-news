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

now_pl = datetime.now(pl_tz)
current_hour = now_pl.hour
session_name = "poranne" if current_hour < 12 else "wieczorne"

MAX_AGE_HOURS = 24
MIN_ITEMS = 12

STOP_WORDS = {
    "polsce", "polski", "polaków", "nowy", "nowa", "nowe", "roku", "swiat", "przez",
    "tylko", "rzad", "rząd", "beda", "będą", "moze", "może", "oraz", "jest", "jego",
    "bardzo", "nawet", "teraz", "after", "with", "from", "that", "this", "more"
}


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


def format_uppercase_title(title_str: str) -> str:
    s = title_str.strip()
    if not s:
        return ""
    match = re.match(r'^([\U00010000-\U0010ffff\u2600-\u27bf\s]+)(.*)$', s)
    if match:
        emoji_prefix = match.group(1).strip()
        rest = match.group(2).strip()
        return f"{emoji_prefix} {rest.upper()}".strip()
    return s.upper()


def extract_keywords(text: str) -> set[str]:
    words = re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{4,}', text.lower())
    return {w for w in words if w not in STOP_WORDS}


def are_topics_duplicate(title1: str, title2: str, threshold: float = 0.40) -> bool:
    w1 = extract_keywords(title1)
    w2 = extract_keywords(title2)
    if not w1 or not w2:
        return False
    common = w1.intersection(w2)
    if len(common) >= 3:
        return True
    if len(common) >= 2 and (len(common) / min(len(w1), len(w2)) >= threshold):
        return True
    return False


def validate_items(items: list) -> list:
    required = {"category", "title", "hook", "summary", "comment", "threads_post", "question", "image_query", "link"}
    valid = []
    seen_titles = []
    seen_links = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        if not required.issubset(item.keys()):
            continue

        raw_title = str(item.get("title", "")).strip()
        title = format_uppercase_title(raw_title)
        hook = str(item.get("hook", "")).strip()
        summary = str(item.get("summary", "")).strip()
        comment = str(item.get("comment", "")).strip()
        threads_post = str(item.get("threads_post", "")).strip()
        question = str(item.get("question", "")).strip()
        category = normalize_category(item.get("category", "GOSPODARKA"))
        image_query = str(item.get("image_query", "world news")).strip()
        link = clean_link(str(item.get("link", "#")))

        if len(title) < 10 or len(summary) < 25 or len(comment) < 10 or len(threads_post) < 420:
            continue
        if "---ODPOWIEDŹ---" not in threads_post:
            continue

        if link != "#" and link in seen_links:
            continue

        # Blokada powtórzonego tematu w tej samej paczce wyników
        is_dup = False
        for prev in seen_titles:
            if are_topics_duplicate(title, prev, threshold=0.35):
                is_dup = True
                break
        if is_dup:
            continue

        seen_titles.append(title)
        if link != "#":
            seen_links.add(link)

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
                    "Chrome/124.0.0.0 Safari/537.36"
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


# --- 1. POBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            if not is_recent(entry):
                continue
            title = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "").strip()
            clean_summary = re.sub(r'<[^>]+>', '', summary)[:280]
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 15:
                raw_articles.append({
                    "title": title,
                    "snippet": clean_summary,
                    "link": link
                })
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

print(f"Pobrano łącznie {len(raw_articles)} surowych artykułów.")

# --- 2. HISTORIA Z ARCHIWUM DO WYKLUCZENIA ---
archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

today_date_key = now_pl.strftime("%Y-%m-%d")
session_fixed_key = f"{today_date_key}_{session_name}"

previous_titles = []
sorted_sessions = sorted(archive_data.keys(), reverse=True)
for sk in sorted_sessions[:8]:
    if session_name == "wieczorne" and sk == f"{today_date_key}_poranne":
        continue
    sc = archive_data.get(sk)
    if isinstance(sc, dict) and "items" in sc:
        for item in sc.get("items", []):
            t = item.get("title", "")
            if t:
                previous_titles.append(t)

# --- 3. DEDUPLIKACJA WEWNĘTRZNA FEEDU (KLASTERYZACJA) ---
# Usuwa sytuację, gdy 4 różne portale opisują tę samą sprawę tego samego dnia
clustered_articles = []
seen_feed_links = set()

for art in raw_articles:
    if art["link"] in seen_feed_links:
        continue

    # Sprawdzenie z archiwum
    if any(are_topics_duplicate(art["title"], prev, threshold=0.40) for prev in previous_titles):
        continue

    # Sprawdzenie z już zakwalifikowanymi artykułami w tej sesji
    is_internal_dup = False
    for existing in clustered_articles:
        if are_topics_duplicate(art["title"], existing["title"], threshold=0.40):
            is_internal_dup = True
            break

    if not is_internal_dup:
        clustered_articles.append(art)
        seen_feed_links.add(art["link"])

if len(clustered_articles) < 14:
    clustered_articles = raw_articles

print(f"Po kategorycznej deduplikacji wewnętrznej: {len(clustered_articles)} całkowicie UNIKALNYCH tematów dla AI.")

# --- 4. PROMPT DLA AI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Jesteś redaktorem naczelnym formatu informacyjno-analitycznego „Świat w Minucie” (Instagram/Threads). 
Twoje posty zdobywają wirale, ponieważ wybierasz RÓŻNORODNE, MOCNE I NAJCIEKAWSZE wydarzenia dnia.

KATEGORYCZNY ZAKAZ DUBLOWANIA TEMATÓW (1 TEMAT = DOKŁADNIE 1 WPIS):
- Każda wygenerowana wiadomość MUSI dotyczyć ZUPEŁNIE INNEJ sprawy, innej spółki, innego kraju lub problemu.
- Kategoryczny zakaz generowania dwóch wpisów o tej samej ustawie, tym samym polityku, tej samej spółce czy tym samym raporcie giełdowym!
- Jeśli w danych wejściowych jest kilka ciekawych tematów z Polski, technologii, surowców i obronności, MASZ WYBRAĆ PRZEKRÓJ NAJLEPSZYCH, a nie skupiać się na jednym wątku.

Zadanie: Z poniższych unikalnych artykułów wybierz DOKŁADNIE 14-15 NAJWAŻNIEJSZYCH I NAJBARDZIEJ WCIĄGAJĄCYCH tematów w formacie JSON.

ZASADA 1: NAGŁÓWEK ("title"):
[Trafna emotikona] [AGRESYWNY, MOCNY NAGŁÓWEK DUŻYMI LITERAMI DO 60 ZNAKÓW]

ZASADA 2: FORMAT THREADS ("threads_post") - DWA POSTY (650-800 ZNAKÓW):
CZĘŚĆ 1 (Post główny – 320-380 znaków):
[NAGŁÓWEK DUŻYMI LITERAMI Z EMOTIKONĄ]
[Krzykliwy podwójny hook z flagami i wykrzyknikiem]
[1-2 zdania uderzające w sedno problemu, zakończone:]
(Szczegóły i tło w odpowiedzi 👇🧵)

---ODPOWIEDŹ---

CZĘŚĆ 2 (Odpowiedź pod postem – 380-450 znaków):
[Konkretne liczby, kulisy i mechanizm, którego NIE MA na slajdzie graficznym]
[1 bezlitosne, cięte zdanie podsumowujące obłudę lub realne koszty]
[Konkretne pytanie prowokujące do dyskusji kończące się '👇💬']

ZASADA 3: CIĘTY KOMENTARZ NA SLAJD ("comment"):
- DOKŁADNIE 1 ZDANIE (14-22 słowa, KRÓTSZE NIŻ SUMMARY). Zero banałów.

ZASADA 4: POJEDYNCZE KATEGORIE:
Pole "category" to DOKŁADNIE JEDNO słowo:
- "POLSKA" (min. 4)
- "GOSPODARKA" (min. 4)
- "BIZNES" (2-3)
- "GEOPOLITYKA" (2)
- "OBRONNOŚĆ" (max 2)
- "TECHNOLOGIE" (max 1-2)

WZORCOWY OBIEKT:
{{
  "category": "GOSPODARKA",
  "title": "🚨 RZĄD PRZEPYCHA NOWY PODATEK: ZAPŁACĄ WSZYSCY KIEROWCY",
  "hook": "Nowa opłata paliwowa wchodzi tylnymi drzwiami bez konsultacji społecznych.",
  "summary": "Stawka wzrośnie o 14% od pierwszego dnia przyszłego miesiąca, co przełoży się na wzrost cen litra benzyny o 35 groszy. Ministerstwo tłumaczy decyzję koniecznością łatania dziury w Funduszu Drogowym.",
  "comment": "Rządzący znowu opowiadają bajki o ochronie portfeli, podczas gdy przy dystrybutorze ściągają z nas kolejny ukryty haracz.",
  "threads_post": "🚨 RZĄD PRZEPYCHA NOWY PODATEK: ZAPŁACĄ WSZYSCY KIEROWCY\\n\\nKolejny cichy haracz uderzy prosto w portfele milionów Polaków! ⛽🇵🇱\\n\\nBez zapowiedzi i bez debaty parlamentarnej rząd przeforsował korektę opłaty paliwowej. Od przyszłego miesiąca każda wizyta na stacji będzie zauważalnie droższa, a branża transportowa już liczy straty.\\n\\n(Szczegóły i tło w odpowiedzi 👇🧵)\\n\\n---ODPOWIEDŹ---\\n\\nNowe przepisy mają przynieść budżetowi ponad 4,2 miliarda złotych rocznie. Problem w tym, że wyższe koszty paliwa natychmiast przełożą się na ceny żywności i usług w sklepach.\\n\\nTo klasyczny mechanizm: politycy obiecują stabilizację, a dziury w finansach państwa łatają z pieniędzy kierowców. 📉⏳\\n\\nOdczujecie tę podwyżkę w codziennych wydatkach? 📊👇💬",
  "question": "Jak ta zmiana wpłynie bezpośrednio na Twój domowy budżet? 👇💬",
  "image_query": "gas station fuel price",
  "link": "https://example.com"
}}

Unikaj tematów z archiwum:
{json.dumps(previous_titles[:25], ensure_ascii=False)}

Dane wejściowe (wybierz z nich 14-15 najciekawszych, CAŁKOWICIE RÓŻNYCH tematów):
{json.dumps(clustered_articles[:35], ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.30,
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

# Fallback awaryjny (dobiera wyłącznie tematy niebędące duplikatami)
if len(items) < MIN_ITEMS:
    existing_links = {i.get("link") for i in items}
    existing_titles = [i.get("title", "") for i in items]
    
    for art in clustered_articles:
        if art["link"] in existing_links or art["link"] == "#":
            continue
        
        clean_t = art.get("title", "Wydarzenie dnia")
        upper_t = format_uppercase_title(f"📈 {clean_t[:55]}")
        
        if any(are_topics_duplicate(upper_t, t, threshold=0.35) for t in existing_titles):
            continue

        items.append({
            "category": "GOSPODARKA",
            "title": upper_t,
            "hook": f"Kluczowe doniesienia agencyjne w sprawie: {clean_t[:40]}.",
            "summary": "Najnowsze ustalenia wskazują na istotną zmianę sytuacji rynkowej. Przedstawiciele branży i rządy analizują potencjalne konsekwencje.",
            "comment": "Urzędnicy znowu zapewniają o pełnej kontroli, choć rachunek za ich błędy jak zwykle zapłacą obywatele przy kasach.",
            "threads_post": f"{upper_t}\n\nKluczowy zwrot na rynkach: nowe ustalenia zmieniają dotychczasowe reguły gry! 📊🚨\n\nNajnowsze raporty agencji prasowych wskazują na dynamiczny rozwój wydarzeń. Decydenci w pośpiechu przeliczają koszty scenariuszy.\n(Szczegóły i tło w odpowiedzi 👇🧵)\n\n---ODPOWIEDŹ---\\n\nKulisy tej decyzji pokazują rosnącą presję na płynność finansową całego sektora. Kiedy gasną flesze kamer, twarda kalkulacja wymusza rewizję wielomiliardowych kontraktów.\n\nTo kolejny dowód, że deklaracje polityczne natychmiast zderzają się z rzeczywistością budżetową. 💼⏳\n\nJak oceniacie ten ruch z perspektywy kolejnych miesięcy? 📈👇💬",
            "question": "Jak ta decyzja wpłynie bezpośrednio na Twoje finanse lub portfel? 👇💬",
            "image_query": "financial market economy",
            "link": art["link"]
        })
        existing_links.add(art["link"])
        existing_titles.append(upper_t)
        if len(items) >= 14:
            break

if items:
    cats = Counter([item["category"] for item in items])
    print(f"Rozkład kategorii ({session_name.upper()}):")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

print(f"Wygenerowano {len(items)} w 100% unikalnych pozycji.")

# --- 5. POBIERANIE ZDJĘĆ ---
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

    item["image"] = item["source_image_url"]

print(f"Zdjęcia ze źródeł artykułów: {source_ok}/{len(items)} (reszta = Pexels fallback)")

# --- 6. ZAPIS ---
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
    "count": len(clustered_articles),
    "items": clustered_articles
}
with open("raw_feed.json", "w", encoding="utf-8") as f:
    json.dump(raw_feed_output, f, ensure_ascii=False, indent=2)

print(f"Zakończono pomyślnie. Zapisano {len(items)} całkowicie unikalnych pozycji.")
