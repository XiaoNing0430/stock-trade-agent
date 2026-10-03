from backend import cross_check


def test_compare_rows_threshold_and_split():
    result = cross_check.compare_rows(
        {"a": (10.0, 100.0), "b": (10.0, 100.0), "c": (10.0, 0.0)},
        {"a": (10.005, 100.5), "b": (10.2, 100.0)},
    )
    assert result.mismatched == ["b"]
    assert result.missing == ["c"]


def test_sampling_is_reproducible_and_anchors():
    first = cross_check.sample_codes([str(i) for i in range(50)], ["42"], "2026-09-17")
    second = cross_check.sample_codes([str(i) for i in range(50)], ["42"], "2026-09-17")
    assert first == second and first[0] == "42" and len(first) == 30


def test_effective_config_workspace_overrides_env(monkeypatch):
    class FakeSettings:
        cross_check_enabled = False
        tushare_token = "env-token"

    monkeypatch.setattr(
        cross_check.storage,
        "get_workspace_settings",
        lambda workspace_id="default": {"crossCheckEnabled": True, "tushareToken": "ws-token"},
    )
    monkeypatch.setattr("backend.settings.get_settings", lambda: FakeSettings())
    assert cross_check.effective_config() == {"enabled": True, "token": "ws-token"}


def test_effective_config_falls_back_to_env(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    class FakeSettings:
        cross_check_enabled = True
        tushare_token = "env-token"

    monkeypatch.setattr(
        cross_check.storage, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    monkeypatch.setattr("backend.settings.get_settings", lambda: FakeSettings())
    assert cross_check.effective_config() == {"enabled": True, "token": "env-token"}


def test_resolve_provider_matrix():
    assert cross_check._resolve_provider(None, {"enabled": False, "token": ""}) is None
    assert cross_check._resolve_provider(None, {"enabled": True, "token": ""}) == "eastmoney"
    assert cross_check._resolve_provider(None, {"enabled": True, "token": "t"}) == "tushare"
    assert cross_check._resolve_provider("eastmoney", {"enabled": False, "token": ""}) == "eastmoney"  # 显式=强制


def test_fetch_tushare_requires_token(monkeypatch):
    monkeypatch.setattr(cross_check, "effective_config", lambda: {"enabled": True, "token": ""})
    import pytest

    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
        cross_check.fetch_tushare(["600000"])


def test_disabled_run_updates_health_result(monkeypatch):
    monkeypatch.setattr(cross_check, "effective_config", lambda: {"enabled": False, "token": ""})
    result = cross_check.run()
    assert result.status == "disabled"
    assert cross_check.last_result()["status"] == "disabled"
