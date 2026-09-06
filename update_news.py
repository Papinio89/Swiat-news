import json
import os
import time
import re
from datetime import datetime
import feedparser
from google import genai
from google.genai import types

RSS_CATEGORIES = {
    "swiat": [
        "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
    ],
    "polska": [
        "https://news.google.com/rss/search?q=Polska+when:1d&hl=pl&gl=PL&ceid=PL:pl"
    ],
    "finanse": [
        "https://news.google.com/rss/search?q=gospodarka+OR+finanse+OR+biznes+when:1d&hl=pl&gl=PL&ceid=PL:pl",
        "https://www.bankier.pl/xml/rss/strefa-inwestora.xml"
    ],
    "technologia": [
        "https://news.google.com/rss/search?q=technologia+OR+AI+when:1d&hl=pl&gl=PL&ceid=PL:pl",
        "https://antyweb.pl/feed"
    ]
}

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

def smart_short_title(title: str) -> str:
    """Znacznie lepszy fallback niż poprzedni"""
    # Usuń źródło na końcu (Google News lubi "Tytuł - Źródło")
    clean = re.split(r"\s+[-–|]\s+", title)[0].strip()
    clean = re.sub(r"\s+", " ", clean)

    # Jeśli nadal za krótki / bezużyteczny
    if len(clean) < 12 or clean.lower() in ["polska", "świat", "news", "aktualności"]:
        clean = title[:70].strip()
        if " - " in clean:
            clean = clean.split(" - ")[0]

    if len(clean) > 58:
        clean = clean[:55] + "..."

    return f"📌 {clean}"


def call_gemini(prompt: str, use_schema: bool = True):
    """Próbuje structured, a jak nie to zwykły JSON"""
    try:
        if use_schema:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "text": {"type": "STRING"},
                                "link": {"type": "STRING"}
                            },
                            "required": ["text", "link"]
                        }
                    },
                    temperature=0.35,
                ),
            )
        else:
            # Fallback bez schema
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt + "\n\nZwróć WYŁĄCZNIE czystą tablicę JSON bez markdown.",
                config=types.GenerateContentConfig(temperature=0.35),
            )

        text = (response.text or "").strip()

        # Oczyszczanie z markdowna na wszelki wypadek
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                start = text.find("[")
                end = text.rfind("]") + 1
                if start >= 0 and end > start:
                    text = text[start:end]

        data = json.loads(text)
        if isinstance(data, list) and len(data) > 0:
            return [
                {"text": str(i.get("text", "")).strip(), "link": str(i.get("link", "#"))}
                for i in data
                if isinstance(i, dict) and i.get("text")
            ][:9]
    except Exception as e:
        print(f"   → Błąd Gemini: {e}")
    return None


categorized_data = {}

for index, (category, urls) in enumerate(RSS_CATEGORIES.items()):
    print(f"\n=== {category.upper()} ===")
    raw_articles = []

    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "#")
                if title and len(title) > 8:
                    raw_articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"RSS error: {e}")

    # Usuń duplikaty po tytule
    seen = set()
    unique = []
    for a in raw_articles:
        t = a["title"][:40]
        if t not in seen:
            seen.add(t)
            unique.append(a)
    raw_articles = unique[:7]  # max 7 na kategorię

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości ({category})", "link": "#"}]
        continue

    if index > 0:
        print("Czekam 8 sekund (rate limit)...")
        time.sleep(8)

    prompt = f"""Jesteś redaktorem minimalistycznego serwisu.
Z poniższych nagłówków wybierz 6-8 najważniejszych i zamień je na BARDZO KRÓTKIE tytuły (max 9 słów).

Styl obowiązkowy (zawsze zaczynaj od emoji lub flagi):
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇺🇦 1600 dni wojny na Ukrainie
- ⛔️ Nie ma giełdy w USA jutro. Dzień Pracy
- 🇷🇺 Putin: pauza uderzeń na Kijów od północy

Zwróć listę obiektów z kluczami "text" i "link".
Link musi być dokładnie taki sam jak w danych.

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    items = call_gemini(prompt, use_schema=True)

    if not items:
        print("   Structured padło → próbuję bez schema...")
        items = call_gemini(prompt, use_schema=False)

    if not items:
        print("   AI całkowicie padło → używam lepszego fallbacku")
        items = [
            {"text": smart_short_title(a["title"]), "link": a["link"]}
            for a in raw_articles
        ]

    categorized_data[category] = items
    print(f"✓ {category}: {len(items)} pozycji")
    for it in items[:3]:
        print(f"   • {it['text']}")

# Data
months_pl = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}
now = datetime.now()
today_str = f"{now.day} {months_pl[now.month]} {now.year}"
today_key = now.strftime("%Y-%m-%d")

output_data = {
    "date": today_str,
    "categories": categorized_data
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# Archiwum
archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        pass

archive_data[today_key] = output_data
# zostaw tylko 25 ostatnich dni
sorted_keys = sorted(archive_data.keys(), reverse=True)[:25]
archive_data = {k: archive_data[k] for k in sorted_keys}

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"\n✅ Zapisano news.json i archive.json — {today_str}")
