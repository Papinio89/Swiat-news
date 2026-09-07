import json
import os
from datetime import datetime
import feedparser
from openai import OpenAI

# Groq (OpenAI-compatible)
client = OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

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

prompt = f"""
Jesteś redaktorem minimalistycznego serwisu informacyjnego.
Przeanalizuj poniższe nagłówki i wybierz 12-15 najważniejszych.

Dla każdej wiadomości stwórz bardzo krótki, uderzeniowy punkt (max 8-10 słów) zaczynający się od flagi lub emoji.
Dokładny styl:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- ⚓️🇺🇸 Iran atakuje balistykami lotniskowiec USA
- ₿ 15 lat temu Bitcoin = 8$
- 🇺🇦 1600 dni wojny na Ukrainie

Zwróć WYŁĄCZNIE czystą tablicę JSON.
Każdy obiekt musi mieć dokładnie dwa klucze:
- "text" (krótki tytuł z emoji)
- "link" (dokładny link z danych wejściowych)

Bez markdown, bez ```json.

Dane:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

try:
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",   # szybki i darmowy
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    text_res = response.choices[0].message.content.strip()

    if "```" in text_res:
        text_res = text_res.replace("```json", "").replace("```", "").strip()

    items = json.loads(text_res)

    # walidacja
    items = [i for i in items if isinstance(i, dict) and "text" in i and "link" in i][:15]

except Exception as e:
    print("Błąd AI:", e)
    items = [{"text": "⚠️ Błąd generowania AI", "link": "#"}]

# Data
today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")

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
    except:
        pass

archive_data[today_key] = output_data

# zostaw tylko ostatnie 30 dni
sorted_keys variables → Actions → New repository secret**  
Nazwa: `GROQ_API_KEY`  
Wartość: Twój klucz

---

### 2. `requirements.txt`

```txt
feedparser>=6.0.11
groq>=0.9.0
