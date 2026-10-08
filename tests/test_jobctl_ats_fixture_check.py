"""Public CLI exposes the fixture gate without implying live ATS verification."""
import json
from unittest.mock import patch
import jobctl

def test_cli_ats_fixture_check_dispatch(monkeypatch,capsys):
    monkeypatch.setattr("sys.argv",["jobctl","ats-fixture-check"])
    with patch("tools.ats_readiness_report.main",return_value=0) as main:
        assert jobctl.main()==0
        main.assert_called_once()

def test_cli_fixture_failure_propagated(monkeypatch):
    monkeypatch.setattr("sys.argv",["jobctl","ats-fixture-check"])
    with patch("tools.ats_readiness_report.main",return_value=1):
        assert jobctl.main()==1
