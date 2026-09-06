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

for index, (category, urls) in enumerate(RSS_CATEGORIES.items()):
    raw_articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
                title = getattr(entry, 'title', '')
                link = getattr(entry, 'link', '#')
                if title:
                    raw_articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"Błąd RSS z {url}: {e}")

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości dla kategorii {category}", "link": "#"}]
        continue

    if index > 0:
        time.sleep(5)

    prompt = f"""
Jesteś redaktorem minimalistycznego serwisu informacyjnego. Przeanalizuj poniższe nagłówki z kategorii '{category}' i wybierz 10 najważniejszych.

ZASADA BEZWZGLĘDNA: Nie kopiuj długich tytułów! Przekształć każdy nagłówek w bardzo krótki, uderzeniowy punkt (maksymalnie do 8-10 słów), zaczynający się od flagi lub emoji, dokładnie w tym stylu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇮🇹 Meloni premierem Włoch najdłużej od 1945 roku

Zwróć wynik WYŁĄCZNIE jako poprawną tablicę JSON. Każdy obiekt w tablicy musi zawierać dokładnie dwa klucze: 
1. "text" (skrócona treść z flagą/emoji) 
2. "link" (przypisz dokładnie ten sam link URL, który był w danych wejściowych dla danego nagłówka).

Żadnego tekstu poza czystym JSON-em (żaden markdown typu ```json).

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    items = []
    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
        )
        text_res = response.text.strip()
        
        if "```" in text_res:
            parts = text_res.split("```")
            for p in parts:
                p_clean = p.strip()
                if p_clean.startswith("["):
                    text_res = p_clean
                    break
                elif p_clean.startswith("json"):
                    text_res = p_clean[4:].strip()
                    break

        items = json.loads(text_res)
    except Exception as e:
        print(f"Błąd AI dla {category}: {e}")
        # Inteligentne skracanie w razie błędu sieciowego API
        items = []
        for art in raw_articles[:10]:
            short_title = art['title'].split(' - ')[0]
            if len(short_title) > 55:
                short_title = short_title[:52] + "..."
            items.append({"text": f"📌 {short_title}", "link": art['link']})

    categorized_data[category] = items

today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")
output_data = {
    "date": today_str,
    "categories": categorized_data
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

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
