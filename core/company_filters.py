from __future__ import annotations

import json
import re
import unicodedata
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Iterable


class CompanyTreatment(StrEnum):
    BLOCK = "BLOCK"
    DEPRIORITIZE = "DEPRIORITIZE"
    REVIEW = "REVIEW"
    ALLOW = "ALLOW"


def normalize_company_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("company name must be a string")
    return " ".join(
        re.findall(r"[^\\W_]+", unicodedata.normalize("NFKC", value).casefold())
    )


@lru_cache(maxsize=1)
def _built_in_rules() -> dict[str, CompanyTreatment]:
    path = Path(__file__).resolve().parent.parent / "config" / "company_filters.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "blocked", "deprioritize", "review"
    } or data["schema_version"] != 1:
        raise ValueError("unsupported company filter registry")
    rules: dict[str, CompanyTreatment] = {}
    for key, treatment in (
        ("blocked", CompanyTreatment.BLOCK),
        ("deprioritize", CompanyTreatment.DEPRIORITIZE),
        ("review", CompanyTreatment.REVIEW),
    ):
        records = data[key]
        if not isinstance(records, list):
            raise ValueError("company filter entries must be a list")
        for record in records:
            if not isinstance(record, dict) or set(record) - {"name", "aliases"}:
                raise ValueError("company filter entry is invalid")
            aliases = record.get("aliases", [])
            if not isinstance(aliases, list):
                raise ValueError("company aliases must be a list")
            for name in [record.get("name"), *aliases]:
                normalized = normalize_company_name(name)
                if not normalized or normalized in rules:
                    raise ValueError("company filter names must be unique and non-empty")
                rules[normalized] = treatment
    return rules


def company_treatment(
    company: str,
    *,
    additional_blocked: Iterable[str] = (),
) -> CompanyTreatment:
    normalized = normalize_company_name(company)
    if not normalized:
        return CompanyTreatment.REVIEW
    if isinstance(additional_blocked, str):
        raise TypeError("additional_blocked must contain company names")
    for name in additional_blocked:
        if normalize_company_name(name) == normalized:
            return CompanyTreatment.BLOCK
    return _built_in_rules().get(normalized, CompanyTreatment.ALLOW)
