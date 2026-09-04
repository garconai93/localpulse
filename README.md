# LocalEvent

**LocalEvent** — agregator de evenimente mici din 7 orașe mari din România (București, Cluj-Napoca, Timișoara, Iași, Constanța, Sibiu, Craiova) + orașe limitrofe (Voluntari, Otopeni, Clinceni).

În loc să cauți pe 12 surse (FB Events, IG, site-uri locale, Eventbrite), LocalEvent îți dă un singur feed curat, cu filtre pe dată, preț și vibe.

## Funcționalități MVP

- ✅ **10 orașe** cu evenimente reale din septembrie 2026 (colectate automat din 6 surse)
- ✅ **Detectare automată a orașului** pe baza geolocației (haversine pe lat/lon)
- ✅ **Dropdown manual** pentru schimbare oraș
- ✅ **Filtre** — perioadă (azi / weekend / 7 zile / toate), preț (gratuit / plătit), vibe (intim / loud / casual / family)
- ✅ **Salvare automată** a orașului ales (localStorage)
- ✅ **Statistici live** — total, gratis, weekend, categorii
- ✅ **Mobile-first responsive** cu dark mode premium
- ✅ **Auto-update zilnic** prin GitHub Actions (workflow `daily-events.yml`)

## Surse agregate

| Sursă | Tip | Acoperire | Evenimente (sept 2026) |
|---|---|---|---|
| **iabilet.ro** | ticketing | Național | ~50 |
| **bilete.ro** | ticketing | Național | ~10 |
| **ticketstore.ro** | ticketing | Național | mic |
| **litoralpress.ro** | știri/evenimente | Litoral | ~3 |
| **clujtourism.ro** | turism | Cluj-Napoca | ~1 |
| **stiudelasorina.ro** | calendar familii | București + Ilfov | ~500 |

## Stack

- HTML/CSS/JS vanilla (zero build tools)
- `events.json` static, încărcat via `fetch`
- GitHub Pages hosting
- GitHub Actions pentru auto-update zilnic (Python + requests + BeautifulSoup)

## Demo

https://garconai93.github.io/localpulse/  →  https://localevent.ro

## Cum funcționează update-ul automat

Workflow-ul `.github/workflows/daily-events.yml` rulează zilnic la 06:00 UTC (08:00 RO):

1. `scripts/fetch_events.py` — scrape iabilet pentru cele 7 orașe
2. `scripts/fetch_stiudelasorina.py` — TEC REST API pentru stiudelasorina.ro
3. `scripts/merge_events.py` — combină datele noi cu `events.json`, marchează evenimentele trecute ca `past:true`
4. Commit + push automat dacă `events.json` s-a schimbat
5. GitHub Pages rebuild automat → site live în 1-2 minute

## Cum adaugi manual evenimente

Editează `events.json` și adaugă obiect nou în array-ul `events` al orașului dorit:

```json
{
  "id": "buc-011",
  "title": "Titlu eveniment",
  "category": "concert",
  "vibe": "loud",
  "date": "2026-09-20",
  "time": "21:00",
  "venue": "Sala X",
  "price": "paid",
  "price_value": 100,
  "source": "manual",
  "url": "https://..."
}
```

Categorii acceptate: `concert`, `teatru`, `standup`, `party`, `expo`, `cinema`, `festival`, `boardgames`, `workshop`, `family`, `conferinta`, `spectacol`, `sport`, `atelier`, `film`, `expozitie`, `targ`, `outdoor`.

Vibe-uri acceptate: `intim`, `loud`, `casual`, `family`.

## License

MIT
