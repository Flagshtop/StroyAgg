// Универсальное извлечение карточек товаров со страницы поиска.
// Не зависит от CSS-классов (на маркетплейсах они часто генерируются и меняются):
// находит ссылки на товары по регулярному выражению и поднимается к контейнеру с ценой.
({ hrefRe, limit, sel }) => {
  sel = sel || {};
  const re = new RegExp(hrefRe, "i");
  const priceRe = /(\d[\d\s   ]*(?:[.,]\d{1,2})?)\s*(₽|руб)/i;
  const badPriceRe = /(мес|×|x\s*\d|бонус|балл|кешб|кэшб|экономи|скидк|выгод|−|-\s*\d+\s*%)/i;
  const badCtxRe = /(\/\s*мес|в месяц|×\s*\d|бонус|балл|кешб|кэшб|сплит|рассроч|частями)/i;
  const delivRe = /(достав|привез|курьер|самовывоз|забрать|получ|в наличии|сегодня|завтра|\d+\s*(раб\S*\s*)?(дн|дня|дней|день)|\d{1,2}\s+(янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек))/i;

  const norm = (h) => { try { const u = new URL(h, location.href); return u.origin + u.pathname.replace(/\/+$/, ""); } catch (e) { return h; } };
  const txt = (el) => ((el && (el.innerText || el.textContent)) || "").replace(/[  ]/g, " ").trim();
  const struck = (el) => {
    for (let e = el, i = 0; e && i < 4; e = e.parentElement, i++) {
      if (/^(S|DEL|STRIKE)$/.test(e.tagName)) return true;
      const st = getComputedStyle(e);
      if ((st.textDecorationLine || st.textDecoration || "").includes("line-through")) return true;
    }
    return false;
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };

  // 1. Карточки
  let cards = [];
  if (sel.card) {
    cards = [...document.querySelectorAll(sel.card)];
  } else {
    const links = [...document.querySelectorAll("a[href]")].filter((a) => re.test(a.href));
    const used = new Set();
    for (const a of links) {
      let el = a, found = null;
      for (let i = 0; i < 12 && el && el !== document.body; i++) {
        if (priceRe.test(txt(el))) { found = el; break; }
        el = el.parentElement;
      }
      if (!found || used.has(found)) continue;
      const hrefs = new Set([...found.querySelectorAll("a[href]")].filter((x) => re.test(x.href)).map((x) => norm(x.href)));
      if (found.tagName !== "A" && hrefs.size > 1) continue; // это уже сетка из нескольких товаров
      // не берём вложенные дубликаты
      if ([...used].some((u) => u.contains(found) || found.contains(u))) continue;
      used.add(found);
      cards.push(found);
    }
  }

  // 2. Поля
  const out = [];
  const seenUrl = new Set();
  for (const card of cards) {
    if (!visible(card)) continue;
    const links = card.tagName === "A" ? [card] : [...card.querySelectorAll("a[href]")].filter((a) => re.test(a.href));
    if (!links.length) continue;
    const url = norm(links[0].href);
    if (seenUrl.has(url)) continue;

    // наименование
    let title = "";
    if (sel.title) title = txt(card.querySelector(sel.title));
    if (!title) {
      const cands = [];
      for (const a of links) {
        cands.push(a.getAttribute("title") || "", a.getAttribute("aria-label") || "", txt(a));
        a.querySelectorAll("img[alt]").forEach((i) => cands.push(i.alt));
      }
      card.querySelectorAll("[itemprop=name], h2, h3, [class*=title i], [class*=name i]").forEach((e) => cands.push(txt(e)));
      title = cands
        .map((s) => s.split("\n").map((x) => x.trim()).filter((x) => x.length > 3 && !priceRe.test(x)).sort((a, b) => b.length - a.length)[0] || "")
        .filter((s) => s.length > 3 && s.length < 400)
        .sort((a, b) => b.length - a.length)[0] || "";
    }

    // цена: первая не зачёркнутая, не «в месяц», не бонусы
    let priceText = "";
    if (sel.price) priceText = txt(card.querySelector(sel.price));
    if (!priceText) {
      const meta = card.querySelector("[itemprop=price]");
      if (meta && meta.getAttribute("content")) priceText = meta.getAttribute("content") + " ₽";
    }
    if (!priceText) {
      const all = [...card.querySelectorAll("*")].filter((e) => {
        const t = txt(e);
        return t.length < 40 && priceRe.test(t) && visible(e);
      });
      const leafs = all.filter((e) => !all.some((o) => o !== e && e.contains(o)));
      for (const e of leafs) {
        const t = txt(e);
        const ctx = txt(e.parentElement).slice(0, 80);
        if (struck(e) || badPriceRe.test(t) || badCtxRe.test(ctx.replace(t, ""))) continue;
        priceText = t;
        break;
      }
      if (!priceText) { const m = txt(card).match(priceRe); if (m) priceText = m[0]; }
    }

    // доставка
    let delivery = "";
    if (sel.delivery) delivery = [...card.querySelectorAll(sel.delivery)].map(txt).join("; ");
    if (!delivery) {
      const lines = txt(card).split("\n").map((s) => s.trim())
        .filter((s) => s && s.length < 120 && delivRe.test(s) && !priceRe.test(s) && s !== title);
      delivery = [...new Set(lines)].slice(0, 3).join("; ");
    }

    if (!title && !priceText) continue;
    seenUrl.add(url);
    out.push({ url, title, priceText, delivery });
    if (out.length >= limit) break;
  }
  return out;
}
