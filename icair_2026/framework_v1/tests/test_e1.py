from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK_ROOT))

from e1.config import PRIMARY_ROUTES  # noqa: E402
from e1.data import (  # noqa: E402
    assert_causal_feature_invariance,
    assign_participant_folds,
    build_causal_history_features,
    model_feature_columns,
)
from e1.routing import assert_label_independent_routing, route_frame  # noqa: E402


def synthetic_behavior(n_subjects: int = 6, n_trials: int = 12) -> pd.DataFrame:
    rows = []
    decks = np.asarray(list("ABCD"))
    for subject_index in range(n_subjects):
        for trial_index in range(n_trials):
            choice = str(decks[(subject_index + trial_index) % len(decks)])
            loss = -250.0 if trial_index % 5 == 0 else 0.0
            reward = 100.0 if choice in {"A", "B"} else 50.0
            rows.append(
                {
                    "dataset_id": "synthetic_behavior",
                    "subject_id": f"p{subject_index:02d}",
                    "study_id": f"s{subject_index % 2}",
                    "trial_id": trial_index + 1,
                    "choice": choice,
                    "reward": reward,
                    "loss_signed": loss,
                    "net_outcome": reward + loss,
                }
            )
    return pd.DataFrame(rows)


def test_current_and_future_suffix_cannot_change_current_features() -> None:
    behavior = synthetic_behavior()
    assert_causal_feature_invariance(
        behavior, windows=(5, 10, 20), block_size=20, maximum_subjects=6
    )
    features = build_causal_history_features(behavior)
    assert "history_score" not in model_feature_columns(features)
    assert not any("eeg" in column.lower() for column in features.columns)


def test_participants_are_assigned_to_one_fold() -> None:
    features = build_causal_history_features(synthetic_behavior())
    assignments = assign_participant_folds(features, n_folds=3, seed=11)
    assert len(assignments) == features["subject_id"].nunique()
    assert not assignments["subject_id"].duplicated().any()
    assert set(assignments["fold"]) == {0, 1, 2}


def test_routes_are_exclusive_capacity_bounded_and_label_independent() -> None:
    frame = pd.DataFrame(
        {
            "subject_id": ["p1"] * 8 + ["p2"] * 8,
            "trial_id": list(range(1, 9)) * 2,
            "score": [0.95, 0.92, 0.88, 0.63, 0.61, 0.50, 0.20, 0.90] * 2,
            "y_true": [1, 0, 1, 1, 0, 1, 0, 1] * 2,
        }
    )
    kwargs = {
        "prompt_threshold": 0.60,
        "automated_alert_cap": 2,
        "review_cap": 1,
        "review_band_width": 0.03,
        "uncertainty_threshold": 0.90,
        "uncertainty_mode": "probability_margin",
    }
    routed = route_frame(frame, **kwargs)
    flags = [f"route_{route}" for route in PRIMARY_ROUTES]
    assert routed[flags].sum(axis=1).eq(1).all()
    assert routed.groupby("subject_id")["route_alert"].sum().le(2).all()
    assert routed.groupby("subject_id")["route_human_review"].sum().le(1).all()
    assert_label_independent_routing(frame, **kwargs)
