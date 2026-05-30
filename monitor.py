"""
Мониторинг наличия Когниттера 60 мг
Нижегородская область + соседние регионы + Центральная Россия
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

DRUG_NAME  = "Когниттера"
DRUG_DOSE  = "60 мг"
PRODUCT_ID = "390849"   # ID товара на Uteka (одинаков для всех регионов)

# ─────────────────────────────────────────────
# РЕГИОНЫ UTEKA
# Мелкие города входят в региональный поддомен:
#   Арзамас, Семёнов, Шарья, Шалунья → nn.uteka.ru
#   Муром                             → vladimir.uteka.ru
# ─────────────────────────────────────────────
UTEKA_REGIONS = [
    # ── Нижегородская область ─────────────────
    {"label": "Нижний Новгород и НО (+ Арзамас, Семёнов, Шарья)",
     "subdomain": "nn"},

    # ── Запрошенные города ────────────────────
    {"label": "Владимир и область (+ Муром)",  "subdomain": "vladimir"},
    {"label": "Казань и Татарстан",            "subdomain": "kazan"},
    {"label": "Пенза и область",               "subdomain": "penza"},
    {"label": "Саранск и Мордовия",            "subdomain": "saransk"},
    {"label": "Чебоксары и Чувашия",           "subdomain": "cheboksary"},
    {"label": "Йошкар-Ола и Марий Эл",        "subdomain": "yoshkar-ola"},
    {"label": "Иваново и область",             "subdomain": "ivanovo"},
    {"label": "Ярославль и область",           "subdomain": "yaroslavl"},
    {"label": "Ульяновск и область",           "subdomain": "ulyanovsk"},

    # ── Новые города (добавлены) ──────────────
    {"label": "Москва и МО",                   "subdomain": "moskva"},
    {"label": "Тула и область",                "subdomain": "tula"},
    {"label": "Калуга и область",              "subdomain": "kaluga"},
    {"label": "Тамбов и область",              "subdomain": "tambov"},
    {"label": "Липецк и область",              "subdomain": "lipetsk"},
    {"label": "Воронеж и область",             "subdomain": "voronezh"},

    # ── Логичные соседи НН ────────────────────
    {"label": "Киров и область",               "subdomain": "kirov"},
    {"label": "Рязань и область",              "subdomain": "ryazan"},
    {"label": "Кострома и область",            "subdomain": "kostroma"},
    {"label": "Саратов и область",             "subdomain": "saratov"},
]


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


async def check_uteka_region(page, subdomain: str, label: str) -> dict:
    """
    Открывает страницу товара и читает:
      - количество аптек: «В наличии в N аптеках» или «из N аптек»
      - цену:            «Цена от N ₽»
      - факт наличия:    отсутствие фразы «сообщить о наличии»
    """
    url = f"https://{subdomain}.uteka.ru/product/kognittera-{PRODUCT_ID}/"
    result = {
        "label":    label,
        "in_stock": False,
        "count":    0,
        "price":    "—",
        "url":      url,
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=35000)
        # Ждём появления блока наличия (Uteka грузит через JS)
        try:
            await page.wait_for_selector(
                "text=/аптек|В наличии|Цена от|Сообщить/i",
                timeout=10000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        body = await page.inner_text("body")

        # ── Проверяем отсутствие ─────────────────────────────
        out_phrases = [
            "сообщить о наличии",
            "нет в наличии",
            "временно отсутствует",
            "нет на складе",
        ]
        if any(p in body.lower() for p in out_phrases):
            return result

        # ── Количество аптек ─────────────────────────────────
        # Форматы на странице:
        #   «В наличии в 2 аптеках»
        #   «из 2 аптек»
        #   «Самовывоз Сегодня бесплатно из 2 аптек»
        count = 0
        m = re.search(r"в наличии в\s+(\d+)\s+апт", body, re.IGNORECASE)
        if not m:
            m = re.search(r"из\s+(\d+)\s+апт", body, re.IGNORECASE)
        if not m:
            m = re.search(r"(\d+)\s+апт[её]", body, re.IGNORECASE)
        if m:
            count = int(m.group(1))

        # ── Цена ─────────────────────────────────────────────
        # «Цена от 1 494 ₽» или просто первое число с ₽
        price = "—"
        mp = re.search(r"[Цц]ена\s+от\s+([\d\s]+₽)", body)
        if not mp:
            mp = re.search(r"([\d][\d\s]*₽)", body)
        if mp:
            price = mp.group(1).strip()

        # ── Считаем «в наличии» если нашли аптеки ИЛИ цену ──
        has_buy = "в корзину" in body.lower() or "купить" in body.lower()
        if (count > 0 or has_buy) and price != "—":
            result["in_stock"] = True
            result["count"]    = count
            result["price"]    = price

    except Exception as e:
        print(f"  ⚠️  {label}: {e}")

    return result


async def run_monitor():
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"\n{'='*62}")
    print(f"  {DRUG_NAME} {DRUG_DOSE} | {now_str}")
    print(f"  Регионов для проверки: {len(UTEKA_REGIONS)}")
    print(f"{'='*62}\n")

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

        for region in UTEKA_REGIONS:
            print(f"🔍 {region['label']}")
            page = await context.new_page()
            res  = await check_uteka_region(page, region["subdomain"], region["label"])
            await page.close()

            if res["in_stock"]:
                cnt_str = f"в {res['count']} аптеках" if res["count"] > 0 else "есть"
                print(f"   ✅ ЕСТЬ — {cnt_str} — от {res['price']}")
                found.append(res)
            else:
                print(f"   ❌ не найдено")
                not_found.append(res["label"])

            await asyncio.sleep(2)

        await browser.close()

    # ── Итоговый отчёт ───────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"  ✅ Найдено в: {len(found)}  ❌ Не найдено: {len(not_found)}")
    print(f"{'='*62}\n")

    if found:
        msg = f"🟢 <b>НАЙДЕНО: {DRUG_NAME} {DRUG_DOSE}!</b>\n📅 {now_str}\n\n"
        for r in found:
            cnt_str = f" · <b>{r['count']} аптеки/аптек</b>" if r["count"] > 0 else ""
            msg += f"📍 <b>{r['label']}</b>{cnt_str}\n"
            msg += f"💰 от {r['price']}\n"
            msg += f"🔗 <a href='{r['url']}'>Открыть на Uteka</a>\n\n"
        await send_telegram(msg)
    else:
        nf  = "\n".join(f"  • {s}" for s in not_found)
        msg = (
            f"⚪ <b>{DRUG_NAME} {DRUG_DOSE}</b> — нигде не найдено\n"
            f"📅 {now_str}\n\n"
            f"Проверено {len(UTEKA_REGIONS)} регионов:\n{nf}"
        )
        await send_telegram(msg)


if __name__ == "__main__":
    asyncio.run(run_monitor())
