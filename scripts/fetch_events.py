#!/usr/bin/env python3
"""
LocalEvent - Event Scraper
Scrape events from iabilet.ro for all 7 cities and emit new events to stdout (JSON).

Output: JSON array of new events, one per city, ready to be merged into events.json.

Usage:
  python3 fetch_events.py [--days 30]

Strategy:
- For each city, scrape iabilet.ro/bilete-in-{slug}
- Parse event blocks: title, date, time, venue, category, price, url
- Skip events already in input events.json (passed as first arg or read from disk)
- Output: list of {city, events: [...]} for the merge step
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: needs requests + beautifulsoup4. pip install requests beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)

CITIES = {
    "bucuresti":   "București",
    "cluj-napoca": "Cluj-Napoca",
    "timisoara":   "Timișoara",
    "iasi":        "Iași",
    "constanta":   "Constanța",
    "sibiu":       "Sibiu",
    "craiova":     "Craiova",
}

# Romanian month abbreviations (iabilet format)
RO_MONTHS = {
    'ian': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'mai': '05', 'iun': '06',
    'iul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'noi': '11', 'dec': '12',
}
RO_DOW = {
    'Lu': 0, 'Ma': 1, 'Mi': 2, 'Jo': 3, 'Vi': 4, 'Sâ': 5, 'Sâ': 5, 'Sâm': 5, 'Du': 6,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


def normalize_date(text):
    """Parse Romanian dates like 'Vi, 4 sep', 'Sâ, 5 sep', '1-3 sep', '18-19 sep', '4 sep'."""
    text = text.strip().lower()
    text = text.replace('â', 'a').replace('î', 'i')  # Normalize diacritics

    # Range: '1-3 sep' or '18-19 sep'
    m = re.search(r'(\d{1,2})-(\d{1,2})\s+([a-z]{3})', text)
    if m:
        return None, None  # multi-day events — skip for now (too complex for MVP)

    # Single: 'Vi, 4 sep'
    m = re.search(r'(\d{1,2})\s+([a-z]{3})', text)
    if m:
        day, mon = m.groups()
        mm = RO_MONTHS.get(mon)
        if mm:
            # Year: assume current year
            from datetime import datetime
            year = datetime.now().year
            return f"{year}-{mm}-{int(day):02d}"

    return None


def normalize_category(text):
    """Map Romanian category labels to our taxonomy."""
    text = text.lower().strip()
    mapping = {
        'concert': 'concert', 'concerte': 'concert', 'rock': 'concert', 'pop': 'concert',
        'pop rock': 'concert', 'metal': 'concert', 'folk': 'concert', 'jazz': 'concert',
        'hip hop': 'concert', 'latino': 'concert', 'world music': 'concert',
        'muzica lautareasca': 'concert', 'muzica de petrecere': 'concert',
        'electronica': 'party', 'party': 'party', 'trap': 'concert', 'k-pop': 'concert',
        'teatru': 'teatru', 'spectacol': 'spectacol', 'spectacole culturale': 'teatru',
        'spectacole pentru copii': 'family',
        'stand-up': 'standup', 'stand-up comedy': 'standup',
        'festival': 'festival', 'festivaluri': 'festival',
        'expo': 'expo', 'expo / muzee': 'expo',
        'cinema': 'cinema',
        'workshop': 'workshop', 'conferinta': 'conferinta', 'conferinte': 'conferinta',
        'boardgames': 'boardgames',
        'clasică': 'concert', 'clasica si balet': 'concert', 'musical': 'spectacol',
        'sport': 'sport', 'degustari': 'workshop', 'retro': 'concert',
        'blues': 'concert',
        'colinde': 'concert', 'populara': 'concert', 'muzica populara': 'concert',
        'turneu': 'concert', 'merchandise': 'concert',
        'book club': 'workshop', 'spiritualitate': 'workshop',
        'alcool': '',  # skip
    }
    for key, val in mapping.items():
        if key in text:
            return val
    return 'concert'  # default fallback


def determine_vibe(category):
    """Heuristic vibe mapping."""
    vibe_map = {
        'concert': 'loud',
        'teatru': 'intim',
        'standup': 'loud',
        'party': 'loud',
        'expo': 'intim',
        'cinema': 'intim',
        'festival': 'casual',
        'boardgames': 'casual',
        'workshop': 'casual',
        'family': 'family',
        'conferinta': 'intim',
        'spectacol': 'intim',
        'sport': 'casual',
    }
    return vibe_map.get(category, 'casual')


def detect_category(text):
    """Detectează categoria unui eveniment pe baza textului (titlu + venue).
    Ordinea verificărilor e IMPORTANTĂ — cele mai specifice vin primele.
    Returnează una din: 'sport', 'family', 'comedy', 'teatru', 'workshop',
    'expo', 'concert', 'cinema'.
    """
    text = text.lower()

    # 1. SPORT — cel mai specific, verifică ÎNTÂI (handbal, meci, liga, echipe, etc.)
    sport_kw = [
        'handbal', 'handball', 'baschet', 'basket', 'volei', 'volleyball',
        'rugby', 'hochei', 'hockey', 'atletism', 'natație', 'natatie',
        'gimnastica', 'gimnastică', 'box', 'lupte', 'ciclism', 'motorsport',
        'formula 1', 'meci', 'liga', 'campionat', 'play-off', 'playoff',
        'liga campionilor', 'champions league', 'euro league', 'euroleague',
        'europa league', 'conference league',
        'fc ', 'cfr', 'fcsb', 'rapid', 'steaua', 'dinamo', 'petrolul', 'astra',
        'otelul', 'cfr cluj', 'fcsb ', 'fcsb-', 'voluntari', 'botoșani', 'botosani',
        'fotbal', 'football', 'soccer', 'turneu sportiv',
        'sala polivalentă', 'sala polivalenta', 'stadion', 'arena',
        'euro 2026', 'world cup', 'cupa mondială',
    ]
    for kw in sport_kw:
        if kw in text:
            return 'sport'

    # 2. CINEMA — verifică ÎNAINTE de teatru (filmele au „2D"/„3D"/„IMAX"/ODYSSEY etc.)
    # DAR nu reclasifica dacă titlul conține indicatori muzicali clari (concert simfonic, operă etc.)
    music_override = [
        'concert simfonic', 'concert simfonic', 'simfonic', 'concert de cameră',
        'concert cameră', 'concert cameral', 'orchestra', 'orchestră',
        'cor ', 'coral', 'operă', 'opera', 'balet', 'recital', 'filarmonica',
        'filarmonic', 'lansare album', 'lansare carte', 'festival de muzică',
        'festival muzica',
    ]
    has_music_override = any(kw in text for kw in music_override)
    if not has_music_override:
        cinema_kw = [
            ' 2d', ' 3d', ' imax', ' 4dx',
            'documentar', 'scurtmetraj',
            'cinematograf', 'cinematografic',
            'cinema', 'cinemateca',
            'film', 'filme', 'filmează', 'filmului', 'filmul',
            'avampremiera', 'avanpremiera',
            'maraton de film', 'maraton film', 'noaptea filmului',
        ]
        for kw in cinema_kw:
            if kw in text:
                return 'cinema'
        # Autori/regizori cunoscuți de film
        cinema_authors = ['coppola', 'spielberg', 'tarantino', 'scorsese', 'kubrick', 'hitchcock']
        for kw in cinema_authors:
            if kw in text:
                return 'cinema'
        # Titluri specifice de filme cunoscute
        film_titles = [
            'odyssey', 'odiseea', 'odissea', 'cars 2d', 'cars 3d',
            'the odyssey',
            'paw patrol', 'patrula cățelușilor', 'patrula catelusilor',
            'michael',  # film biografic Michael Jackson (2025)
            'oppenheimer', 'dune', 'avatar', 'wicked', 'joker',
            'barbie', 'wonka', 'the batman', 'black widow',
            'inside out', 'toy story', 'frozen', 'moana',
            'lion king', 'frozen 2', 'encanto', 'coco',
            'avengers', 'spider-man', 'spiderman',
        ]
        for ft in film_titles:
            if ft in text:
                return 'cinema'

    # 3. FAMILY — pentru copii/baby (specific context)
    family_kw = [
        'pentru copii', 'copiilor', 'pentru cei mici', 'kids', 'baby',
        'junior', 'păpuși', 'papusi', 'atelier pentru copii', 'atelier copii',
        'gradinita', 'grădinița', 'baby friendly', 'școală', 'scoala',
        'educational', 'educativ', 'mini club', 'mini summer',
        'cinemax', 'back to school',
    ]
    for kw in family_kw:
        if kw in text:
            return 'family'

    # 4. COMEDY / STAND-UP
    comedy_kw = ['stand-up', 'stand up', 'standup', 'comedie', 'umor', 'umorist']
    for kw in comedy_kw:
        if kw in text:
            return 'comedy'

    # 5. TEATRU / SPECTACOL — autori și titluri de piese cunoscute
    theatre_authors = [
        'ionesco', 'shakespeare', 'checkov', 'cehov', 'molière', 'moliere',
        'caragiale', 'caragiale', 'kafka', 'beckett', 'pinter', 'ibsen',
        'strindberg', 'gogol', 'ostrovski', 'tartuffe', 'hamlet', 'macbeth',
        'othello', 'caligula', 'faust',
    ]
    for kw in theatre_authors:
        if kw in text:
            return 'teatru'

    theatre_kw = [
        'teatru', 'spectacol', 'shakespeare', 'willy', 'piesă', 'piesa',
        'one man show', 'shakespear', 'comedie shakespear',
        'spectatorul', 'condamnat la moarte', 'lectia', 'lecția',
        'tartuffe', 'tartüff',
    ]
    for kw in theatre_kw:
        if kw in text:
            return 'teatru'

    # Whitelist de piese de teatru cunoscute (titluri care nu au keyword evident)
    theatre_titles = [
        'am comis-o', 'am comis o', 'conu leonida',
        'o noapte furtunoasă', 'o scrisoare pierdută',
        'inspectorul', 'inspectorul general',
        'tantalul familiei', 'oaspetele strain',
        'electronica', 'vrajitoarele din eastwick',
        'cine are nevoie de iubire', 'cine mai are nevoie de iubire',
        'cine se teme de virginia woolf',
        'scurt circuit', 'take ike ana',
    ]
    for t in theatre_titles:
        if t in text:
            return 'teatru'

    # 6. WORKSHOP / ATELIER CREATIV
    workshop_kw = [
        'workshop', 'atelier creativ', 'atelier handmade', 'curs', 'training',
        'masterclass', 'conferinta', 'conferință', 'dezbatere', 'meetup',
    ]
    for kw in workshop_kw:
        if kw in text:
            return 'workshop'

    # 7. EXPO / TÂRG / GALERIE
    expo_kw = [
        'expozitie', 'expoziție', 'expo ', 'galerie', 'art gallery',
        'vernisaj', 'târg', 'targ', 'bazar', 'street food',
    ]
    for kw in expo_kw:
        if kw in text:
            return 'expo'

    # 8. CONCERT / MUZICĂ — verificat LA URMĂ pentru că e cel mai generic
    concert_kw = [
        'concert', 'jazz', 'rock', 'metal', 'party', 'festival de muzică',
        'festival muzica', 'dj set', 'live music', 'acoustic', 'orchestra',
        'orchestră', 'simfonic', 'cor ', 'coral', 'operă', 'opera',
        'balet', 'recital', 'karaoke', 'the voice', 'x factor',
        'lansare album', 'lansare carte', 'folk', 'muzică', 'muzica',
        'cântă', 'canta',
    ]
    for kw in concert_kw:
        if kw in text:
            return 'concert'

    # 9. DEFAULT: concert (cea mai comună categorie)
    return 'concert'


def scrape_city(city_slug, city_name, existing_ids, days=30):
    """Scrape iabilet.ro for one city, return list of new events."""
    url = f"https://m.iabilet.ro/bilete-in-{city_slug}/"
    print(f"[{city_slug}] Fetching {url}...", file=sys.stderr)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[{city_slug}] ERROR: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, 'lxml')
    events = []
    today = time.strftime("%Y-%m-%d")

    # Find all event blocks: links followed by content
    # iabilet pattern: each event is wrapped in <a> with class containing "TownPage"
    event_links = soup.find_all('a', href=re.compile(r'/bilete-'))

    for link in event_links:
        try:
            href = link.get('href', '')
            if not href:
                continue

            # Extract slug from URL for unique ID
            url_slug = re.search(r'/bilete-(.+?)-(?:12|13)\d{3,4}/?$', href)
            if not url_slug:
                url_slug = re.search(r'/bilete-(.+?)/?$', href)
            if not url_slug:
                continue
            event_id_base = url_slug.group(1)

            # Generate unique ID (city-event)
            full_id = f"{city_slug[:3]}-{event_id_base[:30]}-{hash(href) % 10000}"
            if full_id in existing_ids:
                continue  # skip duplicate

            # Extract text content
            full_text = link.get_text(' ', strip=True)
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]

            # Title is usually the longest non-empty line before the venue
            title = None
            venue = None
            date_text = None
            category_text = None

            # Look for category first (italic span)
            cat_span = link.find('span', class_=re.compile(r'(Stand-up|Teatru|Concert|Festival|Expo)'))
            if cat_span:
                category_text = cat_span.get_text(strip=True)

            # Title — find longest text in link
            for line in lines:
                if len(line) > 20 and not any(d in line.lower() for d in ['/', 'bilete', 'categorii']):
                    if not title:
                        title = line
                        break

            # Venue — text after "//" pattern
            venue_match = re.search(r'//\s*([^/]+?)(?:,\s*\w+)?$', full_text)
            if venue_match:
                venue = venue_match.group(1).strip()

            # Date — look for day + month pattern
            date_match = re.search(r'(\d{1,2}\s+(?:ian|feb|mar|apr|mai|iun|iul|aug|sep|oct|noi|dec))', full_text.lower())
            if date_match:
                date_text = date_match.group(0)
            # Or check parent for day names
            if not date_text:
                # Look for sibling/parent text containing date
                parent_text = link.parent.get_text() if link.parent else ''
                date_match = re.search(r'\b(Lu|Ma|Mi|Jo|Vi|Sa|Du),?\s+(\d{1,2}\s+\w{3})\b', parent_text)
                if date_match:
                    date_text = date_match.group(2)

            if not title or not date_text:
                continue

            # Normalize date
            iso_date = normalize_date(date_text)
            if not iso_date or iso_date < today:
                continue  # skip past or unparseable

            # Time — not always available, default to 20:00
            time_match = re.search(r'(\d{1,2}):(\d{2})', full_text)
            event_time = f"{time_match.group(1)}:{time_match.group(2)}" if time_match else "20:00"

            # Category fallback
            category = normalize_category(category_text) if category_text else 'concert'

            # Price — usually "GRATUIT" or empty for paid (we'll mark paid with default 50 lei)
            is_free = 'GRATUIT' in full_text.upper() or 'gratuit' in full_text.lower()

            full_url = urljoin('https://m.iabilet.ro', href)

            event = {
                "id": full_id,
                "title": title[:120],
                "category": category,
                "vibe": determine_vibe(category),
                "date": iso_date,
                "time": event_time,
                "venue": venue or f"loc în {city_name}",
                "address": venue or f"loc în {city_name}",
                "price": "free" if is_free else "paid",
                "price_value": 0 if is_free else 60,
                "source": "iabilet",
                "url": full_url,
                "description": f"{title} — eveniment la {venue or 'locație necunoscută'} din {city_name}.",
                "highlights": [f"dată: {iso_date}", f"ora: {event_time}", f"categorie: {category}"],
                "duration": "1h 30min",
                "age": "All ages",
                "tags": [category, city_slug],
                "map_url": f"https://maps.google.com/?q={venue or city_name}".replace(' ', '+'),
                "organizer": "iabilet.ro",
                "scraped_at": today,
            }
            events.append(event)
            existing_ids.add(full_id)

        except Exception as e:
            print(f"[{city_slug}] Parse error: {e}", file=sys.stderr)
            continue

    print(f"[{city_slug}] Found {len(events)} new events", file=sys.stderr)
    return events



def scrape_bilete_ro(city_slug, city_name, existing_ids, days=30):
    """Scrape bilete.ro/calendar/ for events across all cities.
    Bilete.ro nu filtreaza pe oras in URL, deci luam calendarul complet."""
    url = "https://www.bilete.ro/calendar/"
    print(f"[bilete.ro] Fetching calendar {url}...", file=sys.stderr)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[bilete.ro] ERROR: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(r.text, 'lxml')
    events = []
    today = time.strftime("%Y-%m-%d")

    # Calendar links: /calendar/septembrie-2026/05/ for each day
    day_links = soup.find_all('a', href=re.compile(r'/calendar/[^/]+/\d+/'))

    for link in day_links:
        href = link.get('href', '')
        date_match = re.search(r'/(\d+)/$', href)
        if not date_match:
            continue
        day_num = int(date_match.group(1))
        # Get month from surrounding context (e.g., "Septembrie 2026")
        parent = link.parent
        month_year_text = ''
        for sibling in parent.find_previous_siblings():
            if '2026' in sibling.get_text():
                month_year_text = sibling.get_text()
                break
        # Simple month detection (will be improved if needed)
        if 'Septembrie' in month_year_text or not month_year_text:
            month_num = 9
        elif 'Octombrie' in month_year_text:
            month_num = 10
        else:
            continue  # skip non-relevant months

        iso_date = f"2026-{month_num:02d}-{day_num:02d}"
        if iso_date < today:
            continue

        # Fetch the day page for actual events
        try:
            day_url = urljoin('https://www.bilete.ro', href)
            day_resp = requests.get(day_url, headers=HEADERS, timeout=20)
            day_resp.raise_for_status()
            day_soup = BeautifulSoup(day_resp.text, 'lxml')
        except Exception as e:
            continue

        # Group by day items (ev-list-item) — fiecare eveniment e într-un container clar
        day_items = day_soup.find_all('div', class_=re.compile(r'ev-list-item'))
        if not day_items:
            day_items = day_soup.find_all('a', href=re.compile(r'/(?!calendar|categorii|info)[a-z0-9-]+/?$'))

        for ev_link in day_items:
            try:
                # Dacă day_items conține div-uri, ia link-ul evenimentului din interior
                if ev_link.name == 'div':
                    # Găsește link-ul evenimentului — e cel cu text='' (titlu) care nu e categorie/info/detalii/data
                    title_anchor = None
                    candidate_links = ev_link.find_all('a', href=True)
                    for a in candidate_links:
                        href = a.get('href', '')
                        # Skip categorii, info, calendar, detalii
                        if any(x in href for x in ['/categorii/', '/info/', '/calendar/', '/cauta', '/mvc/']):
                            continue
                        # Skip linkuri cu text 'Detalii', 'Bilete', date (ex: '6 sept'), etc.
                        link_text = a.get_text(strip=True).lower()
                        if link_text in ['detalii', 'bilete', 'contact', 'cauta']:
                            continue
                        if re.match(r'^\d+\s*(sept|oct|nov|dec|ian|feb|mar|apr|mai|iun|iul|aug)$', link_text):
                            continue
                        # Acesta e linkul evenimentului
                        title_anchor = a
                        break
                    if not title_anchor:
                        continue
                    ev_href = title_anchor.get('href', '')
                    # Ia title-ul din textul div-ului (primul chunk semnificativ)
                    item_text = ev_link.get_text(' | ', strip=True)
                    # Pattern: "5 sept | sâmbătă | ora 10:00 | expirat | Capra cu trei iezi | ..."
                    parts = [p.strip() for p in item_text.split('|') if p.strip()]
                    # Sari peste dată, ziua, ora, status (expirat/viitor), rămâne title
                    title = ''
                    for p in parts:
                        if p.lower() in ['expirat', 'detalii', 'bilete']:
                            continue
                        if re.match(r'^\d+ sept$', p, re.IGNORECASE):
                            continue
                        if p.lower().startswith('ora ') or p.lower().startswith('de la'):
                            continue
                        if p.lower() in ['luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă', 'duminică', 'sambata', 'duminica']:
                            continue
                        title = p
                        break
                    if not title or len(title) < 5:
                        continue
                else:
                    ev_href = ev_link.get('href', '')
                    if not ev_href or ev_href.startswith('#') or '/mvc/' in ev_href:
                        continue
                    title_el = ev_link.find(['h3', 'h2', 'span'])
                    title = title_el.get_text(strip=True) if title_el else ev_link.get_text(strip=True).split('\n')[0]
                    if not title or len(title) < 5:
                        continue

                # Skip linkuri non-eveniment evidente (categorii, info)
                if any(x in ev_href for x in ['/calendar/', '/categorii/', '/info/', '/cauta']):
                    continue
                last_seg = ev_href.rstrip('/').split('/')[-1]
                if not re.match(r'^[a-z0-9-]+$', last_seg) or len(last_seg) < 5:
                    continue

                # === DETECȚIE ORAȘ ===
                # Caută map-marker în containerul ev-list-item (sau în părintele link-ului)
                detected_city = None
                search_container = ev_link if ev_link.name == 'div' else ev_link.parent
                # Caută până la 5 niveluri
                for _ in range(5):
                    if search_container is None:
                        break
                    map_icon = search_container.find('i', class_=re.compile(r'fa-map-marker|fa-map'))
                    if map_icon:
                        # Textul orașului e lângă iconiță — primul segment înainte de virgulă
                        marker_text = map_icon.parent.get_text(' ', strip=True) if map_icon.parent else ''
                        city_candidate = marker_text.split(',')[0].strip()
                        if city_candidate:
                            city_norm = city_candidate.lower().replace('ă','a').replace('â','a').replace('î','i').replace('ș','s').replace('ț','t')
                            for slug, name in CITIES.items():
                                name_norm = name.lower().replace('ă','a').replace('â','a').replace('î','i').replace('ș','s').replace('ț','t')
                                if city_norm == name_norm or city_norm == slug.replace('-', ' '):
                                    detected_city = (slug, name)
                                    break
                        if detected_city:
                            break
                    search_container = search_container.parent if hasattr(search_container, 'parent') and search_container.parent else None

                # Fallback URL (fără fetch individual): URL conține slug oraș ca prim segment
                if not detected_city:
                    from urllib.parse import urlparse
                    ev_path = urlparse(urljoin('https://www.bilete.ro', ev_href)).path.strip('/')
                    path_parts = ev_path.split('/')
                    if len(path_parts) >= 2 and path_parts[0] in CITIES:
                        detected_city = (path_parts[0], CITIES[path_parts[0]])

                if not detected_city:
                    continue  # nu putem detecta orașul cu încredere — sărim

                # Reconstruim text_content pentru price/venue
                text_content = ev_link.get_text(' ', strip=True) if hasattr(ev_link, 'get_text') else ''

                # Unique ID
                slug_part = re.sub(r'[^a-z0-9-]', '', ev_href)[:30]
                full_id = f"{detected_city[0][:3]}-br-{slug_part}-{hash(ev_href) % 10000}"
                if full_id in existing_ids:
                    continue

                # Time — default 20:00 (ora exactă nu e pe pagina de zi)
                event_time = "20:00"

                # Price — default paid 60 lei unless we find 'GRATUIT'
                is_free = 'GRATUIT' in text_content.upper()

                # Venue — pattern "Title @ Venue" sau fallback
                venue_match = re.search(r'@\s*([^|]+?)(?:\s*\||$)', text_content)
                venue = venue_match.group(1).strip() if venue_match else f"loc în {detected_city[1]}"

                full_url = urljoin('https://www.bilete.ro', ev_href)

                # Category detection — ordinea contează (mai specific primul!)
                # Verificăm TITLE și VENUE pentru contexte (ex: "Handball" + "Sala Polivalentă" = sport)
                haystack = (title + ' ' + venue).lower()
                category = detect_category(haystack)

                vibe_map = {
                    'concert': 'loud', 'teatru': 'intim', 'family': 'family',
                    'sport': 'casual'
                }

                event = {
                    "id": full_id,
                    "title": title[:120],
                    "category": category,
                    "vibe": vibe_map.get(category, 'casual'),
                    "date": iso_date,
                    "time": event_time,
                    "venue": venue,
                    "address": venue,
                    "city_slug": detected_city[0],  # orașul detectat — sursă de adevăr unică
                    "city_name": detected_city[1],
                    "price": "free" if is_free else "paid",
                    "price_value": 0 if is_free else 60,
                    "source": "bilete.ro",
                    "url": full_url,
                    "description": f"{title} - eveniment la {venue} din {detected_city[1]}, conform calendarului bilete.ro.",
                    "highlights": [f"data: {iso_date}", f"loc: {venue}", f"categorie: {category}"],
                    "duration": "1h 30min",
                    "age": "All ages",
                    "tags": [category, "bilete-ro"],
                    "map_url": f"https://maps.google.com/?q={venue}".replace(' ', '+'),
                    "organizer": "bilete.ro",
                    "scraped_at": today,
                }
                events.append(event)
                existing_ids.add(full_id)

            except Exception as e:
                continue

    # Group by city — FOLOSIM city_slug stocat, NU re-detectăm din text
    # (re-detectarea din venue/description poate da orașe greșite dacă
    # description-ul conține alt nume de oraș)
    by_city = {}
    for ev in events:
        slug = ev.get('city_slug')
        if slug and slug in CITIES:
            if slug not in by_city:
                by_city[slug] = []
            by_city[slug].append(ev)

    print(f"[bilete.ro] Found {len(events)} new events", file=sys.stderr)
    return by_city


def main():
    days = 30
    if '--days' in sys.argv:
        i = sys.argv.index('--days')
        days = int(sys.argv[i + 1])

    # Load existing events.json to skip duplicates
    events_file = Path(__file__).parent.parent / 'events.json'
    existing_ids = set()
    if events_file.exists():
        try:
            data = json.load(open(events_file))
            for city in data.get('cities', []):
                for ev in city.get('events', []):
                    existing_ids.add(ev.get('id', ''))
        except Exception as e:
            print(f"WARN: could not parse events.json: {e}", file=sys.stderr)

    print(f"Existing IDs in events.json: {len(existing_ids)}", file=sys.stderr)

    # Scrape iabilet.ro per city
    all_new = []
    for slug, name in CITIES.items():
        new_events = scrape_city(slug, name, existing_ids, days)
        if new_events:
            all_new.append({"slug": slug, "name": name, "events": new_events})
        time.sleep(2)  # polite delay between cities

    # Scrape bilete.ro (covers all cities in one go)
    bilete_by_city = scrape_bilete_ro(None, None, existing_ids, days)
    if bilete_by_city:
        for slug, events in bilete_by_city.items():
            existing_entry = next((c for c in all_new if c['slug'] == slug), None)
            if existing_entry:
                existing_entry['events'].extend(events)
            else:
                all_new.append({"slug": slug, "name": CITIES[slug], "events": events})
        time.sleep(2)

    # Output: JSON to stdout (merge script reads this)
    print(json.dumps(all_new, ensure_ascii=False))


if __name__ == '__main__':
    main()
