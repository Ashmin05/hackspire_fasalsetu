"""Loaders for the captured real API responses in tests/fixtures/market_prices/.

Every fixture is a trimmed copy of a real response (captured 2026-09-27):
  agmarknet_filters.json          GET daily-price-arrival/filters, trimmed to
                                  West Bengal + Maharashtra and 6 commodities
  agmarknet_datewise_wb_potato_2026_09.json
                                  GET prices-and-arrivals/date-wise/specific-commodity
                                  (West Bengal, Potato, Sept 2026), 4 markets x last 6 days
  agmarknet_datewise_empty.json   the same report for a month nobody reported yet
  ceda_*.json                     CEDA /agmarknet/{commodities,geographies,markets,prices}
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "market_prices"


@lru_cache
def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load(name: str):
    """A fresh deep copy, so tests can mutate it."""
    return copy.deepcopy(_load(name))


def datewise_rows(body: dict) -> list[tuple[str, str, dict]]:
    """(marketName, arrivalDate, row) for every price row in a date-wise report."""
    return [
        (m["marketName"], d["arrivalDate"], row)
        for m in body["markets"]
        for d in m["dates"]
        for row in d["data"]
    ]
