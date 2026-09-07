import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
from google import genai
from PIL import Image, ImageDraw, ImageFont
import urllib.request

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


# --- 5. AUTOMATYCZNE GENEROWANIE GRAFIK (Z CTA I PRZEWIJANIEM) ---
def generate_instagram_cards(items_data, timestamp_str):
    chunks = [items_data[i:i+3] for i in range(0, len(items_data), 3)]
    
    width, height = 1080, 1350
    bg_color = (18, 18, 18)       
    card_bg = (28, 28, 32)       
    text_white = (255, 255, 255)
    accent_color = (59, 130, 246)  # Elektryczny błękit
    
    font_path = "NotoSans-Regular.ttf"
    if not os.path.exists(font_path):
        try:
            urllib.request.urlretrieve("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf", font_path)
        except:
            pass

    try:
        font_title = ImageFont.truetype(font_path, 36)
        font_body = ImageFont.truetype(font_path, 28)
        font_small = ImageFont.truetype(font_path, 22)
        font_cta_big = ImageFont.truetype(font_path, 48)
    except:
        font_title = font_body = font_small = font_cta_big = ImageFont.load_default()

    # Łączna liczba slajdów informacyjnych + 1 slajd końcowy (CTA)
    total_slides = len(chunks) + 1

    # Generowanie standardowych slajdów z newsami
    for index, chunk in enumerate(chunks):
        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Logo pigułka
        draw.rounded_rectangle([(60, 50), (110, 95)], radius=22, outline=accent_color, width=3)
        draw.ellipse([72, 62, 98, 88], fill=accent_color)
        
        draw.text((130, 56), "ŚWIAT W PIGUŁCE", fill=text_white, font=font_title)
        draw.text((900, 62), f"{index+1}/{total_slides}", fill=(156, 163, 175), font=font_small)
        
        draw.line([(60, 125), (1020, 125)], fill=(45, 45, 55), width=2)
        
        y_offset = 165
        card_height = 340
        gap = 30
        
        for item in chunk:
            draw.rounded_rectangle(
                [(60, y_offset), (1020, y_offset + card_height)], 
                radius=18, 
                fill=card_bg,
                outline=(45, 45, 55),
                width=1
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
                
            text_y = y_offset + 35
            for line in lines[:5]: 
                draw.text((90, text_y), line, fill=text_white, font=font_body)
                text_y += 44
                
            y_offset += card_height + gap
            
        # Wskaźnik przewijania w bok (Swipe Indicator) na dole
        draw.text((850, 1300), "Przesuń w bok ➔", fill=accent_color, font=font_small)
            
        safe_timestamp = timestamp_str.replace(":", "-").replace(" ", "_")
        filename = f"{safe_timestamp}_slide_{index+1}.png"
        img.save(filename)
        print(f"Wygenerowano: {filename}")

    # --- GENEROWANIE OSTATNIEGO SLAJDU (CTA - WEZWANIE DO DZIAŁANIA) ---
    cta_img = Image.new("RGB", (width, height), bg_color)
    cta_draw = ImageDraw.Draw(cta_img)
    
    # Duże logo na środku slajdu CTA
    cta_draw.rounded_rectangle([(465, 350), (615, 430)], radius=40, outline=accent_color, width=5)
    cta_draw.ellipse([495, 368, 585, 412], fill=accent_color)
    
    cta_draw.text((width//2 - 210, 480), "ŚWIAT W PIGUŁCE", fill=text_white, font=font_cta_big)
    
    # Ramka na CTA
    cta_draw.rounded_rectangle([(150, 600), (930, 920)], radius=24, fill=card_bg, outline=(45, 45, 55), width=2)
    
    cta_draw.text((width//2 - 270, 660), "🔔 Obserwuj profil, aby", fill=text_white, font=font_title)
    cta_draw.text((width//2 - 310, 715), "nie przegapić żadnego newsa!", fill=accent_color, font=font_title)
    
    cta_draw.text((width//2 - 230, 810), "Zostaw ❤️ i udostępnij dalej!", fill=(156, 163, 175), font=font_body)
    
    cta_draw.text((900, 62), f"{total_slides}/{total_slides}", fill=(156, 163, 175), font=font_small)

    safe_timestamp = timestamp_str.replace(":", "-").replace(" ", "_")
    cta_filename = f"{safe_timestamp}_slide_{total_slides}.png"
    cta_img.save(cta_filename)
    print(f"Wygenerowano slajd CTA: {cta_filename}")

if items:
    generate_instagram_cards(items, f"{date_pretty} {time_pretty}")
