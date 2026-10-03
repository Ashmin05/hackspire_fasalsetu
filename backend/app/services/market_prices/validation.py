"""Data-quality rules for normalised price records.

Two outcomes besides "clean":
* rejected -- the record can't be stored as a price (no modal price, bad
  date, wrong unit, negative number...). It's logged with its raw source row.
* flagged  -- stored as reported, with the finding in quality_flags and the
  issue log (e.g. min > modal). Values are never altered to "fix" a record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.integrations.market_prices.base import ARRIVAL_UNIT, PRICE_UNIT, NormalizedMarketPrice

# Mandis report the same day; a date beyond tomorrow (timezone slack) is wrong.
MAX_FUTURE_DAYS = 1


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


@dataclass
class ValidationResult:
    record: NormalizedMarketPrice
    rejections: list[Finding] = field(default_factory=list)
    flags: list[Finding] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.rejections


def validate(record: NormalizedMarketPrice, *, today: date) -> ValidationResult:
    result = ValidationResult(record)
    reject = result.rejections.append
    flag = result.flags.append

    for name in ("state", "market", "commodity"):
        if not getattr(record, name):
            reject(Finding(f"missing_{name}", f"{name} is missing"))

    if record.arrival_date is None:
        detail = next((i for i in record.parse_issues if i.startswith("arrival_date")), "arrival_date missing")
        reject(Finding("invalid_date", detail))
    elif record.arrival_date > today + timedelta(days=MAX_FUTURE_DAYS):
        reject(Finding("future_date", f"arrival_date {record.arrival_date} is in the future"))

    if record.price_unit != PRICE_UNIT:
        reject(Finding("unexpected_price_unit", f"price unit {record.price_unit!r}, expected {PRICE_UNIT!r}"))

    if record.modal_price is None:
        detail = next((i for i in record.parse_issues if i.startswith("modal_price")), "modal_price missing")
        reject(Finding("missing_modal_price", detail))
    elif record.modal_price == 0:
        reject(Finding("zero_modal_price", "modal_price is 0 (no trade reported)"))

    for name in ("min_price", "max_price", "modal_price"):
        value: Decimal | None = getattr(record, name)
        if value is not None and value < 0:
            reject(Finding("negative_price", f"{name} is negative ({value})"))

    if record.arrival_quantity is not None:
        if record.arrival_quantity < 0:
            reject(Finding("invalid_arrival_quantity", f"arrival_quantity is negative ({record.arrival_quantity})"))
        elif record.arrival_unit != ARRIVAL_UNIT:
            reject(Finding("unexpected_arrival_unit", f"arrival unit {record.arrival_unit!r}, expected {ARRIVAL_UNIT!r}"))
    elif any(i.startswith("arrival_quantity") for i in record.parse_issues):
        flag(Finding("malformed_arrival_quantity", next(i for i in record.parse_issues if i.startswith("arrival_quantity"))))

    # Soft checks: only meaningful once the hard ones pass.
    if not result.rejections:
        low, high, modal = record.min_price, record.max_price, record.modal_price
        if low is None or high is None:
            missing = " and ".join(n for n, v in (("min_price", low), ("max_price", high)) if v is None)
            flag(Finding("missing_min_max", f"{missing} not reported"))
        if low is not None and high is not None and low > high:
            flag(Finding("price_order", f"min_price {low} > max_price {high}"))
        elif (low is not None and modal < low) or (high is not None and modal > high):
            flag(Finding("price_order", f"modal_price {modal} outside [{low}, {high}]"))
        for issue in record.parse_issues:
            if "not in the" in issue or "has no name" in issue:
                flag(Finding("unmatched_market", issue))
    return result
