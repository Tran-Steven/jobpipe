"""Provider-budget guard: blocked search profiles never consume network queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.company_preferences import PrivateCompanyPreferences
from core.job_library_refresh import (
    JobLibraryRefreshStatus,
    ProfileRefreshFailureReason,
    ProfileRefreshSearchStatus,
    PrivateHomeJobLibraryRefreshRunRepository,
    refresh_job_library,
)
from core.private_home import PrivateHome
from core.search_profile import PrivateHomeSearchProfileRepository
from tests.test_application_plan import SUBJECT
from tests.test_job_library_refresh import (
    _candidate,
    _command,
    _profile,
    _search_result,
    _Discovery,
    _Priority,
    _ProfileProvider,
    _Reader,
    _SearchExecutor,
)

URL = "https://job-boards.greenhouse.io/example/jobs/1001"


def _prefs(home: PrivateHome, *, enabled: bool) -> PrivateCompanyPreferences:
    preferences = PrivateCompanyPreferences(home, subject_id=SUBJECT)
    preferences.edit("block", "Blocked Firm")
    if enabled:
        preferences.set_enabled(True)
    return preferences


async def _refresh(home, executor, reader, discovery, priority, *, invocation):
    return await refresh_job_library(
        _command(invocation),
        profile_provider=_ProfileProvider(PrivateHomeSearchProfileRepository(home)),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=priority,
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
        preferences_home=home,
    )


@pytest.mark.asyncio
async def test_blocked_profile_does_not_use_network_or_distort_success(tmp_path: Path):
    home = PrivateHome(tmp_path / "home")
    blocked = _profile(home, "Blocked Firm", "blockedfirm")
    allowed = _profile(home, "Allowed Firm", "allowedfirm")
    _prefs(home, enabled=True)
    executor = _SearchExecutor({
        allowed.profile_id: _search_result(
            allowed, (_candidate(allowed, "safe-1", URL),)
        ),
    })
    reader, discovery, priority = _Reader(), _Discovery(), _Priority()
    result = await _refresh(
        home, executor, reader, discovery, priority, invocation="profile-mixed",
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert executor.calls == [allowed.profile_id]
    assert reader.calls == [URL]
    assert len(discovery.calls) == 1
    assert len(priority.calls) == 1
    entries = {p.profile_id: p for p in result.run.profile_results}
    skipped = entries[blocked.profile_id]
    assert skipped.search_status is ProfileRefreshSearchStatus.SKIPPED
    assert skipped.reason is ProfileRefreshFailureReason.COMPANY_BLOCKED
    assert skipped.source_reason == "COMPANY_BLOCKED"
    assert skipped.candidate_count == 0
    assert entries[allowed.profile_id].search_status is ProfileRefreshSearchStatus.SUCCEEDED
    assert result.run.discovery_summary.unique_candidates == 1


@pytest.mark.asyncio
async def test_all_blocked_profiles_are_truthful_noop_without_provider_or_priority(tmp_path: Path):
    home = PrivateHome(tmp_path / "home")
    blocked = _profile(home, "Blocked Firm", "blockedfirm")
    _prefs(home, enabled=True)
    executor, reader, discovery, priority = _SearchExecutor({}), _Reader(), _Discovery(), _Priority()
    result = await _refresh(
        home, executor, reader, discovery, priority, invocation="profile-noop",
    )
    assert result.status is JobLibraryRefreshStatus.NOOP
    assert result.run.overall_status is JobLibraryRefreshStatus.NOOP
    assert result.run.profile_results[0].search_status is ProfileRefreshSearchStatus.SKIPPED
    assert not executor.calls and not reader.calls and not discovery.calls
    assert not priority.calls
    replay = await _refresh(
        home, executor, reader, discovery, priority, invocation="profile-noop",
    )
    assert replay.status is JobLibraryRefreshStatus.UNCHANGED
    assert replay.run.run_hash == result.run.run_hash
    assert not executor.calls and not priority.calls


@pytest.mark.asyncio
async def test_filter_disabled_preserves_saved_rules_without_skipping_queries(tmp_path: Path):
    home = PrivateHome(tmp_path / "home")
    blocked = _profile(home, "Blocked Firm", "blockedfirm")
    prefs = _prefs(home, enabled=False)
    assert prefs.read().enabled is False
    executor = _SearchExecutor({
        blocked.profile_id: _search_result(blocked, (_candidate(blocked, "b-1", URL),)),
    })
    reader, discovery, priority = _Reader(), _Discovery(), _Priority()
    result = await _refresh(
        home, executor, reader, discovery, priority, invocation="profile-disabled",
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert executor.calls == [blocked.profile_id]
    assert result.run.profile_results[0].search_status is ProfileRefreshSearchStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_unreadable_company_preferences_fail_closed_before_network(tmp_path: Path):
    home = PrivateHome(tmp_path / "home")
    _profile(home, "Blocked Firm", "blockedfirm")
    prefs = PrivateCompanyPreferences(home, subject_id=SUBJECT)
    prefs.path.parent.mkdir(parents=True, exist_ok=True)
    prefs.path.write_text("untrusted-corrupt-settings", encoding="utf-8")
    executor, reader, discovery, priority = _SearchExecutor({}), _Reader(), _Discovery(), _Priority()
    result = await _refresh(
        home, executor, reader, discovery, priority, invocation="profile-fail-closed",
    )
    assert result.status is JobLibraryRefreshStatus.FAILED
    failed = result.run.profile_results[0]
    assert failed.search_status is ProfileRefreshSearchStatus.FAILED
    assert failed.source_reason == "COMPANY_PREFERENCES_UNAVAILABLE"
    assert not executor.calls and not reader.calls and not discovery.calls
    assert not priority.calls


@pytest.mark.asyncio
async def test_symlink_preferences_are_not_bypassed_for_search(tmp_path: Path):
    home = PrivateHome(tmp_path / "home")
    _profile(home, "Blocked Firm", "blockedfirm")
    prefs = PrivateCompanyPreferences(home, subject_id=SUBJECT)
    prefs.path.symlink_to(tmp_path / "missing.json")
    executor = _SearchExecutor({})
    priority = _Priority()
    result = await _refresh(
        home, executor, _Reader(), _Discovery(), priority,
        invocation="profile-symlink-guard",
    )
    assert result.status is JobLibraryRefreshStatus.FAILED
    assert result.run.profile_results[0].source_reason == "COMPANY_PREFERENCES_UNAVAILABLE"
    assert not executor.calls and not priority.calls
