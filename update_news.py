import json
import os
from datetime import datetime
import feedparser
from google import genai

RSS_URLS = [
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"
]

# Pobieramy nagłówki wraz z oryginalnymi linkami
raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:15]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Przekazujemy do AI zarówno tekst jak i linki w formacie JSON, aby model zwrócił sparowane obiekty
prompt = f"""
Przeanalizuj poniższe nagłówki wiadomości ze świata i wybierz 15-20 najważniejszych. 
Przetwórz każdą wiadomość na krótki, zwięzły punkt informacyjny (wzorując się na stylu: "- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r", używając flag państw i emoji).

Zasady:
1. Zwróć wynik WYŁĄCZNIE jako tablicę JSON obiektów, gdzie każdy obiekt ma dokładnie dwa klucze: "text" (przetworzony krótki nagłówek z flagą/emoji) oraz "link" (dokładnie ten sam link URL, który był w danych wejściowych dla danej wiadomości).
2. Żadnego formatowania markdown (żadnego ```json ani ```).

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
    if text_res.startswith("```json"):
        text_res = text_res[7:-3].strip()
    elif text_res.startswith("```"):
        text_res = text_res[3:-3].strip()
    
    items = json.loads(text_res)
except Exception as e:
    print(f"Błąd AI: {e}")
    # Awaryjny fallback, gdyby AI zwróciło błąd
    items = [{"text": f"📌 {art['title'][:60]}...", "link": art['link']} for art in raw_articles[:15]]

today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")

output_data = {
    "date": today_str,
    "items": items
}

# Zapis bieżących wiadomości (baza do odczytu dla strony)
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# Obsługa archiwum
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
