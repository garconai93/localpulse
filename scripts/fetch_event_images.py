#!/usr/bin/env python3
"""
LocalEvent - Download imagini evenimente
Descarcă local pozele reale ale evenimentelor (og:image / JSON-LD image
din paginile sursă). Stochează în events-images/ și actualizează events.json
cu path-ul local.

Rulează DUPĂ fetch_* și merge_events.py.

Usage:
  python3 fetch_event_images.py [--dry-run]
"""
import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UA_DESKTOP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0"
UA_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"

# Surse care folosesc API JSON (image.url direct)
API_IMAGE_SOURCES = {"zilesinopti", "stiudelasorina"}

# Surse care folosesc og:image din pagina HTML
OG_IMAGE_SOURCES = {"iabilet", "bilete.ro", "ticketstore", "litoralpress", "clujtourism", "cluj4ever"}


def sanitize_id(ev_id):
    """Curăță ID-ul pentru a fi folosit ca nume de fișier."""
    s = unicodedata.normalize('NFD', ev_id)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-zA-Z0-9_-]', '_', s)
    return s[:80]


def get_ext(url):
    """Determină extensia imaginii din URL."""
    url_lower = url.lower()
    if '.png' in url_lower: return '.png'
    if '.webp' in url_lower: return '.webp'
    if '.jpeg' in url_lower or '.jpg' in url_lower: return '.jpg'
    return '.jpg'


def encode_url(url):
    """Encode URL corect (caractere non-ASCII în path)."""
    try:
        parsed = urllib.parse.urlparse(url)
        path_encoded = urllib.parse.quote(parsed.path, safe='/-_.~')
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path_encoded, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return url


def extract_og_image(html, url):
    """Extrage og:image sau JSON-LD image din HTML."""
    # 1. og:image
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.IGNORECASE)
    if m:
        img = m.group(1).strip()
        if 'placeholder' not in img.lower() and 'logo' not in img.lower():
            return img

    # 2. JSON-LD (schema.org)
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>([^<]+)</script>', html, re.IGNORECASE):
        try:
            data = json.loads(m.group(1))
            img = data.get('image')
            if isinstance(img, str):
                if 'placeholder' not in img.lower() and 'logo' not in img.lower():
                    return img
            elif isinstance(img, list) and img:
                img = img[0]
                if isinstance(img, str) and 'placeholder' not in img.lower():
                    return img
            elif isinstance(img, dict):
                img = img.get('url')
                if img and 'placeholder' not in img.lower():
                    return img
        except Exception:
            pass

    # 3. twitter:image
    m = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', html, re.IGNORECASE)
    if m:
        img = m.group(1).strip()
        if 'placeholder' not in img.lower() and 'logo' not in img.lower():
            return img

    # 4. prima <img> relevantă
    for img_m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        src = img_m.group(1)
        if 'logo' in src.lower() or 'icon' in src.lower():
            continue
        if 'wp-content' in src.lower() or 'event' in src.lower() or 'img' in src.lower():
            return src

    return None


def fetch_and_download(args):
    """Fetch pagina evenimentului, extrage og:image, descarcă local."""
    ev_id, url, src = args
    safe_id = sanitize_id(ev_id)
    img_dir = Path(__file__).parent.parent / 'events-images'

    # Determină User-Agent
    ua = UA_IOS if 'iabilet' in (url or '') else UA_DESKTOP

    # Skip dacă avem deja un fișier valid
    for ext in ['.jpg', '.png', '.webp', '.jpeg']:
        existing = img_dir / (safe_id + ext)
        if existing.exists() and existing.stat().st_size > 1000:
            return (ev_id, 'exists', existing.name)

    # Fetch HTML
    try:
        req = urllib.request.Request(url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return (ev_id, f'fetch_error: {str(e)[:50]}', None)

    img_url = extract_og_image(html, url)
    if not img_url:
        return (ev_id, 'no_og_image', None)

    # Descarcă
    ext = get_ext(img_url)
    local_path = img_dir / (safe_id + ext)
    try:
        encoded = encode_url(img_url)
        req2 = urllib.request.Request(encoded, headers={'User-Agent': ua, 'Referer': url})
        with urllib.request.urlopen(req2, timeout=15) as r2:
            data = r2.read()
            if len(data) < 500:
                return (ev_id, 'too_small', None)
            with open(local_path, 'wb') as f:
                f.write(data)
            return (ev_id, 'ok', local_path.name)
    except Exception as e:
        return (ev_id, f'dl_error: {str(e)[:50]}', None)


def main():
    parser = argparse.ArgumentParser(description="Download event images")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    events_file = Path(__file__).parent.parent / 'events.json'
    if not events_file.exists():
        print(f"ERROR: {events_file} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(events_file.read_text())
    img_dir = Path(__file__).parent.parent / 'events-images'
    img_dir.mkdir(exist_ok=True)

    # Colectez evenimente care au URL și n-au deja image local
    pending = []
    skipped_local = 0
    skipped_no_url = 0

    for city in data.get('cities', []):
        for e in city.get('events', []):
            ev_id = e.get('id', '')
            url = e.get('url', '')
            src = e.get('source', '')
            current_image = e.get('image', '')

            # Skip dacă image deja există local
            if current_image.startswith('events-images/'):
                safe_id = sanitize_id(ev_id)
                for ext in ['.jpg', '.png', '.webp', '.jpeg']:
                    if (img_dir / (safe_id + ext)).exists():
                        skipped_local += 1
                        break
                else:
                    pending.append((ev_id, url, src))
                continue

            if not url or not url.startswith('http'):
                skipped_no_url += 1
                continue

            pending.append((ev_id, url, src))

    print(f"📊 Evenimente deja cu poză locală: {skipped_local}", file=sys.stderr)
    print(f"⏭️  Evenimente fără URL: {skipped_no_url}", file=sys.stderr)
    print(f"🔄 De procesat: {len(pending)}", file=sys.stderr)

    if not pending:
        print("✅ Toate evenimentele au deja poză.", file=sys.stderr)
        return

    if args.dry_run:
        print("🏁 DRY RUN — nu descarc nimic.", file=sys.stderr)
        return

    # Procesare în paralel
    ok = 0
    errors = 0
    error_samples = []
    updates = {}  # ev_id → local_path

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_and_download, item) for item in pending]
        for i, f in enumerate(as_completed(futures)):
            ev_id, status, fname = f.result()
            if status in ('ok', 'exists'):
                if status == 'ok':
                    ok += 1
                    updates[ev_id] = 'events-images/' + fname
            else:
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append((ev_id, status))
            if (i+1) % 50 == 0:
                print(f"  Progress: {i+1}/{len(pending)}, OK={ok}, errors={errors}", file=sys.stderr)

    # Update events.json
    for city in data.get('cities', []):
        for e in city.get('events', []):
            ev_id = e.get('id', '')
            if ev_id in updates:
                e['image'] = updates[ev_id]

    # Update last_images sync
    data['last_images_sync'] = time.strftime('%Y-%m-%d')

    events_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    print(f"\n✅ Imagini noi descărcate: {ok}", file=sys.stderr)
    print(f"⚠️  Erori: {errors}", file=sys.stderr)
    if error_samples:
        print("Sample erori:", file=sys.stderr)
        for ev_id, status in error_samples:
            print(f"  {ev_id}: {status}", file=sys.stderr)
    print(f"💾 Salvat în {events_file}", file=sys.stderr)


if __name__ == '__main__':
    main()
