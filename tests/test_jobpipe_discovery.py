from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jobpipe_discovery import load_search_profile


def test_load_search_profile(tmp_path: Path) -> None:
    path = tmp_path / "search.yaml"
    path.write_text(yaml.safe_dump({"preferences": {"roles": ["Software Engineer"]}}), encoding="utf-8")
    profile = load_search_profile(str(path))
    assert profile["preferences"]["roles"] == ["Software Engineer"]


def test_load_search_profile_requires_roles(tmp_path: Path) -> None:
    path = tmp_path / "search.yaml"
    path.write_text(yaml.safe_dump({"preferences": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_search_profile(str(path))
