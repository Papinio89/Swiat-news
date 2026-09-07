import json
import os
from datetime import datetime
import feedparser
from google import genai

RSS_URLS = [
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
]

headlines = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            if getattr(entry, "title", None):
                headlines.append(entry.title)
    except Exception:
        pass

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""
Przeanalizuj poniższe nagłówki wiadomości ze świata i wybierz 10-15 najważniejszych. 
Przetwórz je dokładnie na taki styl, format i zwięzłość jak w tym przykładzie:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- ⚓️🇺🇸 Iran atakuje balistykami lotniskowiec USA
- ₿ 15 lat temu Bitcoin = 8$

Zasady:
1. Używaj flag państw i emoji tematycznych na początku każdej linii.
2. Pisz maksymalnie zwięźle, w formie krótkich punktów informacyjnych.
3. Zwróć wynik WYŁĄCZNIE jako tablicę JSON zawierającą same ciągi tekstowe (stringi), bez dodatkowego formatowania markdown kodu.

Nagłówki do przetworzenia:
{json.dumps(headlines, ensure_ascii=False)}
"""

try:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",          # ← model z najwyższym limitem free
        contents=prompt,
    )
    text_res = response.text.strip()

    if text_res.startswith("```json"):
        text_res = text_res[7:-3].strip()
    elif text_res.startswith("```"):
        text_res = text_res[3:-3].strip()

    items = json.loads(text_res)

    if not isinstance(items, list):
        items = [str(items)]

except Exception as e:
    print("Błąd AI:", e)
    items = ["nowy ⚠️ Błąd generowania AI"]

today_str = datetime.now().strftime("%d %B %Y")
output_data = {
    "date": today_str,
    "items": items
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print("Gotowe – zapisano news.json")
