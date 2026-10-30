#!/usr/bin/env python3
"""Świat w Minutę — generator newsów (Gemini + Pexels).

- Bezstratna archiwizacja z podziałem na miesiące (archive_YYYY_MM.json + archive_index.json)
- Eliminacja podwójnych hooków i powtórzeń w postach Threads
- Eliminacja śmieciowych tematów (Lotto, horoskopy, pająki, relacje live)
- Gwarantowane pobieranie zdjęć z Pexels (klucz wpisany na sztywno jako fallback)
- Ochrona przed zdominowaniem feedu przez jeden serwis
Zapisuje: news.json, raw_feed.json, archive.json oraz archiwa comiesięczne
"""
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from time import mktime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import feedparser
from google import genai
from google.genai import types

pl_tz = ZoneInfo("Europe/Warsaw")

# Klucz zdefiniowany w env lub wpisany bezpośrednio jako fallback
DEFAULT_PEXELS_KEY = "N9lZEHVVxzeo70Ool0sBLSnzpZAvgUxeRk7niJKr5pQdMRkQyIouz2QQ"
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip() or DEFAULT_PEXELS_KEY
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

MAX_AGE_HOURS = 24
MIN_ITEMS = 12
MAX_PER_SOURCE = 3
MAX_CANDIDATES = 42
SNIPPET_LEN = 500
MAIN_ARCHIVE_SESSIONS = 60

# Słowa kluczowe artykułów śmieciowych, które MUSZĄ zostać bezwzględnie zignorowane
JUNK_TOPICS_RE = re.compile(
    r"\b(lotto|kumulacj|wyniki losowania|multi multi|mini lotto|ekstra pensja|kaskada|"
    r"horoskop|znaki zodiaku|quiz|krzyżówka|przepis na|ciasto|sałatka|"
    r"gwiazdy tańczą|celebryt|show-biznes|plotk|stylizacj|pająk|pająki|babie lato|"
    r"skrót meczu|relacja na żywo|wynik meczu|bramki z meczu|tabela ligowa)\b",
    re.I
)

# Sprawdzone, proste frazy angielskie dla Pexels per kategoria
CATEGORY_PEXELS_DEFAULTS = {
    "POLSKA": ["poland warsaw", "court law", "police officer", "parliament building"],
    "GOSPODARKA": ["stock market", "money currency", "finance economy", "bank vault"],
    "BIZNES": ["corporate office", "business meeting", "startup technology", "logistics shipping"],
    "GEOPOLITYKA": ["diplomacy summit", "world flags", "united nations", "protest crowd"],
    "OBRONNOŚĆ": ["military army", "soldiers patrol", "armored vehicle", "air force jet"],
    "TECHNOLOGIE": ["artificial intelligence", "cyber security", "data center server", "microchip tech"],
}

FALLBACK_IMAGES = [
    {"url": "https://images.unsplash.com/photo-1534447677768-be436bb09401?q=80&w=1000&auto=format&fit=crop", "credit": "Unsplash", "credit_url": "https://unsplash.com"},
    {"url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=1000&auto=format&fit=crop", "credit": "NASA / Unsplash", "credit_url": "https://unsplash.com"},
    {"url": "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?q=80&w=1000&auto=format&fit=crop", "credit": "Unsplash", "credit_url": "https://unsplash.com"},
    {"url": "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?q=80&w=1000&auto=format&fit=crop", "credit": "Unsplash", "credit_url": "https://unsplash.com"},
    {"url": "https://images.unsplash.com/photo-1507679799987-c73779587ccf?q=80&w=1000&auto=format&fit=crop", "credit": "Unsplash", "credit_url": "https://unsplash.com"},
]

FEEDS = [
    # --- POLSKA: wiadomości ---
    ("https://www.polsatnews.pl/rss/polska.xml", "pl", "POLSKA", "Polsat News"),
    ("https://www.polsatnews.pl/rss/swiat.xml", "pl", "GEOPOLITYKA", "Polsat News"),
    ("https://www.polsatnews.pl/rss/biznes.xml", "pl", "GOSPODARKA", "Polsat News"),
    ("https://www.polsatnews.pl/rss/technologie.xml", "pl", "TECHNOLOGIE", "Polsat News"),
    ("https://tvn24.pl/najnowsze.xml", "pl", "POLSKA", "TVN24"),
    ("https://tvn24.pl/biznes.xml", "pl", "GOSPODARKA", "TVN24"),
    ("https://fakty.interia.pl/feed", "pl", "POLSKA", "Interia"),
    ("https://biznes.interia.pl/feed", "pl", "GOSPODARKA", "Interia Biznes"),
    ("https://wiadomosci.onet.pl/.feed", "pl", "POLSKA", "Onet"),
    ("https://wiadomosci.wp.pl/rss.xml", "pl", "POLSKA", "WP Wiadomości"),
    ("https://wiadomosci.gazeta.pl/pub/rss/wiadomosci_kraj.htm", "pl", "POLSKA", "Gazeta.pl"),
    ("https://notesfrompoland.com/feed/", "en", "POLSKA", "Notes from Poland"),
    # --- POLSKA: gospodarka, biznes, obronność ---
    ("https://www.money.pl/rss/", "pl", "GOSPODARKA", "Money.pl"),
    ("https://businessinsider.com.pl/.rss", "pl", "BIZNES", "Business Insider Polska"),
    ("https://www.bankier.pl/rss/wiadomosci.xml", "pl", "GOSPODARKA", "Bankier.pl"),
    ("https://www.wnp.pl/rss/artykuly.xml", "pl", "GOSPODARKA", "WNP.pl"),
    ("https://archiwum.rp.pl/rss/ekonomia", "pl", "GOSPODARKA", "Rzeczpospolita"),
    ("https://defence24.pl/rss", "pl", "OBRONNOŚĆ", "Defence24"),
    ("https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl", "pl", "POLSKA", "Google News"),
    # --- ŚWIAT: rynki, finanse, surowce ---
    ("https://feeds.bloomberg.com/markets/news.rss", "en", "GOSPODARKA", "Bloomberg"),
    ("https://search.cnbc.com/rs/search/view.html?partnerId=2000&keywords=markets&sort=date", "en", "GOSPODARKA", "CNBC"),
    # --- GEOPOLITYKA I ŚWIAT ---
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "en", "GEOPOLITYKA", "BBC News"),
    ("https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml", "en", "GEOPOLITYKA", "BBC News"),
    ("https://www.theguardian.com/world/rss", "en", "GEOPOLITYKA", "The Guardian"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "en", "GEOPOLITYKA", "Al Jazeera"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "en", "GEOPOLITYKA", "The New York Times"),
    ("https://rss.dw.com/rdf/rss-en-all", "en", "GEOPOLITYKA", "Deutsche Welle"),
    ("https://news.google.com/rss/search?q=world+news+geopolitics&hl=en-US&gl=US&ceid=US:en", "en", "GEOPOLITYKA", "Google News"),
    # --- TECHNOLOGIE / AI ---
    ("https://feeds.arstechnica.com/arstechnica/index", "en", "TECHNOLOGIE", "Ars Technica"),
    ("https://www.theverge.com/rss/index.xml", "en", "TECHNOLOGIE", "The Verge"),
]

POLISH_MONTHS = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}

POLISH_MONTHS_NAMES = {
    1: "Styczeń", 2: "Luty", 3: "Marzec", 4: "Kwiecień",
    5: "Maj", 6: "Czerwiec", 7: "Lipiec", 8: "Sierpień",
    9: "Wrzesień", 10: "Październik", 11: "Listopad", 12: "Grudzień"
}

STOP_WORDS = {
    "polsce", "polski", "polaków", "nowy", "nowa", "nowe", "roku", "swiat", "przez",
    "tylko", "rzad", "rząd", "beda", "będą", "moze", "może", "oraz", "jest", "jego",
    "bardzo", "nawet", "teraz", "after", "with", "from", "that", "this", "more"
}
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}

BAD_ALT_RE = re.compile(r"hurricane|tornado|flood|earthquake|tsunami|cemetery|grave|funeral|coffin|abandoned|ruins|corpse", re.I)
GENERIC_WORDS = {"view", "sign", "signs", "street", "night", "scene", "modern", "aerial", "system", "line",
                 "tracks", "landscape", "area", "concept", "background", "city"}


# ───────────────────────── NARZĘDZIA ─────────────────────────
def clean_link(url: str) -> str:
    if not url or url == "#":
        return "#"
    try:
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "at_medium", "at_campaign", "fbclid", "gclid", "mc_cid", "mc_eid"
        }
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "#"
        if parsed.query:
            qs = parse_qs(parsed.query)
            clean_qs = {k: v[0] for k, v in qs.items() if k not in tracking_params}
            if clean_qs:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urllib.parse.urlencode(clean_qs)}"
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return url
    except Exception:
        return url


def norm_link(url: str) -> str:
    try:
        p = urlparse(str(url).strip().lower())
        host = p.netloc.removeprefix("www.")
        return f"{host}{p.path.rstrip('/')}" + (f"?{p.query}" if "news.google.com" in host and p.query else "")
    except Exception:
        return str(url)


def short_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:10]


def is_recent(entry) -> bool:
    published = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not published:
        return True
    try:
        pub_dt = datetime.fromtimestamp(mktime(published), tz=pl_tz)
        return datetime.now(pl_tz) - pub_dt <= timedelta(hours=MAX_AGE_HOURS)
    except Exception:
        return True


def normalize_category(cat: str) -> str:
    c = str(cat or "").upper().strip()
    if "POLSK" in c:
        return "POLSKA"
    if "OBRON" in c or "WOJSK" in c:
        return "OBRONNOŚĆ"
    if "TECH" in c or c == "AI":
        return "TECHNOLOGIE"
    if "GEOPOLITYK" in c or "ŚWIAT" in c:
        return "GEOPOLITYKA"
    if "BIZNES" in c or "SPÓŁK" in c or "FIRM" in c:
        return "BIZNES"
    return "GOSPODARKA"


def truncate_smart(text: str, max_len: int = 65) -> str:
    """Skraca tekst do pełnego wyrazu, nie ucinając słów w połowie."""
    s = text.strip()
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    last_space = cut.rfind(" ")
    if last_space > 25:
        cut = cut[:last_space]
    return cut.strip()


def format_uppercase_title(title_str: str) -> str:
    s = re.sub(r"\s+\ufe0f", "\ufe0f", title_str.strip())
    if not s:
        return ""
    match = re.match(r'^([\U00010000-\U0010ffff\u2600-\u27bf\ufe0f\s]+)(.*)$', s)
    if match:
        emoji_prefix = match.group(1).strip()
        rest = match.group(2).strip()
        return f"{emoji_prefix} {truncate_smart(rest, 65).upper()}".strip()
    return truncate_smart(s, 65).upper()


def extract_keywords(text: str) -> set:
    words = re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]{4,}', text.lower())
    return {w for w in words if w not in STOP_WORDS}


def are_topics_duplicate(title1: str, title2: str, threshold: float = 0.40) -> bool:
    w1, w2 = extract_keywords(title1), extract_keywords(title2)
    if not w1 or not w2:
        return False
    common = w1 & w2
    if len(common) >= 3:
        return True
    return len(common) >= 2 and len(common) / min(len(w1), len(w2)) >= threshold


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def gen_json(client, prompt: str, temperature: float, safety=None):
    cfg = dict(response_mime_type="application/json", temperature=temperature)
    if safety:
        cfg["safety_settings"] = safety
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=types.GenerateContentConfig(**cfg))
    text = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip()).strip()
    return json.loads(text)


# ───────────────────────── RSS ─────────────────────────
def load_feed(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"],
                                                   "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return feedparser.parse(r.read()), None
    except Exception as ex:
        return None, str(ex)[:70]


def fetch_feeds() -> list:
    articles = []
    for url, lang, cat, default_name in FEEDS:
        feed, err = load_feed(url)
        if feed is None:
            continue
        n = 0
        for entry in feed.entries[:14]:
            if not is_recent(entry):
                continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if len(title) <= 15 or link == "#":
                continue
            
            # FILTR TEMATÓW ŚMIECIOWYCH
            if JUNK_TOPICS_RE.search(title) or JUNK_TOPICS_RE.search(link):
                continue

            src = default_name
            try:
                src = (entry.get("source", {}) or {}).get("title") or default_name
            except Exception:
                pass
            if src and title.endswith(f" - {src}"):
                title = title[: -len(src) - 3].strip()
            summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "")).strip()
            snippet = html_lib.unescape(re.sub(r"\s+", " ", summary))[:SNIPPET_LEN]
            articles.append({"title": title, "snippet": snippet, "link": link, "source_name": src,
                             "lang": lang, "feed_category": cat})
            n += 1
        print(f"  RSS {default_name:<24} {n:>2} art.")
    return articles


def interleave(items: list, per_source: int, limit: int) -> list:
    by_src = defaultdict(list)
    for a in items:
        by_src[a["source_name"]].append(a)
    queues = [v[:per_source] for v in by_src.values()]
    out = []
    while queues and len(out) < limit:
        for q in queues:
            if q and len(out) < limit:
                out.append(q.pop(0))
        queues = [q for q in queues if q]
    return out


# ───────────────────────── ZDJĘCIA ─────────────────────────
def pick_photo(photos: list, query: str, used: set):
    words = set(re.findall(r"[a-z]{4,}", query.lower())) - GENERIC_WORDS
    best, best_score = None, -1
    for p in photos:
        src = p.get("src", {})
        u = src.get("large") or src.get("medium")
        alt = (p.get("alt") or "").lower()
        if not u or u in used or BAD_ALT_RE.search(alt):
            continue
        score = sum(1 for w in words if w in alt)
        if score > best_score:
            best, best_score = (p, u), score
    return best


def fetch_pexels(query: str, used: set, fallback_cat: str = "GOSPODARKA", retries: int = 2):
    if not PEXELS_API_KEY:
        return None

    q_clean = re.sub(r"[^a-zA-Z\s]", " ", query).strip()
    words = [w for w in q_clean.split() if len(w) > 2]

    queries_to_try = []
    if len(words) >= 2:
        queries_to_try.append(f"{words[0]} {words[1]}")
    if len(words) >= 1:
        queries_to_try.append(words[0])

    queries_to_try.extend(CATEGORY_PEXELS_DEFAULTS.get(fallback_cat, ["news economy"]))

    for q in queries_to_try:
        for attempt in range(retries + 1):
            try:
                url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(q)}&per_page=15&orientation=landscape"
                req = urllib.request.Request(url, headers={"Authorization": PEXELS_API_KEY, "User-Agent": "SwiatWMinute-Bot/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    photos = json.loads(resp.read().decode("utf-8")).get("photos", [])
                hit = pick_photo(photos, q, used)
                if hit:
                    p, u = hit
                    used.add(u)
                    src = p.get("src", {})
                    return {
                        "url": u,
                        "portrait": src.get("portrait") or src.get("large2x") or u,
                        "credit": p.get("photographer", ""),
                        "credit_url": p.get("url", "")
                    }
                break
            except Exception:
                if attempt == retries:
                    break
                time.sleep(1)
    return None


def fetch_article_image(url: str):
    if not url or url == "#" or "news.google.com" in url:
        return None
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=7) as resp:
            page = resp.read(800_000).decode("utf-8", errors="ignore")
        for pat in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']'):
            m = re.search(pat, page, re.I)
            if m:
                img = html_lib.unescape(m.group(1).strip())
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http") and not img.endswith(".svg"):
                    return img
    except Exception:
        pass
    return None


# ───────────────────────── WALIDACJA ─────────────────────────
def validate_items(items: list) -> list:
    required = {"category", "title", "hook", "summary", "comment", "threads_post", "question", "image_query", "link"}
    valid, seen_titles, seen_links = [], [], set()
    for item in items:
        if not isinstance(item, dict) or not required.issubset(item.keys()):
            continue
        title = format_uppercase_title(str(item.get("title", "")))
        hook = str(item.get("hook", "")).strip()
        summary = str(item.get("summary", "")).strip()
        comment = str(item.get("comment", "")).strip()
        threads_post = str(item.get("threads_post", "")).strip()
        question = str(item.get("question", "")).strip()
        category = normalize_category(item.get("category", "GOSPODARKA"))
        image_query = str(item.get("image_query", "world news")).strip()
        link = clean_link(str(item.get("link", "#")))
        
        # Elastyczniejszy limit, by nie odrzucać poprawnych odpowiedzi AI
        if len(title) < 10 or len(summary) < 20 or len(comment) < 8 or len(threads_post) < 250:
            continue
        if "---ODPOWIEDŹ---" not in threads_post:
            continue
        if link != "#" and link in seen_links:
            continue
        if any(are_topics_duplicate(title, prev, threshold=0.35) for prev in seen_titles):
            continue
        seen_titles.append(title)
        if link != "#":
            seen_links.add(link)
        valid.append({"category": category, "title": title, "hook": hook, "summary": summary, "comment": comment,
                      "threads_post": threads_post, "question": question, "image_query": image_query, "link": link})
    return valid


def resolve_sources(items: list, candidates: list) -> list:
    by_link = {norm_link(a["link"]): a for a in candidates}
    out, used = [], set()
    for it in items:
        a = by_link.get(norm_link(it["link"]))
        if not a:
            kw = extract_keywords(it["title"] + " " + it["summary"])
            best, best_n = None, 0
            for c in candidates:
                n = len(kw & extract_keywords(c["title"]))
                if n > best_n:
                    best, best_n = c, n
            a = best if best_n >= 2 else None
        if not a or a["link"] in used:
            continue
        used.add(a["link"])
        it["link"] = a["link"]
        it["source_name"] = a["source_name"]
        it["source_title"] = a["title"]
        it["lang"] = a["lang"]
        it["id"] = short_id(a["link"])
        out.append(it)
    return out


DEDUPE_PROMPT = """Poniżej NOWE pozycje i ARCHIWUM (to już opublikowano). Dla każdej nowej pozycji oceń, czy opisuje TO SAMO
WYDARZENIE (ten sam incydent, decyzję, raport, atak, sprawę) co którakolwiek pozycja z archiwum — niezależnie od źródła i języka.
Nowy, istotnie różny rozwój sprawy (nowe fakty, nowa decyzja) NIE jest powtórką.
Zwróć JSON: {"repeats": [id, id, ...]} — tylko id powtórek (pusta tablica, jeśli brak).

NOWE:
__NEW__

ARCHIWUM:
__OLD__
"""


def drop_repeated_events(client, items: list, known_events: list) -> list:
    if not items or not known_events:
        return items
    new = [{"id": i["id"], "title": i["title"], "summary": i["summary"][:200]} for i in items]
    prompt = DEDUPE_PROMPT.replace("__NEW__", json.dumps(new, ensure_ascii=False)).replace("__OLD__", json.dumps(known_events[:90], ensure_ascii=False))
    try:
        data = gen_json(client, prompt, 0.0)
        ids = {str(x) for x in (data.get("repeats", []) if isinstance(data, dict) else [])}
    except Exception as ex:
        print(f"  kontrola powtórzeń nie powiodła się: {ex}")
        return items
    for i in items:
        if i["id"] in ids:
            print(f"  ↺ powtórka wydarzenia z archiwum → {i['title'][:55]}")
    return [i for i in items if i["id"] not in ids]


def translate_titles(client, titles: list) -> list:
    if not titles:
        return []
    prompt = ("Przetłumacz na polski poniższe nagłówki prasowe. Zachowaj sens i nazwy własne, niczego nie dodawaj. "
              "Zwróć WYŁĄCZNIE tablicę JSON ze stringami, dokładnie tyle elementów co na wejściu, w tej samej kolejności.\n"
              + json.dumps(titles, ensure_ascii=False))
    try:
        data = gen_json(client, prompt, 0.1)
        if isinstance(data, list) and len(data) == len(titles):
            return [str(x).strip() or t for x, t in zip(data, titles)]
    except Exception as ex:
        print(f"  tłumaczenie nagłówków nie powiodło się: {ex}")
    return titles


# ───────────────────────── PROMPT AI (FORMAT THREADS BEZ POWTÓRZEŃ) ─────────────────────────
def build_prompt(previous_titles: list, candidates: list) -> str:
    ai_input = [{"title": a["title"], "snippet": a["snippet"], "link": a["link"], "source": a["source_name"]} for a in candidates]
    return f"""Jesteś redaktorem naczelnym formatu informacyjno-analitycznego „Świat w Minutę” (Instagram/Threads). 
Twoje posty zdobywają wirale, ponieważ są zwięzłe, merytoryczne i wolne od pustosłowia.
Kategoryczny zakaz pisania o plotkach, lotto, horoskopach i ciekawostkach przyrodniczych.

KATEGORYCZNY ZAKAZ DUBLOWANIA TEMATÓW (1 TEMAT = DOKŁADNIE 1 WPIS):
- Każda wygenerowana wiadomość MUSI dotyczyć ZUPEŁNIE INNEJ sprawy!

Zadanie: Z poniższych artykułów wybierz DOKŁADNIE 15-16 NAJWAŻNIEJSZYCH tematów w formacie JSON.

ZASADA 1: NAGŁÓWEK ("title"):
[Trafna emotikona] [MOCNY, AGRESYWNY NAGŁÓWEK DUŻYMI LITERAMI DO 60 ZNAKÓW]

ZASADA 2: FORMAT THREADS ("threads_post") - DWA POSTY BEZ POWTÓRZEŃ I BEZ PODWÓJNYCH HOOKÓW:
CZĘŚĆ 1 (Post główny – 200-280 znaków):
[NAGŁÓWEK DUŻYMI LITERAMI Z EMOTIKONĄ]

[DOKŁADNIE JEDNO mocne, konkretne zdanie wprowadzające – co się wydarzyło, zakończone flagą lub emotikoną!]
[1 zdanie wyjaśniające kluczowy skutek lub liczbę.]

(Szczegóły i tło w odpowiedzi 👇🧵)

---ODPOWIEDŹ---

CZĘŚĆ 2 (Odpowiedź pod postem – 320-400 znaków):
[Zupełnie nowe fakty, kulisy i mechanizm, KTÓRYCH NIE BYŁO w poście 1!]
[1 ostre, cięte zdanie obnażające hipokryzję, koszty dla obywateli lub realne intencje polityków.]

[Jedno konkretne pytanie prowokujące do merytorycznej dyskusji kończące się '👇💬']

ZASADA 3: CIĘTY KOMENTARZ NA SLAJD ("comment"):
- DOKŁADNIE 1 ZDANIE (14-22 słowa). Wyrazisty wniosek, zero banałów.

ZASADA 4: ZAPYTANIE DO ZDJĘCIA ("image_query"):
- Dokładnie 1-2 proste słowa po angielsku (np. "courtroom", "military", "parliament", "currency", "police").

ZASADA 5: KATEGORIE:
Pole "category" to DOKŁADNIE JEDNO słowo: POLSKA, GOSPODARKA, BIZNES, GEOPOLITYKA, OBRONNOŚĆ, TECHNOLOGIE.

WZORCOWY OBIEKT:
{{
  "category": "GOSPODARKA",
  "title": "🚨 RZĄD PRZEPYCHA NOWY PODATEK: ZAPŁACĄ WSZYSCY KIEROWCY",
  "hook": "Nowa opłata paliwowa wchodzi tylnymi drzwiami bez konsultacji społecznych.",
  "summary": "Stawka wzrośnie o 14% od pierwszego dnia przyszłego miesiąca, co przełoży się na wzrost cen litra benzyny o 35 groszy.",
  "comment": "Rządzący znowu opowiadają bajki o ochronie portfeli, podczas gdy przy dystrybutorze ściągają z nas kolejny ukryty haracz.",
  "threads_post": "🚨 RZĄD PRZEPYCHA NOWY PODATEK: ZAPŁACĄ WSZYSCY KIEROWCY\\n\\nMinisterstwo przeforsowało korektę opłaty paliwowej, która od przyszłego miesiąca uderzy w portfele milionów Polaków! ⛽🇵🇱\\n\\nKażda wizyta na stacji będzie droższa o kilkanaście złotych, a branża transportowa już zapowiada podwyżki cen towarów.\\n\\n(Szczegóły i tło w odpowiedzi 👇🧵)\\n\\n---ODPOWIEDŹ---\\n\\nNowe przepisy mają przynieść budżetowi ponad 4,2 miliarda złotych rocznie na łatanie dziury w Funduszu Drogowym. Problem w tym, że wyższe koszty paliwa natychmiast przełożą się na ceny żywności i usług w sklepach.\\n\\nPolitycy obiecują stabilizację, a dziury w finansach państwa po cichu łatają z pieniędzy kierowców. 📉⏳\\n\\nOdczujecie tę podwyżkę w codziennych wydatkach? 📊👇💬",
  "question": "Jak ta zmiana wpłynie bezpośrednio na Twój domowy budżet? 👇💬",
  "image_query": "gas station",
  "link": "https://example.com"
}}

Unikaj tematów z archiwum:
{json.dumps(previous_titles[:25], ensure_ascii=False)}

Dane wejściowe:
{json.dumps(ai_input, ensure_ascii=False)}
"""

SAFETY = [
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
]


# ───────────────────────── ARCHIWIZACJA COMIESIĘCZNA ─────────────────────────
def save_monthly_archive(session_key: str, session_data: dict, now_dt: datetime):
    year_month_key = now_dt.strftime("%Y_%m")
    month_file = f"archive_{year_month_key}.json"

    month_data = {}
    if os.path.exists(month_file):
        try:
            with open(month_file, encoding="utf-8") as f:
                month_data = json.load(f)
        except Exception:
            month_data = {}

    month_data[session_key] = session_data
    write_json(month_file, month_data)

    index_file = "archive_index.json"
    index_data = []
    if os.path.exists(index_file):
        try:
            with open(index_file, encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception:
            index_data = []

    month_label = f"{POLISH_MONTHS_NAMES[now_dt.month]} {now_dt.year}"
    if not any(item.get("file") == month_file for item in index_data):
        index_data.append({
            "key": year_month_key,
            "label": month_label,
            "file": month_file,
            "year": now_dt.year,
            "month": now_dt.month
        })
        index_data.sort(key=lambda x: (x["year"], x["month"]), reverse=True)
        write_json(index_file, index_data)


# ───────────────────────── GŁÓWNY PRZEPŁYW ─────────────────────────
def main():
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        sys.exit("Brak GEMINI_API_KEY")

    now_pl = datetime.now(pl_tz)
    session_name = "poranne" if now_pl.hour < 12 else "wieczorne"
    session_key = f"{now_pl.strftime('%Y-%m-%d')}_{session_name}"

    print("1. Pobieranie RSS...")
    raw_articles = fetch_feeds()
    print(f"   pobrano {len(raw_articles)} przefiltrowanych artykułów")
    if not raw_articles:
        sys.exit("Brak artykułów z RSS — przerywam bez nadpisywania")

    archive_data = {}
    if os.path.exists("archive.json"):
        try:
            with open("archive.json", encoding="utf-8") as f:
                archive_data = json.load(f)
        except Exception:
            archive_data = {}

    known_links, previous_titles, known_events = set(), [], []
    for n, sk in enumerate(sorted(archive_data.keys(), reverse=True)):
        sc = archive_data.get(sk)
        if sk == session_key or not isinstance(sc, dict):
            continue
        for item in sc.get("items", []):
            if item.get("link"):
                known_links.add(norm_link(item["link"]))
            if n < 8:
                previous_titles += [t for t in (item.get("title"), item.get("source_title")) if t]
                known_events.append(f"{item.get('title', '')} — {str(item.get('summary', ''))[:160]}")

    print("2. Deduplikacja i grupowanie tematów...")
    clustered, seen = [], set()
    for art in raw_articles:
        k = norm_link(art["link"])
        if k in seen or k in known_links:
            continue
        if any(are_topics_duplicate(art["title"], prev, threshold=0.40) for prev in previous_titles):
            continue
        if any(are_topics_duplicate(art["title"], ex["title"], threshold=0.40) for ex in clustered):
            continue
        clustered.append(art)
        seen.add(k)
    print(f"   unikalnych nowych tematów: {len(clustered)}")
    if not clustered:
        sys.exit("Brak nowych tematów")

    candidates = interleave(clustered, MAX_PER_SOURCE, MAX_CANDIDATES)
    print(f"   kandydaci dla AI: {len(candidates)} z {len({c['source_name'] for c in candidates})} źródeł")

    print("3. Analiza i generowanie przez Gemini...")
    client = genai.Client(api_key=gemini_key)
    prompt = build_prompt(previous_titles, candidates)
    items = []
    for attempt in (1, 2):
        try:
            parsed = gen_json(client, prompt, 0.30, SAFETY)
            raw_items = parsed if isinstance(parsed, list) else parsed.get("items", [])
            got = resolve_sources(validate_items(raw_items), candidates)
            print(f"   próba {attempt}: {len(got)} poprawnych pozycji z {len(raw_items)}")
            if len(got) > len(items):
                items = got
            if len(items) >= MIN_ITEMS:
                break
        except Exception as e:
            print(f"   próba {attempt}: błąd AI: {e}")

    items = drop_repeated_events(client, items, known_events)

    # ZABEZPIECZENIE: Jeśli Gemini zwróciło za mało pozycji, nie psujemy wydania bzdurami
    if len(items) < 8:
        print(f"❌ Gemini zwróciło za mało pozycji ({len(items)}). Prawdopodobnie brak kredytów lub błąd API.")
        sys.exit("Przerywam działanie — zachowuję poprzednie poprawne wydanie w news.json.")

    # Uzupełnienie brakujących 2-3 pozycji (bez ucinania słów w połowie)
    if len(items) < MIN_ITEMS:
        existing = {i["link"] for i in items}
        titles = [i["title"] for i in items]
        for art in candidates:
            if len(items) >= MIN_ITEMS:
                break
            if art["link"] in existing or len(art["snippet"]) < 25 or art["lang"] != "pl":
                continue
            
            clean_title = truncate_smart(art['title'], 60)
            upper_t = format_uppercase_title(f"📰 {clean_title}")
            if any(are_topics_duplicate(upper_t, t, threshold=0.35) for t in titles + previous_titles):
                continue
            cat = normalize_category(art["feed_category"])
            items.append({
                "id": short_id(art["link"]),
                "category": cat,
                "title": upper_t,
                "hook": f"Kluczowe doniesienia: {clean_title}.",
                "summary": art["snippet"],
                "comment": f"Decyzja w obszarze {cat.lower()} rodzi istotne konsekwencje, które wkrótce odczują obywatele.",
                "threads_post": f"{upper_t}\n\nKluczowe doniesienia agencyjne. (Szczegóły w odpowiedzi 👇🧵)\n\n---ODPOWIEDŹ---\n\n{art['snippet'][:300]}\n\nJak to oceniacie? 👇💬",
                "question": "Jak ta sprawa wpłynie na sytuację w kraju? 👇💬",
                "image_query": CATEGORY_PEXELS_DEFAULTS.get(cat, ["news"])[0],
                "link": art["link"],
                "source_name": art["source_name"],
                "source_title": art["title"],
                "lang": art["lang"],
                "auto": True
            })
            existing.add(art["link"])
            titles.append(upper_t)

    print("4. Dobieranie zdjęć (Pexels + OG)...")
    used_imgs = set()

    for idx, item in enumerate(items):
        cat = item.get("category", "GOSPODARKA")
        q = item.get("image_query") or "news"
        og = fetch_article_image(item["link"])
        item["source_image_url"] = og or ""

        # Pobieramy dopasowany Pexels
        ph = fetch_pexels(q, used_imgs, fallback_cat=cat)

        if ph:
            item.update(
                image_url=ph["url"],
                image_portrait=ph["portrait"],
                image_credit=ph["credit"],
                image_credit_url=ph["credit_url"],
                image_illustrative=True,
                image_source="pexels"
            )
        elif og:
            item.update(
                image_url=og,
                image_portrait=og,
                image_credit="",
                image_credit_url="",
                image_illustrative=False,
                image_source="article"
            )
        else:
            fb = FALLBACK_IMAGES[idx % len(FALLBACK_IMAGES)]
            item.update(
                image_url=fb["url"],
                image_portrait=fb["url"],
                image_credit=fb["credit"],
                image_credit_url=fb["credit_url"],
                image_illustrative=True,
                image_source="fallback"
            )

        item["image"] = item["image_url"]

    print("5. Zapisywanie wydania...")
    date_pretty = f"{now_pl.day} {POLISH_MONTHS[now_pl.month]} {now_pl.year}"
    output_data = {
        "date": date_pretty,
        "time": now_pl.strftime("%H:%M"),
        "timestamp": now_pl.strftime("%Y-%m-%d_%H:%M"),
        "items": items
    }
    write_json("news.json", output_data)

    clean_items = [{k: v for k, v in i.items() if k not in ("threads_post", "question", "image_query")} for i in items]
    session_archive_data = {**output_data, "items": clean_items}

    archive_data[session_key] = session_archive_data
    for old in sorted(archive_data.keys())[:-MAIN_ARCHIVE_SESSIONS]:
        del archive_data[old]
    write_json("archive.json", archive_data)

    save_monthly_archive(session_key, session_archive_data, now_pl)

    chosen = {norm_link(i["link"]) for i in items}
    raw_out = [dict(a) for a in clustered[:80] if norm_link(a["link"]) not in chosen]
    to_tr = [a for a in raw_out if a["lang"] == "en"]
    for a, t in zip(to_tr, translate_titles(client, [a["title"] for a in to_tr])):
        a["title_pl"] = t
    for a in raw_out:
        a.setdefault("title_pl", a["title"])
        a.pop("feed_category", None)
    write_json("raw_feed.json", {
        "date": date_pretty,
        "time": output_data["time"],
        "timestamp": output_data["timestamp"],
        "count": len(raw_out),
        "items": raw_out
    })
    print(f"✓ Zakończono z sukcesem. Wygenerowano {len(items)} pozycji.")


if __name__ == "__main__":
    main()
