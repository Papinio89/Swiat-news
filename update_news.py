import json
import os
import time
import re
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

# Inicjalizacja klienta – automatycznie bierze GEMINI_API_KEY z env
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

categorized_data = {}

for index, (category, urls) in enumerate(RSS_CATEGORIES.items()):
    raw_articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "#")
                if title:
                    raw_articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"Błąd RSS z {url}: {e}")

    if not raw_articles:
        categorized_data[category] = [{"text": f"⚠️ Brak wiadomości dla kategorii {category}", "link": "#"}]
        continue

    # Małe opóźnienie między kategoriami (unikanie rate-limit)
    if index > 0:
        time.sleep(4)

    prompt = f"""
Jesteś redaktorem minimalistycznego serwisu informacyjnego. Przeanalizuj poniższe nagłówki z kategorii '{category}' i wybierz maksymalnie 10 najważniejszych.

ZASADA BEZWZGLĘDNA: Nie kopiuj długich tytułów! Przekształć każdy nagłówek w bardzo krótki, uderzeniowy punkt (maksymalnie 8-10 słów), zaczynający się od flagi lub emoji, dokładnie w tym stylu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇮🇹 Meloni premierem Włoch najdłużej od 1945 roku
- 🇺🇦 1600 dni wojny na Ukrainie

Zwróć wynik WYŁĄCZNIE jako czystą tablicę JSON (bez żadnego markdownu, bez ```json, bez komentarzy).
Każdy obiekt musi mieć dokładnie dwa klucze:
1. "text" – skrócona treść z flagą/emoji
2. "link" – dokładnie ten sam URL z danych wejściowych

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

    items = []
    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",   # stabilny i tani; możesz zmienić na gemini-3.8-flash
            contents=prompt,
        )
        text_res = (response.text or "").strip()

        # Usuwanie ewentualnego markdownu
        if "```" in text_res:
            # Wyciągamy pierwszy blok zaczynający się od [
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text_res, re.DOTALL)
            if match:
                text_res = match.group(1)
            else:
                # Fallback – bierzemy wszystko między pierwszym [ a ostatnim ]
                start = text_res.find("[")
                end = text_res.rfind("]") + 1
                if start != -1 and end > start:
                    text_res = text_res[start:end]

        items = json.loads(text_res)

        # Walidacja podstawowa
        if not isinstance(items, list):
            raise ValueError("AI nie zwróciło listy")
        items = [i for i in items if isinstance(i, dict) and "text" in i and "link" in i][:10]

    except Exception as e:
        print(f"Błąd AI dla {category}: {e}")
        # Fallback – proste skrócenie
        items = []
        for art in raw_articles[:10]:
            short = art["title"].split(" - ")[0].split(" | ")[0]
            if len(short) > 60:
                short = short[:57] + "..."
            items.append({"text": f"📌 {short}", "link": art["link"]})

    categorized_data[category] = items
    print(f"✓ {category}: {len(items)} pozycji")

# Data w formacie polskim (prosty sposób)
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
        archive_data = {}

archive_data[today_key] = output_data

# Ogranicz archiwum do ostatnich 30 dni (opcjonalnie)
sorted_keys = sorted(archive_data.keys(), reverse=True)[:30]
archive_data = {k: archive_data[k] for k in sorted_keys}

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"\n✅ Gotowe! Data: {today_str}")
print(f"Kategorie: {list(categorized_data.keys())}")
