from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "icair_2026"
    / "framework_v1"
    / "run_systems_benchmark.py"
)
VERIFY_PATH = (
    Path(__file__).resolve().parents[1]
    / "icair_2026"
    / "framework_v1"
    / "verify_systems_determinism.py"
)


def load_benchmark_module():
    spec = importlib.util.spec_from_file_location("ecrc_systems_benchmark", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_verify_module():
    spec = importlib.util.spec_from_file_location("ecrc_systems_verify", VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_systems_benchmark_structural_determinism(tmp_path) -> None:
    benchmark = load_benchmark_module()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    for directory in (first_dir, second_dir):
        (directory / "databases").mkdir()

    first_performance = benchmark.run_performance_cases(
        first_dir,
        seed=12345,
        repetitions=1,
        single_requests=12,
        workers=4,
        warmup_requests=0,
    )
    first_faults = benchmark.run_fault_scenarios(first_dir)
    first_race = benchmark.run_unsafe_race_witness()
    second_performance = benchmark.run_performance_cases(
        second_dir,
        seed=12345,
        repetitions=1,
        single_requests=12,
        workers=4,
        warmup_requests=0,
    )
    second_faults = benchmark.run_fault_scenarios(second_dir)
    second_race = benchmark.run_unsafe_race_witness()

    first = benchmark.structural_projection(first_performance, first_faults, first_race)
    second = benchmark.structural_projection(
        second_performance, second_faults, second_race
    )
    assert first == second
    assert benchmark.canonical_hash(first) == benchmark.canonical_hash(second)
    assert load_verify_module().compare_structures(first, second)["passed"] is True
    assert all(row["passed"] for row in first_faults)
    assert first_race["passed"] is True
    assert first_race["production_comparator"] is False
    assert first_race["oversubscription_count"] == 1

    by_case = {row["case"]: row for row in first_performance}
    assert by_case["concurrent_24_cap3"]["reservation_counts"]["committed"] == 3
    assert by_case["concurrent_24_cap3"]["capacity_rejections"] == 21
    assert by_case["concurrent_24_cap3"]["oversubscription_count"] == 0
    assert by_case["concurrent_96_cap8"]["reservation_counts"]["committed"] == 8
    assert by_case["concurrent_96_cap8"]["capacity_rejections"] == 88
    assert by_case["concurrent_96_cap8"]["oversubscription_count"] == 0
    for workers in (1, 2, 4, 8, 16):
        sweep = by_case[f"worker_sweep_96_cap8_w{workers}"]
        assert sweep["workers"] == workers
        assert sweep["reservation_counts"]["committed"] == 8
        assert sweep["capacity_rejections"] == 88
        assert sweep["oversubscription_count"] == 0

    aggregate = benchmark.aggregate_performance(first_performance)
    assert {row["case"] for row in aggregate} == set(by_case)
    for row in aggregate:
        for family in ("adjudication_latency", "end_to_end_latency"):
            for metric in ("p50_ms", "p95_ms", "p99_ms"):
                values = row[family][metric]
                assert values["minimum"] <= values["median"] <= values["maximum"]


def test_benchmark_latency_summary_is_well_ordered() -> None:
    benchmark = load_benchmark_module()
    summary = benchmark.latency_summary([1_000_000, 2_000_000, 3_000_000])
    assert 0 < summary["p50_ms"] <= summary["p95_ms"] <= summary["p99_ms"]
    assert summary["maximum_ms"] == 3.0
