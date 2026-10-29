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
passed to the scripts — no `ABZAR_TOKEN=...` copying. A script that hits a 401 mid-run (long imports outlive the
15-minute token) asks the panel for a fresh token and carries on. Pick the target server (production / localhost:4000) at
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

## Category attributes from product specs

```bash
python3 category_specs.py                                # -> output/category_specs.json
ABZAR_TOKEN=... python3 import_category_attributes.py --dry-run
ABZAR_TOKEN=... python3 import_category_attributes.py
```

- `category_specs.py` opens the first product of every category (falls back to the next ones when it has no
  spec list) and parses its bullet list into key/value pairs: «میزان برش استیل: 1.6 میلی متر» → number, unit
  `میلی متر`; «وزن دستگاه 1.08kg» (no colon) → number, unit `kg`; «مدل AT-6112» → text. A `/` between digits
  is read as the Persian decimal point (`6/3psi` = 6.3) except in inch sizes. Brand is dropped (products have a
  brand field); non-pair lines are listed under `skipped`.
- `import_category_attributes.py` gives each of our categories (by slug) an attribute group «ویژگی فنی و ظاهری»
  and adds the missing attributes. It never edits or deletes, so re-running is safe.

## Products

```bash
python3 products.py --limit 3                              # test: first 3 products -> output/products.json
python3 products.py --product saw-perpendicular-at-6112    # test: one product (slug or full URL)
python3 products.py                                        # everything
ABZAR_TOKEN=... python3 import_products.py --dry-run
ABZAR_TOKEN=... python3 import_products.py                 # --update also refreshes existing ones
```

- Category = the most specific of the product's categories that exists on the API; brand = the first of its
  brands/tags that is one of our brands. Import categories and brands first.
- One variant per product: the source SKU (a slug-based `PA-…` one if missing/non-latin/taken), stock = the
  source quantity if shown, else `--default-stock` (10) when in stock, else 0; weight from «وزن …» specs.
- No price on the source («تماس بگیرید») → created with price 0 and **inactive**.
- Specs go into the category's «ویژگی فنی و ظاهری» attributes (missing ones are added), then the product's values.
- Images → product gallery, first one main. Re-running only fills what an existing product is missing.

## Other scripts

- `categories.py` → `output/categories.json`: the full WooCommerce category tree (not just the menu).
- `brands.py` → `output/brands.json` + logos; `import_brands.py` imports them.
