"""Server-only configuration and persistent text usage ledger. No request cap."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .usage import PRICE_SOURCES, PRICE_VERSION, cost_nano_usd, token_usage


ROOT = Path(__file__).resolve().parents[2]


class OpenAIUnavailable(RuntimeError):
    pass


def local_setting(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value.strip()
    path = Path(os.getenv("REHEARSAL_CONFIG_FILE", str(ROOT / ".env.local")))
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, raw_value = line.strip().partition("=")
            if separator and key == name:
                return raw_value.strip().strip("\"'")
    return default


class OpenAIRequestBudget:
    def __init__(
        self,
        api_key: str = "",
        *,
        enabled: bool = False,
        max_requests: int | None = None,
        path: Path | None = None,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key.strip()
        self.enabled = enabled
        # Kept as an ignored compatibility argument for old launchers/tests.
        self.max_requests = None
        self.base_url = base_url.rstrip("/")
        self._path = path or ROOT / "artifacts/openai_api_budget.sqlite3"

    @classmethod
    def from_local_config(cls, *, allow_credentials: bool = True) -> "OpenAIRequestBudget":
        return cls(
            api_key=local_setting("OPENAI_API_KEY") if allow_credentials else "",
            enabled=local_setting("OPENAI_API_ENABLED", "0") == "1" if allow_credentials else False,
            base_url=local_setting("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            path=Path(os.getenv("OPENAI_BUDGET_PATH", str(ROOT / "artifacts/openai_api_budget.sqlite3"))),
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.enabled

    @contextmanager
    def _database(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS reservations ("
                "reservation_id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS text_usage ("
                "reservation_id TEXT PRIMARY KEY, model TEXT, state TEXT NOT NULL, "
                "input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, "
                "cached_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER, "
                "cost_nano_usd INTEGER, price_version TEXT)"
            )
            connection.commit()
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def used_requests(self) -> int:
        with self._database() as database:
            return int(database.execute("SELECT COUNT(*) FROM reservations WHERE operation IN ('text_turn','text_report','text_opening')").fetchone()[0])

    def status(self) -> dict:
        with self._database() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute(
                "SELECT r.operation, r.created_at, u.* FROM reservations r LEFT JOIN text_usage u "
                "ON r.reservation_id=u.reservation_id WHERE r.operation IN ('text_turn','text_report','text_opening') ORDER BY r.created_at DESC"
            )]
        measured = [r for r in rows if r['total_tokens'] is not None]
        priced = [r for r in measured if r['cost_nano_usd'] is not None]
        total = {k: sum(r[k] for r in measured) for k in (
            'input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'cache_write_tokens', 'reasoning_tokens')}
        total.update({
            'measured_requests': len(measured), 'unmeasured_requests': len(rows) - len(measured),
            'priced_requests': len(priced), 'unpriced_requests': len(rows) - len(priced),
            'estimated_cost_usd': sum(r['cost_nano_usd'] for r in priced) / 1_000_000_000 if priced else None,
            'price_version': PRICE_VERSION, 'price_sources': PRICE_SOURCES,
            'first_measured_at': min((r['created_at'] for r in measured), default=None),
            'recent': [{
                'operation': r['operation'], 'created_at': r['created_at'], 'model': r['model'],
                'state': r['state'] or 'untracked', 'total_tokens': r['total_tokens'],
                'estimated_cost_usd': r['cost_nano_usd'] / 1_000_000_000 if r['cost_nano_usd'] is not None else None,
            } for r in rows[:10]],
        })
        return {
            "available": self.available,
            "key_configured": bool(self.api_key),
            "enabled": self.enabled,
            "unlimited": True,
            "max_requests": None,
            "used_requests": len(rows),
            "remaining_requests": None,
            "usage": total,
        }

    def reserve(self, operation: str, reservation_id: str | None = None) -> str:
        if not self.api_key:
            raise OpenAIUnavailable("Добавьте OPENAI_API_KEY в серверный .env.local")
        if not self.enabled:
            raise OpenAIUnavailable("OpenAI API выключен. Нужен OPENAI_API_ENABLED=1")
        rid = reservation_id or str(uuid4())
        with self._database() as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "INSERT INTO reservations (reservation_id, operation) VALUES (?, ?)",
                (rid, operation),
            )
            database.execute("INSERT INTO text_usage(reservation_id,state) VALUES (?,'pending')", (rid,))
        return rid
        # A reservation is never retried or refunded automatically.

    def record(self, rid: str, model: str, usage, tier: str = "default"):
        parsed = token_usage(usage)
        if parsed is None:
            return
        cost = cost_nano_usd(model, parsed, standard_openai=self.base_url == "https://api.openai.com/v1" and tier == "default")
        with self._database() as db:
            # First valid usage wins; duplicate response processing never doubles totals.
            db.execute(
                "UPDATE text_usage SET model=?, input_tokens=?, output_tokens=?, total_tokens=?, "
                "cached_tokens=?, cache_write_tokens=?, reasoning_tokens=?, cost_nano_usd=?, price_version=? "
                "WHERE reservation_id=? AND total_tokens IS NULL",
                (model, parsed['input_tokens'], parsed['output_tokens'], parsed['total_tokens'],
                 parsed['cached_tokens'], parsed['cache_write_tokens'], parsed['reasoning_tokens'],
                 cost, PRICE_VERSION if cost is not None else None, rid),
            )

    def finish(self, rid: str, state: str):
        with self._database() as db:
            db.execute("UPDATE text_usage SET state=? WHERE reservation_id=?", (state, rid))
