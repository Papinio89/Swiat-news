import os
import json
from jinja2 import Template
from playwright.sync_api import sync_playwright
import requests
from bs4 import BeautifulSoup

def pobierz_zdjecie_z_artykulu(url):
    """Pobiera miniaturę og:image z artykułu z maskowaniem jako przeglądarka"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        response = requests.get(url, headers=headers, timeout=6, allow_redirects=True)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                return og_image['content']
    except Exception:
        pass
    
    # Zamiast brzydkich ikon Google, zwracamy pusty string (szablon to ukryje)
    return ""

def przygotuj_teksty(surowy_tekst):
    """Inteligentnie dzieli tekst newsa na pogrubiony nagłówek i treść"""
    czysty = surowy_tekst.replace("🇺🇸", "").replace("🇷🇺", "").replace("🇩🇪", "").replace("🇬🇧", "").strip()
    
    # Próbujemy rozbić po kropce lub dwukropku na tytuł i opis
    if ". " in czysty:
        czesci = czysty.split(". ", 1)
        tytul = czesci[0].strip() + "."
        opis = czesci[1].strip()
    elif ":" in czysty:
        czesci = czysty.split(":", 1)
        tytul = czesci[0].strip() + ":"
        opis = czesci[1].strip()
    else:
        tytul = czysty[:50] + "..."
        opis = czysty
        
    return tytul, opis

def uruchom():
    if not os.path.exists('archive.json'):
        print("Brak pliku archive.json!")
        return

    with open('archive.json', 'r', encoding='utf-8') as f:
        archive = json.load(f)
        
    if not archive:
        print("Plik archive.json jest pusty!")
        return

    klucz_wpisu = list(archive.keys())[-1]
    wpis = archive.get(klucz_wpisu)
    surowe_newsy = wpis.get("items", [])
    
    print(f"➔ Przetwarzanie wpisu: {klucz_wpisu} (Liczba newsów: {len(surowe_newsy)})")

    paczki_newsow = [surowe_newsy[i:i + 3] for i in range(0, len(surowe_newsy), 3)]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1080, 'height': 1350})
        
        with open('template.html', 'r', encoding='utf-8') as f:
            szablon_html = f.read()

        for numer_slajdu, paczka in enumerate(paczki_newsow, start=2):
            przygotowane_elementy = []
            for idx, item in enumerate(paczka, start=1):
                zdjecie_url = pobierz_zdjecie_z_artykulu(item["link"])
                tytul, opis = przygotuj_teksty(item["text"])
                
                przygotowane_elementy.append({
                    "numer": idx,
                    "tytul": tytul,
                    "opis": opis,
                    "zdjecie": zdjecie_url
                })
            
            kontekst = {
                "kategoria": "ŚWIAT / POLITYKA",
                "newsy": przygotowane_elementy,
                "slajd_akt": numer_slajdu,
                "slajd_max": len(paczki_newsow) + 2
            }

            rendered_html = Template(szablon_html).render(kontekst)
            
            temp_path = os.path.abspath('temp_slide.html')
            with open(temp_path, 'w', encoding='utf-8') as temp_f:
                temp_f.write(rendered_html)
                
            page.goto(f"file:///{temp_path}")
            
            nazwa_pliku = f"wynik_{klucz_wpisu}_slajd_{numer_slajdu}.png"
            page.screenshot(path=nazwa_pliku, full_page=True)
            print(f"[OK] Zapisano: {nazwa_pliku}")

        browser.close()
    print("Wygenerowano pomyślnie!")

if __name__ == '__main__':
    uruchom()
