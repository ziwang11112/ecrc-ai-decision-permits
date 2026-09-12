"""Behavior-only data loading and strictly causal history features."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

DECKS = ("A", "B", "C", "D")
RISKY_DECKS = frozenset(("A", "B"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_behavior_table(frame: pd.DataFrame, dataset_id: str) -> pd.DataFrame:
    required = {
        "dataset_id",
        "subject_id",
        "study_id",
        "trial_id",
        "choice",
        "reward",
        "loss_signed",
        "net_outcome",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{dataset_id}: missing normalized columns {sorted(missing)}")
    if any("eeg" in str(column).lower() for column in frame.columns):
        raise ValueError(f"{dataset_id}: EEG-bearing columns are forbidden in E1")

    checked = frame.copy()
    checked["subject_id"] = checked["subject_id"].astype(str)
    checked["study_id"] = checked["study_id"].astype(str)
    checked["trial_id"] = pd.to_numeric(checked["trial_id"], errors="raise").astype(int)
    checked["choice"] = checked["choice"].astype(str).str.strip().str.upper()
    for column in ("reward", "loss_signed", "net_outcome"):
        checked[column] = pd.to_numeric(checked[column], errors="raise").astype(float)
    invalid_choices = sorted(set(checked["choice"]) - set(DECKS))
    if invalid_choices:
        raise ValueError(f"{dataset_id}: invalid deck codes {invalid_choices}")
    key = ["subject_id", "trial_id"]
    if checked.duplicated(key).any():
        raise ValueError(f"{dataset_id}: duplicate participant/trial keys")
    checked = checked.sort_values(key, kind="mergesort").reset_index(drop=True)
    if not np.isfinite(checked[["reward", "loss_signed", "net_outcome"]]).all().all():
        raise ValueError(f"{dataset_id}: non-finite behavioral outcomes")
    return checked


def load_many_labs(path: str | Path) -> pd.DataFrame:
    """Load the public Many Labs IGT behavior table."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    raw = pd.read_csv(source)
    required = {
        "subject_id",
        "study_id",
        "trial_id",
        "choice",
        "reward",
        "loss",
        "net_outcome",
    }
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Many Labs source is missing {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "dataset_id": "many_labs_igt",
            "subject_id": raw["subject_id"].astype(str),
            "study_id": raw["study_id"].astype(str),
            "trial_id": raw["trial_id"],
            "choice": raw["choice"],
            "reward": raw["reward"],
            # Many Labs encodes losses as non-negative magnitudes.
            "loss_signed": -pd.to_numeric(raw["loss"], errors="raise").abs(),
            "net_outcome": raw["net_outcome"],
        }
    )
    reconstructed = frame["reward"] + frame["loss_signed"]
    if not np.allclose(reconstructed, frame["net_outcome"], atol=1e-8):
        raise ValueError("Many Labs reward/loss values do not reconstruct net_outcome")
    return _validate_behavior_table(frame, "many_labs_igt")


def load_mendeley_behavior(
    directory: str | Path,
    *,
    local_manifest: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Load behavior-only IGT columns from the local Mendeley copy.

    The ``EEG sample`` column is deliberately not requested from ``read_csv``.
    The caller receives the local dataset-version record so results cannot be
    silently described as the current upstream version.
    """

    root = Path(directory)
    files = sorted(root.glob("IGT_P*.csv"))
    if not files:
        raise FileNotFoundError(f"No IGT_P*.csv behavior files under {root}")

    version_record: dict[str, object] = {
        "dataset_id": "2pw2m39yct",
        "version": "unverified_local_copy",
        "doi": None,
        "source_url": None,
    }
    manifest: dict[str, object] | None = None
    manifest_verification: dict[str, object] = {
        "performed": False,
        "all_sizes_match": None,
        "all_sha256_match": None,
    }
    if local_manifest is not None:
        manifest_path = Path(local_manifest)
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version_record.update(
            {
                "dataset_id": str(manifest.get("dataset_id", "2pw2m39yct")),
                "version": manifest.get("version", "unknown"),
                "doi": manifest.get("doi"),
                "source_url": manifest.get("source_url"),
                "license": manifest.get("license"),
                "manifest_path": str(manifest_path.resolve()),
                "downloaded_at_utc": manifest.get("downloaded_at_utc"),
            }
        )

    try:
        version_number = int(version_record["version"])
    except (TypeError, ValueError):
        version_number = None
    if version_number == 2:
        expected_metadata = {
            "dataset_id": "2pw2m39yct",
            "version": 2,
            "doi": "10.17632/2pw2m39yct.2",
            "license": "CC BY 4.0",
        }
        if manifest is None:
            raise ValueError("Official version-2 replay requires a download manifest")
        for key, expected in expected_metadata.items():
            if manifest.get(key) != expected:
                raise ValueError(
                    f"Mendeley v2 manifest {key}={manifest.get(key)!r}, "
                    f"expected {expected!r}"
                )
        expected_names = {f"IGT_P{index:02d}.csv" for index in range(1, 60)}
        actual_names = {path.name for path in files}
        if actual_names != expected_names or len(files) != 59:
            raise ValueError("Mendeley v2 input is not exactly IGT_P01..IGT_P59")
        manifest_records: dict[str, dict[str, object]] = {}
        raw_records = manifest.get("files", [])
        if not isinstance(raw_records, list):
            raise ValueError("Mendeley v2 manifest files field is not a list")
        for record in raw_records:
            if not isinstance(record, dict):
                raise ValueError("Mendeley v2 manifest contains a non-object file record")
            destination_name = Path(str(record.get("destination", ""))).name
            if destination_name in manifest_records:
                raise ValueError(f"Duplicate manifest destination {destination_name!r}")
            manifest_records[destination_name] = record
        if set(manifest_records) != expected_names or len(manifest_records) != 59:
            raise ValueError("Mendeley v2 manifest does not cover exactly 59 IGT files")
        for path in files:
            record = manifest_records[path.name]
            expected_size = int(record.get("expected_size", -1))
            expected_sha256 = str(record.get("expected_sha256", "")).lower()
            if path.stat().st_size != expected_size:
                raise ValueError(f"{path.name}: size differs from v2 API manifest")
            if _sha256_file(path) != expected_sha256:
                raise ValueError(f"{path.name}: SHA-256 differs from v2 API manifest")
        policy = manifest.get("download_policy", {})
        if not isinstance(policy, dict):
            raise ValueError("Mendeley v2 manifest download_policy is not an object")
        if policy.get("allowed_source_filename") != "IGT.csv":
            raise ValueError("Mendeley v2 manifest does not enforce the IGT-only allowlist")
        for key in (
            "eeg_download_urls_requested",
            "eeg_files_downloaded",
            "processed_eeg_files_downloaded",
        ):
            if policy.get(key) != 0:
                raise ValueError(f"Mendeley v2 manifest reports nonzero {key}")
        forbidden_files = [
            path
            for path in root.parent.rglob("*")
            if path.is_file()
            and path.name.lower() in {"eeg.csv", "processed_eeg.csv"}
        ]
        if forbidden_files:
            raise ValueError(f"EEG payloads present in behavior-only v2 tree: {forbidden_files}")
        manifest_verification = {
            "performed": True,
            "n_files_verified": len(files),
            "all_sizes_match": True,
            "all_sha256_match": True,
            "igt_only_download_policy": True,
            "eeg_payload_files_present": 0,
        }
        comparison_summary_path = (
            manifest_path.parent / "mendeley_v1_v2_comparison_summary.json"
        )
        comparison_detail_path = (
            manifest_path.parent / "mendeley_v1_v2_file_comparison.csv"
        )
        if comparison_summary_path.is_file() and comparison_detail_path.is_file():
            comparison = json.loads(
                comparison_summary_path.read_text(encoding="utf-8")
            )
            comparison_detail = pd.read_csv(comparison_detail_path)
            required_passes = (
                comparison.get("n_files") == 59,
                comparison.get("v1_total_rows") == 11_800,
                comparison.get("v2_total_rows") == 11_800,
                comparison.get("all_schemas_equal") is True,
                comparison.get("all_row_counts_equal") is True,
                comparison.get("raw_byte_identical_files") == 59,
                comparison.get("normalized_behavior_identical_files") == 59,
                comparison.get("all_v2_api_manifest_checks_passed") is True,
                comparison.get("comparison_used_for_fit_or_threshold_selection")
                is False,
                len(comparison_detail) == 59,
                comparison_detail["raw_bytes_identical"].astype(bool).all(),
                comparison_detail["normalized_behavior_identical"]
                .astype(bool)
                .all(),
            )
            if not all(required_passes):
                raise ValueError("Mendeley v1/v2 behavior-comparison audit did not pass")
            version_record["v1_v2_behavior_comparison"] = {
                "summary_path": str(comparison_summary_path.resolve()),
                "detail_path": str(comparison_detail_path.resolve()),
                "n_files": 59,
                "n_rows_each_version": 11_800,
                "raw_byte_identical_files": 59,
                "normalized_behavior_identical_files": 59,
                "used_for_fit_or_threshold_selection": False,
            }

    if version_number == 2:
        normalized_dataset_id = "mendeley_igt_official_v2"
        normalized_study_id = "mendeley_official_v2"
        interpretation = (
            "frozen external replay on official Mendeley version-2 behavior files; "
            "same-task external cohort, not cross-domain or clinical validation"
        )
    else:
        normalized_dataset_id = "mendeley_igt_local_v1"
        normalized_study_id = "mendeley_local_v1"
        interpretation = (
            "exploratory frozen external replay on the local version-1 behavior files; "
            "not a version-2 replication"
        )

    rows: list[pd.DataFrame] = []
    for path in files:
        # Explicit allowlist prevents reading the EEG alignment column.
        raw = pd.read_csv(path, usecols=["iteration", "decision", "win", "lose"])
        if version_number == 2 and len(raw) != 200:
            raise ValueError(f"{path.name}: official v2 IGT file must have 200 rows")
        subject = path.stem.replace("IGT_", "mendeley_")
        win = pd.to_numeric(raw["win"], errors="raise").astype(float)
        loss_signed = pd.to_numeric(raw["lose"], errors="raise").astype(float)
        if (loss_signed > 0).any():
            raise ValueError(f"{path.name}: expected signed non-positive loss values")
        rows.append(
            pd.DataFrame(
                {
                    "dataset_id": normalized_dataset_id,
                    "subject_id": subject,
                    "study_id": normalized_study_id,
                    "trial_id": raw["iteration"],
                    "choice": raw["decision"],
                    "reward": win,
                    "loss_signed": loss_signed,
                    "net_outcome": win + loss_signed,
                }
            )
        )
    frame = _validate_behavior_table(
        pd.concat(rows, ignore_index=True), normalized_dataset_id
    )
    version_record.update(
        {
            "n_behavior_files": len(files),
            "n_behavior_rows": len(frame),
            "n_behavior_participants": int(frame["subject_id"].nunique()),
            "eeg_files_read": 0,
            "eeg_columns_read": [],
            "manifest_verification": manifest_verification,
            "interpretation": interpretation,
        }
    )
    return frame, version_record


def _entropy(probabilities: Iterable[float]) -> float:
    values = np.asarray(list(probabilities), dtype=float)
    positive = values[values > 0]
    return float(-(positive * np.log2(positive)).sum())


def build_causal_history_features(
    behavior: pd.DataFrame,
    *,
    windows: tuple[int, ...] = (5, 10, 20),
    block_size: int = 20,
) -> pd.DataFrame:
    """Materialize features before appending the current trial to history."""

    if not windows or any(int(window) < 1 for window in windows):
        raise ValueError("history windows must be positive")
    if block_size < 1:
        raise ValueError("block_size must be positive")
    normalized = _validate_behavior_table(behavior, str(behavior["dataset_id"].iloc[0]))
    feature_rows: list[dict[str, object]] = []

    for subject_id, subject in normalized.groupby("subject_id", sort=False):
        subject = subject.sort_values("trial_id", kind="mergesort")
        previous_choices: list[str] = []
        previous_risk: list[int] = []
        previous_loss: list[int] = []
        previous_net: list[float] = []
        counts = {deck: 0 for deck in DECKS}
        cumulative_net = 0.0
        previous_run_length = 0
        previous_choice: str | None = None

        for row in subject.itertuples(index=False):
            n_prior = len(previous_choices)
            smoothed_deck_probabilities = {
                deck: (counts[deck] + 1.0) / (n_prior + len(DECKS)) for deck in DECKS
            }
            smoothed_risk = (
                counts["A"] + counts["B"] + 1.0
            ) / (n_prior + 2.0)
            feature: dict[str, object] = {
                "dataset_id": row.dataset_id,
                "subject_id": subject_id,
                "study_id": row.study_id,
                "trial_id": int(row.trial_id),
                "y_true": int(row.choice in RISKY_DECKS),
                "trial_index": n_prior,
                "block_index": n_prior // block_size,
                "prev_choice_A": int(previous_choice == "A"),
                "prev_choice_B": int(previous_choice == "B"),
                "prev_choice_C": int(previous_choice == "C"),
                "prev_choice_D": int(previous_choice == "D"),
                "prev_risky": float(previous_risk[-1]) if previous_risk else np.nan,
                "prev_reward_100": float(subject.iloc[n_prior - 1]["reward"] / 100.0)
                if n_prior
                else np.nan,
                "prev_loss_magnitude_100": float(
                    -subject.iloc[n_prior - 1]["loss_signed"] / 100.0
                )
                if n_prior
                else np.nan,
                "prev_net_outcome_100": float(previous_net[-1] / 100.0)
                if previous_net
                else np.nan,
                "cumulative_net_prev_100": cumulative_net / 100.0,
                "previous_choice_run_length": previous_run_length,
                "prior_risky_rate_all": smoothed_risk,
                "prior_choice_entropy": _entropy(smoothed_deck_probabilities.values()),
                "history_score": smoothed_risk,
            }
            for deck in DECKS:
                feature[f"prior_choice_probability_{deck}"] = smoothed_deck_probabilities[deck]
            for window in windows:
                risk_slice = previous_risk[-window:]
                loss_slice = previous_loss[-window:]
                net_slice = previous_net[-window:]
                feature[f"rolling_prev_{window}_risky_rate"] = (
                    float(np.mean(risk_slice)) if risk_slice else np.nan
                )
                feature[f"rolling_prev_{window}_loss_rate"] = (
                    float(np.mean(loss_slice)) if loss_slice else np.nan
                )
                feature[f"rolling_prev_{window}_net_mean_100"] = (
                    float(np.mean(net_slice) / 100.0) if net_slice else np.nan
                )
            feature_rows.append(feature)

            current_choice = str(row.choice)
            current_risk = int(current_choice in RISKY_DECKS)
            current_loss = int(float(row.loss_signed) < 0.0)
            current_net = float(row.net_outcome)
            previous_choices.append(current_choice)
            previous_risk.append(current_risk)
            previous_loss.append(current_loss)
            previous_net.append(current_net)
            counts[current_choice] += 1
            cumulative_net += current_net
            if current_choice == previous_choice:
                previous_run_length += 1
            else:
                previous_run_length = 1
            previous_choice = current_choice

    features = pd.DataFrame(feature_rows)
    return features.sort_values(["subject_id", "trial_id"], kind="mergesort").reset_index(
        drop=True
    )


def model_feature_columns(features: pd.DataFrame) -> list[str]:
    metadata = {
        "dataset_id",
        "subject_id",
        "study_id",
        "trial_id",
        "y_true",
        "history_score",
    }
    columns = [column for column in features.columns if column not in metadata]
    # Prior-choice fields are legal; reject only an unqualified/current choice field.
    rejected = [
        column
        for column in columns
        if "eeg" in column.lower()
        or column.lower() in {"choice", "target", "label", "y_true", "balance"}
    ]
    if rejected:
        raise ValueError(f"Forbidden feature columns: {rejected}")
    if not columns:
        raise ValueError("No model features were constructed")
    return columns


def assign_participant_folds(
    features: pd.DataFrame,
    *,
    n_folds: int,
    seed: int,
) -> pd.DataFrame:
    """Study-stratified, participant-grouped deterministic fold assignment."""

    subject_meta = features[["subject_id", "study_id"]].drop_duplicates()
    if subject_meta["subject_id"].duplicated().any():
        raise ValueError("A participant maps to more than one study")
    if len(subject_meta) < n_folds:
        raise ValueError("Fewer participants than requested folds")
    rng = np.random.default_rng(seed)
    assignments: list[dict[str, object]] = []
    for study_id, study in subject_meta.groupby("study_id", sort=True):
        subjects = np.asarray(sorted(study["subject_id"].astype(str)), dtype=object)
        rng.shuffle(subjects)
        offset = int(rng.integers(0, n_folds))
        for index, subject_id in enumerate(subjects):
            assignments.append(
                {
                    "subject_id": str(subject_id),
                    "study_id": str(study_id),
                    "fold": int((index + offset) % n_folds),
                }
            )
    result = pd.DataFrame(assignments).sort_values("subject_id").reset_index(drop=True)
    if result["subject_id"].duplicated().any():
        raise AssertionError("Participant fold assignment is not unique")
    return result


def limit_participants(
    behavior: pd.DataFrame,
    maximum: int | None,
    *,
    seed: int,
) -> pd.DataFrame:
    if maximum is None:
        return behavior.copy()
    if maximum < 2:
        raise ValueError("maximum participants must be at least 2")
    subjects = np.asarray(sorted(behavior["subject_id"].unique()), dtype=object)
    rng = np.random.default_rng(seed)
    rng.shuffle(subjects)
    selected = set(subjects[: min(maximum, len(subjects))])
    return behavior[behavior["subject_id"].isin(selected)].copy()


def assert_causal_feature_invariance(
    behavior: pd.DataFrame,
    *,
    windows: tuple[int, ...],
    block_size: int,
    maximum_subjects: int = 5,
) -> None:
    """Mutate each selected current/future suffix; current features must not move."""

    subjects = sorted(behavior["subject_id"].unique())[:maximum_subjects]
    for subject_id in subjects:
        subject = behavior[behavior["subject_id"].eq(subject_id)].copy()
        if len(subject) < 4:
            continue
        cut = len(subject) // 2
        original = build_causal_history_features(
            subject, windows=windows, block_size=block_size
        )
        mutated = subject.copy()
        suffix_index = mutated.index[cut:]
        mutated.loc[suffix_index, "choice"] = "D"
        mutated.loc[suffix_index, "reward"] = 9_999.0
        mutated.loc[suffix_index, "loss_signed"] = -9_999.0
        mutated.loc[suffix_index, "net_outcome"] = 0.0
        changed = build_causal_history_features(
            mutated, windows=windows, block_size=block_size
        )
        compare_columns = model_feature_columns(original) + ["history_score"]
        left = original.loc[:cut, compare_columns].to_numpy(dtype=float)
        right = changed.loc[:cut, compare_columns].to_numpy(dtype=float)
        if not np.allclose(left, right, equal_nan=True):
            raise AssertionError(
                f"Current/future mutation changed a causal feature for {subject_id}"
            )


def dataset_summary(features: pd.DataFrame, *, version_note: str) -> dict[str, object]:
    trials = features.groupby("subject_id", sort=False).size()
    return {
        "dataset_id": str(features["dataset_id"].iloc[0]),
        "version_note": version_note,
        "n_participants": int(features["subject_id"].nunique()),
        "n_studies": int(features["study_id"].nunique()),
        "n_decisions": int(len(features)),
        "positive_class": "current A/B deck choice (operational high-risk proxy)",
        "positive_prevalence": float(features["y_true"].mean()),
        "trials_per_participant_min": int(trials.min()),
        "trials_per_participant_median": float(trials.median()),
        "trials_per_participant_max": int(trials.max()),
        "eeg_used": False,
    }


__all__ = [
    "assign_participant_folds",
    "assert_causal_feature_invariance",
    "build_causal_history_features",
    "dataset_summary",
    "limit_participants",
    "load_many_labs",
    "load_mendeley_behavior",
    "model_feature_columns",
]
