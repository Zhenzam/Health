"""
Мониторинг наличия Когниттера 60 мг в аптеках Нижегородской области
Использует Playwright для обхода защиты сайтов
"""

import asyncio
import os
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright
import httpx

# ─────────────────────────────────────────────
# НАСТРОЙКИ — меняй только здесь
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

DRUG_NAME = "Когниттера"
DRUG_DOSE = "60 мг"
SEARCH_QUERY = "Когниттера 60"

# Сайты для мониторинга (url, тип парсинга)
SITES = [
    {
        "name": "Uteka (агрегатор — 1600+ аптек НН и области)",
        "url": "https://nn.uteka.ru/lekarstvennye-sredstva/nervnaya-sistema/kognittera/",
        "type": "uteka",
    },
    {
        "name": "Zdravcity",
        "url": "https://zdravcity.ru/g_kognittera/r_nnovgorod/",
        "type": "zdravcity",
    },
    {
        "name": "Apteka.ru",
        "url": "https://www.apteka.ru/nnovgorod/search/?q=когниттера+60",
        "type": "apteka_ru",
    },
    {
        "name": "eApteka",
        "url": "https://www.eapteka.ru/goods/search/?q=когниттера+60",
        "type": "eapteka",
    },
    {
        "name": "Rigla",
        "url": "https://www.rigla.ru/search?query=когниттера+60",
        "type": "rigla",
    },
    {
        "name": "Planeta Zdorovya",
        "url": "https://planetazdorovo.ru/search/?q=когниттера+60",
        "type": "planetazdorovo",
    },
    {
        "name": "Stolichki",
        "url": "https://stolichki.ru/search?q=когниттера+60",
        "type": "stolichki",
    },
    {
        "name": "366.ru",
        "url": "https://366.ru/search/?query=когниттера+60",
        "type": "366ru",
    },
]
# ─────────────────────────────────────────────


async def send_telegram(message: str):
    """Отправить сообщение в Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️  Telegram не настроен — вывожу в консоль:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })
        if resp.status_code != 200:
            print(f"❌ Ошибка Telegram: {resp.text}")
        else:
            print("✅ Telegram уведомление отправлено")


def is_target_drug(text: str) -> bool:
    """Проверяем что текст содержит нужный препарат с нужной дозировкой"""
    text_lower = text.lower()
    has_name = "когниттера" in text_lower
    has_dose = "60" in text_lower
    return has_name and has_dose


async def check_uteka(page) -> list[dict]:
    """Uteka — агрегатор, самый важный источник"""
    results = []
    try:
        await page.goto(
            "https://nn.uteka.ru/lekarstvennye-sredstva/nervnaya-sistema/kognittera/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        # Ищем карточки товаров
        items = await page.query_selector_all("[class*='product-card'], [class*='ProductCard'], article")
        for item in items:
            text = await item.inner_text()
            if is_target_drug(text):
                # Проверяем наличие (отсутствие фразы "нет в наличии")
                in_stock = not any(phrase in text.lower() for phrase in [
                    "нет в наличии", "под заказ", "сообщить о наличии", "нет на складе"
                ])
                # Ищем цену
                price_match = re.search(r"(\d[\d\s]*)\s*₽", text)
                price = price_match.group(0) if price_match else "цена неизвестна"
                # Ссылка
                link_el = await item.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else ""
                if href and not href.startswith("http"):
                    href = "https://nn.uteka.ru" + href

                results.append({
                    "site": "Uteka (НН и область)",
                    "name": text.split("\n")[0][:80],
                    "price": price,
                    "in_stock": in_stock,
                    "url": href or "https://nn.uteka.ru/lekarstvennye-sredstva/nervnaya-sistema/kognittera/",
                })

        # Если не нашли через карточки — fallback через текст страницы
        if not results:
            body = await page.inner_text("body")
            if is_target_drug(body):
                in_stock = not any(p in body.lower() for p in ["нет в наличии", "сообщить о наличии"])
                price_match = re.search(r"(\d[\d\s]+)\s*₽", body)
                results.append({
                    "site": "Uteka (НН и область)",
                    "name": f"{DRUG_NAME} {DRUG_DOSE}",
                    "price": price_match.group(0) if price_match else "—",
                    "in_stock": in_stock,
                    "url": "https://nn.uteka.ru/lekarstvennye-sredstva/nervnaya-sistema/kognittera/",
                })
    except Exception as e:
        print(f"  ⚠️  Uteka: {e}")
    return results


async def check_generic_site(page, site: dict) -> list[dict]:
    """Универсальный парсер для остальных сайтов"""
    results = []
    try:
        await page.goto(site["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Пробуем несколько типовых селекторов для карточек товаров
        selectors = [
            "[class*='product-card']",
            "[class*='ProductCard']",
            "[class*='product_card']",
            "[class*='catalog-item']",
            "[class*='search-result']",
            "article",
            "[class*='good']",
            "[class*='item']",
        ]

        found_items = []
        for sel in selectors:
            items = await page.query_selector_all(sel)
            if len(items) > 0:
                found_items = items
                break

        for item in found_items[:20]:  # не больше 20 результатов
            try:
                text = await item.inner_text()
                if is_target_drug(text):
                    in_stock = not any(phrase in text.lower() for phrase in [
                        "нет в наличии", "под заказ", "сообщить о наличии",
                        "нет на складе", "временно отсутствует",
                    ])
                    price_match = re.search(r"(\d[\d\s]*)\s*₽", text)
                    link_el = await item.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else ""
                    domain = "/".join(site["url"].split("/")[:3])
                    if href and not href.startswith("http"):
                        href = domain + href

                    results.append({
                        "site": site["name"],
                        "name": text.split("\n")[0][:80],
                        "price": price_match.group(0) if price_match else "—",
                        "in_stock": in_stock,
                        "url": href or site["url"],
                    })
            except Exception:
                continue

        # Fallback — анализ всего текста страницы
        if not results:
            body = await page.inner_text("body")
            if is_target_drug(body):
                in_stock = not any(p in body.lower() for p in [
                    "нет в наличии", "сообщить о наличии", "временно отсутствует"
                ])
                price_match = re.search(r"(\d[\d\s]+)\s*₽", body)
                results.append({
                    "site": site["name"],
                    "name": f"{DRUG_NAME} {DRUG_DOSE}",
                    "price": price_match.group(0) if price_match else "—",
                    "in_stock": in_stock,
                    "url": site["url"],
                })

    except Exception as e:
        print(f"  ⚠️  {site['name']}: {e}")
    return results


async def run_monitor():
    print(f"\n{'='*55}")
    print(f"  Мониторинг: {DRUG_NAME} {DRUG_DOSE}")
    print(f"  Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"{'='*55}\n")

    all_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
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

        for site in SITES:
            print(f"🔍 Проверяю: {site['name']}")
            page = await context.new_page()

            if site["type"] == "uteka":
                results = await check_uteka(page)
            else:
                results = await check_generic_site(page, site)

            await page.close()

            for r in results:
                status = "✅ ЕСТЬ" if r["in_stock"] else "❌ нет"
                print(f"   {status} | {r['name'][:50]} | {r['price']}")

            all_results.extend(results)
            await asyncio.sleep(2)  # пауза между сайтами

        await browser.close()

    # ── Формируем отчёт ──────────────────────────────────────
    in_stock = [r for r in all_results if r["in_stock"]]
    not_found = [r for r in all_results if not r["in_stock"]]

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    if in_stock:
        msg = f"🟢 <b>НАЙДЕНО: {DRUG_NAME} {DRUG_DOSE}</b>\n"
        msg += f"📅 {now}\n\n"
        for r in in_stock:
            msg += f"<b>{r['site']}</b>\n"
            msg += f"💊 {r['name']}\n"
            msg += f"💰 {r['price']}\n"
            msg += f"🔗 <a href='{r['url']}'>Перейти</a>\n\n"
        await send_telegram(msg)
    else:
        # Если ничего не нашли — тихий лог (не спамим каждый день)
        # Отправляем только краткое "не найдено" раз в день
        msg = f"⚪ <b>{DRUG_NAME} {DRUG_DOSE}</b> — не найдено\n📅 {now}\n\n"
        if not_found:
            sites_checked = ", ".join(set(r["site"] for r in not_found))
            msg += f"Проверено: {sites_checked}"
        else:
            msg += "Препарат не обнаружен ни на одном из сайтов."
        await send_telegram(msg)

    print(f"\n{'='*55}")
    print(f"  Найдено в наличии: {len(in_stock)}")
    print(f"  Не в наличии: {len(not_found)}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(run_monitor())
