"""The steps panel.py can run, grouped by feature and listed in the order to run them.

Every script (or new flag worth a button) gets an entry here — the panel only runs what is listed, by id.

  id         unique, stable (the browser keeps each step's last result under it)
  title/desc Persian, shown on the page
  args       argv after `python3` — fixed, never built from browser input
  token      needs ABZAR_TOKEN; the panel adds it plus `--base` (when not the default server)
  danger     irreversible on the server — asks for confirmation before running
  optional   not part of the group's "run all"
"""

GROUPS = [
    {
        "id": "menu-categories",
        "title": "دسته‌بندی‌ها از منوی سایت (حذف و ایمپورت دوباره)",
        "desc": "فقط دسته‌هایی که منوی «دسته‌بندی‌ها» در صفحه‌ی اصلی pumaair.ir نشان می‌دهد.",
        "steps": [
            {
                "id": "menu-crawl",
                "title": "خواندن منوی دسته‌بندی‌ها",
                "desc": "خروجی: output/menu_categories.json و آیکن‌ها در output/category_icons/. به سرور دست نمی‌زند.",
                "args": ["menu_categories.py"],
            },
            {
                "id": "menu-crawl-html",
                "title": "خواندن منو از صفحه‌ی ذخیره‌شده",
                "desc": "اگر مرحله‌ی قبل لینکی پیدا نکرد: صفحه‌ی اصلی را از مرورگر با نام saved.html در پوشه‌ی crowler ذخیره کنید و این را بزنید.",
                "args": ["menu_categories.py", "--html", "saved.html"],
                "optional": True,
            },
            {
                "id": "menu-reset-dry",
                "title": "پیش‌نمایش حذف همه‌ی دسته‌ها",
                "desc": "فقط فهرست می‌کند چه چیزی حذف می‌شود و چه چیزی (به‌خاطر داشتن محصول) می‌ماند.",
                "args": ["reset_categories.py", "--dry-run"],
                "token": True,
            },
            {
                "id": "menu-reset",
                "title": "حذف همه‌ی دسته‌ها و تصاویرشان",
                "desc": "غیرقابل برگشت. دسته‌ای که هنوز محصول دارد پاک نمی‌شود (blocked).",
                "args": ["reset_categories.py", "--yes"],
                "token": True,
                "danger": True,
            },
            {
                "id": "menu-import",
                "title": "ایمپورت دسته‌ها",
                "desc": "به ترتیب والد ← فرزند. دسته‌های موجود (هم‌اسلاگ) رد می‌شوند.",
                "args": ["import_categories.py", "--src", "output/menu_categories.json"],
                "token": True,
            },
            {
                "id": "menu-images",
                "title": "ایمپورت تصاویر دسته‌ها",
                "desc": "آیکن منو برای دسته‌های اصلی، تصویر دسته یا پرفروش‌ترین محصول برای بقیه.",
                "args": ["import_category_images.py", "--src", "output/menu_categories.json"],
                "token": True,
            },
        ],
    },
    {
        "id": "tree-categories",
        "title": "درخت کامل دسته‌بندی‌ها (WooCommerce)",
        "desc": "همه‌ی دسته‌های فروشگاه، نه فقط منو. چیزی پاک نمی‌شود؛ فقط دسته‌های جاافتاده ساخته می‌شوند.",
        "steps": [
            {
                "id": "tree-crawl",
                "title": "خواندن درخت دسته‌ها",
                "desc": "خروجی: output/categories.json. به سرور دست نمی‌زند.",
                "args": ["categories.py"],
            },
            {
                "id": "tree-import-dry",
                "title": "پیش‌نمایش ایمپورت",
                "desc": "نشان می‌دهد چه دسته‌هایی ساخته می‌شوند؛ چیزی نمی‌نویسد.",
                "args": ["import_categories.py", "--dry-run"],
                "token": True,
            },
            {
                "id": "tree-import",
                "title": "ایمپورت دسته‌ها",
                "desc": "دسته‌های جاافتاده را می‌سازد.",
                "args": ["import_categories.py"],
                "token": True,
            },
            {
                "id": "tree-update",
                "title": "اصلاح عنوان/والد/ترتیب دسته‌های موجود",
                "desc": "دسته‌هایی که با سایت فرق دارند را به‌روز می‌کند.",
                "args": ["import_categories.py", "--update"],
                "token": True,
                "optional": True,
            },
            {
                "id": "tree-images",
                "title": "ایمپورت تصاویر دسته‌ها",
                "desc": "فقط برای دسته‌هایی که تصویر ندارند.",
                "args": ["import_category_images.py"],
                "token": True,
            },
            {
                "id": "tree-images-replace",
                "title": "جایگزینی تصاویر موجود",
                "desc": "تصویر دسته‌هایی که از قبل تصویر دارند را هم عوض می‌کند.",
                "args": ["import_category_images.py", "--replace"],
                "token": True,
                "optional": True,
            },
        ],
    },
    {
        "id": "category-attributes",
        "title": "ویژگی‌های دسته‌بندی (ویژگی فنی و ظاهری)",
        "desc": "مشخصات اولین محصول هر دسته را می‌خواند و برای هر دسته‌ی سایت ما گروه «ویژگی فنی و ظاهری» با همان ویژگی‌ها می‌سازد. اول دسته‌ها باید ایمپورت شده باشند.",
        "steps": [
            {
                "id": "attrs-crawl",
                "title": "خواندن مشخصات اولین محصول هر دسته",
                "desc": "خروجی: output/category_specs.json (کلید/مقدار، واحد و نوع هر ویژگی). به سرور دست نمی‌زند.",
                "args": ["category_specs.py"],
            },
            {
                "id": "attrs-import-dry",
                "title": "پیش‌نمایش ساخت ویژگی‌ها",
                "desc": "برای هر دسته نشان می‌دهد چه ویژگی‌هایی ساخته می‌شود؛ چیزی نمی‌نویسد.",
                "args": ["import_category_attributes.py", "--dry-run"],
                "token": True,
            },
            {
                "id": "attrs-import",
                "title": "ساخت گروه و ویژگی‌ها",
                "desc": "فقط اضافه می‌کند؛ ویژگی هم‌نام موجود دست نمی‌خورد و چیزی حذف نمی‌شود.",
                "args": ["import_category_attributes.py"],
                "token": True,
            },
        ],
    },
    {
        "id": "brands",
        "title": "برندها",
        "desc": "برندهای منوی سایت با لوگو.",
        "steps": [
            {
                "id": "brands-crawl",
                "title": "خواندن برندها و لوگوها",
                "desc": "خروجی: output/brands.json و output/brand_logos/. برای تبدیل SVG به sharp در ../api/node_modules نیاز دارد.",
                "args": ["brands.py"],
            },
            {
                "id": "brands-unlinked",
                "title": "لوگوهای بی‌صاحب",
                "desc": "لوگوهایی که به برندی نسبت داده نشدند را فهرست می‌کند (برای عیب‌یابی).",
                "args": ["brands.py", "--list-unlinked"],
                "optional": True,
            },
            {
                "id": "brands-import-dry",
                "title": "پیش‌نمایش ایمپورت برندها",
                "desc": "چیزی نمی‌نویسد.",
                "args": ["import_brands.py", "--dry-run"],
                "token": True,
            },
            {
                "id": "brands-import",
                "title": "ایمپورت برندها",
                "desc": "برندهای جاافتاده را می‌سازد و لوگوی جاافتاده را آپلود می‌کند.",
                "args": ["import_brands.py"],
                "token": True,
            },
            {
                "id": "brands-replace",
                "title": "جایگزینی لوگوهای موجود",
                "desc": "لوگوی برندهایی که از قبل لوگو دارند را هم عوض می‌کند.",
                "args": ["import_brands.py", "--replace"],
                "token": True,
                "optional": True,
            },
        ],
    },
]

STEPS = {s["id"]: s for g in GROUPS for s in g["steps"]}
