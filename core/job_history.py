from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from .event_ledger import hash_job_url
from .private_home import PrivateHome


class JobHistoryState(StrEnum):
    APPLIED_SELF_REPORTED = "APPLIED_SELF_REPORTED"
    DISMISSED = "DISMISSED"


class PrivateJobHistory:
    def __init__(self, home: PrivateHome | None = None) -> None:
        self.home = home or PrivateHome.discover()

    @property
    def path(self) -> Path:
        return self.home.paths.state / "job-history.sqlite3"

    @contextmanager
    def _connect(self):
        path = self.home.ensure().state / "job-history.sqlite3"
        if path.is_symlink():
            raise ValueError("job history database cannot be a symlink")
        connection = sqlite3.connect(path, timeout=5)
        try:
            os.chmod(path, 0o600)
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS job_history ("
                "identity_hash TEXT PRIMARY KEY, "
                "state TEXT NOT NULL CHECK (state IN ('APPLIED_SELF_REPORTED', 'DISMISSED')), "
                "recorded_at TEXT NOT NULL)"
            )
            connection.commit()
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _identity(url: str) -> str:
        if not isinstance(url, str):
            raise ValueError("posting URL must be an absolute HTTP(S) URL")
        parsed = urlsplit(url.strip())
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("posting URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("posting URLs must not contain credentials")
        return hash_job_url(url)

    def state_for(self, url: str) -> JobHistoryState | None:
        identity = self._identity(url)
        if not self.path.exists():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM job_history WHERE identity_hash = ?", (identity,)
            ).fetchone()
        return JobHistoryState(row[0]) if row else None

    def mark(self, url: str, state: JobHistoryState) -> JobHistoryState:
        identity = self._identity(url)
        state = JobHistoryState(state)
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT state FROM job_history WHERE identity_hash = ?", (identity,)
            ).fetchone()
            if previous and previous[0] == JobHistoryState.APPLIED_SELF_REPORTED.value:
                if state is JobHistoryState.DISMISSED:
                    raise ValueError("clear the self-reported application before dismissing")
            connection.execute(
                "INSERT INTO job_history (identity_hash, state, recorded_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(identity_hash) DO UPDATE SET "
                "state=excluded.state, recorded_at=excluded.recorded_at",
                (identity, state.value, datetime.now(timezone.utc).isoformat()),
            )
        return state

    def clear(self, url: str) -> None:
        identity = self._identity(url)
        if not self.path.exists():
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM job_history WHERE identity_hash = ?", (identity,)
            )
