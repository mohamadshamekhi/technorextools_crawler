#!/usr/bin/env python3
"""pumaair.ir mega-menu category crawler.

Reads the "دسته‌بندی‌ها" mega menu on the homepage (left: top-level tabs with an icon, right: their
sub-categories, some of which have their own children) and writes only the categories that menu shows:

  output/menu_categories.json          flat, parents first — the input of import_categories.py --src
  output/category_icons/<slug>.png     top-level menu icon, rasterised (the API takes PNG/JPEG/WebP)

  python3 menu_categories.py
  python3 menu_categories.py --html page.html     # parse a saved copy of the homepage instead
  python3 menu_categories.py --save-html          # also keep output/home.html (to debug the parser)

Hierarchy, in order of trust:
  1. tabs (role="tab" + aria-controls -> role="tabpanel"): each tab is a top-level category;
  2. otherwise <li> nesting of menu items (a WordPress nav menu);
  3. inside a tab / when neither exists: the WooCommerce parent of each category, limited to the
     categories the menu shows (so a heading like «پیچ گوشتی بادی» keeps its children).
Slugs are the source slugs (Persian ones transliterated, see categories.py). Images: the menu icon for
top-level categories, the WooCommerce category image otherwise (import_category_images.py falls back to
the most popular product's image).
"""
import argparse
import json
import re
import sys
import urllib.parse
from html import unescape
from pathlib import Path

from brands import SITE, Tree, http_get, rasterise
from categories import fetch_all, to_slug
from import_category_images import http_get as fetch_file

OUT_DIR = Path("output")
ICON_DIR = OUT_DIR / "category_icons"
ALL_PREFIX = "همه محصولات"


class TextTree(Tree):
    """brands.Tree plus text nodes and parent links."""

    def handle_data(self, data):
        if data.strip():
            self.stack[-1]["kids"].append({"tag": "#text", "a": {}, "kids": [], "text": data})


def link_parents(node, parent=None):
    node["parent"] = parent
    for kid in node["kids"]:
        link_parents(kid, node)


def walk(node):
    yield node
    for kid in node["kids"]:
        yield from walk(kid)


def text(node):
    parts = [n["text"] for n in walk(node) if n["tag"] == "#text"]
    return re.sub(r"\s+", " ", unescape(" ".join(parts))).strip()


def ancestors(node):
    node = node["parent"]
    while node:
        yield node
        node = node["parent"]


def cat_slug(href):
    """Last path segment of a /product-category/a/b/ link (WooCommerce nests parents in the URL)."""
    _, found, rest = urllib.parse.urlparse(href or "").path.partition("/product-category/")
    segments = [s for s in rest.split("/") if s]
    return urllib.parse.unquote(segments[-1]).lower() if found and segments else None


def icon_of(node):
    """First inline svg (not an icon-font arrow) or img inside node -> ("svg", markup) / ("img", src)."""
    for n in walk(node):
        if n["tag"] == "svg" and "e-font-icon-svg" not in (n["a"].get("class") or ""):
            return "svg", n["source"]
        if n["tag"] == "img":
            src = n["a"].get("data-src") or n["a"].get("data-lazy-src") or n["a"].get("src") or ""
            if src and not src.startswith("data:"):
                return "img", urllib.parse.urljoin(SITE + "/", src)
    return None


def item_of(a):
    """The element that holds one menu item: the highest ancestor containing no other category link."""
    best = a
    for anc in ancestors(a):
        if sum(1 for n in walk(anc) if n["tag"] == "a" and cat_slug(n["a"].get("href"))) > 1:
            break
        best = anc
    return best


def menu_links(root):
    return [n for n in walk(root) if n["tag"] == "a" and cat_slug(n["a"].get("href"))]


def from_tabs(root, wc_by_slug):
    """[(top_slug, title, icon, [links in its panel])] for every tab whose panel holds category links."""
    by_id = {n["a"]["id"]: n for n in walk(root) if n["a"].get("id")}
    tops = []
    for tab in walk(root):
        if tab["a"].get("role") != "tab" or not tab["a"].get("aria-controls"):
            continue
        panel = by_id.get(tab["a"]["aria-controls"])
        links = menu_links(panel) if panel else []
        if not links:
            continue
        title = text(tab)
        # the panel's «همه محصولات X» link, else a link titled like the tab, else the tab's own link
        top = next((a for a in links if text(a).startswith(ALL_PREFIX)), None) \
            or next((a for a in links if text(a) == title), None)
        slug = cat_slug(top["a"]["href"]) if top else cat_slug(next(
            (n["a"].get("href") for n in walk(tab) if n["tag"] == "a"), None))
        if not slug:
            slug = next((s for s, c in wc_by_slug.items() if unescape(c["name"]).strip() == title), None)
        if not slug:
            print(f"  ! tab «{title}» has no category link — skipped", file=sys.stderr)
            continue
        tops.append((slug, title, icon_of(tab), [a for a in links if cat_slug(a["a"]["href"]) != slug]))
    return tops


def from_li(links):
    """{slug: parent slug or None} from <li> nesting, or None if the menu isn't a nested list."""
    parents, nested = {}, False
    for a in links:
        slug, own_li = cat_slug(a["a"]["href"]), None
        parent = None
        for anc in ancestors(a):
            if anc["tag"] != "li":
                continue
            if own_li is None:
                own_li = anc
                continue
            head = next((n for n in walk(anc) if n["tag"] == "a" and cat_slug(n["a"].get("href"))), None)
            if head is not None and head is not a:
                parent = cat_slug(head["a"]["href"])
                break
        nested |= parent is not None
        parents.setdefault(slug, parent)
    return parents if nested else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", type=Path, help="parse this saved homepage instead of downloading it")
    ap.add_argument("--save-html", action="store_true", help="keep the downloaded homepage as output/home.html")
    args = ap.parse_args()

    html = args.html.read_text(encoding="utf-8") if args.html else http_get(SITE + "/").decode("utf-8", "replace")
    OUT_DIR.mkdir(exist_ok=True)
    if args.save_html:
        (OUT_DIR / "home.html").write_text(html, encoding="utf-8")

    wc = fetch_all()
    wc_by_id = {c["id"]: c for c in wc}
    wc_by_slug = {urllib.parse.unquote(c["slug"]).lower(): c for c in wc}

    tree = TextTree(html)
    link_parents(tree.root)
    links = menu_links(tree.root)
    if not links:
        sys.exit("no /product-category/ links on the homepage — the menu may be loaded by JS; "
                 "save the page from a browser and re-run with --html")

    # slug -> {title, parent, icon, order}; first occurrence wins (the menu is repeated for mobile)
    cats = {}

    def add(slug, title, parent, icon):
        if slug in cats or slug == parent:
            return
        cats[slug] = {"title": title, "parent": parent, "icon": icon, "order": len(cats)}

    def wc_parent(slug, allowed):
        """Nearest WooCommerce ancestor of slug that is in `allowed`."""
        c = wc_by_slug.get(slug)
        while c and c["parent"] in wc_by_id:
            c = wc_by_id[c["parent"]]
            p = urllib.parse.unquote(c["slug"]).lower()
            if p in allowed:
                return p
        return None

    def title_of(a, slug):
        t = text(a)
        if t and not t.startswith(ALL_PREFIX):
            return t
        c = wc_by_slug.get(slug)
        return unescape(c["name"]).strip() if c else t

    tops = from_tabs(tree.root, wc_by_slug)
    if tops:
        strategy = f"tabs ({len(tops)})"
        for slug, title, icon, _ in tops:
            add(slug, title, None, icon)
        for top, _, _, panel in tops:
            allowed = {cat_slug(a["a"]["href"]) for a in panel} | {top}
            for a in panel:
                slug = cat_slug(a["a"]["href"])
                add(slug, title_of(a, slug), wc_parent(slug, allowed) or top, None)
    else:
        nesting = from_li(links)
        strategy = "li nesting" if nesting else "woocommerce parents"
        allowed = {cat_slug(a["a"]["href"]) for a in links}
        for a in links:
            slug = cat_slug(a["a"]["href"])
            parent = nesting[slug] if nesting else wc_parent(slug, allowed)
            add(slug, title_of(a, slug), parent, None)
        for slug, c in cats.items():  # icons only on top-level items
            if not c["parent"]:
                a = next(a for a in links if cat_slug(a["a"]["href"]) == slug)
                c["icon"] = icon_of(item_of(a))

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    depth_memo = {}

    def depth(slug):
        if slug not in depth_memo:
            p = cats[slug]["parent"]
            depth_memo[slug] = 0 if p not in cats else depth(p) + 1
        return depth_memo[slug]

    flat = []
    for raw_slug, c in cats.items():
        slug = to_slug(raw_slug)[0]
        icon = None
        if c["icon"]:
            kind, payload = c["icon"]
            content = payload.encode() if kind == "svg" else fetch_file(payload)[0]
            ext = "svg" if kind == "svg" else (Path(urllib.parse.urlparse(payload).path).suffix.lstrip(".") or "img")
            src = ICON_DIR / f"{slug}.{ext}"
            src.write_bytes(content)
            png = ICON_DIR / f"{slug}.png"
            if src != png:
                rasterise(src, png)
            icon = str(png.relative_to(OUT_DIR))
        w = wc_by_slug.get(raw_slug)
        parent = c["parent"] if c["parent"] in cats else None
        flat.append({
            "sourceId": w["id"] if w else None,
            "title": c["title"],
            "slug": slug,
            "slugGenerated": to_slug(raw_slug)[1],
            "sourceSlug": raw_slug,
            "parentSlug": to_slug(parent)[0] if parent else None,
            "depth": depth(raw_slug),
            "sortOrder": c["order"],
            "productCount": w["count"] if w else None,
            "icon": icon,
            "imageUrl": ((w or {}).get("image") or {}).get("src"),
            "url": w["permalink"] if w else f"{SITE}/product-category/{urllib.parse.quote(raw_slug)}/",
        })
    flat.sort(key=lambda c: (c["depth"], c["sortOrder"]))
    dupes = {c["slug"] for c in flat if sum(1 for d in flat if d["slug"] == c["slug"]) > 1}
    if dupes:
        sys.exit(f"slug collision after transliteration: {', '.join(sorted(dupes))} — add SLUG_OVERRIDES in categories.py")

    (OUT_DIR / "menu_categories.json").write_text(json.dumps(flat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    children = {}
    for c in flat:
        children.setdefault(c["parentSlug"], []).append(c)

    def show(parent, ind=0):
        for c in children.get(parent, []):
            flags = [f for f, on in (("icon", c["icon"]), ("img", c["imageUrl"]), ("not in woocommerce", not c["sourceId"]),
                                     ("slug generated", c["slugGenerated"])) if on]
            print(f"{'  ' * ind}- {c['title']}  [{c['slug']}]  {', '.join(flags)}")
            show(c["slug"], ind + 1)
    show(None)
    print(f"\n{len(flat)} categories ({len(children.get(None, []))} top-level, hierarchy from {strategy}) "
          f"-> output/menu_categories.json", file=sys.stderr)


if __name__ == "__main__":
    main()
