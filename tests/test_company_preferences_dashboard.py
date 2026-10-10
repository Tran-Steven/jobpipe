from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from core.authenticated_subject import (
    AuthenticatedSubjectContext,
    AuthenticationMethod,
)
from core.company_filters import CompanyTreatment
from core.company_preferences import (
    PrivateCompanyPreferences,
    effective_company_treatment,
)
from core.private_home import PrivateHome
from dashboard.server import app
from tests.test_application_plan import NOW, SUBJECT


def _context(subject_id: str) -> AuthenticatedSubjectContext:
    return AuthenticatedSubjectContext(
        session_id="company_pref_dashboard_session_reference_2026",
        subject_id=subject_id,
        authentication_method=AuthenticationMethod.LOCAL_KEYCHAIN_SESSION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def _install(monkeypatch, home: PrivateHome, subject_id: str) -> None:
    async def authenticated(_request):
        return _context(subject_id)

    monkeypatch.setattr(
        app.state, "authenticated_subject_dependency", authenticated,
        raising=False,
    )
    monkeypatch.setattr(
        app.state, "company_preferences_home", home, raising=False
    )


def test_subject_scoped_dashboard_company_preferences_are_isolated(
    tmp_path: Path, monkeypatch
) -> None:
    home = PrivateHome(tmp_path / "private")
    _install(monkeypatch, home, SUBJECT)
    client = TestClient(app)
    read = client.get("/api/company-preferences")
    assert read.status_code == 200
    assert read.json()["enabled"] is False

    headers = {"X-JobOps-Preferences-Action": "1", "Origin": "http://testserver"}
    enabled = client.post(
        "/api/company-preferences",
        json={"action": "enable"}, headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    allowed = client.post(
        "/api/company-preferences",
        json={"action": "allow", "company": "TCS"}, headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] == ["TCS"]
    blocked = client.post(
        "/api/company-preferences",
        json={"action": "block", "company": "Example Firm"}, headers=headers,
    )
    assert blocked.status_code == 200
    assert blocked.json()["blocked"] == ["Example Firm"]
    stored = PrivateCompanyPreferences(home, subject_id=SUBJECT)
    assert stored.path.stat().st_mode & 0o077 == 0
    assert effective_company_treatment(
        "TCS", preferences=stored.read()
    ) is CompanyTreatment.ALLOW
    assert effective_company_treatment(
        "Example Firm", preferences=stored.read()
    ) is CompanyTreatment.BLOCK
    assert not PrivateCompanyPreferences(home).read().enabled

    another = "subject-another-candidate"
    _install(monkeypatch, home, another)
    assert client.get("/api/company-preferences").json()["blocked"] == []
    assert client.get("/api/company-preferences").json()["enabled"] is False
    assert PrivateCompanyPreferences(home, subject_id=another).path != stored.path
    assert PrivateCompanyPreferences(home, subject_id=SUBJECT).read().allowed == ("TCS",)


def test_company_preferences_updates_reject_cross_site_and_extra_fields(
    tmp_path: Path, monkeypatch
) -> None:
    home = PrivateHome(tmp_path / "private")
    _install(monkeypatch, home, SUBJECT)
    client = TestClient(app)
    valid = {"X-JobOps-Preferences-Action": "1"}
    cases = (
        ({"action": "enable"}, {}, 403),
        ({"action": "enable"}, {
            **valid, "Origin": "https://external.example.invalid"
        }, 403),
        ({"action": "enable"}, {
            **valid, "Sec-Fetch-Site": "cross-site"
        }, 403),
        ({"action": "enable", "subject_id": "another"}, valid, 422),
        ({"action": "block", "company": " "}, valid, 422),
        ({"action": "allow", "company": "x" * 161}, valid, 422),
        ({"action": "enable", "company": "TCS"}, valid, 422),
        ({"action": "submit"}, valid, 422),
    )
    for body, headers, expected in cases:
        response = client.post(
            "/api/company-preferences", json=body, headers=headers
        )
        assert response.status_code == expected
    assert not PrivateCompanyPreferences(home, subject_id=SUBJECT).path.exists()


def test_company_preferences_fail_closed_without_injected_private_home(
    tmp_path: Path, monkeypatch
) -> None:
    _install(monkeypatch, PrivateHome(tmp_path / "private"), SUBJECT)
    monkeypatch.setattr(app.state, "company_preferences_home", None)
    assert TestClient(app).get("/api/company-preferences").status_code == 503


def test_company_preferences_settings_ui_is_attached_to_authenticated_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    markup = (root / "dashboard/templates/index.html").read_text()
    script = (root / "dashboard/static/app.js").read_text()
    assert 'id="company-preferences-panel"' in markup
    assert 'getJson("/api/company-preferences")' in script
    assert 'fetch("/api/company-preferences"' in script
    assert '"X-JobOps-Preferences-Action": "1"' in script
    assert 'data-clear-company=' in script
    assert "renderCompanyPreferences()" in script
