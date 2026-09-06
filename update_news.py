import json
import os
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
categorized_data = {}

for category, urls in RSS_CATEGORIES.items():
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

    prompt = f"""
Przeanalizuj poniższe nagłówki wiadomości i wybierz do 15 najważniejszych.
Dla każdej wiadomości stwórz krótki, minimalistyczny punkt z flagą/emoji na początku.
Zwróć wynik WYŁĄCZNIE jako poprawną tablicę JSON obiektów, gdzie każdy obiekt ma dokładnie dwa klucze: "text" (przetworzony tekst z flagą i emoji) oraz "link" (dokładny link URL przekazany w danych wejściowych). Żadnego markdown typu ```json.

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
            text_res = text_res[7:-3].strip()
        elif text_res.startswith("```"):
            text_res = text_res[3:-3].strip()
        
        items = json.loads(text_res)


except Exception as e:
    print(f"Szczegóły błędu dla {category}: {e}")
    items = [{"text": f"⚠️ Błąd: {str(e)[:40]}", "link": "#"}]



    categorized_data[category] = items

today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")
output_data = {
    "date": today_str,
    "categories": categorized_data
}

# Zapis bieżących newsów
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# Obsługa pliku archiwum
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
