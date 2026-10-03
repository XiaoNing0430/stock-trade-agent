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


def test_disabled_run_updates_health_result():
    result = cross_check.run()
    assert result.status == "disabled"
    assert cross_check.last_result()["status"] == "disabled"
