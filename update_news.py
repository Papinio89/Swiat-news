import json
import os
from datetime import datetime
import feedparser
from google import genai

RSS_URLS = [
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://www.reuters.com/world/"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

# Pobieramy poprzednie wydanie z dzisiejszego dnia (jeśli istnieje), aby unikać duplikatów wieczorem
archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

today_date_key = datetime.now().strftime("%Y-%m-%d")
previous_topics = []
for k, v in archive_data.items():
    if k.startswith(today_date_key):
        for item in v.get("items", []):
            previous_topics.append(item.get("text", ""))

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""
Przeanalizuj poniższe nagłówki wiadomości i stwórz minimalistyczny przegląd w stylu profesjonalnych kanałów informacyjnych z platformy X (krótkie, uderzeniowe fakty z flagami i emoji).

Wymagania:
1. Wybierz 15-20 najważniejszych, poważnych wiadomości (geopolitika, finanse, konflikty, gospodarka).
2. Dodaj dodatkowo 5-7 luźniejszych, ciekawych lub zaskakujących newsów/ciekawostek ze świata.
3. Łącznie przygotuj około 22-27 pozycji.
4. UNIKAJ TYCH TEMATÓW (były już w porannym wydaniu): {json.dumps(previous_topics, ensure_ascii=False)}
5. Zwróć wynik WYŁĄCZNIE jako tablicę JSON obiektów, gdzie każdy obiekt ma dokładnie dwa klucze: "text" (przetworzony krótki nagłówek z flagą/emoji) oraz "link" (dokładnie ten sam link URL).
6. Żadnego formatowania markdown (żadnego ```json ani ```).

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
    items = [{"text": f"📌 {art['title'][:60]}...", "link": art['link']} for art in raw_articles[:20]]

now = datetime.now()
timestamp_key = now.strftime("%Y-%m-%d_%H:%M")
date_pretty = now.strftime("%d %B %Y")
time_pretty = now.strftime("%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

# Zapis bieżących newsów
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

# Zapis w archiwum pod unikalnym kluczem sesji (np. 2026-09-07_06:00)
archive_data[timestamp_key] = output_data

with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
