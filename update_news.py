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
        time.sleep(3)

    prompt = f"""
Jesteś redaktorem minimalistycznego serwisu informacyjnego. Przeanalizuj poniższe nagłówki z kategorii '{category}' i wybierz 10-12 najważniejszych.

ZASADA KLUCZOWA: Nie kopiuj dosłownie długich tytułów z RSS! Przetwórz je na krótkie, chwytliwe, uderzeniowe punkty informacyjne (maksymalnie do kilkunastu słów), dokładnie tak jak w tym wzorcu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇮🇹 Meloni premierem Włoch najdłużej od 1945 roku
- 🇺🇸🇷🇺 Delegacja USA spotkała się z Putinem ws. Ukrainy

Wymagania:
1. Każda linia (pole "text") MUSI zaczynać się od odpowiedniej flagi państwa lub emoji tematycznego.
2. Usuń zbędny szum medialny, nazwy portali czy przydługie wprowadzenia. Skup się na czystym fakcie.
3. Zwróć wynik WYŁĄCZNIE jako tablicę JSON obiektów z dwoma kluczami: "text" (skrócony, przetworzony tekst z flagą/emoji) oraz "link" (przypisz dokładnie ten sam link URL, który był w danych wejściowych dla danego nagłówka).
4. Żadnego formatowania markdown (żadnego ```json ani ```), wyłącznie czysty tekst JSON zaczynający się od [ i kończący się na ].

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
                p_trim = p.strip()
                if p_trim.startswith("[") or p_trim.startswith("json"):
                    if p_trim.startswith("json"):
                        p_trim = p_trim[4:].strip()
                    text_res = p_trim
                    break

        items = json.loads(text_res)
    except Exception as e:
        print(f"Błąd AI dla {category}: {e}")
        items = [{"text": f"📌 {art['title'][:60]}...", "link": art['link']} for art in raw_articles[:10]]

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
