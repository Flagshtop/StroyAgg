from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional


@dataclass
class Offer:
    query: str
    marketplace: str
    title: str
    price: Optional[float]
    url: str
    delivery_text: str = ""
    delivery_days: Optional[int] = None
    delivery_date: Optional[date] = None
    is_best_price: bool = False
    is_fastest: bool = False
    found_at: datetime = field(default_factory=datetime.now)

    def as_dict(self) -> dict:
        return asdict(self)


def mark_best(offers: list[Offer]) -> None:
    """Помечает по каждому запросу самое дешёвое и самое быстрое предложение."""
    by_query: dict[str, list[Offer]] = {}
    for o in offers:
        o.is_best_price = o.is_fastest = False
        by_query.setdefault(o.query, []).append(o)
    for items in by_query.values():
        priced = [o for o in items if o.price is not None]
        if priced:
            best = min(o.price for o in priced)
            for o in priced:
                o.is_best_price = o.price == best
        timed = [o for o in items if o.delivery_days is not None]
        if timed:
            fastest = min(o.delivery_days for o in timed)
            # среди одинаково быстрых отмечаем все
            for o in timed:
                o.is_fastest = o.delivery_days == fastest
