import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai
from PIL import Image, ImageDraw, ImageFont

# --- 1. KONFIGURACJA I POBIERANIE RSS ---
pl_tz = ZoneInfo("Europe/Warsaw")

RSS_URLS = [
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
    "https://news.google.com/rss/search?q=world+news+finance+tech+science&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss?hl=pl&gl=PL&ceid=PL:pl"
]

raw_articles = []
for url in RSS_URLS:
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:12]:
            title = getattr(entry, 'title', '')
            link = getattr(entry, 'link', '#')
            if title:
                raw_articles.append({"title": title, "link": link})
    except Exception as e:
        print(f"Błąd RSS z {url}: {e}")

# --- 2. OBSŁUGA ARCHIWUM I SESJI ---
archive_file = "archive.json"
archive_data = {}
if os.path.exists(archive_file):
    try:
        with open(archive_file, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    except Exception:
        archive_data = {}

now_pl = datetime.now(pl_tz)
today_date_key = now_pl.strftime("%Y-%m-%d")
current_hour = now_pl.hour

session_name = "poranne" if current_hour < 12 else "wieczorne"
session_fixed_key = f"{today_date_key}_{session_name}"

previous_topics = []
if session_name == "wieczorne":
    morning_key = f"{today_date_key}_poranne"
    if morning_key in archive_data:
        for item in archive_data[morning_key].get("items", []):
            if "text" in item:
                previous_topics.append(item["text"])

# --- 3. ZAPYTANIE DO GEMINI ---
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

prompt = f"""Przeanalizuj poniższe nagłówki i stwórz profesjonalny, globalny przegląd w stylu platformy X (przetłumacz i sformatuj wszystko na język polski).

BEZWGLĘDNIE WYMAGANA STRUKTURA (podział na dwie części):
1. CZĘŚĆ GŁÓWNA (12-15 wiadomości): Skup się w 80% na świecie (geopolityka, rynki finansowe, Wall Street, gospodarka globalna, konflikty). Każda musi zaczynać się od odpowiedniej flagi państwa lub ikony tematycznej (np. 🇺🇸, 🇨🇳, 🇪🇺, 📈, ⚖️). Zakaz używania ikony globu (🌍).
2. CZĘŚĆ LUZU / CIEKAWOSTKI (4-6 wiadomości): Obowiązkowo dodaj luźniejsze, zaskakujące lub fascynujące tematy ze świata (nauka, kosmos, AI, technologie, nietypowe fakty, lifestyle). Każda z unikalnym emoji (np. 🚀, 🤖, 🧠, 🦖, ☕, 🧬).

ZASADY:
- Unikaj powtarzania tematów z poranka: {json.dumps(previous_topics, ensure_ascii=False)}
- Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów z kluczami: "text" oraz "link" (dokładnie ten sam URL z wejścia).
- Żadnego formatowania markdown (żadnego ```json ani ```).

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""

items = []
try:
    response = client.models.generate_content(
        model='gemini-3.6-flash',
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
    items = [{"text": f"📌 {art['title']}", "link": art['link']} for art in raw_articles[:15]]

timestamp_key = now_pl.strftime("%Y-%m-%d_%H:%M")
date_pretty = now_pl.strftime("%d %B %Y")
time_pretty = now_pl.strftime("%H:%M")

output_data = {
    "date": date_pretty,
    "time": time_pretty,
    "timestamp": timestamp_key,
    "items": items
}

# --- 4. ZAPIS PLIKÓW DLA STRONY ---
with open("news.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

archive_data[session_fixed_key] = output_data

with open("archive.json", "w", encoding="utf-8") as f:
    json.dump(archive_data, f, ensure_ascii=False, indent=2)


# --- 5. AUTOMATYCZNE GENEROWANIE GRAFIK DLA INSTAGRAMA ---
def generate_instagram_cards(items_data, timestamp_str):
    chunks = [items_data[i:i+3] for i in range(0, len(items_data), 3)]
    
    width, height = 1080, 1350
    bg_color = (18, 18, 18)       
    card_bg = (26, 26, 26)       
    text_white = (255, 255, 255)
    accent_color = (59, 130, 246)  
    
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 30)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 22)
    except:
        font_title = font_body = font_small = ImageFont.load_default()

    total_slides = len(chunks)

    for index, chunk in enumerate(chunks):
        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        draw.text((60, 60), "ŚWIAT W PIGUŁCE", fill=accent_color, font=font_title)
        draw.text((850, 65), f"{index+1}/{total_slides}", fill=(156, 163, 175), font=font_small)
        
        draw.line([(60, 120), (1020, 120)], fill=(40, 40, 40), width=2)
        
        y_offset = 170
        card_height = 330
        gap = 35
        
        for item in chunk:
            draw.rounded_rectangle(
                [(60, y_offset), (1020, y_offset + card_height)], 
                radius=16, 
                fill=card_bg
            )
            
            text = item.get("text", "")
            words = text.split()
            lines = []
            current_line = ""
            for word in words:
                test_line = current_line + " " + word if current_line else word
                if draw.textlength(test_line, font=font_body) < 900:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
                
            text_y = y_offset + 40
            for line in lines[:5]: 
                draw.text((90, text_y), line, fill=text_white, font=font_body)
                text_y += 45
                
            y_offset += card_height + gap
            
        safe_timestamp = timestamp_str.replace(":", "-").replace(" ", "_")
        filename = f"{safe_timestamp}_slide_{index+1}.png"
        img.save(filename)
        print(f"Wygenerowano: {filename}")

if items:
    generate_instagram_cards(items, f"{date_pretty} {time_pretty}")
