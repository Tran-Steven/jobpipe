from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .company_filters import CompanyTreatment, company_treatment, normalize_company_name
from .private_home import PrivateHome


@dataclass(frozen=True)
class CompanyPreferences:
    enabled: bool = False
    builtin_enabled: bool = True
    blocked: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.builtin_enabled) is not bool:
            raise ValueError("company filter switches must be booleans")
        for group in (self.blocked, self.allowed):
            if not isinstance(group, tuple):
                raise ValueError("company names must be tuples")
            names = [normalize_company_name(name) for name in group]
            if not all(names) or len(names) != len(set(names)):
                raise ValueError("company names must be nonempty and unique")
        if set(map(normalize_company_name, self.blocked)) & set(
            map(normalize_company_name, self.allowed)
        ):
            raise ValueError("a company cannot be both blocked and allowed")

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "enabled": self.enabled,
            "builtin_enabled": self.builtin_enabled,
            "blocked": list(self.blocked),
            "allowed": list(self.allowed),
        }


class PrivateCompanyPreferences:
    def __init__(
        self, home: PrivateHome | None = None, *, subject_id: str | None = None
    ) -> None:
        self.home = home or PrivateHome.discover()
        if subject_id is not None and (
            not isinstance(subject_id, str)
            or not subject_id.strip()
            or len(subject_id) > 160
        ):
            raise ValueError("invalid company preferences subject")
        self.subject_id = subject_id

    @property
    def path(self) -> Path:
        if self.subject_id is None:
            return self.home.paths.state / "company-preferences.json"
        key = hashlib.sha256(self.subject_id.encode("utf-8")).hexdigest()
        return self.home.paths.state / f"company-preferences-{key}.json"

    def read(self) -> CompanyPreferences:
        path = self.path
        if path.is_symlink():
            raise ValueError("company preferences cannot be a symlink")
        if not path.exists():
            return CompanyPreferences()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {
            "schema_version", "enabled", "builtin_enabled", "blocked", "allowed"
        } or data["schema_version"] != 1:
            raise ValueError("invalid company preference schema")
        if not isinstance(data["blocked"], list) or not isinstance(data["allowed"], list):
            raise ValueError("company preference entries must be lists")
        if not all(isinstance(item, str) for item in data["blocked"] + data["allowed"]):
            raise ValueError("company preference names must be strings")
        return CompanyPreferences(
            enabled=data["enabled"],
            builtin_enabled=data["builtin_enabled"],
            blocked=tuple(data["blocked"]),
            allowed=tuple(data["allowed"]),
        )

    def write(self, prefs: CompanyPreferences) -> None:
        if not isinstance(prefs, CompanyPreferences):
            raise TypeError("expected CompanyPreferences")
        self.home.ensure()
        path = self.path
        if path.is_symlink():
            raise ValueError("company preferences cannot be a symlink")
        descriptor, name = tempfile.mkstemp(prefix=".company-preferences.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(prefs.to_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def set_enabled(self, enabled: bool) -> CompanyPreferences:
        from dataclasses import replace

        updated = replace(self.read(), enabled=enabled)
        self.write(updated)
        return updated

    def set_builtin_enabled(self, enabled: bool) -> CompanyPreferences:
        from dataclasses import replace

        updated = replace(self.read(), builtin_enabled=enabled)
        self.write(updated)
        return updated

    def edit(self, action: str, name: str) -> CompanyPreferences:
        from dataclasses import replace

        key = normalize_company_name(name)
        if not key:
            raise ValueError("company name is empty")
        current = self.read()
        blocked = [x for x in current.blocked if normalize_company_name(x) != key]
        allowed = [x for x in current.allowed if normalize_company_name(x) != key]
        if action == "block":
            blocked.append(name.strip())
        elif action == "allow":
            allowed.append(name.strip())
        elif action != "clear":
            raise ValueError("unsupported company preference action")
        updated = replace(current, blocked=tuple(blocked), allowed=tuple(allowed))
        self.write(updated)
        return updated


def effective_company_treatment(
    company: str,
    *,
    additional_blocked: tuple[str, ...] | list[str] = (),
    preferences: CompanyPreferences | None = None,
    subject_id: str | None = None,
) -> CompanyTreatment:
    prefs = (
        preferences
        if preferences is not None
        else PrivateCompanyPreferences(subject_id=subject_id).read()
    )
    if not prefs.enabled:
        return CompanyTreatment.ALLOW
    normalized = normalize_company_name(company)
    if not normalized:
        return CompanyTreatment.REVIEW
    if normalized in {normalize_company_name(value) for value in prefs.allowed}:
        return CompanyTreatment.ALLOW
    if normalized in {normalize_company_name(value) for value in prefs.blocked}:
        return CompanyTreatment.BLOCK
    for value in additional_blocked:
        if normalized == normalize_company_name(value):
            return CompanyTreatment.BLOCK
    if prefs.builtin_enabled:
        return company_treatment(company)
    return CompanyTreatment.ALLOW
