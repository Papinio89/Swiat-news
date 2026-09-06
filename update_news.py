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
            for entry in feed.entries[:10]:
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
Przeanalizuj poniższe nagłówki wiadomości dla kategorii '{category}' i wybierz 10-15 najważniejszych.
Przetwórz je na niezwykle zwięzłe, chwytliwe punkty informacyjne wzorując się na tym stylu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- ⚓️🇺🇸 Iran atakuje balistykami lotniskowiec USA
- 💻 OpenAI zapowiada nowy model AI

Zasady:
1. Używaj flag państw i emoji tematycznych na początku każdej linii.
2. Pisz maksymalnie krótko i treściwie (usuń zbędny szum medialny).
3. Zwróć wynik WYŁĄCZNIE jako tablicę JSON obiektów z kluczami: "text" (przetworzony krótki tekst z flagą/emoji) oraz "link" (przypisz dokładnie ten sam link URL, który był w danych wejściowych dla danego nagłówka).
4. Żadnego formatowania markdown (żaden ```json ani ```), zwróć czysty tekst JSON zaczynający się od [ i kończący się na ].

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
        # Awaryjne skrócenie tytułów w przypadku błędu zamiast wklejania gigantycznych zdań
        items = [{"text": f"📌 {art['title'][:70]}...", "link": art['link']} for art in raw_articles[:10]]

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
