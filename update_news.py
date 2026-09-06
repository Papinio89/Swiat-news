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
    print(f"\n=== Przetwarzam: {category} ===")
    
    raw_articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:  # mniej = bezpieczniej
                title = getattr(entry, 'title', '').strip()
                link = getattr(entry, 'link', '#')
                if title and len(title) > 10:
                    raw_articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"RSS błąd: {e}")

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości ({category})", "link": "#"}]
        continue

    # Długi odstęp – kluczowe
    if index > 0:
        print("Czekam 15 sekund (ochrona rate-limitu)...")
        time.sleep(15)

    prompt = f"""
Przeanalizuj poniższe nagłówki i wybierz do 10 najważniejszych.
Dla każdej stwórz bardzo krótki punkt z flagą/emoji na początku.
Styl:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇺🇦 1600 dni wojny na Ukrainie

Zwróć WYŁĄCZNIE czystą tablicę JSON.
Każdy obiekt: "text" i "link".
Żadnego markdown.

Dane:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    items = None
    for attempt in range(2):  # maksymalnie 2 próby
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=prompt,
            )
            text_res = response.text.strip()

            # Czyszczenie markdown
            if "```" in text_res:
                text_res = text_res.replace("```json", "").replace("```", "").strip()

            items = json.loads(text_res)

            if isinstance(items, list) and len(items) > 0:
                items = [i for i in items if isinstance(i, dict) and "text" in i][:10]
                break
            else:
                raise ValueError("Pusta lub zła lista")

        except Exception as e:
            print(f"Próba {attempt+1} nieudana: {e}")
            if attempt == 0:
                print("Czekam 10 sekund i próbuję jeszcze raz...")
                time.sleep(10)

    if not items:
        items = [{"text": f"⚠️ Błąd pobierania kategorii {category}", "link": "#"}]

    categorized_data[category] = items
    print(f"✓ {category}: {len(items)} pozycji")
    for it in items[:2]:
        print(f"   → {it.get('text', '')[:60]}")

# Data
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

print("\n✅ Gotowe")
