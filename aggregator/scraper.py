"""Поиск на маркетплейсах через настоящий браузер (Microsoft Edge / Chrome, установленные в Windows).

Используется постоянный профиль браузера: выбранный город доставки, вход в аккаунт
и пройденные проверки «я не робот» сохраняются между запусками.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote_plus

from .delivery import parse_delivery, parse_price
from .models import Offer
from .paths import bundle_dir, data_dir, resource

log = logging.getLogger(__name__)

CAPTCHA_MARKERS = (
    "showcaptcha", "captcha", "smartcaptcha", "не робот", "подтвердите, что запросы отправляли вы",
    "checking your browser", "ddos-guard", "qrator", "доступ ограничен", "access denied",
)


@dataclass
class Site:
    id: str
    name: str
    search_url: str
    product_href: str
    home: str = ""
    enabled: bool = True
    selectors: dict = field(default_factory=dict)

    def url_for(self, query: str) -> str:
        return self.search_url.replace("{q}", quote_plus(query))


def load_sites() -> list[Site]:
    with open(resource("sites.json"), encoding="utf-8") as f:
        raw = json.load(f)
    return [Site(**{k: v for k, v in s.items() if k in Site.__dataclass_fields__}) for s in raw["sites"]]


class CaptchaError(RuntimeError):
    pass


class Scraper:
    """Обёртка над Playwright. Создавать и использовать в одном потоке."""

    def __init__(self, headless: bool = False, timeout_s: int = 40,
                 log_cb: Callable[[str], None] = print,
                 stop_cb: Callable[[], bool] = lambda: False,
                 captcha_wait_s: int = 180):
        self.headless = headless
        self.timeout_ms = timeout_s * 1000
        self.log = log_cb
        self.stopped = stop_cb
        self.captcha_wait_s = captcha_wait_s
        self._pw = None
        self.ctx = None
        self._js = (bundle_dir() / "aggregator" / "extract.js").read_text(encoding="utf-8")

    # ---------- жизненный цикл ----------
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        profile = str(data_dir() / "browser-profile")
        args = ["--disable-blink-features=AutomationControlled", "--lang=ru-RU"]
        last_err = None
        # В Windows всегда есть Edge; при его отсутствии пробуем Chrome, затем встроенный Chromium.
        for channel in ("msedge", "chrome", None):
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    profile, channel=channel, headless=self.headless, args=args,
                    locale="ru-RU", timezone_id="Europe/Moscow",
                    viewport={"width": 1400, "height": 900},
                    ignore_default_args=["--enable-automation"],
                )
                self.log(f"Браузер запущен ({channel or 'chromium'})")
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        if self.ctx is None:
            raise RuntimeError(f"Не удалось запустить браузер (Edge/Chrome): {last_err}")
        self.ctx.set_default_timeout(self.timeout_ms)
        self.ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    def close(self):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
            self.ctx = self._pw = None

    # ---------- поиск ----------
    def _is_captcha(self, page) -> bool:
        try:
            url = page.url.lower()
            head = (page.title() + " " + page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 1500)")).lower()
        except Exception:  # noqa: BLE001
            return False
        return any(m in url for m in ("captcha", "showcaptcha")) or any(m in head for m in CAPTCHA_MARKERS[2:])

    def _handle_captcha(self, page, site: Site):
        if not self._is_captcha(page):
            return
        if self.headless:
            raise CaptchaError(f"{site.name}: проверка «я не робот». Снимите галочку «Скрытый режим» и пройдите её в окне браузера.")
        self.log(f"{site.name}: пройдите проверку «я не робот» в окне браузера (жду до {self.captcha_wait_s} с)…")
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + self.captcha_wait_s
        while time.time() < deadline and not self.stopped():
            page.wait_for_timeout(1500)
            if not self._is_captcha(page):
                self.log(f"{site.name}: проверка пройдена")
                page.wait_for_timeout(1500)
                return
        raise CaptchaError(f"{site.name}: проверка «я не робот» не пройдена")

    def _scroll(self, page, times: int = 4):
        for _ in range(times):
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(600)
        page.evaluate("() => window.scrollTo(0, 0)")

    def search(self, site: Site, query: str, limit: int = 20, deep: bool = False) -> list[Offer]:
        page = self.ctx.new_page()
        try:
            page.goto(site.url_for(query), wait_until="domcontentloaded")
            self._handle_captcha(page, site)
            try:
                page.wait_for_function(
                    "re => [...document.querySelectorAll('a[href]')].some(a => new RegExp(re,'i').test(a.href))",
                    arg=site.product_href, timeout=self.timeout_ms,
                )
            except Exception:  # noqa: BLE001
                self._handle_captcha(page, site)
                body = page.evaluate("() => document.body ? document.body.innerText.slice(0, 400) : ''")
                if any(s in body.lower() for s in ("ничего не найдено", "не нашли", "нет результатов", "по вашему запросу ничего")):
                    return []
                self.log(f"{site.name}: товары на странице не найдены")
                return []
            page.wait_for_timeout(1200)
            self._scroll(page)
            raw = page.evaluate(self._js, {"hrefRe": site.product_href, "limit": limit, "sel": site.selectors or {}})
            offers = []
            for r in raw:
                days, ddate = parse_delivery(r.get("delivery", ""))
                offers.append(Offer(
                    query=query, marketplace=site.name, title=(r.get("title") or "").strip()[:500],
                    price=parse_price(r.get("priceText", "")), url=r["url"],
                    delivery_text=(r.get("delivery") or "")[:300], delivery_days=days, delivery_date=ddate,
                ))
            if deep:
                self._refine_delivery(offers, site)
            return offers
        finally:
            page.close()

    def _refine_delivery(self, offers: list[Offer], site: Site, max_pages: int = 10):
        """Открывает карточки без срока доставки и ищет срок на странице товара."""
        todo = [o for o in offers if o.delivery_days is None][:max_pages]
        for o in todo:
            if self.stopped():
                return
            page = self.ctx.new_page()
            try:
                page.goto(o.url, wait_until="domcontentloaded")
                self._handle_captcha(page, site)
                page.wait_for_timeout(2500)
                lines = page.evaluate(
                    r"""() => (document.body.innerText || '').split('\n').map(s => s.trim())
                        .filter(s => s && s.length < 120 && /(достав|курьер|самовывоз|забрать|получ)/i.test(s)
                                 && /(сегодня|завтра|\d+\s*(дн|дня|дней|день|ч\b|час)|\d{1,2}\s+(янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек))/i.test(s))
                        .slice(0, 4)""")
                if lines:
                    o.delivery_text = "; ".join(dict.fromkeys(lines))[:300]
                    o.delivery_days, o.delivery_date = parse_delivery(o.delivery_text)
            except CaptchaError:
                raise
            except Exception as e:  # noqa: BLE001
                log.debug("refine %s: %s", o.url, e)
            finally:
                page.close()

    def open_for_setup(self, urls: list[str]):
        """Открывает сайты во вкладках, чтобы пользователь выбрал город / вошёл / прошёл капчу."""
        for u in urls:
            p = self.ctx.new_page()
            try:
                p.goto(u, wait_until="domcontentloaded")
            except Exception as e:  # noqa: BLE001
                self.log(f"{u}: {e}")
