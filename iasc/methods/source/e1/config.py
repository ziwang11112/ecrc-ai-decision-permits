"""Frozen configuration for the E1 cross-model governance experiment."""

from __future__ import annotations

from dataclasses import asdict, dataclass

SCRIPT_VERSION = "1.1.0"
PRIMARY_ROUTES = ("alert", "no_action", "abstain", "human_review")
MODEL_NAMES = ("history_baseline", "regularised_logistic", "hist_gradient_boosting")


@dataclass(frozen=True)
class E1Config:
    """Predeclared settings; no setting is tuned on an evaluation fold."""

    seed: int = 20_260_813
    outer_folds: int = 5
    inner_folds: int = 3
    bootstrap_replicates: int = 2_000
    bootstrap_confidence_level: float = 0.95
    history_windows: tuple[int, ...] = (5, 10, 20)
    block_size: int = 20
    automated_alert_caps: tuple[int, ...] = (2, 4, 6, 8)
    reference_alert_cap: int = 8
    review_cap: int = 2
    review_band_width: float = 0.03
    uncertainty_mode: str = "probability_margin"
    uncertainty_threshold: float = 0.90
    threshold_grid_start: float = 0.30
    threshold_grid_stop: float = 0.85
    threshold_grid_step: float = 0.01
    false_action_limit_per_100: float = 9.0
    action_precision_floor: float = 0.60

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


__all__ = [
    "E1Config",
    "MODEL_NAMES",
    "PRIMARY_ROUTES",
    "SCRIPT_VERSION",
]
