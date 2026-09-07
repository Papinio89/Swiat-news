from PIL import Image, ImageDraw, ImageFont
import os
from datetime import datetime

def generate_instagram_cards(items_data, timestamp_str):
    # Dzielimy dynamicznie newsy na paczki po 3 elementy (niezależnie od tego, czy jest ich 12, 16 czy 22)
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
            
        # Formatowanie nazwy pliku: np. "07.09.2026_19-10_slide_1.png"
        safe_timestamp = timestamp_str.replace(":", "-").replace(" ", "_")
        filename = f"{safe_timestamp}_slide_{index+1}.png"
        img.save(filename)
        print(f"Wygenerowano: {filename}")

# Przykładowe wywołanie z przekazaniem stringa z datą i godziną (np. z zmiennej timestamp_key)
if items:
    generate_instagram_cards(items, f"{date_pretty} {time_pretty}")
