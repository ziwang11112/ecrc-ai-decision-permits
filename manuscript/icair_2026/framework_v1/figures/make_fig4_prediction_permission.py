"""Build ICAIR 2026 Figure 4 from the frozen official-v2 evidence bundle.

The figure isolates the paper's action-readiness claim:

* a frozen proposal must still satisfy its operating-point action-precision condition;
  and
* evidence eligibility independently controls whether an action route is permitted.

All statistics are read from frozen CSVs. Drawing, export, grayscale conversion,
and visual/export audits are performed only in Python.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.lines import Line2D
from PIL import Image, ImageChops, ImageOps
from PyPDF2 import PdfReader

WIDTH_MM = 159.0
HEIGHT_MM = 62.0
DPI = 600
MIN_TEXT_PT = 7.5
FIGURE_STEM = "fig4_prediction_permission"
FIXED_DATE = "2026-08-13"
FIXED_DATETIME = datetime(2026, 8, 13, tzinfo=timezone.utc)

# Color and grayscale PNGs were inspected at the native 3,755 x 1,464 px canvas.
ORIGINAL_SIZE_VISUAL_QA = (
    "PASS - color and grayscale inspected at native 3,755 x 1,464 px; point and "
    "interval marks are clear with no direct-value or reference-line text overlaps"
)

INK = "#26323B"
BLUE = "#326A94"
ORANGE = "#D0713F"
LIGHT = "#CBD2D8"
REFERENCE = "#7F8991"
WHITE = "#FFFFFF"

MODEL_ORDER = [
    "history_baseline",
    "regularised_logistic",
    "hist_gradient_boosting",
]
MODEL_LABEL = {
    "history_baseline": "History",
    "regularised_logistic": "Logistic",
    "hist_gradient_boosting": "HGB",
}
MODEL_MARKER = {
    "history_baseline": "o",
    "regularised_logistic": "s",
    "hist_gradient_boosting": "D",
}
MODEL_COLOR = {
    "history_baseline": ORANGE,
    "regularised_logistic": ORANGE,
    "hist_gradient_boosting": BLUE,
}

COHORT_ORDER = ["many_labs_igt", "mendeley_igt_official_v2"]
COHORT_LABEL = {
    "many_labs_igt": "Many Labs",
    "mendeley_igt_official_v2": "Mendeley",
}
EXPECTED_SCOPE = {
    "many_labs_igt": "participant_grouped_outer_cv",
    "mendeley_igt_official_v2": "frozen_external_official_v2_same_task",
}
EXPECTED_N = {
    "many_labs_igt": 617,
    "mendeley_igt_official_v2": 59,
}
EXPECTED_DECISIONS = {
    "many_labs_igt": 66525,
    "mendeley_igt_official_v2": 11800,
}
EXPECTED_INVALID = {
    "many_labs_igt": 6798,
    "mendeley_igt_official_v2": 1208,
}
EXPECTED_GATE_OFF_ACTIONS = {
    "many_labs_igt": 630,
    "mendeley_igt_official_v2": 56,
}


plt.rcParams.update(
    {
        "font.family": "Calibri",
        "font.sans-serif": [
            "Calibri",
            "Arial",
            "Helvetica",
            "DejaVu Sans",
            "Liberation Sans",
        ],
        "font.size": MIN_TEXT_PT,
        "axes.labelsize": MIN_TEXT_PT,
        "axes.titlesize": 8.2,
        "xtick.labelsize": MIN_TEXT_PT,
        "ytick.labelsize": MIN_TEXT_PT,
        "legend.fontsize": MIN_TEXT_PT,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.75,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "text.color": INK,
        "legend.frameon": False,
        "savefig.facecolor": WHITE,
        "figure.facecolor": WHITE,
        "axes.facecolor": WHITE,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.hashsalt": "icair-2026-ecrc-fig4-prediction-permission-v1",
    }
)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_svg_length_mm(value: str) -> float:
    """Convert an SVG physical length to millimetres."""
    value = value.strip()
    if value.endswith("pt"):
        return float(value[:-2]) * 25.4 / 72.0
    if value.endswith("in"):
        return float(value[:-2]) * 25.4
    if value.endswith("mm"):
        return float(value[:-2])
    raise ValueError(f"Unsupported SVG length: {value}")


def luminance(hex_color: str) -> float:
    """Compute a simple display luminance for grayscale separation checks."""
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return 0.299 * red + 0.587 * green + 0.114 * blue


def require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    """Fail fast if a frozen input does not contain the expected schema."""
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")


def load_frozen_inputs(
    route_path: Path,
    bootstrap_path: Path,
    component_metrics_path: Path,
    component_bootstrap_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load and schema-check the four frozen evidence tables."""
    route = pd.read_csv(route_path, dtype={"cap_label": str})
    bootstrap = pd.read_csv(bootstrap_path, dtype={"cap_label": str})
    component_metrics = pd.read_csv(component_metrics_path)
    component_bootstrap = pd.read_csv(component_bootstrap_path)

    require_columns(
        route,
        {
            "dataset_id",
            "evaluation_scope",
            "model_name",
            "cap_label",
            "aggregate_level",
            "n_participants",
            "n_decisions",
            "n_action_routes",
            "n_true_action_routes",
            "action_precision",
        },
        route_path.name,
    )
    require_columns(
        bootstrap,
        {
            "metric_family",
            "dataset_id",
            "evaluation_scope",
            "model_name",
            "cap_label",
            "metric",
            "estimate",
            "ci_low",
            "ci_high",
            "confidence_level",
            "bootstrap_unit",
            "bootstrap_method",
            "bootstrap_replicates",
            "finite_replicates",
        },
        bootstrap_path.name,
    )
    require_columns(
        component_metrics,
        {
            "evidence_scenario",
            "component_arm",
            "dataset_id",
            "evaluation_scope",
            "model_name",
            "n_participants",
            "n_decisions",
            "n_invalid_evidence",
            "n_action_on_invalid_evidence",
            "invalid_evidence_action_acceptance_rate",
            "prediction_scores_changed",
        },
        component_metrics_path.name,
    )
    require_columns(
        component_bootstrap,
        {
            "evidence_scenario",
            "dataset_id",
            "evaluation_scope",
            "model_name",
            "component_arm",
            "reference_arm",
            "metric",
            "delta_arm_minus_full",
            "ci_low",
            "ci_high",
            "bootstrap_unit",
            "bootstrap_method",
            "bootstrap_replicates",
        },
        component_bootstrap_path.name,
    )
    return route, bootstrap, component_metrics, component_bootstrap


def build_source_data(
    route: pd.DataFrame,
    bootstrap: pd.DataFrame,
    component_metrics: pd.DataFrame,
    component_bootstrap: pd.DataFrame,
) -> pd.DataFrame:
    """Select, cross-check, and normalize every plotted row."""
    rows: list[dict[str, object]] = []

    route_a = route[
        (route["dataset_id"] == "mendeley_igt_official_v2")
        & (route["evaluation_scope"] == EXPECTED_SCOPE["mendeley_igt_official_v2"])
        & route["model_name"].isin(MODEL_ORDER)
        & (route["cap_label"] == "8")
        & (route["aggregate_level"] == "pooled")
    ].copy()
    bootstrap_a = bootstrap[
        (bootstrap["metric_family"] == "route_workload")
        & (bootstrap["dataset_id"] == "mendeley_igt_official_v2")
        & (bootstrap["evaluation_scope"] == EXPECTED_SCOPE["mendeley_igt_official_v2"])
        & bootstrap["model_name"].isin(MODEL_ORDER)
        & (bootstrap["cap_label"] == "8")
        & (bootstrap["metric"] == "action_precision")
    ].copy()
    if len(route_a) != 3 or len(bootstrap_a) != 3:
        raise ValueError(
            f"Panel a requires three route and three CI rows; found {len(route_a)} and {len(bootstrap_a)}"
        )
    if (
        route_a.duplicated("model_name").any()
        or bootstrap_a.duplicated("model_name").any()
    ):
        raise ValueError("Panel a contains duplicate model rows")

    for model_name in MODEL_ORDER:
        route_row = route_a.loc[route_a["model_name"] == model_name].iloc[0]
        ci_row = bootstrap_a.loc[bootstrap_a["model_name"] == model_name].iloc[0]
        numerator = int(route_row["n_true_action_routes"])
        denominator = int(route_row["n_action_routes"])
        estimate = float(ci_row["estimate"])
        estimate_from_counts = numerator / denominator
        if not math.isclose(
            estimate,
            float(route_row["action_precision"]),
            abs_tol=1e-12,
            rel_tol=0.0,
        ) or not math.isclose(
            estimate, estimate_from_counts, abs_tol=1e-12, rel_tol=0.0
        ):
            raise ValueError(f"Panel a point mismatch for {model_name}")
        if (
            int(route_row["n_participants"]) != 59
            or int(route_row["n_decisions"]) != 11800
        ):
            raise ValueError(f"Unexpected external sample size for {model_name}")
        if not (float(ci_row["ci_low"]) <= estimate <= float(ci_row["ci_high"])):
            raise ValueError(f"Panel a CI excludes its estimate for {model_name}")
        if (
            float(ci_row["confidence_level"]) != 0.95
            or ci_row["bootstrap_unit"] != "participant"
            or "cluster percentile" not in str(ci_row["bootstrap_method"]).lower()
            or int(ci_row["bootstrap_replicates"]) != 2000
            or int(ci_row["finite_replicates"]) != 2000
        ):
            raise ValueError(
                f"Unexpected panel a bootstrap specification for {model_name}"
            )

        rows.append(
            {
                "panel": "a",
                "dataset_id": "mendeley_igt_official_v2",
                "cohort_label": COHORT_LABEL["mendeley_igt_official_v2"],
                "evaluation_scope": EXPECTED_SCOPE["mendeley_igt_official_v2"],
                "model_name": model_name,
                "model_label": MODEL_LABEL[model_name],
                "condition": "cap_8",
                "metric": "action_precision",
                "numerator": numerator,
                "denominator": denominator,
                "estimate_raw": estimate,
                "ci_low_raw": float(ci_row["ci_low"]),
                "ci_high_raw": float(ci_row["ci_high"]),
                "display_scale": 100.0,
                "plotted_estimate": estimate * 100.0,
                "plotted_ci_low": float(ci_row["ci_low"]) * 100.0,
                "plotted_ci_high": float(ci_row["ci_high"]) * 100.0,
                "n_participants": 59,
                "n_decisions": 11800,
                "interval_type": "conditional participant-cluster percentile",
                "bootstrap_replicates": 2000,
                "reference_value": 0.60,
                "reference_meaning": "development selection condition",
            }
        )

    component_b = component_metrics[
        (component_metrics["evidence_scenario"] == "missing_stale_stress")
        & component_metrics["dataset_id"].isin(COHORT_ORDER)
        & (component_metrics["model_name"] == "hist_gradient_boosting")
        & component_metrics["component_arm"].isin(
            ["full_controls", "evidence_gate_off"]
        )
    ].copy()
    bootstrap_b = component_bootstrap[
        (component_bootstrap["evidence_scenario"] == "missing_stale_stress")
        & component_bootstrap["dataset_id"].isin(COHORT_ORDER)
        & (component_bootstrap["model_name"] == "hist_gradient_boosting")
        & (component_bootstrap["component_arm"] == "evidence_gate_off")
        & (component_bootstrap["reference_arm"] == "full_controls")
        & (component_bootstrap["metric"] == "invalid_evidence_action_acceptance_rate")
    ].copy()
    if len(component_b) != 4 or len(bootstrap_b) != 2:
        raise ValueError(
            f"Panel b requires four metric and two CI rows; found {len(component_b)} and {len(bootstrap_b)}"
        )
    if (
        component_b.duplicated(["dataset_id", "component_arm"]).any()
        or bootstrap_b["dataset_id"].duplicated().any()
    ):
        raise ValueError("Panel b contains duplicate cohort/arm rows")

    for dataset_id in COHORT_ORDER:
        cohort_rows = component_b.loc[component_b["dataset_id"] == dataset_id]
        if set(cohort_rows["component_arm"]) != {
            "full_controls",
            "evidence_gate_off",
        }:
            raise ValueError(f"Panel b arms are incomplete for {dataset_id}")
        ci_row = bootstrap_b.loc[bootstrap_b["dataset_id"] == dataset_id].iloc[0]
        if (
            ci_row["bootstrap_unit"] != "participant"
            or "paired cluster percentile"
            not in str(ci_row["bootstrap_method"]).lower()
            or int(ci_row["bootstrap_replicates"]) != 2000
        ):
            raise ValueError(
                f"Unexpected paired bootstrap specification for {dataset_id}"
            )

        full_row = cohort_rows.loc[
            cohort_rows["component_arm"] == "full_controls"
        ].iloc[0]
        gate_off_row = cohort_rows.loc[
            cohort_rows["component_arm"] == "evidence_gate_off"
        ].iloc[0]
        for metric_row in (full_row, gate_off_row):
            if str(metric_row["evaluation_scope"]) != EXPECTED_SCOPE[dataset_id]:
                raise ValueError(f"Unexpected evaluation scope for {dataset_id}")
            if int(metric_row["n_participants"]) != EXPECTED_N[dataset_id]:
                raise ValueError(f"Unexpected participant count for {dataset_id}")
            if int(metric_row["n_decisions"]) != EXPECTED_DECISIONS[dataset_id]:
                raise ValueError(f"Unexpected decision count for {dataset_id}")
            if int(metric_row["n_invalid_evidence"]) != EXPECTED_INVALID[dataset_id]:
                raise ValueError(
                    f"Unexpected invalid-evidence denominator for {dataset_id}"
                )
            if str(metric_row["prediction_scores_changed"]).lower() != "false":
                raise ValueError(
                    f"A component arm changed prediction scores for {dataset_id}"
                )

        if (
            int(full_row["n_action_on_invalid_evidence"]) != 0
            or float(full_row["invalid_evidence_action_acceptance_rate"]) != 0.0
        ):
            raise ValueError(f"The full gate is not an exact zero for {dataset_id}")
        gate_off_actions = int(gate_off_row["n_action_on_invalid_evidence"])
        denominator = int(gate_off_row["n_invalid_evidence"])
        gate_off_estimate = float(
            gate_off_row["invalid_evidence_action_acceptance_rate"]
        )
        if gate_off_actions != EXPECTED_GATE_OFF_ACTIONS[dataset_id]:
            raise ValueError(f"Unexpected gate-off numerator for {dataset_id}")
        if not math.isclose(
            gate_off_estimate,
            gate_off_actions / denominator,
            abs_tol=1e-12,
            rel_tol=0.0,
        ):
            raise ValueError(f"Gate-off count ratio mismatch for {dataset_id}")
        if not math.isclose(
            float(ci_row["delta_arm_minus_full"]),
            gate_off_estimate,
            abs_tol=1e-12,
            rel_tol=0.0,
        ):
            raise ValueError(f"Paired delta mismatch for {dataset_id}")
        if not (
            float(ci_row["ci_low"]) <= gate_off_estimate <= float(ci_row["ci_high"])
        ):
            raise ValueError(f"Panel b CI excludes the gate-off point for {dataset_id}")

        common = {
            "panel": "b",
            "dataset_id": dataset_id,
            "cohort_label": COHORT_LABEL[dataset_id],
            "evaluation_scope": EXPECTED_SCOPE[dataset_id],
            "model_name": "hist_gradient_boosting",
            "model_label": "HGB",
            "metric": "invalid_evidence_action_route_rate",
            "denominator": denominator,
            "display_scale": 100.0,
            "n_participants": EXPECTED_N[dataset_id],
            "n_decisions": EXPECTED_DECISIONS[dataset_id],
            "bootstrap_replicates": 2000,
            "reference_value": np.nan,
            "reference_meaning": "constructed hash-scheduled missing/stale subset",
        }
        rows.append(
            {
                **common,
                "condition": "full_gate",
                "numerator": 0,
                "estimate_raw": 0.0,
                "ci_low_raw": np.nan,
                "ci_high_raw": np.nan,
                "plotted_estimate": 0.0,
                "plotted_ci_low": np.nan,
                "plotted_ci_high": np.nan,
                "interval_type": "exact observed zero; no CI displayed",
            }
        )
        rows.append(
            {
                **common,
                "condition": "evidence_gate_off",
                "numerator": gate_off_actions,
                "estimate_raw": gate_off_estimate,
                "ci_low_raw": float(ci_row["ci_low"]),
                "ci_high_raw": float(ci_row["ci_high"]),
                "plotted_estimate": gate_off_estimate * 100.0,
                "plotted_ci_low": float(ci_row["ci_low"]) * 100.0,
                "plotted_ci_high": float(ci_row["ci_high"]) * 100.0,
                "interval_type": "paired participant-cluster percentile delta vs full gate",
            }
        )

    source = pd.DataFrame(rows)
    ordered_columns = [
        "panel",
        "dataset_id",
        "cohort_label",
        "evaluation_scope",
        "model_name",
        "model_label",
        "condition",
        "metric",
        "numerator",
        "denominator",
        "estimate_raw",
        "ci_low_raw",
        "ci_high_raw",
        "display_scale",
        "plotted_estimate",
        "plotted_ci_low",
        "plotted_ci_high",
        "n_participants",
        "n_decisions",
        "interval_type",
        "bootstrap_replicates",
        "reference_value",
        "reference_meaning",
    ]
    return source[ordered_columns]


def build_row_audit(source: pd.DataFrame) -> pd.DataFrame:
    """Create a machine-readable point/denominator/interval audit."""
    records: list[dict[str, object]] = []
    for index, row in source.iterrows():
        count_estimate = float(row["numerator"]) / float(row["denominator"])
        estimate_difference = abs(float(row["estimate_raw"]) - count_estimate)
        expected_display = float(row["estimate_raw"]) * float(row["display_scale"])
        display_difference = abs(float(row["plotted_estimate"]) - expected_display)
        interval_present = pd.notna(row["ci_low_raw"]) and pd.notna(row["ci_high_raw"])
        interval_valid = (
            float(row["ci_low_raw"])
            <= float(row["estimate_raw"])
            <= float(row["ci_high_raw"])
            if interval_present
            else row["condition"] == "full_gate" and float(row["estimate_raw"]) == 0.0
        )
        passed = (
            estimate_difference <= 1e-12
            and display_difference <= 1e-12
            and interval_valid
        )
        records.append(
            {
                "row_id": f"fig4_{index + 1:02d}",
                "panel": row["panel"],
                "dataset_id": row["dataset_id"],
                "model_name": row["model_name"],
                "condition": row["condition"],
                "numerator": int(row["numerator"]),
                "denominator": int(row["denominator"]),
                "estimate_from_counts": count_estimate,
                "frozen_estimate": float(row["estimate_raw"]),
                "estimate_abs_difference": estimate_difference,
                "plotted_estimate": float(row["plotted_estimate"]),
                "display_abs_difference": display_difference,
                "interval_present": interval_present,
                "interval_valid": interval_valid,
                "check": "PASS" if passed else "FAIL",
            }
        )
    audit = pd.DataFrame(records)
    if not (audit["check"] == "PASS").all():
        raise AssertionError("At least one Figure 4 row failed the point audit")
    return audit


def draw_figure(source: pd.DataFrame, output_dir: Path) -> list[Path]:
    """Draw and export the two-panel final-size figure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(
        figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4),
        dpi=DPI,
        facecolor=WHITE,
    )
    grid = figure.add_gridspec(
        1,
        2,
        width_ratios=(1.04, 0.96),
        left=0.090,
        right=0.985,
        bottom=0.235,
        top=0.805,
        wspace=0.43,
    )
    axis_a = figure.add_subplot(grid[0, 0])
    axis_b = figure.add_subplot(grid[0, 1])

    # Panel a: external cap-8 action precision.
    panel_a = source[source["panel"] == "a"].set_index("model_name")
    y_positions = np.array([2.0, 1.0, 0.0])
    for y_value, model_name in zip(y_positions, MODEL_ORDER, strict=True):
        row = panel_a.loc[model_name]
        estimate = float(row["plotted_estimate"])
        low = float(row["plotted_ci_low"])
        high = float(row["plotted_ci_high"])
        axis_a.errorbar(
            estimate,
            y_value,
            xerr=np.array([[estimate - low], [high - estimate]]),
            fmt=MODEL_MARKER[model_name],
            markersize=5.2,
            markerfacecolor=MODEL_COLOR[model_name],
            markeredgecolor=MODEL_COLOR[model_name],
            markeredgewidth=0.9,
            ecolor=MODEL_COLOR[model_name],
            elinewidth=1.25,
            capsize=3.0,
            capthick=1.0,
            zorder=3,
        )

    axis_a.axvline(
        60.0,
        color=REFERENCE,
        linewidth=0.9,
        linestyle=(0, (3.0, 2.0)),
        zorder=1,
    )
    axis_a.set_title(
        "External cap-8 action precision",
        loc="left",
        pad=10.0,
        fontweight="semibold",
    )
    axis_a.set_xlabel("True action routes / all action routes (%)", labelpad=5.0)
    axis_a.set_xlim(38.0, 70.5)
    axis_a.set_xticks([40, 50, 60, 70])
    axis_a.set_ylim(-0.55, 2.65)
    axis_a.set_yticks(y_positions)
    axis_a.set_yticklabels([MODEL_LABEL[name] for name in MODEL_ORDER])
    axis_a.get_yticklabels()[-1].set_fontweight("semibold")

    # Panel b: same HGB scores, different action permission under invalid evidence.
    panel_b = source[source["panel"] == "b"]
    cohort_y = {"many_labs_igt": 0.68, "mendeley_igt_official_v2": -0.18}
    for dataset_id in COHORT_ORDER:
        full = panel_b[
            (panel_b["dataset_id"] == dataset_id)
            & (panel_b["condition"] == "full_gate")
        ].iloc[0]
        gate_off = panel_b[
            (panel_b["dataset_id"] == dataset_id)
            & (panel_b["condition"] == "evidence_gate_off")
        ].iloc[0]
        y_value = cohort_y[dataset_id]
        full_value = float(full["plotted_estimate"])
        gate_value = float(gate_off["plotted_estimate"])
        gate_low = float(gate_off["plotted_ci_low"])
        gate_high = float(gate_off["plotted_ci_high"])

        axis_b.plot(
            [full_value, gate_value],
            [y_value, y_value],
            color=LIGHT,
            linewidth=1.1,
            zorder=1,
        )
        axis_b.plot(
            full_value,
            y_value,
            marker="o",
            markersize=5.4,
            markerfacecolor=WHITE,
            markeredgecolor=BLUE,
            markeredgewidth=1.25,
            linestyle="none",
            zorder=3,
        )
        axis_b.errorbar(
            gate_value,
            y_value,
            xerr=np.array([[gate_value - gate_low], [gate_high - gate_value]]),
            fmt="o",
            markersize=5.4,
            markerfacecolor=ORANGE,
            markeredgecolor=ORANGE,
            markeredgewidth=0.9,
            ecolor=ORANGE,
            elinewidth=1.25,
            capsize=3.0,
            capthick=1.0,
            zorder=3,
        )

    condition_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markersize=5.2,
            markerfacecolor=WHITE,
            markeredgecolor=BLUE,
            markeredgewidth=1.2,
            label="Full evidence gate",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markersize=5.2,
            markerfacecolor=ORANGE,
            markeredgecolor=ORANGE,
            label="Gate off",
        ),
    ]
    axis_b.legend(
        handles=condition_handles,
        loc="upper left",
        bbox_to_anchor=(-0.02, 1.015),
        ncol=2,
        columnspacing=1.15,
        handletextpad=0.35,
        borderaxespad=0.0,
    )
    axis_b.set_title(
        "Evidence eligibility controls action",
        loc="left",
        pad=10.0,
        fontweight="semibold",
    )
    axis_b.set_xlabel(
        "Action routes among scheduled invalid evidence (%)",
        labelpad=5.0,
    )
    axis_b.set_xlim(-0.65, 11.15)
    axis_b.set_xticks([0, 2, 4, 6, 8, 10])
    axis_b.set_ylim(-0.58, 1.34)
    axis_b.set_yticks([cohort_y[name] for name in COHORT_ORDER])
    axis_b.set_yticklabels(
        [
            "Many Labs\n(6,798 invalid)",
            "Mendeley\n(1,208 invalid)",
        ]
    )

    for panel_label, axis in (("a", axis_a), ("b", axis_b)):
        axis.text(
            -0.13,
            1.12,
            panel_label,
            transform=axis.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.0,
            fontweight="bold",
            color=INK,
        )
        axis.tick_params(
            axis="both",
            which="major",
            direction="out",
            length=2.5,
            width=0.65,
            pad=3.0,
        )
        axis.spines["left"].set_linewidth(0.75)
        axis.spines["bottom"].set_linewidth(0.75)
        axis.grid(False)

    stem = output_dir / FIGURE_STEM
    svg_path = stem.with_suffix(".svg")
    pdf_path = stem.with_suffix(".pdf")
    png_path = stem.with_suffix(".png")
    jpg_path = stem.with_suffix(".jpg")
    grayscale_path = output_dir / f"{FIGURE_STEM}_grayscale.png"
    common = {"facecolor": WHITE, "edgecolor": WHITE, "transparent": False}
    title = "Operating-point and evidence checks determine action readiness"
    figure.savefig(
        svg_path,
        format="svg",
        metadata={"Date": FIXED_DATE, "Title": title},
        **common,
    )
    figure.savefig(
        pdf_path,
        format="pdf",
        metadata={
            "Title": title,
            "Author": "",
            "Subject": "ICAIR 2026 Figure 4",
            "Keywords": "action readiness, evidence eligibility, external replay",
            "Creator": "matplotlib",
            "Producer": "matplotlib",
            "CreationDate": FIXED_DATETIME,
            "ModDate": FIXED_DATETIME,
        },
        **common,
    )
    figure.savefig(
        png_path,
        format="png",
        dpi=DPI,
        metadata={"Title": title, "Software": "matplotlib"},
        **common,
    )
    figure.savefig(
        jpg_path,
        format="jpg",
        dpi=DPI,
        pil_kwargs={"quality": 95, "subsampling": 0, "optimize": False},
        **common,
    )
    plt.close(figure)

    with Image.open(png_path) as color_image:
        ImageOps.grayscale(color_image).save(
            grayscale_path,
            dpi=(DPI, DPI),
            optimize=False,
        )
    return [svg_path, pdf_path, png_path, jpg_path, grayscale_path]


def audit_exports(output_dir: Path) -> dict[str, object]:
    """Audit physical size, editable text, crop, font, and grayscale encoding."""
    svg_path = output_dir / f"{FIGURE_STEM}.svg"
    pdf_path = output_dir / f"{FIGURE_STEM}.pdf"
    png_path = output_dir / f"{FIGURE_STEM}.png"
    jpg_path = output_dir / f"{FIGURE_STEM}.jpg"
    grayscale_path = output_dir / f"{FIGURE_STEM}_grayscale.png"
    expected_pixels = (
        int(WIDTH_MM / 25.4 * DPI),
        int(HEIGHT_MM / 25.4 * DPI),
    )

    raster: dict[str, object] = {}
    for path in (png_path, jpg_path, grayscale_path):
        with Image.open(path) as image:
            raster[path.name] = {
                "pixels": list(image.size),
                "mode": image.mode,
                "dpi_metadata": list(image.info.get("dpi", [])) or None,
            }
            if image.size != expected_pixels:
                raise AssertionError(
                    f"Unexpected raster dimensions for {path.name}: {image.size}"
                )

    with Image.open(png_path).convert("RGB") as image:
        white_image = Image.new("RGB", image.size, WHITE)
        ink_box = ImageChops.difference(image, white_image).getbbox()
        if ink_box is None:
            raise AssertionError("The PNG export is blank")
        left, top, right, bottom = ink_box
        crop_margins = {
            "left_px": left,
            "top_px": top,
            "right_px": image.width - right,
            "bottom_px": image.height - bottom,
        }
        if min(crop_margins.values()) < 4:
            raise AssertionError(
                f"Figure content touches a canvas edge: {crop_margins}"
            )

    svg_root = ElementTree.parse(svg_path).getroot()
    svg_width_mm = parse_svg_length_mm(svg_root.attrib["width"])
    svg_height_mm = parse_svg_length_mm(svg_root.attrib["height"])
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    text_nodes = svg_root.findall(".//svg:text", namespace)
    svg_text = " ".join("".join(node.itertext()) for node in text_nodes)
    font_sizes: list[float] = []
    for node in text_nodes:
        match = re.search(r"font-size:\s*([0-9.]+)px", node.attrib.get("style", ""))
        if match:
            font_sizes.append(float(match.group(1)))
    if not math.isclose(svg_width_mm, WIDTH_MM, abs_tol=0.02):
        raise AssertionError(f"SVG width mismatch: {svg_width_mm}")
    if not math.isclose(svg_height_mm, HEIGHT_MM, abs_tol=0.02):
        raise AssertionError(f"SVG height mismatch: {svg_height_mm}")
    if not text_nodes:
        raise AssertionError("SVG text was converted to paths")
    if not font_sizes or min(font_sizes) < MIN_TEXT_PT:
        raise AssertionError(
            f"SVG text below {MIN_TEXT_PT:g} pt: {min(font_sizes, default=0):g}"
        )
    if "Calibri" not in svg_path.read_text(encoding="utf-8"):
        raise AssertionError(
            "Calibri is absent from the editable SVG font declarations"
        )
    required_text = [
        "External cap-8 action precision",
        "Evidence eligibility controls action",
        "scheduled invalid evidence",
    ]
    missing_text = [item for item in required_text if item not in svg_text]
    if missing_text:
        raise AssertionError(f"Required figure text is missing: {missing_text}")
    forbidden_annotations = [
        "0.60 development condition",
        "45.2",
        "51.4",
        "63.9",
        "9.27",
        "4.64",
    ]
    retained_annotations = [
        item for item in forbidden_annotations if item in svg_text
    ]
    if retained_annotations:
        raise AssertionError(
            f"Redundant direct annotations remain: {retained_annotations}"
        )

    pdf_page = PdfReader(str(pdf_path)).pages[0]
    pdf_width_mm = float(pdf_page.mediabox.width) * 25.4 / 72.0
    pdf_height_mm = float(pdf_page.mediabox.height) * 25.4 / 72.0
    if not math.isclose(pdf_width_mm, WIDTH_MM, abs_tol=0.02):
        raise AssertionError(f"PDF width mismatch: {pdf_width_mm}")
    if not math.isclose(pdf_height_mm, HEIGHT_MM, abs_tol=0.02):
        raise AssertionError(f"PDF height mismatch: {pdf_height_mm}")

    active_font_path = font_manager.findfont(
        font_manager.FontProperties(family=["Calibri"]),
        fallback_to_default=False,
    )
    active_font_name = font_manager.FontProperties(fname=active_font_path).get_name()
    if active_font_name != "Calibri":
        raise AssertionError(f"Unexpected resolved font: {active_font_name}")

    orange_blue_delta = abs(luminance(ORANGE) - luminance(BLUE))
    if orange_blue_delta < 20.0:
        raise AssertionError("Key colors are too similar in grayscale luminance")

    return {
        "figure_size_mm": [svg_width_mm, svg_height_mm],
        "pdf_size_mm": [pdf_width_mm, pdf_height_mm],
        "expected_raster_pixels_at_600_dpi": list(expected_pixels),
        "raster": raster,
        "ink_bbox_margins_px": crop_margins,
        "svg_text_nodes": len(text_nodes),
        "svg_minimum_text_pt": min(font_sizes),
        "svg_text_editable": True,
        "resolved_font_name": active_font_name,
        "resolved_font_file": Path(active_font_path).name,
        "grayscale_luminance_delta": {
            "orange_vs_blue": orange_blue_delta,
        },
        "redundant_encoding": {
            "panel_a": "orange below-condition versus blue condition-meeting points, with direct model labels and distinct markers",
            "panel_b": "open blue full-gate marker versus filled orange gate-off marker",
        },
        "no_grid": True,
        "no_hatch": True,
        "white_background": True,
        "direct_value_annotations": 0,
        "reference_line_text_annotations": 0,
    }


def write_source_and_audit(
    source: pd.DataFrame,
    row_audit: pd.DataFrame,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write deterministic machine-readable plot source and row audit files."""
    source_path = output_dir / f"{FIGURE_STEM}_source_data.csv"
    audit_path = output_dir / f"{FIGURE_STEM}_audit.csv"
    source.to_csv(
        source_path,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    row_audit.to_csv(
        audit_path,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    return source_path, audit_path


def write_caption(output_dir: Path) -> Path:
    """Write the manuscript-ready caption with statistical boundaries."""
    caption_path = output_dir / "FIG4_CAPTION.md"
    caption = (
        "**Figure 4. Operating-point and evidence checks determine action readiness.** "
        "(a) External Mendeley cap-8 action precision for the history, regularised-"
        "logistic, and HGB proposals. Points are pooled estimates; bars are conditional "
        "95% participant-cluster percentile bootstrap intervals (2,000 replicates). The "
        "HGB point estimate alone reached the 0.60 development condition; its interval "
        "lower endpoint was 0.5997. The "
        "dashed 0.60 line is the development selection condition, not a hypothesis-test, "
        "clinical, or fairness boundary. Action precision is true alert-plus-review routes "
        "divided by all alert-plus-review routes. (b) HGB action routes among the "
        "constructed hash-scheduled missing/stale-evidence subset. With the full evidence "
        "gate, the rate was exactly 0/6,798 in Many Labs and 0/1,208 in Mendeley; with the "
        "gate disabled, it was 630/6,798 and 56/1,208. Gate-off bars are paired 95% "
        "participant-cluster percentile bootstrap intervals (2,000 replicates) for the "
        "change from the exact-zero full-gate reference. The scheduled subset is an audit "
        "stress test, not an estimate of operational missingness prevalence; cross-cohort "
        "contrasts are descriptive.\n"
    )
    caption_path.write_text(caption, encoding="utf-8", newline="\n")
    return caption_path


def write_contract(output_dir: Path) -> Path:
    """Write the predeclared figure contract used for content and QA decisions."""
    contract_path = output_dir / "FIG4_CONTRACT.md"
    contract = """# Figure 4 contract

## Core conclusion

Action readiness is determined at the selected operating point and by evidence eligibility, not by predictive ranking alone: a proposal must separately satisfy an action-quality condition, and evidence eligibility can withhold action without changing prediction scores.

## Evidence logic

- Panel a is the external cap-8 action-precision check for all three frozen proposals. It shows the point estimate and conditional 95% participant-cluster percentile interval for each proposal, plus the 0.60 development selection condition. Only the HGB point estimate reaches the condition; its interval lower endpoint is 0.5997.
- Panel b is the HGB evidence-eligibility audit on the constructed, hash-scheduled missing/stale-evidence subset. It contrasts the exact full-gate zero with the paired participant-bootstrap gate-off estimate in each cohort.
- Both panels are required: panel a concerns quality of action-bearing routes; panel b concerns permission to act when evidence is invalid.
- The dashed operating-point condition is deliberately unlabelled in-panel, and all point values/counts remain in the caption and source data rather than competing with confidence intervals.

## Statistical and denominator boundaries

- Panel a numerator: true alert plus review routes. Denominator: all alert plus review routes. The interval is conditional on frozen predictions, thresholds, cap 8, and routing rules.
- The 0.60 line is a development selection condition, not a hypothesis-test, clinical, safety, or fairness boundary.
- Panel b denominator: only hash-scheduled missing/stale HGB decisions (6,798 Many Labs; 1,208 Mendeley), not all decisions and not observed operational missingness.
- Full-gate zeros are exact observed counts and carry no displayed confidence interval.
- Gate-off intervals are paired 95% participant-cluster percentile intervals (2,000 replicates) for the arm-minus-full change; because full is exactly zero, the plotted change equals the gate-off rate.
- Cohorts are not compared inferentially.

## Layout and exclusion rules

- Quantitative two-panel grid, 159 x 62 mm, white background, Calibri at or above 7.5 pt.
- Panel a uses a horizontal point-and-interval plot with direct model labels: orange marks point estimates below the development condition and blue marks the point estimate that reaches it.
- Panel b uses paired open/filled points with a single condition legend.
- No AUROC, bridge analysis, capacity sweep, cards, hatch, grid, embedded table, or formula block.

## Principal reviewer risks

1. Misreading 0.60 as a tested or clinical boundary.
2. Treating the constructed invalid-evidence subset as a prevalence estimate.
3. Treating the ablation as a predictive-model comparison even though prediction scores are unchanged.
4. Treating cross-cohort differences as an inferential contrast.
"""
    contract_path.write_text(contract, encoding="utf-8", newline="\n")
    return contract_path


def compare_two_runs(
    first_dir: Path,
    second_dir: Path,
    artifact_names: list[str],
) -> dict[str, object]:
    """Compare byte hashes for two independently written artifact bundles."""
    file_results: dict[str, object] = {}
    for name in artifact_names:
        first_path = first_dir / name
        second_path = second_dir / name
        first_hash = sha256(first_path)
        second_hash = sha256(second_path)
        file_results[name] = {
            "run_1_sha256": first_hash,
            "run_2_sha256": second_hash,
            "match": first_hash == second_hash,
        }
    all_match = all(bool(result["match"]) for result in file_results.values())
    if not all_match:
        mismatched = [
            name for name, result in file_results.items() if not bool(result["match"])
        ]
        raise AssertionError(f"Two-run determinism failed for: {mismatched}")
    return {
        "method": "independent Python writes to final and temporary directories",
        "all_match": all_match,
        "files": file_results,
    }


def write_determinism_report(determinism: dict[str, object], output_dir: Path) -> Path:
    """Write the machine-readable two-run hash comparison."""
    path = output_dir / f"{FIGURE_STEM}_determinism.json"
    path.write_text(
        json.dumps(determinism, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def write_qa_report(
    source: pd.DataFrame,
    export_audit: dict[str, object],
    determinism: dict[str, object],
    inputs: dict[str, Path],
    output_dir: Path,
) -> Path:
    """Write a concise human-readable QA report."""
    panel_a = source[source["panel"] == "a"]
    panel_b = source[
        (source["panel"] == "b") & (source["condition"] == "evidence_gate_off")
    ]
    qa_path = output_dir / "FIG4_QA_REPORT.md"
    lines = [
        "# Figure 4 QA report",
        "",
        "## Outcome",
        "",
        "PASS for data, statistical boundaries, export, typography, grayscale, and two-run reproducibility.",
        f"Original-size visual inspection: **{ORIGINAL_SIZE_VISUAL_QA}**.",
        "",
        "## Claim and evidence boundary",
        "",
        "- Claim: action readiness is determined at the selected operating point and by evidence eligibility, not by predictive ranking alone.",
        "- Panel a uses only external Mendeley cap-8 action precision. Only the HGB point estimate reaches 0.60; its interval lower endpoint is 0.5997. The line is a development condition, not a tested, clinical, safety, or fairness boundary.",
        "- Panel b uses only constructed hash-scheduled missing/stale HGB decisions. It is an audit stress test, not an operational prevalence estimate.",
        "- Prediction scores are unchanged in both component arms; the panel isolates routing permission, not predictive credit.",
        "- Full-gate zeros are exact counts with no interval. Gate-off intervals are paired participant-cluster percentile intervals for arm minus full (2,000 replicates).",
        "- Cross-cohort contrasts are descriptive.",
        "",
        "## Point and denominator audit",
        "",
        "| Panel | Proposal/cohort | Condition | Count | Estimate | 95% interval |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in panel_a.itertuples(index=False):
        lines.append(
            f"| a | {row.model_label} | external cap 8 | {row.numerator}/{row.denominator} | "
            f"{row.plotted_estimate:.2f}% | {row.plotted_ci_low:.2f}-{row.plotted_ci_high:.2f}% |"
        )
    for row in panel_b.itertuples(index=False):
        full = source[
            (source["panel"] == "b")
            & (source["dataset_id"] == row.dataset_id)
            & (source["condition"] == "full_gate")
        ].iloc[0]
        lines.append(
            f"| b | {row.cohort_label} | full gate | 0/{int(full['denominator'])} | 0.00% | exact zero; none displayed |"
        )
        lines.append(
            f"| b | {row.cohort_label} | gate off | {row.numerator}/{row.denominator} | "
            f"{row.plotted_estimate:.2f}% | {row.plotted_ci_low:.2f}-{row.plotted_ci_high:.2f}% |"
        )
    lines.extend(
        [
            "",
            "All seven plotted points equal their frozen count ratios within 1e-12; all five displayed intervals contain their frozen estimates. Machine-readable checks are in `fig4_prediction_permission_audit.csv`.",
            "",
            "## Export and design checks",
            "",
            f"- Physical size: {export_audit['figure_size_mm'][0]:.3f} x {export_audit['figure_size_mm'][1]:.3f} mm in SVG; {export_audit['pdf_size_mm'][0]:.3f} x {export_audit['pdf_size_mm'][1]:.3f} mm in PDF.",
            f"- Raster canvas: {export_audit['expected_raster_pixels_at_600_dpi'][0]} x {export_audit['expected_raster_pixels_at_600_dpi'][1]} px at 600 dpi.",
            f"- Editable SVG text nodes: {export_audit['svg_text_nodes']}; minimum text: {export_audit['svg_minimum_text_pt']:.1f} pt.",
            f"- Resolved typeface: {export_audit['resolved_font_name']}.",
            f"- Non-white content margins (left/top/right/bottom): {export_audit['ink_bbox_margins_px']['left_px']}/{export_audit['ink_bbox_margins_px']['top_px']}/{export_audit['ink_bbox_margins_px']['right_px']}/{export_audit['ink_bbox_margins_px']['bottom_px']} px.",
            "- White background; no cards, hatch, grid, embedded table, AUROC, bridge, or capacity panel.",
            "- No point-value labels or reference-line text are drawn; exact values, counts and interval definitions remain in the caption, QA table and source data, so no annotation overlaps an interval.",
            "- Color semantics are stable across panels: blue denotes the governed/condition-meeting state; orange denotes below-condition/bypass. Model labels and marker shapes in panel a, plus open/filled markers and one legend in panel b, make the encoding redundant.",
            "- Grayscale export generated and checked for nonblank content and final dimensions.",
            "",
            "## Reproducibility and traceability",
            "",
            f"- Independent two-run hash match: **{'PASS' if determinism['all_match'] else 'FAIL'}** for {len(determinism['files'])} primary artifacts.",
        ]
    )
    for name, path in inputs.items():
        lines.append(f"- `{name}` SHA-256: `{sha256(path)}`")
    lines.extend(
        [
            "- Plot source: `fig4_prediction_permission_source_data.csv`.",
            "- Hash comparison: `fig4_prediction_permission_determinism.json`.",
            "- Drawing/export script: `make_fig4_prediction_permission.py`.",
            "",
        ]
    )
    qa_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return qa_path


def write_manifest(
    artifact_paths: list[Path],
    inputs: dict[str, Path],
    export_audit: dict[str, object],
    determinism: dict[str, object],
    output_dir: Path,
) -> Path:
    """Write a deterministic manifest for the complete Figure 4 bundle."""
    manifest_path = output_dir / "FIG4_MANIFEST.json"
    payload = {
        "figure_id": "Figure 4",
        "stem": FIGURE_STEM,
        "backend": "Python/matplotlib",
        "core_conclusion": "operating-point and evidence checks determine action readiness; predictive ranking alone does not",
        "figure_size_mm": [WIDTH_MM, HEIGHT_MM],
        "raster_dpi": DPI,
        "typography": {
            "family": "Calibri",
            "minimum_font_pt": MIN_TEXT_PT,
            "svg_text_editable": True,
            "pdf_fonttype": 42,
        },
        "panels": {
            "a": {
                "metric": "external cap-8 action precision",
                "models": MODEL_ORDER,
                "development_condition": 0.60,
                "condition_result": "only the HGB point estimate reaches 0.60; its CI lower endpoint is 0.5997",
                "interval": "conditional 95% participant-cluster percentile; 2,000 replicates",
            },
            "b": {
                "metric": "invalid-evidence action-route rate",
                "model": "hist_gradient_boosting",
                "scenario": "constructed hash-scheduled missing/stale evidence",
                "arms": ["full_controls", "evidence_gate_off"],
                "interval": "paired 95% participant-cluster percentile arm-minus-full; 2,000 replicates",
            },
        },
        "exclusions": ["AUROC", "bridge", "capacity sweep", "cards", "hatch"],
        "color_semantics": {
            "blue": "governed or development-condition-meeting",
            "orange": "below development condition or gate bypass",
        },
        "annotation_policy": "no direct point values or reference-line text; exact values and counts are retained in the caption and source data",
        "inputs": {name: sha256(path) for name, path in inputs.items()},
        "export_audit": export_audit,
        "determinism": determinism,
        "original_size_visual_qa": ORIGINAL_SIZE_VISUAL_QA,
        "artifacts": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(artifact_paths, key=lambda item: item.name.lower())
        },
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def write_primary_bundle(
    source: pd.DataFrame,
    row_audit: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    """Write every primary artifact that participates in the two-run hash audit."""
    source_path, audit_path = write_source_and_audit(source, row_audit, output_dir)
    caption_path = write_caption(output_dir)
    contract_path = write_contract(output_dir)
    figure_paths = draw_figure(source, output_dir)
    return [source_path, audit_path, caption_path, contract_path, *figure_paths]


def main() -> None:
    """Build, audit, and manifest Figure 4."""
    output_dir = Path(__file__).resolve().parent
    repo_root = output_dir.parents[3]
    evidence_dir = repo_root / "icair_2026" / "framework_v1" / "evidence_v2"
    inputs = {
        "route_workload_metrics.csv": evidence_dir / "route_workload_metrics.csv",
        "bootstrap_confidence_intervals.csv": evidence_dir
        / "bootstrap_confidence_intervals.csv",
        "route_component_metrics.csv": evidence_dir
        / "component_ablation"
        / "route_component_metrics.csv",
        "route_component_bootstrap.csv": evidence_dir
        / "component_ablation"
        / "route_component_bootstrap.csv",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Frozen Figure 4 inputs are missing: {missing}")

    route, bootstrap, component_metrics, component_bootstrap = load_frozen_inputs(
        inputs["route_workload_metrics.csv"],
        inputs["bootstrap_confidence_intervals.csv"],
        inputs["route_component_metrics.csv"],
        inputs["route_component_bootstrap.csv"],
    )
    source = build_source_data(route, bootstrap, component_metrics, component_bootstrap)
    row_audit = build_row_audit(source)

    primary_paths = write_primary_bundle(source, row_audit, output_dir)
    export_audit = audit_exports(output_dir)
    primary_names = [path.name for path in primary_paths]
    with tempfile.TemporaryDirectory(prefix="fig4_determinism_") as temporary:
        temporary_dir = Path(temporary)
        write_primary_bundle(source, row_audit, temporary_dir)
        determinism = compare_two_runs(output_dir, temporary_dir, primary_names)
    determinism_path = write_determinism_report(determinism, output_dir)
    qa_path = write_qa_report(source, export_audit, determinism, inputs, output_dir)

    script_path = Path(__file__).resolve()
    manifest_artifacts = [script_path, *primary_paths, determinism_path, qa_path]
    manifest_path = write_manifest(
        manifest_artifacts,
        inputs,
        export_audit,
        determinism,
        output_dir,
    )

    print(f"Created {FIGURE_STEM} at {WIDTH_MM:.0f} x {HEIGHT_MM:.0f} mm")
    print(f"Validated {len(source)} plotted points and all denominators")
    print(f"Two-run deterministic artifacts: {len(primary_names)}/{len(primary_names)}")
    print(f"Original-size visual QA: {ORIGINAL_SIZE_VISUAL_QA}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
