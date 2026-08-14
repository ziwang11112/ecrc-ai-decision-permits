from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


TRIAL_COUNTS = (95, 100, 150)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize the Many Labs IGT matrix CSV files into a behavior-only "
            "long table for local system-level benchmark replay."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=(
            ROOT
            / "data"
            / "raw"
            / "external"
            / "many_labs_igt"
            / "extracted"
            / "IGTdataSteingroever2014"
        ),
        help="Directory containing choice_*.csv, wi_*.csv, lo_*.csv, index_*.csv.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=(
            ROOT
            / "data"
            / "raw"
            / "external"
            / "many_labs_igt"
            / "many_labs_igt_behavior_long.csv"
        ),
        help="Ignored behavior-only long CSV to write.",
    )
    args = parser.parse_args()

    table = build_many_labs_long_table(args.input_dir)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output_csv, index=False)

    summary = summarize_many_labs_long_table(table)
    print(f"wrote: {args.output_csv}")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


def build_many_labs_long_table(input_dir: str | Path) -> pd.DataFrame:
    """Return a long behavior table from Many Labs IGT matrix CSV files."""

    root = Path(input_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Many Labs input directory not found: {root}")

    frames = [_load_trial_count(root, n_trials) for n_trials in TRIAL_COUNTS]
    table = pd.concat(frames, ignore_index=True)
    table = table.sort_values(["subject_id", "trial_id"], kind="mergesort")
    return table.reset_index(drop=True)


def summarize_many_labs_long_table(table: pd.DataFrame) -> dict[str, int]:
    """Return compact local-run diagnostics for the normalized table."""

    return {
        "n_subjects": int(table["subject_id"].nunique()),
        "n_rows": int(len(table)),
        "n_95_trial_subjects": int(table.loc[table["trial_count"].eq(95), "subject_id"].nunique()),
        "n_100_trial_subjects": int(table.loc[table["trial_count"].eq(100), "subject_id"].nunique()),
        "n_150_trial_subjects": int(table.loc[table["trial_count"].eq(150), "subject_id"].nunique()),
        "n_missing_choices": int(table["choice"].isna().sum()),
        "n_missing_rewards": int(table["reward"].isna().sum()),
        "n_missing_losses": int(table["loss"].isna().sum()),
    }


def _load_trial_count(root: Path, n_trials: int) -> pd.DataFrame:
    choices = _read_matrix(root / f"choice_{n_trials}.csv")
    rewards = _read_matrix(root / f"wi_{n_trials}.csv")
    losses = _read_matrix(root / f"lo_{n_trials}.csv")
    index = _read_index(root / f"index_{n_trials}.csv")

    if not (choices.shape == rewards.shape == losses.shape):
        raise ValueError(
            f"Matrix shape mismatch for {n_trials} trials: "
            f"choice={choices.shape}, reward={rewards.shape}, loss={losses.shape}"
        )
    if len(index) != len(choices):
        raise ValueError(
            f"Index row mismatch for {n_trials} trials: "
            f"index={len(index)}, matrix={len(choices)}"
        )

    rows: list[dict[str, object]] = []
    for row_position, row_label in enumerate(choices.index):
        subject_number = _subject_number(row_label)
        study = str(index.iloc[row_position]["Study"])
        subject_id = f"many_labs_{n_trials}_{subject_number:03d}"
        session_id = subject_id
        for trial_offset in range(n_trials):
            trial_id = trial_offset + 1
            reward = float(rewards.iat[row_position, trial_offset])
            signed_loss = float(losses.iat[row_position, trial_offset])
            loss_magnitude = abs(signed_loss)
            rows.append(
                {
                    "subject_id": subject_id,
                    "source_subject_label": str(row_label),
                    "source_subject_number": int(subject_number),
                    "study_id": study,
                    "session_id": session_id,
                    "trial_count": int(n_trials),
                    "trial_id": int(trial_id),
                    "choice": _deck_label(choices.iat[row_position, trial_offset]),
                    "reward": reward,
                    "loss": loss_magnitude,
                    "net_outcome": reward - loss_magnitude,
                }
            )
    return pd.DataFrame(rows)


def _read_matrix(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path, index_col=0)


def _read_index(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path)
    expected = {"Subj", "Study"}
    missing = expected.difference(frame.columns)
    if missing:
        raise ValueError(f"Index file {path} missing columns: {sorted(missing)}")
    return frame


def _subject_number(row_label: object) -> int:
    text = str(row_label)
    if "_" in text:
        text = text.rsplit("_", 1)[-1]
    return int(text)


def _deck_label(value: object) -> str:
    numeric = int(value)
    mapping = {1: "A", 2: "B", 3: "C", 4: "D"}
    if numeric not in mapping:
        raise ValueError(f"Unexpected IGT deck code: {value!r}")
    return mapping[numeric]


if __name__ == "__main__":
    raise SystemExit(main())
