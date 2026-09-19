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

# Konfiguracja obrazów
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

def sanitize_text(text: str) -> str:
    """Usuwa problematyczne znaki Unicode."""
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
    if not url or url == "#": return "#"
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
    if not published: return True
    try:
        pub_dt = datetime.fromtimestamp(mktime(published), tz=pl_tz)
        age = datetime.now(pl_tz) - pub_dt
        return age <= timedelta(hours=MAX_AGE_HOURS)
    except Exception:
        return True

def fetch_article_image(url: str) -> str | None:
    if not url or url == "#" or "news.google.com" in url: return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']'
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                img = m.group(1).strip()
                if img.startswith("//"): img = "https:" + img
                if img.startswith("http"): return img
    except Exception: pass
    return None

def fetch_pexels_image_url(query):
    if not PEXELS_API_KEY: return FALLBACK_IMG
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
    req = urllib.request.Request(url, headers={"Authorization": PEXELS_API_KEY, "User-Agent": "Bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                photos = data.get("photos", [])
                if photos:
                    src = photos[0].get("src", {})
                    return src.get("large") or src.get("medium") or FALLBACK_IMG
    except Exception: pass
    return FALLBACK_IMG

def validate_items(items: list) -> list:
    """Super łagodna walidacja - akceptuje polskie klucze jeśli AI zapomniało angielskich."""
    valid = []
    for item in items:
        if not isinstance(item, dict): continue
        
        title = sanitize_text(str(item.get("title", item.get("tytul", ""))))
        if len(title) < 5: continue
        
        summary = sanitize_text(str(item.get("summary", item.get("opis", "Pobrano nagłówek bez szczegółów."))))
        comment = sanitize_text(str(item.get("comment", item.get("komentarz", "Trwa analiza strategiczna."))))
        category = sanitize_text(str(item.get("category", item.get("kategoria", "PILNE")))).upper()
        image_query = sanitize_text(str(item.get("image_query", "military conflict")))
        link = clean_link(str(item.get("link", item.get("url", "#"))))

        valid.append({
            "category": category if category else "PILNE",
            "title": title,
            "summary": summary if summary else "Brak opisu.",
            "comment": comment if comment else "Oczekiwanie na rozwój wydarzeń.",
            "image_query": image_query if image_query else "military",
            "link": link
        })
        if len(valid) >= TARGET_ITEMS:
            break
    return valid

# --- ZBIERANIE RSS ---
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:4]:
            if not is_recent(entry): continue
            title = getattr(entry, "title", "").strip()
            link = clean_link(getattr(entry, "link", "#"))
            if title and len(title) > 12:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

if len(raw_articles) < TARGET_ITEMS:
    print("Ratunek: pobieram bez restrykcji czasowych...")
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                title = getattr(entry, "title", "").strip()
                link = clean_link(getattr(entry, "link", "#"))
                if title and len(title) > 12:
                    raw_articles.append({"title": title, "link": link})
        except: pass

# --- DEDUPLIKACJA ---
filtered_raw_articles = []
seen_titles = set()
for art in raw_articles:
    t = art['title'].lower()
    if t not in seen_titles:
        filtered_raw_articles.append(art)
        seen_titles.add(t)

articles_for_ai = filtered_raw_articles[:15]

# BARDZO WAŻNE: Jeśli RSS zawiódł na 100% i nie pobrał nic, podkładamy sztuczne artykuły pod AI
if not articles_for_ai:
    print("KRYTYCZNE: Pusta lista wejściowa (IP GitHuba zablokowane?). Wstawiam wpisy awaryjne.")
    articles_for_ai = [
        {"title": "Cisza informacyjna w kluczowych agencjach prasowych", "link": "#"},
        {"title": "Trwa monitorowanie globalnych systemów bezpieczeństwa", "link": "#"},
        {"title": "Stabilna sytuacja na głównych frontach dyplomatycznych", "link": "#"}
    ]

# --- AI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Wybierz DOKŁADNIE {TARGET_ITEMS} NAJMOCNIEJSZYCH tematów militarnych/geopolitycznych z poniższej listy.

Zasady:
- Tytuł: zwięzły, z 1 emotikoną (🚨 🛡️ ⚔️ 🚀). 
- Summary: 1 zdanie, konkretny fakt.
- Comment: chłodna puenta strategiczna (1 zdanie).
- Category: WIELKIE LITERY (np. OBRONNOŚĆ, KONFLIKTY).
- image_query: 2-3 angielskie słowa kluczowe.
- link: dokładnie ten sam URL z wejścia.

Zwróć WYŁĄCZNIE tablicę JSON. Żadnego formatowania.
Wejście:
{json.dumps(articles_for_ai, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt
    )
    text_res = response.text.strip()
    
    if text_res.startswith("```json"): text_res = text_res[7:-3].strip()
    elif text_res.startswith("```"): text_res = text_res[3:-3].strip()
        
    raw_items = json.loads(text_res)
    if isinstance(raw_items, dict) and "items" in raw_items:
        raw_items = raw_items["items"]
    elif isinstance(raw_items, dict):
        raw_items = [raw_items]
        
    items = validate_items(raw_items)
except Exception as e:
    print(f"Błąd AI: {e}")
    traceback.print_exc()

# --- BLOK RATUNKOWY (Zabezpiecza przed pustym fast.json) ---
while len(items) < TARGET_ITEMS:
    existing_links = {i.get('link') for i in items if isinstance(i, dict)}
    added = False
    
    for art in articles_for_ai:
        if art['link'] not in existing_links and art['link'] != "#":
            items.append({
                "category": "PILNE",
                "title": f"🚨 {art.get('title', 'Wiadomość z agencji prasowych')}",
                "summary": "Najnowsze raporty agencji informują o rozwoju sytuacji w tym obszarze.",
                "comment": "Oczekujemy na szczegółowe raporty analityczne.",
                "image_query": "breaking news military",
                "link": art.get("link", "#")
            })
            existing_links.add(art['link'])
            added = True
            if len(items) >= TARGET_ITEMS: break
            
    if not added and len(items) < TARGET_ITEMS:
        # Jeśli nawet rezerwowe linki się skończyły
        items.append({
            "category": "RAPORT",
            "title": "🚨 Trwa weryfikacja nowych informacji ze świata",
            "summary": "Systemy analityczne zbierają najświeższe doniesienia.",
            "comment": "Szczegóły zostaną udostępnione wkrótce.",
            "image_query": "news room",
            "link": "#"
        })

items = items[:TARGET_ITEMS]

# --- ZDJĘCIA ---
for item in items:
    img_url = fetch_article_image(item.get("link", ""))
    if not img_url:
        q = item.get("image_query", "military conflict")
        img_url = fetch_pexels_image_url(q)
    item["image_url"] = img_url

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

print(f"Zapisano {len(items)} newsy do fast.json.")
