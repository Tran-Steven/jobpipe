"""Fail-closed loading of tier-specific application materials from Private Home."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .bundles import JobSpec, MaterialBundle, file_sha256
from .event_ledger import hash_job_url
from .policy import CoverLetterStrategy, JobTier, MaterialStrategy, PolicyDecision
from .private_home import PrivateHome, PrivateHomeError


MATERIAL_MANIFEST_SCHEMA_VERSION = 1


class MaterialValidationError(RuntimeError):
    """Raised before browser launch when required material attestations are absent."""


@dataclass(frozen=True, slots=True)
class MaterialManifest:
    path: Path
    document: Mapping[str, Any]
    resume_path: Path
    cover_letter_path: Path | None


def materialize_existing_resume(
    *,
    home: PrivateHome,
    resume_path: str | Path,
    subject_id: str,
    job_id: str,
) -> Path:
    source = home.contained_path(Path(resume_path).expanduser())
    if source.is_symlink() or not source.is_file():
        raise MaterialValidationError("existing resume is missing or unsafe")
    content = source.read_bytes()
    if not content.startswith(b"%PDF-"):
        raise MaterialValidationError("existing resume must be a PDF")
    normalized_subject = str(subject_id or "").strip()
    normalized_job = str(job_id or "").strip()
    if not normalized_subject or not normalized_job:
        raise MaterialValidationError("managed existing resume requires subject and job identity")
    subject_key = (
        "subject-"
        + hashlib.sha256(normalized_subject.encode("utf-8")).hexdigest()
    )
    digest = hashlib.sha256(content).hexdigest()
    target = (
        home.paths.preparation
        / "route-existing"
        / subject_key
        / normalized_job
        / f"resume-{digest}.pdf"
    )
    home.write_bytes_if_absent(target, content)
    resolved = home.contained_path(target)
    if (
        resolved.is_symlink()
        or not resolved.is_file()
        or file_sha256(resolved) != digest
    ):
        raise MaterialValidationError("managed existing resume failed integrity verification")
    return resolved


def _nonempty_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _private_artifact(home: PrivateHome, job_dir: Path, value: Any) -> Path:
    raw = Path(str(value or ""))
    if not str(raw):
        raise MaterialValidationError("material manifest contains an empty artifact path")
    candidate = raw if raw.is_absolute() else job_dir / raw
    try:
        resolved = home.contained_path(candidate)
    except PrivateHomeError as exc:
        raise MaterialValidationError("material artifact must remain inside Private Home") from exc
    try:
        resolved.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise MaterialValidationError(
            "customized material must live in its job-specific generated directory"
        ) from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise MaterialValidationError("material artifact is missing or unsafe")
    return resolved


def load_material_manifest(home: PrivateHome, job: JobSpec) -> MaterialManifest:
    job_dir = home.paths.generated_documents / job.job_id
    path = home.contained_path(job_dir / "manifest.json")
    if not path.is_file() or path.is_symlink():
        raise MaterialValidationError(
            f"tier {job.tier.value} requires a private material manifest for {job.job_id}"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterialValidationError("private material manifest is invalid") from exc
    if not isinstance(document, Mapping):
        raise MaterialValidationError("private material manifest must be an object")
    if int(document.get("schema_version", 0)) != MATERIAL_MANIFEST_SCHEMA_VERSION:
        raise MaterialValidationError("unsupported private material manifest schema")
    if document.get("job_id") != job.job_id or document.get("tier") != job.tier.value:
        raise MaterialValidationError("material manifest is bound to another job or tier")
    if document.get("job_url_hash") != hash_job_url(job.url):
        raise MaterialValidationError("material manifest URL binding does not match this job")

    resume_path = _private_artifact(home, job_dir, document.get("resume_path"))
    if document.get("resume_sha256") != file_sha256(resume_path):
        raise MaterialValidationError("resume content differs from its material attestation")
    cover_path: Path | None = None
    if document.get("cover_letter_path"):
        cover_path = _private_artifact(home, job_dir, document["cover_letter_path"])
        if document.get("cover_letter_sha256") != file_sha256(cover_path):
            raise MaterialValidationError(
                "cover letter content differs from its material attestation"
            )
    return MaterialManifest(path, document, resume_path, cover_path)


def build_tier_materials(
    *,
    home: PrivateHome,
    job: JobSpec,
    policy: PolicyDecision,
    fallback_resume: Path,
) -> MaterialBundle:
    """Load policy-compliant artifacts, blocking before browser use on any gap."""

    if policy.material_strategy is MaterialStrategy.ROUTE_EXISTING:
        return MaterialBundle.build(
            resume_path=fallback_resume,
            metadata={
                "source": "private_csv_queue",
                "tier": job.tier.value,
                "quality_attestation": "route_existing",
            },
        )

    manifest = load_material_manifest(home, job)
    document = manifest.document
    if document.get("facts_verified") is not True:
        raise MaterialValidationError("customized materials lack a verified-facts attestation")
    if document.get("job_specific") is not True:
        raise MaterialValidationError("customized resume is not attested as job-specific")

    qa = document.get("resume_visual_qa")
    if (
        not isinstance(qa, Mapping)
        or qa.get("passed") is not True
        or qa.get("artifact_sha256") != file_sha256(manifest.resume_path)
        or not _nonempty_timestamp(qa.get("checked_at"))
    ):
        raise MaterialValidationError("customized resume has no valid visual-QA attestation")

    if policy.material_strategy is MaterialStrategy.BESPOKE and document.get("bespoke") is not True:
        raise MaterialValidationError("High-tier resume is not attested as bespoke")
    if policy.material_strategy is MaterialStrategy.TARGETED and document.get("targeted") is not True:
        raise MaterialValidationError("Medium-tier resume is not attested as targeted")

    cover_letter = ""
    if policy.cover_letter_strategy in {
        CoverLetterStrategy.NARRATIVE,
        CoverLetterStrategy.TARGETED,
    }:
        if manifest.cover_letter_path is None:
            raise MaterialValidationError("this tier requires a job-specific cover letter")
        cover_letter = manifest.cover_letter_path.read_text(encoding="utf-8").strip()
        if not cover_letter:
            raise MaterialValidationError("job-specific cover letter is empty")
        if document.get("cover_letter_job_specific") is not True:
            raise MaterialValidationError("cover letter is not attested as job-specific")
    if (
        policy.cover_letter_strategy is CoverLetterStrategy.NARRATIVE
        and document.get("narrative_alignment") is not True
    ):
        raise MaterialValidationError(
            "High-tier cover letter lacks a narrative company/role alignment attestation"
        )

    return MaterialBundle.build(
        resume_path=manifest.resume_path,
        cover_letter=cover_letter,
        metadata={
            "source": "private_material_manifest",
            "tier": job.tier.value,
            "manifest_sha256": file_sha256(manifest.path),
            "visual_qa": True,
            "facts_verified": True,
        },
    )


__all__ = [
    "MATERIAL_MANIFEST_SCHEMA_VERSION",
    "MaterialManifest",
    "MaterialValidationError",
    "build_tier_materials",
    "load_material_manifest",
    "materialize_existing_resume",
]
