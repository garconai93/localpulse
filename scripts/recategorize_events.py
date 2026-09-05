#!/usr/bin/env python3
"""
LocalEvent - Recategorizare evenimente
Reaplică logica de detectare categorie pe events.json existent,
pentru a corecta evenimente încadrate greșit în trecut.

Usage:
  python3 recategorize_events.py [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

# Import logica centralizată
sys.path.insert(0, str(Path(__file__).parent))
from fetch_events import detect_category


def main():
    parser = argparse.ArgumentParser(description="Recategorize events in events.json")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving")
    args = parser.parse_args()

    events_file = Path(__file__).parent.parent / 'events.json'
    if not events_file.exists():
        print(f"ERROR: {events_file} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(events_file.read_text())

    # Vibe mapping per categorie
    vibe_map = {
        'concert': 'loud',
        'teatru': 'intim',
        'family': 'family',
        'sport': 'casual',
        'comedy': 'loud',
        'workshop': 'casual',
        'expo': 'intim',
    }

    # Mapare: categorie veche → categorie nouă standard
    # Astfel, alias-urile vechi (atelier, spectacol, familie, outdoor) sunt
    # normalizate la cele noi (family, teatru, family, concert/other).
    alias_map = {
        'spectacol': 'teatru',      # spectacol vechi = teatru
        'familie': 'family',
        'expozitie': 'expo',
        'standup': 'comedy',
        'conferinta': 'workshop',
        'film': 'family',           # film la cinema pt copii
        'festival': 'concert',
        'cinema': 'family',
        'party': 'concert',
        'boardgames': 'family',
        'targ': 'expo',
    }

    # După normalizarea alias-urilor, reclasifică DOAR dacă detect_category
    # dă ceva cu prioritate mai mare decât categoria normalizată.
    priority = {
        'sport': 100, 'family': 80, 'comedy': 60, 'teatru': 50,
        'workshop': 40, 'expo': 30, 'concert': 10,
        'atelier': 20,  # e neutru — nu e concert dar nici specific
        'outdoor': 20,  # similar
    }

    changes = 0
    by_change = {}  # (old, new) -> count
    samples = []

    for city in data.get('cities', []):
        for e in city.get('events', []):
            old_cat = e.get('category', 'concert')
            # Normalizare alias
            old_cat_norm = alias_map.get(old_cat, old_cat)

            title = e.get('title', '') or ''
            venue = e.get('venue', '') or ''
            haystack = (title + ' ' + venue).lower()
            new_cat = detect_category(haystack)

            old_p = priority.get(old_cat_norm, 0)
            new_p = priority.get(new_cat, 0)
            # Reclasifică DOAR dacă:
            # - noua categorie e diferită de cea normalizată
            # - noua categorie are prioritate strict mai mare
            if new_cat != old_cat_norm and new_p > old_p:
                key = (old_cat, new_cat)
                by_change[key] = by_change.get(key, 0) + 1
                if len(samples) < 100:
                    samples.append({
                        'title': title[:80],
                        'city': city['slug'],
                        'old': old_cat,
                        'new': new_cat,
                    })
                e['category'] = new_cat
                # Update vibe dacă se schimbă categoria
                new_vibe = vibe_map.get(new_cat, 'casual')
                if e.get('vibe') != new_vibe:
                    e['vibe'] = new_vibe
                changes += 1

    print(f"📊 Total evenimente actualizate: {changes}", file=sys.stderr)
    print(f"\n🔄 Distribuție schimbări (old → new):", file=sys.stderr)
    for (old, new), n in sorted(by_change.items(), key=lambda x: -x[1]):
        print(f"   {old:12} → {new:12} : {n}", file=sys.stderr)

    print(f"\n📋 Sample (primele 30):", file=sys.stderr)
    for s in samples:
        print(f"   [{s['city']:12}] {s['old']:10} → {s['new']:10} | {s['title']}", file=sys.stderr)

    if args.dry_run:
        print(f"\n🏁 DRY RUN: nu am salvat nimic.", file=sys.stderr)
        return

    data['last_recategorized'] = __import__('time').strftime("%Y-%m-%d")
    events_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n✅ Salvat în {events_file}", file=sys.stderr)


if __name__ == '__main__':
    main()
