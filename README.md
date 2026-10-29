# technorextools_crawler

Crawls pumaair.ir and imports into the Technorex API (`https://api.technorextools.com`, override with `--base`).
Python 3 standard library only; rasterising SVG logos/icons uses `sharp` from `../api/node_modules`.
Import scripts read the admin access token from `ABZAR_TOKEN` and never print it.

## Panel (recommended)

```bash
python3 panel.py        # opens http://127.0.0.1:8765
```

Every step below, grouped by feature and in order, with a run button and live output. Log in once with the
admin mobile (OTP) inside the panel; the token stays in the panel process, is refreshed before each step and
passed to the scripts — no `ABZAR_TOKEN=...` copying. Pick the target server (production / localhost:4000) at
the top. Steps are registered in `panel_steps.py`; a new script gets an entry there in the same change.

## Categories from the homepage mega menu (wipe and re-import)

```bash
python3 menu_categories.py                     # -> output/menu_categories.json + output/category_icons/
ABZAR_TOKEN=... python3 reset_categories.py --dry-run
ABZAR_TOKEN=... python3 reset_categories.py --yes
ABZAR_TOKEN=... python3 import_categories.py --src output/menu_categories.json
ABZAR_TOKEN=... python3 import_category_images.py --src output/menu_categories.json
```

- `reset_categories.py` deletes every category (children first) and its images. A category that still
  has products can't be deleted (API 409) — it and its parents are reported `blocked` and kept.
- If `menu_categories.py` finds no links (menu built by JS), save the homepage from a browser and run
  `python3 menu_categories.py --html saved.html`. `--save-html` keeps the downloaded page for debugging.

## Other scripts

- `categories.py` → `output/categories.json`: the full WooCommerce category tree (not just the menu).
- `brands.py` → `output/brands.json` + logos; `import_brands.py` imports them.
