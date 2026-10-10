"""Private, evidence-gated identity links between third-party listings and ATS jobs.

Links are created ONLY after a successful, independently read employer posting
corroborates source employer, title and native requisition identity. Stored
values are SHA-256 identity hashes, not raw listing URLs. A single user's
Private Home is the ownership boundary, like the existing job-history ledger.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from source_connectors.contract import ReadJobResult, SourceJobObservation

from .event_ledger import _job_url_hash_candidates, hash_job_url
from .posting_verification import (
    PostingVerification,
    supported_employer_identity,
    verify_employer_observation,
)
from .private_home import PrivateHome


def _valid_public_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise ValueError("posting alias URL is invalid")
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise ValueError("posting alias URL is invalid") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise ValueError("posting alias URL is invalid")
    return url


class VerifiedPostingAliases:
    """Durable hash-only links. No guessed company/title or fuzzy link creation."""

    def __init__(self, home: PrivateHome | None = None) -> None:
        self.home = home or PrivateHome.discover()

    @property
    def path(self) -> Path:
        return self.home.paths.state / "verified-posting-aliases.sqlite3"

    @contextmanager
    def _connect(self):
        self.home.ensure()
        path = self.path
        if path.is_symlink():
            raise ValueError("posting alias database cannot be a symlink")
        connection = sqlite3.connect(path, timeout=5)
        try:
            os.chmod(path, 0o600)
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS verified_aliases ("
                "source_hash TEXT PRIMARY KEY, "
                "employer_hash TEXT NOT NULL, "
                "recorded_at TEXT NOT NULL, "
                "CHECK (source_hash != employer_hash))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_verified_aliases_employer "
                "ON verified_aliases(employer_hash)"
            )
            connection.commit()
            with connection:
                yield connection
        finally:
            connection.close()

    def identity_hashes(self, url: str) -> tuple[str, ...]:
        """Existing aliases in both directions; no DB creation on a lookup miss."""
        _valid_public_url(url)
        candidates = set(_job_url_hash_candidates(url))
        path = self.path
        if path.is_symlink():
            raise ValueError("posting alias database cannot be a symlink")
        if not path.is_file():
            return tuple(sorted(candidates))
        with self._connect() as connection:
            placeholders = ",".join("?" for _ in candidates)
            anchors = {
                item[0]
                for item in connection.execute(
                    f"SELECT employer_hash FROM verified_aliases "
                    f"WHERE source_hash IN ({placeholders})",
                    tuple(candidates),
                ).fetchall()
            }
            anchors.update(candidates)
            placeholders = ",".join("?" for _ in anchors)
            connected = connection.execute(
                f"SELECT source_hash, employer_hash FROM verified_aliases "
                f"WHERE employer_hash IN ({placeholders})",
                tuple(anchors),
            ).fetchall()
        for source_hash, employer_hash in connected:
            candidates.add(source_hash)
            candidates.add(employer_hash)
        return tuple(sorted(candidates))

    def record_verified(
        self,
        *,
        source: SourceJobObservation,
        employer_url: str,
        employer_read: ReadJobResult,
    ) -> bool:
        """Idempotent verified write. Refuse attempts to relink to a new job."""
        if not isinstance(source, SourceJobObservation):
            raise TypeError("source must be a typed public observation")
        external_url = _valid_public_url(source.source_url)
        target_url = _valid_public_url(employer_url)
        if (
            source.application_url is None
            or hash_job_url(source.application_url) != hash_job_url(target_url)
            or supported_employer_identity(external_url) is not None
            or supported_employer_identity(target_url) is None
            or verify_employer_observation(
                source, target_url, employer_read
            ) is not PostingVerification.VERIFIED
        ):
            raise ValueError("posting relationship has no corroborated ATS evidence")
        source_hash = hash_job_url(external_url)
        employer_hash = hash_job_url(target_url)
        if source_hash == employer_hash:
            raise ValueError("posting alias must connect distinct URL identities")
        with self._connect() as connection:
            # BEGIN IMMEDIATE serializes competing source mappings.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT employer_hash FROM verified_aliases WHERE source_hash=?",
                (source_hash,),
            ).fetchone()
            if row is not None:
                if row[0] != employer_hash:
                    raise ValueError("verified posting alias conflicts with earlier employer")
                return False
            connection.execute(
                "INSERT INTO verified_aliases(source_hash, employer_hash, recorded_at) "
                "VALUES (?, ?, ?)",
                (source_hash, employer_hash, datetime.now(timezone.utc).isoformat()),
            )
        return True


__all__ = ["VerifiedPostingAliases"]
