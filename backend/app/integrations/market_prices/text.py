"""Parsing helpers shared by every provider.

They clean representation only (whitespace, thousands separators, date
formats) and never change a value's meaning: anything they can't read comes
back as None plus a reason, for the validator to reject or flag.
"""

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_WHITESPACE = re.compile(r"\s+")
_KEY_DROP = re.compile(r"[^a-z0-9]+")
# Suffixes the sources attach inconsistently to the same market's name
# ("Bara Bazar (Posta Bazar) APMC" on Agmarknet 2.0 vs "Bara Bazar (Posta
# Bazar)" on CEDA). Only used for *matching* -- stored names keep them.
_MARKET_SUFFIXES = ("apmc", "mandi", "market", "regulated market", "vfpck market")

TWO_PLACES = Decimal("0.01")

# The same commodity spelt differently across sources (CEDA and data.gov.in
# keep the old portal's "Paddy(Dhan)(...)" names), keyed by name_key(). Only
# genuinely identical commodities belong here.
COMMODITY_ALIASES = {
    "paddy dhan common": "paddy common",
    "paddy dhan basmati": "paddy basmati",
}

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ")


def clean_text(value) -> str | None:
    """Collapse internal whitespace and trim; None/blank -> None."""
    if value is None:
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


def name_key(value: str | None) -> str:
    """Case/punctuation/diacritic-insensitive key for matching the same
    entity across sources ("Purba Bardhaman" == "purba-bardhaman")."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _KEY_DROP.sub(" ", text.lower()).strip()


def market_key(value: str | None) -> str:
    key = name_key(value)
    for suffix in _MARKET_SUFFIXES:
        if key.endswith(" " + suffix):
            key = key[: -len(suffix) - 1].strip()
    return key


def parse_decimal(value, field_name: str, issues: list[str]) -> Decimal | None:
    """Number -> Decimal rounded to paise. Strings may carry thousands
    separators ("1,950"). Non-numbers ("NR", "-", "") -> None + an issue."""
    if value is None:
        issues.append(f"{field_name} missing")
        return None
    if isinstance(value, bool):
        issues.append(f"{field_name} not a number: {value!r}")
        return None
    text = str(value).replace(",", "").strip()
    if not text:
        issues.append(f"{field_name} missing")
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        issues.append(f"{field_name} not a number: {value!r}")
        return None
    if not number.is_finite():
        issues.append(f"{field_name} not a finite number: {value!r}")
        return None
    return number.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def parse_date(value, issues: list[str]) -> date | None:
    text = clean_text(value)
    if text is None:
        issues.append("arrival_date missing")
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    issues.append(f"arrival_date unparseable: {value!r}")
    return None


def commodity_keys(value: str | None) -> set[str]:
    """Every name_key a commodity name may appear under, across sources."""
    key = name_key(value)
    keys = {key}
    for a, b in COMMODITY_ALIASES.items():
        if key in (a, b):
            keys |= {a, b}
    return keys - {""}
