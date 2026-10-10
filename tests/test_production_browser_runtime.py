"""Focused P2c7a production Browser runtime tests with fake Playwright."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.authorized_submission_execution import (
    BrowserLeaseProvider as AuthorizedBrowserLeaseProvider,
)
from core.event_ledger import EventLedger
from core.leases import LeaseManager
from core.non_submit_application_execution import (
    BrowserLeaseProvider as NonSubmitBrowserLeaseProvider,
)
from core.private_home import PrivateHome
from core.production_browser_runtime import (
    BROWSER_RUNTIME_CONFIG_CONTRACT_VERSION,
    BrowserRuntimeFailure,
    BrowserRuntimeState,
    ProductionBrowserRuntimeError,
    build_production_browser_runtime,
    project_browser_runtime_config,
)


class _Page:
    def __init__(self, context: "_Context") -> None:
        self.context = context
        self.closed = False
        self.timeout = 0
        self.navigation_timeout = 0

    def set_default_timeout(self, value: int) -> None:
        self.timeout = value

    def set_default_navigation_timeout(self, value: int) -> None:
        self.navigation_timeout = value

    async def close(self) -> None:
        self.closed = True
        if self in self.context.pages:
            self.context.pages.remove(self)


class _Context:
    def __init__(self) -> None:
        self.pages = [_Page(self)]
        self.closed = False
        self.created: list[_Page] = []
        self.timeout = 0
        self.navigation_timeout = 0

    def set_default_timeout(self, value: int) -> None:
        self.timeout = value

    def set_default_navigation_timeout(self, value: int) -> None:
        self.navigation_timeout = value

    async def new_page(self) -> _Page:
        page = _Page(self)
        self.pages.append(page)
        self.created.append(page)
        return page

    async def close(self) -> None:
        self.closed = True
        for page in tuple(self.pages):
            await page.close()


class _Chromium:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.context = _Context()

    async def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs)
        return self.context


class _Playwright:
    def __init__(self) -> None:
        self.chromium = _Chromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _parts(tmp_path: Path):
    home = PrivateHome(tmp_path / "private-home")
    home.ensure()
    playwright = _Playwright()
    factory_calls = []

    async def factory():
        factory_calls.append("start")
        return playwright

    config = project_browser_runtime_config(
        {
            "personal": {"email": "must-not-be-read"},
            "common_answers": {"secret": "must-not-be-read"},
            "resume_path": "/must/not/be/read",
            "browser_runtime": {
                "config_contract_version": (
                    BROWSER_RUNTIME_CONFIG_CONTRACT_VERSION
                ),
                "profile_name": "synthetic-production",
                "headless": True,
                "single_subject_mode": True,
            },
        },
        private_home=home,
    )
    manager = LeaseManager(EventLedger(home.paths.event_ledger))
    runtime = build_production_browser_runtime(
        config=config,
        private_home=home,
        lease_manager=manager,
        playwright_factory=factory,
    )
    return home, playwright, factory_calls, runtime


@pytest.mark.asyncio
async def test_typed_config_startup_and_safe_diagnostics(tmp_path: Path) -> None:
    home, playwright, calls, runtime = _parts(tmp_path)

    assert calls == []
    await runtime.start()
    await runtime.start()

    assert calls == ["start"]
    assert runtime.state is BrowserRuntimeState.STARTED
    assert len(playwright.chromium.calls) == 1
    launch = playwright.chromium.calls[0]
    assert launch["accept_downloads"] is False
    assert launch["headless"] is True
    assert not playwright.chromium.context.pages
    diagnostic = runtime.diagnostics
    assert diagnostic.persistent_context_enabled is True
    assert str(home.root) not in repr(diagnostic)

    locked_home, _, _, locked = _parts(tmp_path / "locked")
    lock = locked.config.user_data_directory / "SingletonLock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("synthetic", encoding="utf-8")
    with pytest.raises(ProductionBrowserRuntimeError) as exc:
        await locked.start()
    assert exc.value.failure is BrowserRuntimeFailure.PROFILE_LOCKED
    assert str(locked_home.root) not in str(exc.value)

    _, _, _, linked = _parts(tmp_path / "linked")
    linked.config.user_data_directory.parent.mkdir(parents=True, exist_ok=True)
    linked.config.user_data_directory.symlink_to(
        tmp_path / "uncontrolled-profile",
        target_is_directory=True,
    )
    with pytest.raises(ProductionBrowserRuntimeError) as unsafe:
        await linked.start()
    assert unsafe.value.failure is (
        BrowserRuntimeFailure.PROFILE_DIRECTORY_INVALID
    )


@pytest.mark.asyncio
async def test_exclusive_lease_page_lifecycle_and_exception_release(
    tmp_path: Path,
) -> None:
    _, playwright, _, runtime = _parts(tmp_path)
    await runtime.start()
    provider = runtime.lease_provider()

    with pytest.raises(RuntimeError, match="synthetic"):
        async with provider.lease(owner="run-synthetic-one") as leased:
            first_page = leased.page
            assert leased.owner == "run-synthetic-one"
            assert leased.lease.resource == "browser:chromium"
            with pytest.raises(ProductionBrowserRuntimeError) as busy:
                async with provider.lease(owner="run-synthetic-two"):
                    pass
            assert busy.value.failure is BrowserRuntimeFailure.LEASE_UNAVAILABLE
            raise RuntimeError("synthetic")

    assert first_page.closed is True
    assert runtime.lease_manager.get("browser:chromium") is None
    assert playwright.chromium.context.closed is False

    acquired = asyncio.Event()

    async def cancelled_lease() -> None:
        async with provider.lease(owner="run-synthetic-cancel"):
            acquired.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(cancelled_lease())
    await acquired.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.lease_manager.get("browser:chromium") is None

    async with provider.lease(owner="run-synthetic-three") as second:
        assert second.page is not first_page
        assert second.page.timeout == 30_000


@pytest.mark.asyncio
async def test_provider_satisfies_both_execution_ports_without_side_effects(
    tmp_path: Path,
) -> None:
    _, playwright, _, runtime = _parts(tmp_path)
    provider = runtime.lease_provider()
    assert isinstance(provider, NonSubmitBrowserLeaseProvider)
    assert isinstance(provider, AuthorizedBrowserLeaseProvider)
    assert playwright.chromium.calls == []

    with pytest.raises(ProductionBrowserRuntimeError) as not_started:
        async with provider.lease(owner="run-before-start"):
            pass
    assert not_started.value.failure is BrowserRuntimeFailure.RUNTIME_NOT_STARTED

    await runtime.start()
    async with provider.lease(owner="run-p2c3") as p2c3:
        p2c3_token = p2c3.lease.token
    async with provider.lease(owner="run-p2c6") as p2c6:
        assert p2c6.lease.token != p2c3_token
    assert len(playwright.chromium.context.created) == 2


@pytest.mark.asyncio
async def test_shutdown_is_idempotent_and_blocks_new_leases(
    tmp_path: Path,
) -> None:
    _, playwright, _, runtime = _parts(tmp_path)
    await runtime.start()
    page = None
    async with runtime.lease_provider().lease(owner="run-before-close") as lease:
        page = lease.page
    await runtime.close()
    await runtime.close()

    assert page is not None and page.closed is True
    assert playwright.chromium.context.closed is True
    assert playwright.stopped is True
    assert runtime.state is BrowserRuntimeState.CLOSED
    assert runtime.diagnostics.persistent_context_enabled is False
    with pytest.raises(ProductionBrowserRuntimeError) as closed:
        async with runtime.lease_provider().lease(owner="run-after-close"):
            pass
    assert closed.value.failure is BrowserRuntimeFailure.RUNTIME_CLOSED


@pytest.mark.asyncio
async def test_human_suspension_keeps_exact_page_and_releases_global_lease(
    tmp_path: Path,
) -> None:
    _, playwright, _, runtime = _parts(tmp_path)
    await runtime.start()
    provider = runtime.lease_provider()
    async with provider.lease(owner="run-one") as lease:
        page = lease.page
        capability = lease.suspend_for_human(ttl_seconds=120)
        assert isinstance(capability, str) and len(capability) >= 32
        assert not page.closed
        with pytest.raises(ProductionBrowserRuntimeError) as double:
            lease.suspend_for_human()
        assert double.value.failure is BrowserRuntimeFailure.SESSION_RESUME_REJECTED

    assert not page.closed
    assert page in playwright.chromium.context.pages
    assert runtime.lease_manager.get("browser:chromium") is None
    assert runtime._active_count == 0
    assert len(playwright.chromium.context.created) == 1
    with pytest.raises(ProductionBrowserRuntimeError) as blocked:
        async with provider.lease(owner="unrelated-run"):
            pytest.fail("cannot enter while human challenge is suspended")
    assert blocked.value.failure is BrowserRuntimeFailure.SESSION_SUSPENDED
    assert len(playwright.chromium.context.created) == 1

    async with provider.lease(owner="run-one", resume_token=capability) as resumed:
        assert resumed.page is page
        assert resumed.owner == "run-one"
        assert resumed.page.closed is False
    assert page.closed is True
    assert len(playwright.chromium.context.created) == 1
    assert runtime.lease_manager.get("browser:chromium") is None
    await runtime.close()


@pytest.mark.asyncio
async def test_suspended_session_rejects_wrong_capability_owner_and_replay(
    tmp_path: Path,
) -> None:
    _, _, _, runtime = _parts(tmp_path)
    await runtime.start()
    provider = runtime.lease_provider()
    async with provider.lease(owner="original-run") as active:
        token = active.suspend_for_human()
    for owner, capability in (
        ("wrong-run", token),
        ("original-run", "forged-token"),
    ):
        with pytest.raises(ProductionBrowserRuntimeError) as denied:
            async with provider.lease(owner=owner, resume_token=capability):
                pytest.fail("invalid credential must not access held page")
        assert denied.value.failure is BrowserRuntimeFailure.SESSION_RESUME_REJECTED
        assert not active.page.closed
    async with provider.lease(owner="original-run", resume_token=token):
        pass
    with pytest.raises(ProductionBrowserRuntimeError) as replay:
        async with provider.lease(owner="original-run", resume_token=token):
            pytest.fail("spent capability must never start a new page")
    assert replay.value.failure is BrowserRuntimeFailure.SESSION_RESUME_REJECTED
    assert runtime._suspended is None


@pytest.mark.asyncio
async def test_expiry_fails_closed_and_never_resurrects_old_challenge(
    tmp_path: Path,
) -> None:
    _, playwright, _, runtime = _parts(tmp_path)
    clock = [0.0]
    runtime._monotonic = lambda: clock[0]
    await runtime.start()
    provider = runtime.lease_provider()
    async with provider.lease(owner="expiring-run") as active:
        page = active.page
        token = active.suspend_for_human(ttl_seconds=3)
    clock[0] = 3.0
    with pytest.raises(ProductionBrowserRuntimeError) as expired:
        async with provider.lease(owner="expiring-run", resume_token=token):
            pytest.fail("expired challenge capability cannot resume")
    assert expired.value.failure is BrowserRuntimeFailure.SESSION_EXPIRED
    assert page.closed is True
    assert runtime._suspended is None
    assert runtime.lease_manager.get("browser:chromium") is None
    assert len(playwright.chromium.context.created) == 1
    with pytest.raises(ProductionBrowserRuntimeError) as replay:
        async with provider.lease(owner="expiring-run", resume_token=token):
            pass
    assert replay.value.failure is BrowserRuntimeFailure.SESSION_RESUME_REJECTED


@pytest.mark.asyncio
async def test_suspension_on_fault_is_cancelled_and_lease_handle_is_revoked(
    tmp_path: Path,
) -> None:
    _, _, _, runtime = _parts(tmp_path)
    await runtime.start()
    provider = runtime.lease_provider()
    parked = None
    with pytest.raises(RuntimeError, match="adapter crashed"):
        async with provider.lease(owner="crash-run") as leased:
            parked = leased
            leased.suspend_for_human()
            raise RuntimeError("adapter crashed")
    assert runtime._suspended is None
    assert parked.page.closed is True
    assert runtime.lease_manager.get("browser:chromium") is None
    with pytest.raises(ProductionBrowserRuntimeError) as stale:
        parked.suspend_for_human()
    assert stale.value.failure is BrowserRuntimeFailure.SESSION_RESUME_REJECTED
    async with provider.lease(owner="other-run") as fresh:
        assert fresh.page is not parked.page


@pytest.mark.asyncio
async def test_runtime_shutdown_invalidates_held_challenge_and_never_exposes_it(
    tmp_path: Path,
) -> None:
    home, playwright, _, runtime = _parts(tmp_path)
    await runtime.start()
    async with runtime.lease_provider().lease(owner="shutdown-run") as leased:
        page = leased.page
        token = leased.suspend_for_human()
    assert token not in repr(runtime.diagnostics)
    assert str(home.root) not in repr(runtime.diagnostics)
    await runtime.close()
    assert page.closed is True
    assert playwright.chromium.context.closed
    assert runtime._suspended is None
    with pytest.raises(ProductionBrowserRuntimeError) as closed:
        async with runtime.lease_provider().lease(
            owner="shutdown-run", resume_token=token
        ):
            pass
    assert closed.value.failure is BrowserRuntimeFailure.RUNTIME_CLOSED


@pytest.mark.asyncio
async def test_suspension_ttl_policy_and_empty_token_do_not_modify_active_session(
    tmp_path: Path,
) -> None:
    _, _, _, runtime = _parts(tmp_path)
    await runtime.start()
    provider = runtime.lease_provider()
    async with provider.lease(owner="ttl-run") as leased:
        for ttl in (0, -1, 1801, True, "600"):
            with pytest.raises(ProductionBrowserRuntimeError) as invalid:
                leased.suspend_for_human(ttl_seconds=ttl)
            assert invalid.value.failure is BrowserRuntimeFailure.CONFIGURATION_ERROR
        token = leased.suspend_for_human(ttl_seconds=60)
    with pytest.raises(ProductionBrowserRuntimeError) as empty:
        async with provider.lease(owner="ttl-run", resume_token=""):
            pass
    assert empty.value.failure is BrowserRuntimeFailure.SESSION_RESUME_REJECTED
    async with provider.lease(owner="ttl-run", resume_token=token) as recovered:
        assert recovered.page is leased.page


@pytest.mark.asyncio
async def test_human_page_expires_automatically_without_followup_browser_request(
    tmp_path: Path,
) -> None:
    _, playwright, _, runtime = _parts(tmp_path)
    await runtime.start()
    async with runtime.lease_provider().lease(owner="attended-user-run") as leased:
        page = leased.page
        leased.suspend_for_human(ttl_seconds=1)
    assert not page.closed
    await asyncio.sleep(1.1)
    assert page.closed
    assert runtime._suspended is None
    assert runtime._suspend_timer is None
    assert runtime.lease_manager.get("browser:chromium") is None
    assert len(playwright.chromium.context.created) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_suspending_and_resuming_does_not_leave_delayed_expiry_timer(
    tmp_path: Path,
) -> None:
    _, _, _, runtime = _parts(tmp_path)
    await runtime.start()
    async with runtime.lease_provider().lease(owner="handoff-run") as first:
        token = first.suspend_for_human(ttl_seconds=1)
    original_timer = runtime._suspend_timer
    assert original_timer is not None
    async with runtime.lease_provider().lease(
        owner="handoff-run", resume_token=token
    ) as resumed:
        assert resumed.page is first.page
        assert original_timer.cancelled()
        assert runtime._suspend_timer is None
    await asyncio.sleep(1.1)
    assert runtime._suspended is None
    assert runtime._suspend_timer is None
    await runtime.close()
