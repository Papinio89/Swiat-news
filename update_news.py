import json
import os
import time
from datetime import datetime
import feedparser
from google import genai

print("=== START ===")
print(f"Czas: {datetime.now()}")
print(f"Klucz API: {'TAK' if os.environ.get('GEMINI_API_KEY') else 'NIE'}")

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Pobieranie RSS ---
def get_articles(urls, limit=6):
    articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:limit]:
                title = getattr(entry, 'title', '').strip()
                link = getattr(entry, 'link', '#')
                if title and len(title) > 10:
                    articles.append({"title": title, "link": link})
        except Exception as e:
            print(f"RSS błąd: {e}")
    return articles[:6]

swiat_articles = get_articles([
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
])
polska_articles = get_articles([
    "https://news.google.com/rss/search?q=Polska&hl=pl&gl=PL&ceid=PL:pl"
])

print(f"Świat: {len(swiat_articles)} art.")
print(f"Polska: {len(polska_articles)} art.")

# --- Jedno zapytanie do AI ---
prompt = f"""
Jesteś redaktorem. Przeanalizuj dwie grupy nagłówków i dla każdej wybierz 6-8 najważniejszych.

Dla każdej wiadomości stwórz krótki punkt zaczynający się od flagi lub emoji, w stylu:
- 🇨🇳 Chiny: 80% wzrost importu węgla koksowego r/r
- 👟 NIKE wyleci z S&P 100 po 18 latach
- 🇺🇦 1600 dni wojny na Ukrainie

Zwróć WYŁĄCZNIE czysty JSON w formacie:
{{
  "swiat": [ {{"text": "...", "link": "..."}}, ... ],
  "polska": [ {{"text": "...", "link": "..."}}, ... ]
}}

Bez markdown, bez ```json.

Dane świat:
{json.dumps(swiat_articles, ensure_ascii=False)}

Dane polska:
{json.dumps(polska_articles, ensure_ascii=False)}
"""

categorized_data = {
    "swiat": [{"text": "⚠️ Błąd AI – świat", "link": "#"}],
    "polska": [{"text": "⚠️ Błąd AI – polska", "link": "#"}]
}

try:
    print("Wysyłam jedno zapytanie do Gemini...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",          # model z lepszym limitem free
        contents=prompt,
    )
    text_res = response.text.strip()
    print(f"Odpowiedź (początek): {text_res[:150]}")

    # Czyszczenie
    text_res = text_res.replace("```json", "").replace("```", "").strip()
    data = json.loads(text_res)

    if isinstance(data, dict):
        if "swiat" in data and isinstance(data["swiat"], list):
            categorized_data["swiat"] = [
                i for i in data["swiat"] 
                if isinstance(i, dict) and "text" in i
            ][:8]
        if "polska" in data and isinstance(data["polska"], list):
            categorized_data["polska"] = [
                i for i in data["polska"] 
                if isinstance(i, dict) and "text" in i
            ][:8]

    print(f"Świat: {len(categorized_data['swiat'])} pozycji")
    print(f"Polska: {len(categorized_data['polska'])} pozycji")

except Exception as e:
    print(f"BŁĄD Gemini: {type(e).__name__}: {e}")

# --- Zapis ---
today_key = datetime.now().strftime("%Y-%m-%d")
today_str = datetime.now().strftime("%d %B %Y")

output_data = {
    "date": today_str,
    "categories": categorized_data
}

with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)
print("Zapisano news.json")

archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except:
        pass

archive_data[today_key] = output_data
with open(archive_file, "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)
print("Zapisano archive.json")

print("=== KONIEC ===")
