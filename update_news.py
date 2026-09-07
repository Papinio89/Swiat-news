import json
import os
from datetime import datetime
import feedparser
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

RSS_URLS = [
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:12]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "#")
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception:
        pass

# Usuwamy duplikaty
seen = set()
unique = []
for a in raw_articles:
    t = a["title"][:50]
    if t not in seen:
        seen.add(t)
        unique.append(a)
raw_articles = unique[:12]

prompt = f"""
Jesteś redaktorem minimalistycznego serwisu informacyjnego.
Przeanalizuj poniższe nagłówki i wybierz 10-12 najważniejszych.

Dla każdej wiadomości stwórz bardzo krótki punkt z flagą lub emoji na początku, dokładnie w tym stylu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- ⚓️🇺🇸 Iran atakuje balistykami lotniskowiec USA
- ₿ 15 lat temu Bitcoin = 8$
- 🇺🇦 1600 dni wojny na Ukrainie

Zwróć wynik WYŁĄCZNIE jako czystą tablicę JSON.
Każdy obiekt musi mieć dokładnie dwa klucze:
- "text" (krótki tytuł z emoji)
- "link" (dokładnie ten sam link z danych wejściowych)

Żadnego markdown typu ```json.

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

try:
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=1500,
    )
    text_res = completion.choices[0].message.content.strip()

    if "```" in text_res:
        text_res = text_res.replace("```json", "").replace("```", "").strip()

    items = json.loads(text_res)

    if not isinstance(items, list):
        raise ValueError("Nie lista")

    items = [i for i in items if isinstance(i, dict) and "text" in i and "link" in i][:12]

except Exception as e:
    print("Błąd AI:", e)
    items = [{"text": "⚠️ Błąd generowania AI", "link": "#"}]

# Data po polsku
months = {
    1: "stycznia", 2: "lutego", 3: "marca", 4: "kwietnia",
    5: "maja", 6: "czerwca", 7: "lipca", 8: "sierpnia",
    9: "września", 10: "października", 11: "listopada", 12: "grudnia"
}
now = datetime.now()
today_str = f"{now.day} {months[now.month]} {now.year}"
today_key = now.strftime("%Y-%m-%d")

output_data = {
    "date": today_str,
    "items": items
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
        pass

archive_data[today_key] = output_data

# Zostawiamy ostatnie 30 dni
sorted_keys = sorted(archive_data.keys(), reverse=True)[:30]
archive_data = {k: archive_data[k] for k in sorted_keys}

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)

print(f"Gotowe – {len(items)} pozycji")
