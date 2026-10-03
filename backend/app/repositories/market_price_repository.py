"""Persistence for market prices, ingestion runs and quality issues."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_price import MarketPrice, PriceIngestionRun, PriceQualityIssue

CHUNK = 500
# Columns a re-fetched report may legitimately change.
MUTABLE_FIELDS = (
    "market_id",
    "state_id",
    "commodity_id",
    "variety_id",
    "grade_id",
    "arrival_date",
    "min_price",
    "max_price",
    "modal_price",
    "arrival_quantity",
    "unit",
    "arrival_unit",
    "quality_flags",
)


def _chunks(items: list, size: int = CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class MarketPriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------ prices

    async def existing_prices(self, source: str, record_ids: list[str]) -> dict[str, dict]:
        """source_record_id -> {id, <mutable fields>} for rows already stored."""
        found: dict[str, dict] = {}
        columns = [MarketPrice.id, MarketPrice.source_record_id, *(getattr(MarketPrice, f) for f in MUTABLE_FIELDS)]
        for chunk in _chunks(record_ids):
            rows = await self.session.execute(
                select(*columns).where(MarketPrice.source == source, MarketPrice.source_record_id.in_(chunk))
            )
            for row in rows.mappings():
                found[row["source_record_id"]] = dict(row)
        return found

    async def insert_prices(self, rows: list[dict]) -> None:
        for chunk in _chunks(rows):
            await self.session.execute(insert(MarketPrice), chunk)

    async def update_prices(self, rows: list[dict]) -> None:
        """Bulk UPDATE by primary key; each dict carries "id"."""
        now = datetime.now(timezone.utc)
        for chunk in _chunks(rows):
            await self.session.execute(update(MarketPrice), [dict(r, updated_at=now) for r in chunk])

    # -------------------------------------------------------------- runs

    async def start_run(self, kind: str, *, provider: str | None = None, params: dict | None = None) -> PriceIngestionRun:
        run = PriceIngestionRun(kind=kind, provider=provider, params=params or {}, status="running", notes=[])
        self.session.add(run)
        await self.session.commit()
        return run

    async def finish_run(self, run: PriceIngestionRun, *, status: str, error: str | None = None) -> PriceIngestionRun:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
        run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
        run.error = error[:4000] if error else None
        await self.session.commit()
        return run

    async def get_run(self, run_id: int) -> PriceIngestionRun | None:
        return await self.session.get(PriceIngestionRun, run_id)

    async def latest_run(self, kind: str, *, status: str | None = None) -> PriceIngestionRun | None:
        query = select(PriceIngestionRun).where(PriceIngestionRun.kind == kind, PriceIngestionRun.finished_at.is_not(None))
        if status:
            query = query.where(PriceIngestionRun.status == status)
        return await self.session.scalar(query.order_by(PriceIngestionRun.started_at.desc(), PriceIngestionRun.id.desc()).limit(1))

    # ------------------------------------------------------------ issues

    async def known_issue_keys(self, source: str, record_ids: list[str]) -> set[tuple[str, str]]:
        """(source_record_id, code) pairs already logged, so re-fetching the
        same bad row every night doesn't grow the log."""
        keys: set[tuple[str, str]] = set()
        for chunk in _chunks([r for r in record_ids if r]):
            rows = await self.session.execute(
                select(PriceQualityIssue.source_record_id, PriceQualityIssue.code).where(
                    PriceQualityIssue.source == source, PriceQualityIssue.source_record_id.in_(chunk)
                )
            )
            keys |= {(r[0], r[1]) for r in rows}
        return keys

    async def add_issues(self, issues: list[dict]) -> None:
        for chunk in _chunks(issues):
            await self.session.execute(insert(PriceQualityIssue), chunk)
