import json
import os
import time
from datetime import datetime
import feedparser
from google import genai

RSS_CATEGORIES = {
    "swiat": [
        "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
    ],
    "polska": [
        "https://news.google.com/rss/search?q=Polska&hl=pl&gl=PL&ceid=PL:pl"
    ]
}

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
categorized_data = {}

for index, (category, urls) in enumerate(RSS_CATEGORIES.items()):
    raw_articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = getattr(entry, 'title', '')
                link = getattr(entry, 'link', '#')
                if title:
                    raw_articles.append({"title": title, "link": link})
        except Exception:
            pass

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości ({category})", "link": "#"}]
        continue

    if index > 0:
        time.sleep(5)

    prompt = f"""
Przeanalizuj poniższe nagłówki wiadomości i wybierz do 12 najważniejszych.
Dla każdej wiadomości stwórz krótki, minimalistyczny punkt z flagą/emoji na początku, w stylu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇺🇦 1600 dni wojny na Ukrainie

Zwróć wynik WYŁĄCZNIE jako poprawną tablicę JSON obiektów.
Każdy obiekt musi mieć dokładnie dwa klucze: "text" i "link".
Żadnego markdown typu ```json.

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
        )
        text_res = response.text.strip()

        if text_res.startswith("```json"):
            text_res = text_res[7:]
        if text_res.startswith("```"):
            text_res = text_res[3:]
        if text_res.endswith("```"):
            text_res = text_res[:-3]
        text_res = text_res.strip()

        items = json.loads(text_res)

        if not isinstance(items, list):
            raise ValueError("Nie lista")
        items = [i for i in items if isinstance(i, dict) and "text" in i and "link" in i][:12]

    except Exception as e:
        print(f"Błąd AI ({category}): {e}")
        items = [{"text": f"⚠️ Błąd pobierania kategorii {category}", "link": "#"}]

    categorized_data[category] = items
    print(f"✓ {category}: {len(items)} pozycji")

today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")

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
        archive_data = {}

archive_data[today_key] = output_data

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print("✅ Gotowe")
