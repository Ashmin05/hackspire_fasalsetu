"""Catalogue sync (Agmarknet 2.0 -> states/districts/markets/commodities/
varieties/grades) and the resolver that maps any provider's names onto those
rows.

Matching rules, strictest first:
  1. external id (only for Agmarknet records -- the ids are Agmarknet's),
  2. name within the right parent (market within state, district within
     state, variety within commodity), case/punctuation-insensitive, with
     known cross-source aliases for commodities.
A name matching several rows is *ambiguous* and rejected rather than
guessed. Unknown states/commodities are rejected (the catalogue is
authoritative); an unknown market/variety/grade reported by a source is
created, and the record is flagged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.market_prices.base import NormalizedMarketPrice, ProviderCatalog
from app.integrations.market_prices.text import commodity_keys, market_key, name_key
from app.models.market_price import Commodity, Grade, Market, MarketDistrict, MarketState, Variety
from app.services.market_prices.validation import Finding


@dataclass
class CatalogSyncStats:
    states: int = 0
    districts: int = 0
    markets: int = 0
    commodities: int = 0
    varieties: int = 0
    grades: int = 0
    created: int = 0
    updated: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ResolvedIds:
    state_id: int
    district_id: int | None
    market_id: int
    commodity_id: int
    variety_id: int | None
    grade_id: int | None


async def sync_catalog(session: AsyncSession, catalog: ProviderCatalog) -> CatalogSyncStats:
    """Insert/update catalogue rows by external id. A row created earlier by
    name alone (from a fallback source) is adopted when Agmarknet's
    catalogue later lists it."""
    stats = CatalogSyncStats()

    async def upsert(model, items, *, key_parent=None, build, update_fields, stat_name, name_fn=name_key):
        existing = (await session.execute(select(model))).scalars().all()
        by_ext = {row.external_id: row for row in existing if row.external_id}
        by_key: dict[tuple, list] = defaultdict(list)
        for row in existing:
            if not row.external_id:
                by_key[(key_parent(row) if key_parent else None, row.name_key)].append(row)
        result = {}
        for item in items:
            values = build(item)
            if values is None:
                continue
            row = by_ext.get(item.external_id)
            if row is None:
                orphans = by_key.get((values.get("_parent"), values["name_key"])) or []
                row = orphans.pop(0) if orphans else None
            values.pop("_parent", None)
            if row is None:
                row = model(external_id=item.external_id, **values)
                session.add(row)
                stats.created += 1
            else:
                changed = row.external_id != item.external_id or any(
                    getattr(row, f) != values[f] for f in update_fields if f in values
                )
                row.external_id = item.external_id
                for f in update_fields:
                    if f in values:
                        setattr(row, f, values[f])
                stats.updated += int(changed)
            by_ext[item.external_id] = row
            result[item.external_id] = row
        await session.flush()
        setattr(stats, stat_name, len(result))
        return result

    states = await upsert(
        MarketState,
        catalog.states,
        build=lambda s: {"name": s.name, "name_key": name_key(s.name)},
        update_fields=("name", "name_key"),
        stat_name="states",
    )
    districts = await upsert(
        MarketDistrict,
        catalog.districts,
        key_parent=lambda row: row.state_id,
        build=lambda d: (
            {"state_id": states[d.state_external_id].id, "_parent": states[d.state_external_id].id,
             "name": d.name, "name_key": name_key(d.name)}
            if d.state_external_id in states else None
        ),
        update_fields=("state_id", "name", "name_key"),
        stat_name="districts",
    )
    await upsert(
        Market,
        catalog.markets,
        key_parent=lambda row: row.state_id,
        build=lambda m: (
            {"state_id": states[m.state_external_id].id, "_parent": states[m.state_external_id].id,
             "district_id": districts[m.district_external_id].id if m.district_external_id in districts else None,
             "name": m.name, "name_key": market_key(m.name)}
            if m.state_external_id in states else None
        ),
        update_fields=("state_id", "district_id", "name", "name_key"),
        stat_name="markets",
    )
    commodities = await upsert(
        Commodity,
        catalog.commodities,
        build=lambda c: {"name": c.name, "name_key": name_key(c.name), "commodity_group": c.commodity_group},
        update_fields=("name", "name_key", "commodity_group"),
        stat_name="commodities",
    )
    grades_seen: set[str] = set()

    def grade_values(g):
        key = name_key(g.name)
        if key in grades_seen:
            return None
        grades_seen.add(key)
        return {"name": g.name, "name_key": key}

    await upsert(Grade, catalog.grades, build=grade_values, update_fields=("name", "name_key"), stat_name="grades")

    # Varieties: Agmarknet shares one variety id across several commodities,
    # so rows are keyed (commodity, name) and carry the id as a reference.
    existing = (await session.execute(select(Variety))).scalars().all()
    varieties = {(v.commodity_id, v.name_key): v for v in existing}
    count = 0
    for variety in catalog.varieties:
        key = name_key(variety.name)
        for commodity_ext in variety.commodity_external_ids:
            commodity = commodities.get(commodity_ext)
            if commodity is None:
                continue
            row = varieties.get((commodity.id, key))
            if row is None:
                row = Variety(commodity_id=commodity.id, external_id=variety.external_id, name=variety.name, name_key=key)
                session.add(row)
                varieties[(commodity.id, key)] = row
                stats.created += 1
            elif row.external_id is None:
                row.external_id = variety.external_id
                stats.updated += 1
            count += 1
    stats.varieties = count
    await session.flush()
    return stats


class CatalogResolver:
    """In-memory index of the catalogue for resolving a batch of records.
    Rows it has to create are added to the session (flushed for their ids)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.loaded = False

    async def load(self) -> None:
        s = self.session
        self.states = (await s.execute(select(MarketState))).scalars().all()
        self.state_by_ext = {r.external_id: r for r in self.states if r.external_id}
        self.state_by_key = {r.name_key: r for r in self.states}

        districts = (await s.execute(select(MarketDistrict))).scalars().all()
        self.district_by_ext = {r.external_id: r for r in districts if r.external_id}
        self.district_by_key = {(r.state_id, r.name_key): r for r in districts}

        markets = (await s.execute(select(Market))).scalars().all()
        self.market_by_ext = {r.external_id: r for r in markets if r.external_id}
        self.markets_by_key: dict[tuple, list[Market]] = defaultdict(list)
        for r in markets:
            self.markets_by_key[(r.state_id, r.name_key)].append(r)

        commodities = (await s.execute(select(Commodity))).scalars().all()
        self.commodity_by_ext = {r.external_id: r for r in commodities if r.external_id}
        self.commodities_by_key: dict[str, list[Commodity]] = defaultdict(list)
        for r in commodities:
            self.commodities_by_key[r.name_key].append(r)

        varieties = (await s.execute(select(Variety))).scalars().all()
        self.variety_by_key = {(r.commodity_id, r.name_key): r for r in varieties}
        grades = (await s.execute(select(Grade))).scalars().all()
        self.grade_by_key = {r.name_key: r for r in grades}
        self.loaded = True

    @property
    def empty(self) -> bool:
        return not self.states

    async def resolve(self, record: NormalizedMarketPrice) -> tuple[ResolvedIds | None, list[Finding], list[Finding]]:
        """-> (ids or None, rejections, flags)."""
        if not self.loaded:
            await self.load()
        rejections: list[Finding] = []
        flags: list[Finding] = []
        is_agmarknet = record.source == "agmarknet"

        state = (self.state_by_ext.get(record.state_external_id) if is_agmarknet else None) or self.state_by_key.get(
            name_key(record.state)
        )
        if state is None:
            rejections.append(Finding("unknown_state", f"state {record.state!r} is not in the catalogue"))

        commodity = self.commodity_by_ext.get(record.commodity_external_id) if is_agmarknet else None
        if commodity is None:
            matches = {c.id: c for key in commodity_keys(record.commodity) for c in self.commodities_by_key.get(key, [])}
            if len(matches) == 1:
                commodity = next(iter(matches.values()))
            elif len(matches) > 1:
                rejections.append(Finding("ambiguous_commodity", f"commodity {record.commodity!r} matches {len(matches)} catalogue entries"))
            else:
                rejections.append(Finding("unknown_commodity", f"commodity {record.commodity!r} is not in the catalogue"))
        if rejections:
            return None, rejections, flags

        district = (self.district_by_ext.get(record.district_external_id) if is_agmarknet else None) or (
            self.district_by_key.get((state.id, name_key(record.district))) if record.district else None
        )

        market = self.market_by_ext.get(record.market_external_id) if is_agmarknet else None
        if market is None:
            candidates = self.markets_by_key.get((state.id, market_key(record.market)), [])
            if district is not None and len(candidates) > 1:
                candidates = [m for m in candidates if m.district_id == district.id] or candidates
            if len(candidates) > 1:
                return None, [Finding("ambiguous_market", f"market {record.market!r} matches {len(candidates)} markets in {state.name}")], flags
            if candidates:
                market = candidates[0]
            else:
                market = Market(
                    state_id=state.id,
                    district_id=district.id if district else None,
                    name=record.market,
                    name_key=market_key(record.market),
                )
                self.session.add(market)
                await self.session.flush()
                self.markets_by_key[(state.id, market.name_key)].append(market)
                flags.append(Finding("new_market", f"market {record.market!r} added from {record.source} (not in the Agmarknet catalogue)"))
        if district is None and market.district_id is not None:
            district_id = market.district_id
        else:
            district_id = district.id if district else None

        variety_id = None
        if record.variety:
            key = name_key(record.variety)
            variety = self.variety_by_key.get((commodity.id, key))
            if variety is None:
                variety = Variety(commodity_id=commodity.id, name=record.variety, name_key=key)
                self.session.add(variety)
                await self.session.flush()
                self.variety_by_key[(commodity.id, key)] = variety
            variety_id = variety.id

        grade_id = None
        if record.grade:
            key = name_key(record.grade)
            grade = self.grade_by_key.get(key)
            if grade is None:
                grade = Grade(name=record.grade, name_key=key)
                self.session.add(grade)
                await self.session.flush()
                self.grade_by_key[key] = grade
            grade_id = grade.id

        return (
            ResolvedIds(
                state_id=state.id,
                district_id=district_id,
                market_id=market.id,
                commodity_id=commodity.id,
                variety_id=variety_id,
                grade_id=grade_id,
            ),
            rejections,
            flags,
        )
