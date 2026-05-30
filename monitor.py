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

DRUG_NAME = "Когниттера"
DRUG_DOSE = "60 мг"

# ─────────────────────────────────────────────
# ПРЯМЫЕ ССЫЛКИ на страницу товара по регионам
# Когниттера 60мг имеет ID 390849 на Uteka
# ─────────────────────────────────────────────
UTEKA_REGIONS = [
    # ── Нижегородская область ─────────────────────────────────
    {"label": "Нижний Новгород и НО",   "subdomain": "nn"},

    # ── Запрошенные города/регионы ────────────────────────────
    {"label": "Владимир и область (+ Муром)", "subdomain": "vladimir"},
    {"label": "Казань и Татарстан",     "subdomain": "kazan"},
    {"label": "Пенза и область",        "subdomain": "penza"},
    {"label": "Саранск и Мордовия",     "subdomain": "saransk"},
    {"label": "Чебоксары и Чувашия",    "subdomain": "cheboksary"},
    {"label": "Йошкар-Ола и Марий Эл", "subdomain": "yoshkar-ola"},
    {"label": "Иваново и область",      "subdomain": "ivanovo"},
    {"label": "Ярославль и область",    "subdomain": "yaroslavl"},
    {"label": "Ульяновск и область",    "subdomain": "ulyanovsk"},

    # ── Дополнительные соседи НН ──────────────────────────────
    {"label": "Киров и область",        "subdomain": "kirov"},
    {"label": "Рязань и область",       "subdomain": "ryazan"},
    {"label": "Кострома и область",     "subdomain": "kostroma"},
    {"label": "Саратов и область",      "subdomain": "saratov"},
]
# Примечание: Арзамас, Семёнов, Шарья, Шалунья — входят в nn.uteka.ru
# Муром — входит в vladimir.uteka.ru

PRODUCT_ID = "390849"  # ID Когниттеры на Uteka (одинаков для всех регионов)

# Дополнительные федеральные сайты
EXTRA_SITES = [
    {
        "name": "Zdravcity",
        "url":  "https://zdravcity.ru/g_kognittera/",
        "in_stock_selector":  "[class*='price']",
        "out_phrases": ["сообщить о наличии", "нет в наличии", "временно отсутствует"],
    },
]
# ─────────────────────────────────────────────


async def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram не настроен:\n", message)
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
            print(f"❌ Telegram: {resp.text}")
        else:
            print("✅ Telegram отправлено")


def extract_price(text: str) -> str:
    m = re.search(r"[\d\s]+₽", text)
    return m.group(0).strip() if m else "—"


async def check_uteka_region(page, subdomain: str, label: str) -> dict:
    """
    Проверяет конкретную страницу товара на Uteka.
    Ждёт загрузки динамического блока с аптеками.
    Возвращает: {label, in_stock, count, price, url}
    """
    url = f"https://{subdomain}.uteka.ru/product/kognittera-{PRODUCT_ID}/"
    result = {"label": label, "in_stock": False, "count": 0, "price": "—", "url": url}

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)

        # Ждём появления блока с аптеками или кнопки "Сообщить о наличии"
        # Uteka подгружает список аптек через JS — даём до 10 сек
        try:
            await page.wait_for_selector(
                "[class*='pharmacy'], [class*='Pharmacy'], "
                "[class*='store'], [class*='offer'], "
                "button[class*='notify'], [class*='available']",
                timeout=10000,
            )
        except Exception:
            pass  # если не появилось — всё равно анализируем текст

        await page.wait_for_timeout(2000)  # дополнительная пауза для JS

        body = await page.inner_text("body")
        body_lower = body.lower()

        # Признаки ОТСУТСТВИЯ
        out_phrases = [
            "сообщить о наличии",
            "нет в наличии",
            "временно отсутствует",
            "нет на складе",
            "под заказ",
        ]
        is_out = any(p in body_lower for p in out_phrases)

        # Признаки НАЛИЧИЯ — ищем блок с аптеками и ценой
        # Uteka показывает "в N аптеках" или просто цену со ссылкой "Купить"
        pharmacy_count_match = re.search(r"в\s+(\d+)\s+апт", body_lower)
        has_price = bool(re.search(r"\d[\d\s]*₽", body))
        has_buy_button = "купить" in body_lower or "в корзину" in body_lower

        if not is_out and (pharmacy_count_match or has_buy_button) and has_price:
            result["in_stock"] = True
            result["count"] = int(pharmacy_count_match.group(1)) if pharmacy_count_match else 1
            result["price"] = extract_price(body)

    except Exception as e:
        print(f"  ⚠️  {label}: {e}")

    return result


async def check_extra_site(page, site: dict) -> dict:
    """Парсит федеральный сайт (Zdravcity и др.)"""
    result = {"label": site["name"], "in_stock": False, "count": 0, "price": "—", "url": site["url"]}
    try:
        await page.goto(site["url"], wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(3000)
        body = await page.inner_text("body")
        body_lower = body.lower()

        is_out = any(p in body_lower for p in site.get("out_phrases", []))
        has_price = bool(re.search(r"\d[\d\s]*₽", body))
        has_kognittera_60 = "когниттера" in body_lower and "60" in body_lower

        if has_kognittera_60 and has_price and not is_out:
            result["in_stock"] = True
            result["price"] = extract_price(body)
    except Exception as e:
        print(f"  ⚠️  {site['name']}: {e}")
    return result


async def run_monitor():
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"\n{'='*60}")
    print(f"  {DRUG_NAME} {DRUG_DOSE} | {now_str}")
    print(f"  Регионов: {len(UTEKA_REGIONS)} + {len(EXTRA_SITES)} доп. сайтов")
    print(f"{'='*60}\n")

    found:     list[dict] = []
    not_found: list[str]  = []

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
            print(f"🔍 {region['label']}")
            page = await context.new_page()
            res  = await check_uteka_region(page, region["subdomain"], region["label"])
            await page.close()

            if res["in_stock"]:
                cnt = f" (в {res['count']} аптеках)" if res["count"] > 1 else ""
                print(f"   ✅ ЕСТЬ{cnt} — {res['price']}")
                found.append(res)
            else:
                print(f"   ❌ нет в наличии")
                not_found.append(res["label"])

            await asyncio.sleep(2)

        # ── Дополнительные сайты ──────────────────────────────
        for site in EXTRA_SITES:
            print(f"🔍 {site['name']}")
            page = await context.new_page()
            res  = await check_extra_site(page, site)
            await page.close()

            if res["in_stock"]:
                print(f"   ✅ ЕСТЬ — {res['price']}")
                found.append(res)
            else:
                print(f"   ❌ нет в наличии")
                not_found.append(res["label"])

            await asyncio.sleep(2)

        await browser.close()

    # ── Итог ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ✅ Найдено: {len(found)}  ❌ Не найдено: {len(not_found)}")
    print(f"{'='*60}\n")

    if found:
        msg = f"🟢 <b>НАЙДЕНО: {DRUG_NAME} {DRUG_DOSE}!</b>\n📅 {now_str}\n\n"
        for r in found:
            cnt = f" · в {r['count']} аптеках" if r.get("count", 0) > 1 else ""
            msg += f"📍 <b>{r['label']}</b>{cnt}\n"
            msg += f"💰 от {r['price']}\n"
            msg += f"🔗 <a href='{r['url']}'>Открыть на Uteka</a>\n\n"
        await send_telegram(msg)
    else:
        nf = "\n".join(f"  • {s}" for s in not_found)
        msg = (
            f"⚪ <b>{DRUG_NAME} {DRUG_DOSE}</b> — нигде не найдено\n"
            f"📅 {now_str}\n\n"
            f"Проверено {len(not_found)} регионов:\n{nf}"
        )
        await send_telegram(msg)


if __name__ == "__main__":
    asyncio.run(run_monitor())
