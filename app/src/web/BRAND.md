# Brand packs

The app is not compiled for any one bank. At start-up `src/brand.ts` loads
`public/brand/brands.json` — a manifest written by
`tools/brand/fetch_brand.py` — and applies the default pack's colours (CSS
custom properties), favicon, logos and names. Copy authored for the fictional
**CFC Bank** is relabelled client-side to the selected bank's short name.

```
public/brand/
├── brands.json          generated · git-ignored · { default, order, brands[] }
├── favicon.png          neutral favicon before the manifest loads
├── cfc/                 fictional default - the only pack in git
│   ├── brand.json       name, short, aliases, colours, asset file names
│   ├── lockup.png       sign-in card logo
│   ├── mark.png         top-bar mark (legible on the brand colour)
│   └── favicon.png      64 px
└── <bank-id>/           fetched at deploy time · git-ignored
```

Without `brands.json` the app falls back to the built-in CFC Bank pack, so a
fresh clone always renders.

## brand.json

```json
{
  "name": "RBC Personal Banking",
  "short": "RBC",
  "aliases": ["rbc", "royal bank", "royal bank of canada"],
  "colors": { "brand": "#005daa", "accent": "#fedf01" },
  "assets": { "lockup": "lockup.png", "mark": "mark.png", "favicon": "favicon.png" }
}
```

Only `name` and `colors.brand` are required. Missing shades (`brandDeep`,
`brandTint`, `brandLine`, `brandInk`, `accentInk`, `accentFg`) are derived,
with a contrast floor so text on white and on the top bar stays legible.

## Adding a bank

```powershell
python tools/brand/fetch_brand.py --bank "Royal Bank of Canada"        # lookup
python tools/brand/fetch_brand.py --bank "Contoso Bank" --offline --logo .\logo.png --primary "#0b5cab"
python tools/brand/fetch_brand.py --list
```

See [docs/deploy-for-your-bank.md](../../../docs/deploy-for-your-bank.md).

Bank marks are used **for demo presentation only**; all data in this
application is synthetic. Packs for real banks are kept out of the repository —
confirm you may use a bank's marks before presenting them.
