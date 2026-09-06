import json
import os
import time
from datetime import datetime
import feedparser
from google import genai

print("=== START ===")
print(f"Czas: {datetime.now()}")
print(f"GEMINI_API_KEY ustawiony: {'TAK' if os.environ.get('GEMINI_API_KEY') else 'NIE'}")

RSS_CATEGORIES = {
    "swiat": [
        "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
    ],
    "polska": [
        "https://news.google.com/rss/search?q=Polska&hl=pl&gl=PL&ceid=PL:pl"
    ]
}

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
print("Klient Gemini utworzony OK")

categorized_data = {}

for index, (category, urls) in enumerate(RSS_CATEGORIES.items()):
    print(f"\n----- {category.upper()} -----")
    
    raw_articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            print(f"RSS: {len(feed.entries)} wpisów")
            for entry in feed.entries[:6]:
                title = getattr(entry, 'title', '').strip()
                link = getattr(entry, 'link', '#')
                if title and len(title) > 10:
                    raw_articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"Błąd RSS: {e}")

    print(f"Zebrano {len(raw_articles)} artykułów")

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak artykułów ({category})", "link": "#"}]
        continue

    if index > 0:
        print("Czekam 20 sekund...")
        time.sleep(20)

    prompt = f"""Przeanalizuj nagłówki i wybierz do 8 najważniejszych.
Stwórz krótkie punkty z emoji/flagą na początku (styl: 🇨🇳 Chiny: 80% wzrost importu węgla...).
Zwróć TYLKO czystą tablicę JSON z obiektami "text" i "link". Bez markdown.

Dane:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    items = None
    try:
        print("Wysyłam do Gemini...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',          # ← zmieniony model (wyższy limit free)
            contents=prompt,
        )
        text_res = response.text.strip()
        print(f"Odpowiedź (początek): {text_res[:120]}")

        text_res = text_res.replace("```json", "").replace("```", "").strip()
        items = json.loads(text_res)

        if isinstance(items, list) and len(items) > 0:
            items = [i for i in items if isinstance(i, dict) and "text" in i][:8]
            print(f"OK – {len(items)} pozycji")
        else:
            raise ValueError("Pusta lista")

    except Exception as e:
        print(f"BŁĄD Gemini: {type(e).__name__}: {e}")
        items = [{"text": f"⚠️ Błąd AI – {category}", "link": "#"}]

    categorized_data[category] = items

# Zapis
today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")

output_data = {
    "date": today_str,
    "categories": categorized_data
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)
print("Zapisano news.json")

archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except:
        pass

archive_data[today_key] = output_data
with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
print("Zapisano archive.json")

print("\n=== KONIEC ===")
print(json.dumps({k: len(v) for k, v in categorized_data.items()}, ensure_ascii=False))
