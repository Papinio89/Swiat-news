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
        except Exception as e:
            print(f"Błąd RSS z {url}: {e}")

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości dla kategorii {category}", "link": "#"}]
        continue

    prompt = f"""
Przeanalizuj poniższe nagłówki wiadomości i wybierz do 15 najważniejszych.
Dla każdej wiadomości stwórz krótki punkt z flagą/emoji na początku.
Zwróć wynik WYŁĄCZNIE jako tablicę JSON obiektów z kluczami: "text" oraz "link" (przypisz oryginalny link).
Ważne: Nie używaj żadnego formatowania markdown (żadnego ```json ani ```), zwróć czysty tekst JSON zaczynający się od [ i kończący się na ].

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
        
        # Agresywne czyszczenie ewentualnego markdowna
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
        print(f"Błąd AI dla {category}: {e}, tekst odpowiedzi: {response.text if 'response' in locals() else 'brak'}")
        # Awaryjny fallback: jeśli AI zawiedzie, bierzemy bezpośrednio surowe nagłówki z RSS bez AI, żeby stroni nie psuć
        items = [{"text": f"🌐 {art['title']}", "link": art['link']} for art in raw_articles[:10]]

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
