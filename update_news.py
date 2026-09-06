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
        "https://news.google.com/rss/search?q=Polska&hl=pl&gl=PL&ceid=PL:pl"
    ],
    "finanse": [
        "https://news.google.com/rss/search?q=gospodarka+finanse+biznes&hl=pl&gl=PL&ceid=PL:pl",
        "https://www.bankier.pl/xml/rss/strefa-inwestora.xml"
    ],
    "technologia": [
        "https://news.google.com/rss/search?q=technologia+AI&hl=pl&gl=PL&ceid=PL:pl",
        "https://antyweb.pl/feed"
    ]
}

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Schema wymuszająca czysty JSON
NEWS_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING"},
            "link": {"type": "STRING"}
        },
        "required": ["text", "link"]
    }
}

def clean_fallback_title(title: str) -> str:
    """Proste skracanie bez AI"""
    short = title.split(" - ")[0].split(" | ")[0].split(" – ")[0]
    short = re.sub(r"\s+", " ", short).strip()
    if len(short) > 55:
        short = short[:52] + "..."
    return f"📌 {short}"

categorized_data = {}

for index, (category, urls) in enumerate(RSS_CATEGORIES.items()):
    raw_articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:  # mniej = stabilniej
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "#")
                if title and link:
                    raw_articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"Błąd RSS {url}: {e}")

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości ({category})", "link": "#"}]
        continue

    if index > 0:
        time.sleep(5)  # ważne przy free tier

    # Krótki, twardy prompt
    prompt = f"""Jesteś redaktorem. Z poniższych nagłówków wybierz 8-10 najważniejszych.

Zamień każdy na BARDZO KRÓTKI tytuł (max 8-10 słów) zaczynający się od emoji/flagi.
Styl obowiązkowy:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇺🇦 1600 dni wojny na Ukrainie
- ⛔️ Nie ma giełdy w USA jutro. Dzień Pracy

Zwróć TYLKO listę obiektów z polami "text" i "link".
Link musi być dokładnie taki sam jak w danych wejściowych.

Dane:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    items = []
    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",          # możesz zmienić na "gemini-3.8-flash"
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=NEWS_SCHEMA,
                    temperature=0.4,               # niższa = bardziej przewidywalna
                ),
            )

            text_res = (response.text or "").strip()
            items = json.loads(text_res)

            # dodatkowa walidacja
            if isinstance(items, list) and len(items) > 0:
                items = [
                    {"text": i["text"].strip(), "link": i["link"]}
                    for i in items
                    if isinstance(i, dict) and "text" in i and "link" in i
                ][:10]
                if items:
                    break  # sukces

        except Exception as e:
            print(f"Próba {attempt+1}/{max_retries} nieudana ({category}): {e}")
            time.sleep(3)

    # Fallback tylko gdy AI kompletnie padło
    if not items:
        print(f"⚠️ Fallback dla {category}")
        items = [
            {"text": clean_fallback_title(art["title"]), "link": art["link"]}
            for art in raw_articles[:8]
        ]

    categorized_data[category] = items
    print(f"✓ {category}: {len(items)} pozycji")

# Data po polsku
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

# Archiwum (ostatnie 30 dni)
archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        pass

archive_data[today_key] = output_data
sorted_keys = sorted(archive_data.keys(), reverse=True)[:30]
archive_data = {k: archive_data[k] for k in sorted_keys}

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"\n✅ Gotowe — {today_str}")
