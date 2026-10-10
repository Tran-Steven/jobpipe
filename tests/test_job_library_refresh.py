"""Focused S3b Manual Full Job Library Refresh tests."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

from core.job_discovery import (
    DiscoveryChange,
    DiscoveryDisposition,
    DiscoveryReason,
    DiscoveryTrigger,
    JobDiscoveryResponse,
    JobIntakeIntent,
)
from core.job_library_refresh import (
    CandidateDiscoveryStatus,
    CandidateRefreshReason,
    CandidateMembershipStatus,
    JobLibraryRefreshStatus,
    ManualJobLibraryRefreshCommand,
    PrivateHomeJobLibraryRefreshRunRepository,
    refresh_job_library,
)
from core.job_search import (
    CandidateSet,
    JobSearchReason,
    JobSearchResult,
    SearchCandidate,
)
from core.private_home import PrivateHome
from core.search_profile import (
    PrivateHomeSearchProfileRepository,
    SaveSearchProfileCommand,
    SearchProfileSourceKind,
    SearchProfileSourceReference,
    save_search_profile,
)
from core.selective_reprioritization import (
    SelectiveBatchOverallStatus,
    SelectiveBatchReprioritizationResult,
    SelectiveBatchSummary,
)
from core.subject_job_discovery import (
    SubjectJobDiscoveryResult,
    SubjectJobDiscoveryStatus,
)
from core.subject_job_library import (
    RegisterSubjectJobMembershipStatus,
    SubjectJobLibraryMembership,
)
from source_connectors.contract import (
    AtsType,
    FieldProvenance,
    ProvenanceSource,
    ReadJobReason,
    ReadJobResult,
    SourceJobObservation,
    SourcePlatform,
    WorkMode,
)
from tests.test_application_plan import NOW, SUBJECT


def _raw(cls, **values):
    instance = object.__new__(cls)
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    return instance


def _profile(home, name, board):
    result = save_search_profile(
        SaveSearchProfileCommand(
            subject_id=SUBJECT,
            display_name=name,
            company=name,
            title="Engineer",
            source=SearchProfileSourceReference(
                SearchProfileSourceKind.KNOWN_GREENHOUSE_BOARD,
                board,
            ),
            enabled=True,
            now=NOW,
        ),
        repository=PrivateHomeSearchProfileRepository(home),
    )
    return result.profile


def _candidate(profile, candidate_id, url):
    return SearchCandidate(
        candidate_id=candidate_id,
        company=profile.search_request.company,
        title="Engineer",
        location=None,
        source_platform=SourcePlatform.GREENHOUSE,
        source_url=url,
        source_job_id=candidate_id,
    )


def _search_result(profile, candidates):
    return JobSearchResult.succeeded(
        CandidateSet(
            candidate_set_id=(
                f"candidate-set-{profile.profile_version}-"
                f"{profile.profile_id}"
            ),
            request_id=profile.search_request.request_id,
            candidates=tuple(candidates),
            created_at=NOW,
        )
    )


def _observation(url):
    return SourceJobObservation(
        source_platform=SourcePlatform.GREENHOUSE,
        source_job_id=url.rstrip("/").split("/")[-1].split("#")[0],
        source_url=url,
        application_url=url,
        company="Example Labs",
        title="Engineer",
        description="Build synthetic systems.",
        location="Remote",
        work_mode=WorkMode.REMOTE,
        posted_at=None,
        ats_type=AtsType.GREENHOUSE,
        observed_at=NOW.isoformat(),
        provenance=(
            FieldProvenance(
                field="title",
                source=ProvenanceSource.SOURCE_API,
                source_field="title",
            ),
        ),
    )


def _priority(status="COMPLETED", *, failed=0):
    summary = SelectiveBatchSummary(
        requested=1,
        selected=1,
        created=1 - failed,
        unchanged=0,
        skipped_current=0,
        skipped_incomplete=0,
        not_found=0,
        failed=failed,
    )
    return _raw(
        SelectiveBatchReprioritizationResult,
        overall_status=SelectiveBatchOverallStatus(status),
        summary=summary,
        subject_id=SUBJECT,
        now=NOW,
    )


class _ProfileProvider:
    def __init__(self, repository):
        self.repository = repository
        self.calls = 0

    def list_enabled(self, subject_id):
        self.calls += 1
        return self.repository.list_enabled(subject_id)


class _SearchExecutor:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def search(self, profile):
        self.calls.append(profile.profile_id)
        result = self.results[profile.profile_id]
        if isinstance(result, Exception):
            raise result
        return result


class _Reader:
    def __init__(self, failures=()):
        self.failures = set(failures)
        self.calls = []

    async def __call__(self, request):
        self.calls.append(request.url)
        if request.url in self.failures:
            return ReadJobResult.failed(ReadJobReason.SOURCE_UNAVAILABLE)
        return ReadJobResult.succeeded(_observation(request.url))


class _Discovery:
    def __init__(self, failed_urls=()):
        self.failed_urls = set(failed_urls)
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        url = request.request.proposal.resolved_candidate.source_url
        if url in self.failed_urls:
            response = JobDiscoveryResponse(
                disposition=DiscoveryDisposition.REJECTED,
                original_intent=JobIntakeIntent.ADD_JOB,
                reason_code=DiscoveryReason.PROPOSAL_UNSUPPORTED,
            )
            return SubjectJobDiscoveryResult(
                SubjectJobDiscoveryStatus.NOT_ACCEPTED,
                response,
                None,
                None,
            )
        response = JobDiscoveryResponse(
                disposition=DiscoveryDisposition.ACCEPTED,
                original_intent=JobIntakeIntent.ADD_JOB,
                reason_code=DiscoveryReason.JOB_CREATED,
                run_id=f"discovery-{len(self.calls)}",
                job_id=f"job-{len(self.calls)}",
            change=DiscoveryChange.CREATED,
        )
        membership = SubjectJobLibraryMembership.create(
            subject_id=request.subject_id,
            job_id=response.job_id,
            first_discovery_run_id=response.run_id,
            first_discovery_run_hash="a" * 64,
            first_job_revision_id=f"{response.job_id}:revision:1",
            first_job_revision_hash="b" * 64,
            source_kind=request.source_kind,
            source_ref=request.source_ref,
            created_at=request.now,
            invocation_id=request.invocation_id,
        )
        return SubjectJobDiscoveryResult(
            SubjectJobDiscoveryStatus.ACCEPTED,
            response,
            membership,
            RegisterSubjectJobMembershipStatus.CREATED,
        )


class _Priority:
    def __init__(self, result=None):
        self.result = result or _priority()
        self.calls = []

    async def __call__(self, command):
        self.calls.append(command)
        return self.result


def _command(invocation="refresh-001"):
    return ManualJobLibraryRefreshCommand(
        subject_id=SUBJECT,
        invocation_id=invocation,
        now=NOW,
        max_reprioritizations=5,
    )


@pytest.mark.asyncio
async def test_profiles_search_once_and_duplicate_url_reads_discovers_once(
    tmp_path,
):
    home = PrivateHome(tmp_path)
    first = _profile(home, "Alpha", "alpha")
    second = _profile(home, "Beta", "beta")
    url = "https://job-boards.greenhouse.io/example/jobs/1001"
    executor = _SearchExecutor(
        {
            first.profile_id: _search_result(
                first, (_candidate(first, "a-1", url),)
            ),
            second.profile_id: _search_result(
                second, (_candidate(second, "b-1", f"{url}#details"),)
            ),
        }
    )
    reader = _Reader()
    discovery = _Discovery()
    priority = _Priority()
    repository = PrivateHomeJobLibraryRefreshRunRepository(home)

    result = await refresh_job_library(
        _command(),
        profile_provider=_ProfileProvider(
            PrivateHomeSearchProfileRepository(home)
        ),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=priority,
        repository=repository,
    )

    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert len(executor.calls) == 2
    assert reader.calls == [url]
    assert len(discovery.calls) == 1
    assert discovery.calls[0].subject_id == SUBJECT
    assert discovery.calls[0].request.trigger is (
        DiscoveryTrigger.MANUAL_LIBRARY_REFRESH
    )
    assert (
        discovery.calls[0].request.proposal.intent
        is JobIntakeIntent.ADD_JOB
    )
    assert result.run.candidate_results[0].source_profile_ids == (
        first.profile_id,
        second.profile_id,
    )
    assert (
        result.run.candidate_results[0].membership_status
        is CandidateMembershipStatus.CREATED
    )
    assert result.run.candidate_results[0].membership_id is not None
    persisted = repository.get_by_invocation(SUBJECT, "refresh-001")
    assert (
        persisted.run.candidate_results[0].membership_id
        == result.run.candidate_results[0].membership_id
    )
    assert len(priority.calls) == 1
    assert priority.calls[0].subject_id == SUBJECT
    assert priority.calls[0].now == NOW
    assert priority.calls[0].max_jobs == 5


@pytest.mark.asyncio
async def test_profile_reader_discovery_failures_are_isolated_then_priority_runs(
    tmp_path,
):
    home = PrivateHome(tmp_path)
    profiles = tuple(
        _profile(home, name, name.casefold())
        for name in ("A", "B", "C", "D")
    )
    urls = tuple(
        f"https://job-boards.greenhouse.io/example/jobs/{index}"
        for index in range(1, 4)
    )
    executor = _SearchExecutor(
        {
            profiles[0].profile_id: RuntimeError("synthetic search failure"),
            profiles[1].profile_id: _search_result(
                profiles[1], (_candidate(profiles[1], "b", urls[0]),)
            ),
            profiles[2].profile_id: _search_result(
                profiles[2], (_candidate(profiles[2], "c", urls[1]),)
            ),
            profiles[3].profile_id: _search_result(
                profiles[3], (_candidate(profiles[3], "d", urls[2]),)
            ),
        }
    )
    reader = _Reader(failures=(urls[0],))
    discovery = _Discovery(failed_urls=(urls[1],))
    priority = _Priority()

    result = await refresh_job_library(
        _command("refresh-partial"),
        profile_provider=_ProfileProvider(
            PrivateHomeSearchProfileRepository(home)
        ),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=priority,
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )

    assert result.status is JobLibraryRefreshStatus.PARTIAL_FAILURE
    assert len(executor.calls) == 4
    assert len(reader.calls) == 3
    assert len(discovery.calls) == 2
    assert len(priority.calls) == 1
    assert result.run.discovery_summary.created == 1
    assert result.run.discovery_summary.failed == 2


@pytest.mark.asyncio
async def test_no_profiles_is_noop_and_invocation_replay_calls_nothing(
    tmp_path,
):
    home = PrivateHome(tmp_path)
    provider = _ProfileProvider(PrivateHomeSearchProfileRepository(home))
    executor = _SearchExecutor({})
    reader = _Reader()
    discovery = _Discovery()
    priority = _Priority()
    repository = PrivateHomeJobLibraryRefreshRunRepository(home)
    first = await refresh_job_library(
        _command("refresh-noop"),
        profile_provider=provider,
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=priority,
        repository=repository,
    )
    forbidden_provider = _ProfileProvider(
        PrivateHomeSearchProfileRepository(home)
    )
    replay = await refresh_job_library(
        _command("refresh-noop"),
        profile_provider=forbidden_provider,
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=priority,
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )

    assert first.status is JobLibraryRefreshStatus.NOOP
    assert replay.status is JobLibraryRefreshStatus.UNCHANGED
    assert provider.calls == 1
    assert forbidden_provider.calls == 0
    assert executor.calls == []
    assert reader.calls == []
    assert discovery.calls == []
    assert priority.calls == []


@pytest.mark.asyncio
async def test_all_search_failure_is_failed_and_boundary_has_no_application_flow(
    tmp_path,
):
    home = PrivateHome(tmp_path)
    profile = _profile(home, "Only", "only")
    priority = _Priority()
    result = await refresh_job_library(
        _command("refresh-failed"),
        profile_provider=_ProfileProvider(
            PrivateHomeSearchProfileRepository(home)
        ),
        search_executor=_SearchExecutor(
            {profile.profile_id: RuntimeError("synthetic failure")}
        ),
        public_job_reader=_Reader(),
        discovery=_Discovery(),
        priority_refresh=priority,
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )

    assert result.status is JobLibraryRefreshStatus.FAILED
    assert len(priority.calls) == 1
    source = Path("core/job_library_refresh.py").read_text(encoding="utf-8")
    for forbidden in (
        "application_plan",
        "selective_batch_preparation",
        "selective_batch_execution",
        "automation_cycle",
        "greenhouse_board",
        "Browser",
        "submit",
        "EXPIRED",
    ):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_blocked_employer_is_skipped_before_public_read(tmp_path, monkeypatch) -> None:
    from core.company_preferences import CompanyPreferences, effective_company_treatment
    import core.job_library_refresh as target_module

    monkeypatch.setattr(
        target_module,
        "effective_company_treatment",
        lambda company, **kwargs: effective_company_treatment(
            company, preferences=CompanyPreferences(enabled=True), **kwargs
        ),
    )
    home = PrivateHome(tmp_path)
    profile = _profile(home, "Jobgether", "jobgether")
    url = "https://job-boards.greenhouse.io/jobgether/jobs/1024"
    executor = _SearchExecutor({
        profile.profile_id: _search_result(
            profile, (_candidate(profile, "blocked-1", url),)
        ),
    })
    reader = _Reader()
    discovery = _Discovery()
    result = await refresh_job_library(
        _command("refresh-company-blocked"),
        profile_provider=_ProfileProvider(PrivateHomeSearchProfileRepository(home)),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=_Priority(),
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert reader.calls == []
    assert discovery.calls == []
    assert result.run.candidate_results[0].reason is CandidateRefreshReason.BLOCKED_COMPANY
    assert result.run.candidate_results[0].discovery_status is CandidateDiscoveryStatus.SKIPPED


@pytest.mark.asyncio
async def test_blocked_employer_from_public_read_is_not_imported(tmp_path, monkeypatch) -> None:
    from core.company_preferences import CompanyPreferences, effective_company_treatment
    import core.job_library_refresh as target_module

    monkeypatch.setattr(
        target_module,
        "effective_company_treatment",
        lambda company, **kwargs: effective_company_treatment(
            company, preferences=CompanyPreferences(enabled=True), **kwargs
        ),
    )
    home = PrivateHome(tmp_path)
    profile = _profile(home, "Example Labs", "examplelabs")
    url = "https://job-boards.greenhouse.io/examplelabs/jobs/1025"
    executor = _SearchExecutor({
        profile.profile_id: _search_result(
            profile, (_candidate(profile, "blocked-2", url),)
        ),
    })

    class _BlockedReader(_Reader):
        async def __call__(self, request):
            self.calls.append(request.url)
            return ReadJobResult.succeeded(
                replace(_observation(request.url), company="SynergisticIT")
            )

    reader = _BlockedReader()
    discovery = _Discovery()
    result = await refresh_job_library(
        _command("refresh-source-company-blocked"),
        profile_provider=_ProfileProvider(PrivateHomeSearchProfileRepository(home)),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=_Priority(),
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert reader.calls == [url]
    assert discovery.calls == []
    assert result.run.candidate_results[0].reason is CandidateRefreshReason.BLOCKED_COMPANY


@pytest.mark.asyncio
async def test_risky_public_posting_requires_review_before_discovery(tmp_path) -> None:
    home = PrivateHome(tmp_path)
    profile = _profile(home, "Synthetic Company", "synthetic")
    url = "https://job-boards.greenhouse.io/synthetic/jobs/10126"
    executor = _SearchExecutor({
        profile.profile_id: _search_result(
            profile, (_candidate(profile, "risk-1", url),)
        ),
    })

    class _RiskyReader(_Reader):
        async def __call__(self, request):
            self.calls.append(request.url)
            return ReadJobResult.succeeded(
                replace(
                    _observation(request.url),
                    description="Applicants must pay a $250 application fee.",
                )
            )

    reader = _RiskyReader()
    discovery = _Discovery()
    priority = _Priority()
    result = await refresh_job_library(
        _command("refresh-risk-review"),
        profile_provider=_ProfileProvider(
            PrivateHomeSearchProfileRepository(home)
        ),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=priority,
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert reader.calls == [url]
    assert discovery.calls == []
    assert result.run.discovery_summary.skipped == 1
    assert result.run.discovery_summary.failed == 0
    assert result.run.candidate_results[0].reason is CandidateRefreshReason.QUALITY_REVIEW_REQUIRED
    assert "candidate_payment_request" in result.run.candidate_results[0].source_reason


@pytest.mark.asyncio
async def test_definitively_closed_employer_posting_is_skipped_not_retried(
    tmp_path,
) -> None:
    home = PrivateHome(tmp_path)
    profile = _profile(home, "Example Labs", "examplelabs")
    url = "https://job-boards.greenhouse.io/example/jobs/88881"
    executor = _SearchExecutor({
        profile.profile_id: _search_result(
            profile, (_candidate(profile, "closed-1", url),)
        ),
    })

    class _ClosedReader(_Reader):
        async def __call__(self, request):
            self.calls.append(request.url)
            return ReadJobResult.failed(ReadJobReason.JOB_CLOSED)

    reader = _ClosedReader()
    discovery = _Discovery()
    result = await refresh_job_library(
        _command("refresh-closed"),
        profile_provider=_ProfileProvider(PrivateHomeSearchProfileRepository(home)),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=_Priority(),
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert reader.calls == [url]
    assert discovery.calls == []
    assert result.run.discovery_summary.skipped == 1
    assert result.run.discovery_summary.failed == 0
    assert result.run.candidate_results[0].reason is CandidateRefreshReason.POSTING_CLOSED


@pytest.mark.asyncio
async def test_cross_site_alias_requires_live_employer_read_and_only_one_discovery(
    tmp_path,
) -> None:
    home = PrivateHome(tmp_path)
    first = _profile(home, "One", "one")
    second = _profile(home, "Two", "two")
    external = "https://www.linkedin.com/jobs/view/1234567890"
    employer = "https://job-boards.greenhouse.io/example/jobs/1001"
    executor = _SearchExecutor({
        first.profile_id: _search_result(
            first, (_candidate(first, "linkedin-1", external),)
        ),
        second.profile_id: _search_result(
            second, (_candidate(second, "greenhouse-1", employer),)
        ),
    })

    class _AliasReader(_Reader):
        async def __call__(self, request):
            self.calls.append(request.url)
            if request.url == external:
                return ReadJobResult.succeeded(
                    replace(
                        _observation(external),
                        source_platform=SourcePlatform.GENERIC_WEB,
                        ats_type=AtsType.UNKNOWN,
                        application_url=employer,
                    )
                )
            return ReadJobResult.succeeded(_observation(employer))

    reader = _AliasReader()
    discovery = _Discovery()
    result = await refresh_job_library(
        _command("refresh-alias"),
        profile_provider=_ProfileProvider(PrivateHomeSearchProfileRepository(home)),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=_Priority(),
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
        preferences_home=home,
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert reader.calls == [external, employer]  # employer evidence reused
    assert len(discovery.calls) == 1
    assert discovery.calls[0].request.proposal.resolved_candidate.source_url == employer
    assert result.run.discovery_summary.skipped == 1
    assert result.run.candidate_results[1].reason is CandidateRefreshReason.DUPLICATE_VERIFIED_POSTING
    # Unlike an in-memory dedup table, this survives a new refresh/process.
    from core.verified_posting_aliases import VerifiedPostingAliases
    from core.event_ledger import hash_job_url
    aliases = VerifiedPostingAliases(home)
    assert hash_job_url(external) in aliases.identity_hashes(employer)
    assert hash_job_url(employer) in aliases.identity_hashes(external)
    assert aliases.path.stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "employer_state, expected_reason",
    [
        ("CLOSED", CandidateRefreshReason.POSTING_CLOSED),
        ("UNAVAILABLE", CandidateRefreshReason.POSTING_VERIFICATION_INCONCLUSIVE),
        ("MISMATCH", CandidateRefreshReason.POSTING_IDENTITY_CONFLICT),
    ],
)
async def test_uncorroborated_external_links_never_enter_modern_discovery(
    tmp_path, employer_state, expected_reason
) -> None:
    home = PrivateHome(tmp_path)
    profile = _profile(home, "Example Labs", "examplelabs")
    external = "https://www.linkedin.com/jobs/view/2233445566"
    employer = "https://jobs.lever.co/example/job-5566"
    executor = _SearchExecutor({
        profile.profile_id: _search_result(
            profile, (_candidate(profile, "external-1", external),)
        ),
    })

    class _UncertainReader(_Reader):
        async def __call__(self, request):
            self.calls.append(request.url)
            if request.url == external:
                return ReadJobResult.succeeded(
                    replace(
                        _observation(external),
                        source_platform=SourcePlatform.GENERIC_WEB,
                        ats_type=AtsType.UNKNOWN,
                        application_url=employer,
                    )
                )
            if employer_state == "CLOSED":
                return ReadJobResult.failed(ReadJobReason.JOB_NOT_FOUND)
            if employer_state == "UNAVAILABLE":
                return ReadJobResult.failed(ReadJobReason.SOURCE_UNAVAILABLE)
            return ReadJobResult.succeeded(
                replace(_observation(employer), title="Unrelated Title")
            )

    reader = _UncertainReader()
    discovery = _Discovery()
    result = await refresh_job_library(
        _command(f"refresh-{employer_state.lower()}"),
        profile_provider=_ProfileProvider(PrivateHomeSearchProfileRepository(home)),
        search_executor=executor,
        public_job_reader=reader,
        discovery=discovery,
        priority_refresh=_Priority(),
        repository=PrivateHomeJobLibraryRefreshRunRepository(home),
    )
    assert result.status is JobLibraryRefreshStatus.COMPLETED
    assert reader.calls == [external, employer]
    assert discovery.calls == []
    assert result.run.discovery_summary.failed == 0
    assert result.run.candidate_results[0].reason is expected_reason
