import os
import json
from jinja2 import Template
from playwright.sync_api import sync_playwright
import requests
from bs4 import BeautifulSoup

def pobierz_zdjecie_z_artykulu(url):
    """Pobiera miniaturę og:image z artykułu"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        soup = BeautifulSoup(response.text, 'html.parser')
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return og_image['content']
    except Exception:
        pass
    return "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe"

def uruchom():
    if not os.path.exists('archive.json'):
        print("Brak pliku archive.json!")
        return

    with open('archive.json', 'r', encoding='utf-8') as f:
        archive = json.load(f)
        
    if not archive:
        print("Plik archive.json jest pusty!")
        return

    # Pobieramy klucze z archiwum (np. ["2026-09-07_wieczorne", "2026-09-08_poranne"])
    wszystkie_klucze = list(archive.keys())
    
    # Bierzemy OSTATNI klucz z listy (najnowszy wpis dodany do archiwum)
    klucz_wpisu = wszystkie_klucze[-1]
    wpis = archive.get(klucz_wpisu)
    
    surowe_newsy = wpis.get("items", [])
    print(f"➔ Automatycznie wykryto najnowszy wpis: {klucz_wpisu}")
    print(f"➔ Liczba newsów do przetworzenia: {len(surowe_newsy)}")

    if not surowe_newsy:
        print("Brak newsów w tym wpisie!")
        return

    # Podział newsów na paczki po 3 (wersja skrócona karuzeli)
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
                czysty_tekst = item["text"]
                
                przygotowane_elementy.append({
                    "numer": idx,
                    "tytul": czysty_tekst.split(". ")[0].replace("🇺🇸", "").replace("🇷🇺", "").replace("🇩🇪", "").strip(),
                    "opis": czysty_tekst,
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
    print("Wszystko wygenerowane pomyślnie!")

if __name__ == '__main__':
    uruchom()
