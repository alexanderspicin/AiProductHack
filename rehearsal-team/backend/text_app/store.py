from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import Scenario, Session, Settings


class Conflict(Exception):
    pass


class Store:
    """Single-worker local PoC. SQLite commits each state change, no in-memory history."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS documents (kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))")
            db.execute("CREATE TABLE IF NOT EXISTS starts (request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL)")
        path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, kind: str, key: str):
        with self.connection() as db:
            row = db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def all(self, kind: str):
        with self.connection() as db:
            rows = db.execute("SELECT body FROM documents WHERE kind=? ORDER BY rowid DESC", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind: str, key: str, value, expected_revision: int | None = None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected_revision is not None:
                row = db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
                if row is None or json.loads(row[0])["revision"] != expected_revision:
                    raise Conflict("Настройки изменились в другой вкладке. Обновите страницу и повторите правку.")
            db.execute("INSERT INTO documents VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body", (kind, key, value.model_dump_json()))

    def scenario(self, key: str) -> Scenario:
        return Scenario.model_validate(self.get("scenario", key))

    def session(self, key: str) -> Session:
        return Session.model_validate(self.get("session", key))

    def settings(self) -> Settings:
        try:
            return Settings.model_validate(self.get("settings", "main"))
        except KeyError:
            return Settings()

    def recover(self):
        for raw in self.all("session"):
            session = Session.model_validate(raw)
            changed = False
            for turn in session.turns:
                if turn.status == "pending":
                    turn.status = "cancelled"
                    changed = True
            if session.report_status == "pending":
                session.report_status = "failed"
                session.report_error = "Сервер перезапустился. Стенограмма сохранена; разбор можно запросить повторно."
                changed = True
            if changed:
                self.put("session", session.id, session)

    def find_start(self, request_id: str) -> str | None:
        with self.connection() as db:
            row = db.execute("SELECT session_id FROM starts WHERE request_id=?", (request_id,)).fetchone()
        return row[0] if row else None

    def save_start(self, request_id: str, session: Session):
        with self.connection() as db:
            db.execute("INSERT INTO starts VALUES (?,?)", (request_id, session.id))
            db.execute("INSERT INTO documents VALUES ('session',?,?)", (session.id, session.model_dump_json()))
