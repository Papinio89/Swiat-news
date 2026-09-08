prompt = f"""Przeanalizuj poniższe nagłówki i stwórz dynamiczny przegląd globalny (przetłumacz i sformatuj na język polski).

WYMAGANA STRUKTURA (12-16 elementów):
Podziel wiadomości na dwie wyraźne grupy:
1. FAKTY I GOSPODARKA (ok. 75% treści): Ważne wiadomości ze świata, geopolityka, rynki (np. KGHM, JSW, waluty, surowce, konflikty, decyzje rządowe).
2. CIEKAWOSTKI I LUŹNE TEMATY (ok. 25% treści, minimum 3-4 pozycje): Obowiązkowo dodaj zaskakujące, nietypowe lub lżejsze ciekawostki, anegdoty ze świata nauki, technologii lub codzienne smaczki (z unikalnymi emoji typu 🐝, 🤖, 🧠, 🚀).

Każdy obiekt na liście musi zawierać dokładnie następujące klucze:
- "category": Kategoria pisana wielkimi literami (np. "ŚWIAT / GOSPODARKA", "TECHNOLOGIE", "CIEKAWOSTKA / LIFE").
- "title": Krótki, chwytliwy nagłówek z dopasowaną emotikoną na początku (np. "🐝 Dzień Pszczół: Niezwykłe odkrycia...").
- "summary": Konkretny, krótki opis w 1-2 zdaniach.
- "comment": Trafny, lekki lub wnikliwy komentarz analityczny (odpowiednik idei żarówki).
- "link": Dokładnie ten sam URL z wejścia dla danej wiadomości (jeśli to luźna ciekawostka bez linku, możesz przypisać link do głównego źródła lub pierwszy z listy).

ZASADY:
- Unikaj powtarzania tematów z poranka: {json.dumps(previous_topics, ensure_ascii=False)}
- Zwróć WYŁĄCZNIE czystą tablicę JSON obiektów z powyższymi kluczami.
- Żadnego formatowania markdown (żadnego ```json ani ```).

Dane wejściowe:
{json.dumps(raw_articles, ensure_ascii=False)}
"""
