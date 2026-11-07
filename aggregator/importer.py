"""Импорт списка позиций из CSV / XLSX / TXT."""
from __future__ import annotations

import csv
from pathlib import Path

NAME_HDR = ("наимен", "назван", "товар", "запрос", "позици", "name", "query", "product")
ART_HDR = ("артикул", "код", "sku", "article", "part")


def _clean(rows) -> list[str]:
    """Если есть строка заголовков — берём столбец «Наименование» (+ «Артикул»), иначе первый столбец."""
    rows = [[("" if c is None else str(c).strip()) for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    name_col, art_col, start = 0, None, 0
    header = [c.lower() for c in rows[0]]
    if any(len(h) < 30 and h.startswith(NAME_HDR + ART_HDR) for h in header if h):
        start = 1
        name_col = next((i for i, h in enumerate(header) if any(w in h for w in NAME_HDR)), None)
        art_col = next((i for i, h in enumerate(header) if any(w in h for w in ART_HDR)), None)
        if name_col is None:
            name_col, art_col = (art_col if art_col is not None else 0), None
    out: list[str] = []
    for r in rows[start:]:
        name = r[name_col] if name_col < len(r) else ""
        art = r[art_col] if art_col is not None and art_col < len(r) else ""
        q = f"{name} {art}" if art and art not in name else (name or art)
        if q:
            out.append(q)
    return list(dict.fromkeys(out))


def load_queries(path: str | Path) -> list[str]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(p, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return _clean(ws.iter_rows(values_only=True))
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if ext == ".txt":
        return _clean([[line] for line in text.splitlines()])
    # Запятая в наименованиях встречается постоянно («3,5х35», «12,5 мм»), поэтому
    # разделителем считаем только «;» (Excel в русской локали) или табуляцию.
    sample = text[:4096]
    delim = ";" if ";" in sample else ("\t" if "\t" in sample else None)
    if delim is None:
        return _clean([[line] for line in text.splitlines()])
    return _clean(csv.reader(text.splitlines(), delimiter=delim))
