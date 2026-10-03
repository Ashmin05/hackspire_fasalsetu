"""The ingestion pipeline:

    provider (raw response -> parsed -> NormalizedMarketPrice)
      -> validate            reject unusable records, flag suspicious ones
      -> deduplicate         within the batch, by (source, source_record_id)
      -> resolve             names/ids -> catalogue rows
      -> upsert              insert new, update changed, skip unchanged
      -> log                 run statistics + quality issues (raw rows kept)

Idempotent: a record's identity is (source, source_record_id), so running the
same fetch twice inserts nothing the second time. Each query is committed on
its own, so a failure part-way keeps everything before it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.market_prices.base import (
    NormalizedMarketPrice,
    PriceDataProvider,
    PriceQuery,
    ProviderError,
    ProviderPriceBatch,
)
from app.models.market_price import PriceIngestionRun
from app.repositories.market_price_repository import MarketPriceRepository
from app.services.market_prices.catalog import CatalogResolver, sync_catalog
from app.services.market_prices.validation import Finding, validate

logger = logging.getLogger(__name__)


@dataclass
class BatchStats:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0  # unchanged re-fetches + exact in-batch duplicates
    rejected: int = 0
    flagged: int = 0
    requests: int = 0

    def add_to(self, run: PriceIngestionRun) -> None:
        run.records_fetched += self.fetched
        run.records_inserted += self.inserted
        run.records_updated += self.updated
        run.records_skipped += self.skipped
        run.records_rejected += self.rejected
        run.records_flagged += self.flagged
        run.requests_made += self.requests


@dataclass
class QueryOutcome:
    query: PriceQuery
    provider: str | None
    stats: BatchStats
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def _same(a, b) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return (a is None and b is None) or (a is not None and b is not None and Decimal(str(a)) == Decimal(str(b)))
    if isinstance(a, datetime) or isinstance(b, datetime):
        return a == b
    return a == b


class MarketPriceIngestionService:
    def __init__(
        self,
        session: AsyncSession,
        providers: list[PriceDataProvider],
        *,
        today: date | None = None,
    ) -> None:
        self.session = session
        self.repository = MarketPriceRepository(session)
        self.providers = providers
        self.today = today or date.today()
        self.resolver = CatalogResolver(session)
        # commodity_id -> earliest arrival_date inserted/updated, for the
        # analytics refresh that follows (see analytics.refresh_analytics).
        self.touched: dict[int, date] = {}

    # ------------------------------------------------------------ catalogue

    async def sync_catalog(self, provider: PriceDataProvider) -> PriceIngestionRun:
        run = await self.repository.start_run("catalog", provider=provider.name)
        run_id = run.id
        try:
            catalog = await provider.fetch_catalog()
            stats = await sync_catalog(self.session, catalog)
            run = await self.repository.get_run(run_id)
            run.requests_made = 1
            run.notes = [stats.as_dict()]
            await self.session.commit()
            self.resolver.loaded = False
            return await self.repository.finish_run(run, status="succeeded")
        except Exception as exc:  # noqa: BLE001 -- recorded on the run
            await self.session.rollback()
            run = await self.repository.get_run(run_id)
            logger.warning("Catalogue sync from %s failed: %s", provider.name, exc)
            return await self.repository.finish_run(run, status="failed", error=f"{type(exc).__name__}: {exc}")

    async def ensure_catalog(self) -> None:
        """Pull the catalogue once if it has never been loaded."""
        await self.resolver.load()
        if self.resolver.empty:
            primary = next((p for p in self.providers if p.name == "agmarknet"), None)
            if primary is None:
                raise ProviderError("No catalogue loaded and the Agmarknet provider isn't configured")
            run = await self.sync_catalog(primary)
            if run.status != "succeeded":
                raise ProviderError(f"Catalogue sync failed: {run.error}")
            await self.resolver.load()

    # --------------------------------------------------------------- prices

    async def ingest(self, queries: list[PriceQuery], *, kind: str, params: dict | None = None) -> PriceIngestionRun:
        """Fetch + store every query, falling back across providers on
        errors. The run is 'succeeded' if every query was served, 'partial'
        if some were, 'failed' if none."""
        run = await self.repository.start_run(kind, params=params or {})
        run_id = run.id
        outcomes: list[QueryOutcome] = []
        try:
            await self.ensure_catalog()
        except Exception as exc:  # noqa: BLE001
            await self.session.rollback()
            run = await self.repository.get_run(run_id)
            return await self.repository.finish_run(run, status="failed", error=f"{type(exc).__name__}: {exc}")

        for query in queries:
            outcome = await self.ingest_query(query, run_id=run_id)
            outcomes.append(outcome)

        run = await self.repository.get_run(run_id)
        served = [o for o in outcomes if o.ok]
        providers = sorted({o.provider for o in served if o.provider})
        run.provider = ",".join(providers) or None
        run.notes = [
            {
                "state": o.query.state,
                "commodity": o.query.commodity,
                "from": o.query.from_date.isoformat(),
                "to": o.query.to_date.isoformat(),
                "provider": o.provider,
                "fetched": o.stats.fetched,
                "inserted": o.stats.inserted,
                "updated": o.stats.updated,
                "rejected": o.stats.rejected,
                **({"error": o.error} if o.error else {}),
                **({"notes": o.notes} if o.notes else {}),
            }
            for o in outcomes
        ]
        for o in outcomes:
            o.stats.add_to(run)
        status = "succeeded" if len(served) == len(outcomes) else ("partial" if served else "failed")
        errors = "; ".join(f"{o.query.state}/{o.query.commodity}: {o.error}" for o in outcomes if o.error)
        run = await self.repository.finish_run(run, status=status, error=errors or None)
        logger.info(
            "Market price %s run %s %s: %d fetched, %d inserted, %d updated, %d skipped, %d rejected, %d flagged, %d request(s), %d ms",
            kind, run.id, status, run.records_fetched, run.records_inserted, run.records_updated,
            run.records_skipped, run.records_rejected, run.records_flagged, run.requests_made, run.duration_ms or 0,
        )
        return run

    async def ingest_query(self, query: PriceQuery, *, run_id: int | None) -> QueryOutcome:
        errors: list[str] = []
        for provider in self.providers:
            try:
                batch = await provider.fetch_prices(query)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.info("%s couldn't serve %s/%s: %s", provider.name, query.state, query.commodity, exc)
                continue
            try:
                stats = await self.store_batch(batch, run_id=run_id)
                await self.session.commit()
            except Exception as exc:  # noqa: BLE001 -- a storage bug must not kill the run
                await self.session.rollback()
                self.resolver.loaded = False  # the rollback expired every cached row
                logger.exception("Storing %s/%s from %s failed", query.state, query.commodity, provider.name)
                return QueryOutcome(query, provider.name, BatchStats(requests=batch.requests_made), error=f"storage: {exc}")
            return QueryOutcome(query, provider.name, stats, notes=[*errors, *batch.notes])
        return QueryOutcome(query, None, BatchStats(), error=" | ".join(errors) or "no provider configured")

    async def store_batch(self, batch: ProviderPriceBatch, *, run_id: int | None) -> BatchStats:
        stats = BatchStats(fetched=len(batch.records), requests=batch.requests_made)
        if not self.resolver.loaded:
            await self.resolver.load()
        issues: list[dict] = []
        now = datetime.now(timezone.utc)

        def log(record: NormalizedMarketPrice, severity: str, finding: Finding) -> None:
            issues.append(
                {
                    "run_id": run_id,
                    "severity": severity,
                    "code": finding.code,
                    "message": finding.message,
                    "source": record.source,
                    "source_record_id": record.source_record_id,
                    "raw": _jsonable(record.raw),
                    "created_at": now,
                }
            )

        # 1. validate + 2. deduplicate within the batch
        accepted: dict[str, tuple[NormalizedMarketPrice, list[Finding]]] = {}
        for record in batch.records:
            result = validate(record, today=self.today)
            if not result.accepted:
                stats.rejected += 1
                for finding in result.rejections:
                    log(record, "rejected", finding)
                continue
            previous = accepted.get(record.source_record_id)
            if previous is not None:
                if _price_tuple(previous[0]) == _price_tuple(record):
                    stats.skipped += 1  # exact duplicate row
                else:
                    stats.rejected += 1
                    log(record, "rejected", Finding("conflicting_duplicate", "same report appears twice in one response with different values; first kept"))
                continue
            accepted[record.source_record_id] = (record, result.flags)

        # 3. resolve against the catalogue
        rows: list[tuple[dict, list[Finding]]] = []
        for record, flags in accepted.values():
            ids, rejections, extra_flags = await self.resolver.resolve(record)
            if ids is None:
                stats.rejected += 1
                for finding in rejections:
                    log(record, "rejected", finding)
                continue
            all_flags = [*flags, *extra_flags]
            rows.append(
                (
                    {
                        "market_id": ids.market_id,
                        "state_id": ids.state_id,
                        "commodity_id": ids.commodity_id,
                        "variety_id": ids.variety_id,
                        "grade_id": ids.grade_id,
                        "arrival_date": record.arrival_date,
                        "min_price": record.min_price,
                        "max_price": record.max_price,
                        "modal_price": record.modal_price,
                        "arrival_quantity": record.arrival_quantity,
                        "unit": record.price_unit,
                        "arrival_unit": record.arrival_unit if record.arrival_quantity is not None else None,
                        "quality_flags": sorted({f.code for f in all_flags}),
                        "source": record.source,
                        "source_record_id": record.source_record_id,
                        "fetched_at": now,
                        "_record": record,
                        "_flags": all_flags,
                    },
                    all_flags,
                )
            )

        # 4. upsert: insert new, update changed, skip unchanged
        by_source: dict[str, list] = {}
        for row, _ in rows:
            by_source.setdefault(row["source"], []).append(row)
        to_insert: list[dict] = []
        to_update: list[dict] = []
        written: set[str] = set()  # source_record_ids inserted or changed
        for source, source_rows in by_source.items():
            existing = await self.repository.existing_prices(source, [r["source_record_id"] for r in source_rows])
            for row in source_rows:
                current = existing.get(row["source_record_id"])
                if row["_flags"]:
                    stats.flagged += 1
                columns = {k: v for k, v in row.items() if not k.startswith("_")}
                if current is None:
                    to_insert.append(columns | {"created_at": now, "updated_at": now})
                    written.add(row["source_record_id"])
                elif _unchanged(current, row):
                    stats.skipped += 1
                else:
                    to_update.append(
                        {"id": current["id"], **{k: v for k, v in columns.items() if k not in ("source", "source_record_id")}}
                    )
                    written.add(row["source_record_id"])
        await self.repository.insert_prices(to_insert)
        await self.repository.update_prices(to_update)
        stats.inserted, stats.updated = len(to_insert), len(to_update)
        for row in (*to_insert, *to_update):
            earliest = self.touched.get(row["commodity_id"])
            if earliest is None or row["arrival_date"] < earliest:
                self.touched[row["commodity_id"]] = row["arrival_date"]

        # 5. log flags for rows whose data is new or changed
        for row, flags in rows:
            if flags and row["source_record_id"] in written:
                for finding in flags:
                    log(row["_record"], "flagged", finding)

        # Don't re-log an issue already recorded for the same source row.
        if issues:
            known: set[tuple[str, str]] = set()
            for source in {i["source"] for i in issues}:
                known |= await self.repository.known_issue_keys(source, [i["source_record_id"] for i in issues if i["source"] == source])
            fresh, seen = [], set()
            for issue in issues:
                key = (issue["source_record_id"], issue["code"])
                if key in known or key in seen:
                    continue
                seen.add(key)
                fresh.append(issue)
            await self.repository.add_issues(fresh)
        return stats


COMPARED_FIELDS = (
    "market_id", "state_id", "commodity_id", "variety_id", "grade_id", "arrival_date",
    "min_price", "max_price", "modal_price", "arrival_quantity", "unit", "arrival_unit",
)


def _unchanged(current: dict, row: dict) -> bool:
    return all(_same(current[f], row[f]) for f in COMPARED_FIELDS) and list(current["quality_flags"] or []) == row["quality_flags"]


def _price_tuple(record: NormalizedMarketPrice) -> tuple:
    return (record.min_price, record.max_price, record.modal_price, record.arrival_quantity, record.arrival_date)


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
