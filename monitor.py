"""
Мониторинг наличия Когниттера 60 мг
Нижегородская область + соседние регионы
"""

import asyncio
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright
import httpx

# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

DRUG_NAME    = "Когниттера"
DRUG_DOSE    = "60 мг"

# ─────────────────────────────────────────────
# РЕГИОНЫ И ГОРОДА
# Каждый регион — отдельный поддомен Uteka.
# Мелкие города (Муром, Арзамас и др.) входят
# в региональный поддомен и проверяются автоматически.
# ─────────────────────────────────────────────
UTEKA_REGIONS = [
    # ── Нижегородская область ─────────────────
    {"label": "Нижний Новгород и НО",      "subdomain": "nn"},

    # ── Соседние регионы (запрошены) ──────────
    {"label": "Владимир и область",        "subdomain": "vladimir"},
    {"label": "Казань и Татарстан",        "subdomain": "kazan"},
    {"label": "Пенза и область",           "subdomain": "penza"},
    {"label": "Саранск и Мордовия",        "subdomain": "saransk"},
    {"label": "Чебоксары и Чувашия",       "subdomain": "cheboksary"},
    {"label": "Йошкар-Ола и Марий Эл",    "subdomain": "yoshkar-ola"},
    {"label": "Иваново и область",         "subdomain": "ivanovo"},
    {"label": "Ярославль и область",       "subdomain": "yaroslavl"},
    {"label": "Ульяновск и область",       "subdomain": "ulyanovsk"},

    # ── Дополнительно — логичные соседи НН ───
    {"label": "Киров и область",           "subdomain": "kirov"},
    {"label": "Рязань и область",          "subdomain": "ryazan"},
    {"label": "Кострома и область",        "subdomain": "kostroma"},
    {"label": "Тверь и область",           "subdomain": "tver"},
    {"label": "Саратов и область",         "subdomain": "saratov"},
]
# Примечание: Муром входит в vladimir.uteka.ru,
# Арзамас, Шарья, Шалунья, Семёнов — в nn.uteka.ru

# Дополнительные прямые сайты (федеральные, сами ищут по всем городам)
EXTRA_SITES = [
    {
        "name": "Zdravcity (все регионы)",
        "url":  "https://zdravcity.ru/g_kognittera/",
    },
    {
        "name": "eApteka (все регионы)",
        "url":  "https://www.eapteka.ru/goods/search/?q=когниттера+60",
    },
]
# ─────────────────────────────────────────────


async def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram не настроен, вывод в консоль:\n", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })
        if resp.status_code != 200:
            print(f"❌ Telegram ошибка: {resp.text}")
        else:
            print("✅ Telegram уведомление отправлено")


def is_target(text: str) -> bool:
    t = text.lower()
    return "когниттера" in t and "60" in t


def extract_price(text: str) -> str:
    m = re.search(r"(\d[\d\s]*)\s*₽", text)
    return m.group(0).strip() if m else "—"


def is_in_stock(text: str) -> bool:
    t = text.lower()
    out_phrases = [
        "нет в наличии", "под заказ", "сообщить о наличии",
        "нет на складе", "временно отсутствует", "нет в продаже",
    ]
    return not any(p in t for p in out_phrases)


async def scrape_page(page, url: str, site_label: str) -> list[dict]:
    """Универсальный парсер — пробует несколько стратегий."""
    results = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(3000)

        # Стратегия 1: карточки товаров
        card_selectors = [
            "[class*='product-card']", "[class*='ProductCard']",
            "[class*='product_card']", "[class*='catalog-item']",
            "[class*='search-result']", "[class*='good-card']",
            "[class*='item-card']", "article",
        ]
        cards = []
        for sel in card_selectors:
            items = await page.query_selector_all(sel)
            if items:
                cards = items
                break

        for card in cards[:15]:
            try:
                text = await card.inner_text()
                if not is_target(text):
                    continue
                link_el = await card.query_selector("a")
                href = (await link_el.get_attribute("href") if link_el else "") or ""
                if href and not href.startswith("http"):
                    domain = "/".join(url.split("/")[:3])
                    href = domain + href
                results.append({
                    "site":     site_label,
                    "name":     text.split("\n")[0][:80].strip(),
                    "price":    extract_price(text),
                    "in_stock": is_in_stock(text),
                    "url":      href or url,
                })
            except Exception:
                continue

        # Стратегия 2: полный текст страницы (fallback)
        if not results:
            body = await page.inner_text("body")
            if is_target(body):
                results.append({
                    "site":     site_label,
                    "name":     f"{DRUG_NAME} {DRUG_DOSE}",
                    "price":    extract_price(body),
                    "in_stock": is_in_stock(body),
                    "url":      url,
                })

    except Exception as e:
        print(f"  ⚠️  {site_label}: {e}")

    return results


async def run_monitor():
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"\n{'='*60}")
    print(f"  Мониторинг: {DRUG_NAME} {DRUG_DOSE}")
    print(f"  Время: {now_str}")
    print(f"  Регионов для проверки: {len(UTEKA_REGIONS)}")
    print(f"{'='*60}\n")

    all_results: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1280, "height": 800},
        )

        # ── Uteka по регионам ─────────────────────────────────
        for region in UTEKA_REGIONS:
            sub   = region["subdomain"]
            label = region["label"]
            url   = f"https://{sub}.uteka.ru/lekarstvennye-sredstva/nervnaya-sistema/kognittera/"
            print(f"🔍 {label}")
            page  = await context.new_page()
            res   = await scrape_page(page, url, label)
            await page.close()

            for r in res:
                icon = "✅" if r["in_stock"] else "❌"
                print(f"   {icon} {r['name'][:55]} | {r['price']}")
            if not res:
                print("   — не найдено")

            all_results.extend(res)
            await asyncio.sleep(1.5)

        # ── Дополнительные федеральные сайты ─────────────────
        for site in EXTRA_SITES:
            print(f"🔍 {site['name']}")
            page = await context.new_page()
            res  = await scrape_page(page, site["url"], site["name"])
            await page.close()

            for r in res:
                icon = "✅" if r["in_stock"] else "❌"
                print(f"   {icon} {r['name'][:55]} | {r['price']}")
            if not res:
                print("   — не найдено")

            all_results.extend(res)
            await asyncio.sleep(1.5)

        await browser.close()

    # ── Формируем итоговый отчёт ──────────────────────────────
    in_stock  = [r for r in all_results if r["in_stock"]]
    not_found = [r for r in all_results if not r["in_stock"]]
    checked   = sorted(set(r["site"] for r in all_results))

    print(f"\n{'='*60}")
    print(f"  ✅ Найдено в наличии: {len(in_stock)}")
    print(f"  ❌ Не в наличии:      {len(not_found)}")
    print(f"  📍 Проверено источников: {len(checked)}")
    print(f"{'='*60}\n")

    if in_stock:
        msg = f"🟢 <b>НАЙДЕНО: {DRUG_NAME} {DRUG_DOSE}!</b>\n📅 {now_str}\n\n"
        for r in in_stock:
            msg += f"📍 <b>{r['site']}</b>\n"
            msg += f"💊 {r['name']}\n"
            msg += f"💰 {r['price']}\n"
            msg += f"🔗 <a href='{r['url']}'>Открыть страницу</a>\n\n"
        await send_telegram(msg)
    else:
        # Группируем проверенные регионы для читаемого отчёта
        regions_str = "\n".join(f"  • {s}" for s in checked) if checked else "  нет данных"
        msg = (
            f"⚪ <b>{DRUG_NAME} {DRUG_DOSE}</b> — не найдено\n"
            f"📅 {now_str}\n\n"
            f"Проверено {len(checked)} источников:\n{regions_str}"
        )
        await send_telegram(msg)


if __name__ == "__main__":
    asyncio.run(run_monitor())
