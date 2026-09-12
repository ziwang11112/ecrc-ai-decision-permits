"""Fixed proposal models and participant-grouped prediction helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import MODEL_NAMES
from .data import assign_participant_folds


def model_specifications(seed: int) -> dict[str, dict[str, object]]:
    return {
        "history_baseline": {
            "family": "causal_smoothed_history_rule",
            "fit_required": False,
            "score": "(prior A/B choices + 1) / (prior choices + 2)",
            "uses_current_choice": False,
        },
        "regularised_logistic": {
            "family": "logistic_regression",
            "fit_required": True,
            "imputer": "training-fold median; empty columns retained",
            "scaler": "training-fold StandardScaler",
            "penalty": "L2",
            "C": 1.0,
            "solver": "lbfgs",
            "max_iter": 2_000,
            "random_state": seed,
        },
        "hist_gradient_boosting": {
            "family": "hist_gradient_boosting",
            "fit_required": True,
            "imputer": "training-fold median; empty columns retained",
            "learning_rate": 0.05,
            "max_iter": 200,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 30,
            "l2_regularization": 1.0,
            "early_stopping": False,
            "random_state": seed,
        },
    }


def build_estimator(model_name: str, *, seed: int) -> Pipeline | None:
    if model_name == "history_baseline":
        return None
    if model_name == "regularised_logistic":
        return Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median",
                        keep_empty_features=True,
                        add_indicator=True,
                    ),
                ),
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        C=1.0,
                        solver="lbfgs",
                        max_iter=2_000,
                        random_state=seed,
                    ),
                ),
            ]
        )
    if model_name == "hist_gradient_boosting":
        return Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median",
                        keep_empty_features=True,
                        add_indicator=True,
                    ),
                ),
                (
                    "classifier",
                    HistGradientBoostingClassifier(
                        learning_rate=0.05,
                        max_iter=200,
                        max_leaf_nodes=15,
                        min_samples_leaf=30,
                        l2_regularization=1.0,
                        early_stopping=False,
                        random_state=seed,
                    ),
                ),
            ]
        )
    raise ValueError(f"Unknown model {model_name!r}; expected {MODEL_NAMES}")


def _feature_matrix(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    return frame[feature_columns].apply(pd.to_numeric, errors="coerce")


def fit_model(
    model_name: str,
    train: pd.DataFrame,
    *,
    feature_columns: list[str],
    seed: int,
) -> Any:
    estimator = build_estimator(model_name, seed=seed)
    if estimator is None:
        return None
    y = train["y_true"].to_numpy(dtype=int)
    if np.unique(y).size < 2:
        raise ValueError(f"{model_name}: training fold has only one class")
    estimator.fit(_feature_matrix(train, feature_columns), y)
    return estimator


def predict_scores(
    model_name: str,
    estimator: Any,
    frame: pd.DataFrame,
    *,
    feature_columns: list[str],
) -> np.ndarray:
    if model_name == "history_baseline":
        return frame["history_score"].to_numpy(dtype=float)
    score = estimator.predict_proba(_feature_matrix(frame, feature_columns))[:, 1]
    return np.clip(np.asarray(score, dtype=float), 0.0, 1.0)


def grouped_oof_predictions(
    train_pool: pd.DataFrame,
    *,
    model_name: str,
    feature_columns: list[str],
    n_folds: int,
    seed: int,
) -> pd.DataFrame:
    """Get train-pool predictions without scoring a fitted participant."""

    assignments = assign_participant_folds(train_pool, n_folds=n_folds, seed=seed)
    frames: list[pd.DataFrame] = []
    seen_test_subjects: set[str] = set()
    all_subjects = set(train_pool["subject_id"].astype(str).unique())
    for fold in sorted(assignments["fold"].unique()):
        test_subjects = set(
            assignments.loc[assignments["fold"].eq(fold), "subject_id"].astype(str)
        )
        fit_subjects = all_subjects - test_subjects
        if fit_subjects & test_subjects:
            raise AssertionError("Participant leakage across inner fit/test groups")
        fit = train_pool[train_pool["subject_id"].isin(fit_subjects)]
        test = train_pool[train_pool["subject_id"].isin(test_subjects)].copy()
        estimator = fit_model(
            model_name,
            fit,
            feature_columns=feature_columns,
            seed=seed + int(fold),
        )
        test["score"] = predict_scores(
            model_name,
            estimator,
            test,
            feature_columns=feature_columns,
        )
        test["inner_fold"] = int(fold)
        frames.append(test)
        seen_test_subjects.update(test_subjects)
    if seen_test_subjects != all_subjects:
        raise AssertionError("Inner OOF did not score every participant exactly once")
    result = pd.concat(frames, ignore_index=True)
    key = ["subject_id", "trial_id"]
    if result.duplicated(key).any() or len(result) != len(train_pool):
        raise AssertionError("Inner OOF prediction keys are not one-to-one")
    return result.sort_values(key, kind="mergesort").reset_index(drop=True)


def fit_and_score_outer_fold(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    model_name: str,
    feature_columns: list[str],
    seed: int,
) -> tuple[Any, pd.DataFrame]:
    train_subjects = set(train["subject_id"].astype(str).unique())
    test_subjects = set(test["subject_id"].astype(str).unique())
    if train_subjects & test_subjects:
        raise AssertionError("Participant leakage across outer fit/test groups")
    estimator = fit_model(
        model_name,
        train,
        feature_columns=feature_columns,
        seed=seed,
    )
    scored = test.copy()
    scored["score"] = predict_scores(
        model_name,
        estimator,
        scored,
        feature_columns=feature_columns,
    )
    return estimator, scored


def save_frozen_model(
    model_name: str,
    estimator: Any,
    output_dir: str | Path,
) -> Path | None:
    if estimator is None:
        return None
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{model_name}.joblib"
    joblib.dump(estimator, path, compress=3)
    return path


__all__ = [
    "fit_and_score_outer_fold",
    "fit_model",
    "grouped_oof_predictions",
    "model_specifications",
    "predict_scores",
    "save_frozen_model",
]
