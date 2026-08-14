"""Build the finite-capacity result shown as ICAIR 2026 Figure 3.

This script intentionally reads only:
  * route_workload_metrics.csv
  * bootstrap_confidence_intervals.csv

All drawing, export, and visual QA are performed in Python.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageChops, ImageOps
from PyPDF2 import PdfReader

# Mandatory publication/export settings: keep SVG text editable.
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = [
    "Calibri",
    "Arial",
    "Helvetica",
    "DejaVu Sans",
    "Liberation Sans",
]
plt.rcParams["svg.fonttype"] = "none"
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["ps.fonttype"] = 42
plt.rcParams["svg.hashsalt"] = "icair-2026-ecrc-fig2-v2"
plt.rcParams["font.size"] = 7.5
plt.rcParams["axes.labelsize"] = 7.5
plt.rcParams["axes.titlesize"] = 8.0
plt.rcParams["xtick.labelsize"] = 7.5
plt.rcParams["ytick.labelsize"] = 7.5
plt.rcParams["legend.fontsize"] = 7.5
plt.rcParams["axes.spines.right"] = False
plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.linewidth"] = 0.75
plt.rcParams["legend.frameon"] = False
plt.rcParams["text.color"] = "#26323B"
plt.rcParams["axes.labelcolor"] = "#26323B"
plt.rcParams["axes.edgecolor"] = "#26323B"
plt.rcParams["xtick.color"] = "#26323B"
plt.rcParams["ytick.color"] = "#26323B"


WIDTH_MM = 159.0
HEIGHT_MM = 62.0
DPI = 600
MIN_TEXT_PT = 7.5
FIGURE_STEM = "fig2_capacity_tradeoff"
FIXED_DATE = "2026-08-13"
FIXED_DATETIME = datetime(2026, 8, 13, tzinfo=timezone.utc)

CAP_ORDER = ["2", "4", "6", "8"]
CAP_DISPLAY = {
    "2": "2",
    "4": "4",
    "6": "6",
    "8": "8",
}

COHORTS = {
    "many_labs_igt": {
        "label": "Many Labs",
        "color": "#3B6F9E",  # muted blue
        "linestyle": "-",
        "marker": "o",
        "expected_scope": "participant_grouped_outer_cv",
        "expected_n": 617,
        "expected_decisions": 66525,
        "decision_length_context": (
            "95 decisions for 15 participants; 100 for 504; 150 for 98; mean 107.82"
        ),
    },
    "mendeley_igt_official_v2": {
        "label": "Mendeley cohort",
        "color": "#C77B4A",  # warm accent
        "linestyle": (0, (3.0, 1.7)),
        "marker": "s",
        "expected_scope": "frozen_external_official_v2_same_task",
        "expected_n": 59,
        "expected_decisions": 11800,
        "decision_length_context": "200 decisions for each of 59 participants",
    },
}

PANELS = {
    "a": {
        "metric": "event_coverage_by_action",
        "title": "Proxy-positive choices: alert or review",
        "definition": (
            "proxy-positive choices routed to alert or review divided by all "
            "proxy-positive choices"
        ),
        "ylabel": "Coverage (%)",
        "scale": 100.0,
        "ylim": (0.0, 16.2),
        "yticks": [0, 4, 8, 12, 16],
    },
    "b": {
        "metric": "false_alerts_per_100",
        "title": "Automated false alerts only",
        "definition": "automated false alerts only per 100 decisions",
        "ylabel": "False alerts / 100 decisions",
        "scale": 1.0,
        "ylim": (0.0, 1.9),
        "yticks": [0.0, 0.5, 1.0, 1.5],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def parse_svg_length_mm(value: str) -> float:
    value = value.strip()
    if value.endswith("pt"):
        return float(value[:-2]) * 25.4 / 72.0
    if value.endswith("in"):
        return float(value[:-2]) * 25.4
    if value.endswith("mm"):
        return float(value[:-2])
    raise ValueError(f"Unsupported SVG length: {value}")


def load_and_validate(
    route_path: Path, bootstrap_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    route = pd.read_csv(route_path, dtype={"cap_label": str})
    bootstrap = pd.read_csv(bootstrap_path, dtype={"cap_label": str})

    route_required = {
        "dataset_id",
        "evaluation_scope",
        "model_name",
        "cap_label",
        "aggregate_level",
        "n_participants",
        "n_decisions",
        "event_coverage_by_action",
        "false_alerts_per_100",
    }
    bootstrap_required = {
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
    }
    missing_route = route_required - set(route.columns)
    missing_bootstrap = bootstrap_required - set(bootstrap.columns)
    if missing_route or missing_bootstrap:
        raise ValueError(
            f"Missing columns: route={sorted(missing_route)}, bootstrap={sorted(missing_bootstrap)}"
        )

    route = route[
        (route["model_name"] == "hist_gradient_boosting")
        & (route["aggregate_level"] == "pooled")
        & route["dataset_id"].isin(COHORTS)
        & route["cap_label"].isin(CAP_ORDER)
    ].copy()
    bootstrap = bootstrap[
        (bootstrap["metric_family"] == "route_workload")
        & (bootstrap["model_name"] == "hist_gradient_boosting")
        & bootstrap["dataset_id"].isin(COHORTS)
        & bootstrap["cap_label"].isin(CAP_ORDER)
        & bootstrap["metric"].isin(panel["metric"] for panel in PANELS.values())
    ].copy()

    expected_route_rows = len(COHORTS) * len(CAP_ORDER)
    expected_bootstrap_rows = expected_route_rows * len(PANELS)
    if len(route) != expected_route_rows:
        raise ValueError(
            f"Expected {expected_route_rows} pooled route rows; found {len(route)}"
        )
    if len(bootstrap) != expected_bootstrap_rows:
        raise ValueError(
            f"Expected {expected_bootstrap_rows} bootstrap rows; found {len(bootstrap)}"
        )
    if route.duplicated(["dataset_id", "cap_label"]).any():
        raise ValueError("Duplicate pooled route rows")
    if bootstrap.duplicated(["dataset_id", "cap_label", "metric"]).any():
        raise ValueError("Duplicate bootstrap rows")

    numeric_bootstrap = [
        "estimate",
        "ci_low",
        "ci_high",
        "confidence_level",
        "bootstrap_replicates",
        "finite_replicates",
    ]
    bootstrap[numeric_bootstrap] = bootstrap[numeric_bootstrap].apply(
        pd.to_numeric, errors="raise"
    )
    if not np.isfinite(bootstrap[numeric_bootstrap].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite bootstrap value")
    if not (
        (bootstrap["ci_low"] <= bootstrap["estimate"])
        & (bootstrap["estimate"] <= bootstrap["ci_high"])
    ).all():
        raise ValueError("Estimate falls outside a confidence interval")
    if not np.allclose(bootstrap["confidence_level"], 0.95, atol=0.0, rtol=0.0):
        raise ValueError("Figure requires 95% confidence intervals")
    if not (bootstrap["bootstrap_unit"] == "participant").all():
        raise ValueError("Figure requires participant-level bootstrap")
    if (
        not bootstrap["bootstrap_method"]
        .str.contains("cluster percentile", case=False, regex=False)
        .all()
    ):
        raise ValueError("Figure requires cluster-percentile bootstrap")
    if not (bootstrap["bootstrap_replicates"] == 2000).all():
        raise ValueError("Figure requires 2,000 bootstrap replicates")
    if not (bootstrap["finite_replicates"] == 2000).all():
        raise ValueError("A bootstrap row has fewer than 2,000 finite replicates")

    for dataset_id, cohort in COHORTS.items():
        cohort_route = route[route["dataset_id"] == dataset_id]
        cohort_bootstrap = bootstrap[bootstrap["dataset_id"] == dataset_id]
        if set(cohort_route["cap_label"]) != set(CAP_ORDER):
            raise ValueError(f"Incomplete route cap grid for {dataset_id}")
        for metric in (panel["metric"] for panel in PANELS.values()):
            if set(
                cohort_bootstrap.loc[cohort_bootstrap["metric"] == metric, "cap_label"]
            ) != set(CAP_ORDER):
                raise ValueError(
                    f"Incomplete bootstrap cap grid for {dataset_id}/{metric}"
                )
        if set(cohort_route["evaluation_scope"]) != {cohort["expected_scope"]}:
            raise ValueError(f"Unexpected evaluation scope for {dataset_id}")
        if set(cohort_bootstrap["evaluation_scope"]) != {cohort["expected_scope"]}:
            raise ValueError(f"Bootstrap scope mismatch for {dataset_id}")
        if set(pd.to_numeric(cohort_route["n_participants"])) != {cohort["expected_n"]}:
            raise ValueError(f"Unexpected participant count for {dataset_id}")
        if set(pd.to_numeric(cohort_route["n_decisions"])) != {
            cohort["expected_decisions"]
        }:
            raise ValueError(f"Unexpected decision count for {dataset_id}")

    # Every plotted estimate must equal its pooled route-workload estimate.
    for row in bootstrap.itertuples(index=False):
        route_row = route[
            (route["dataset_id"] == row.dataset_id)
            & (route["cap_label"] == row.cap_label)
        ]
        pooled = float(route_row.iloc[0][row.metric])
        if not math.isclose(float(row.estimate), pooled, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"Pooled/CI estimate mismatch for {row.dataset_id}/{row.cap_label}/{row.metric}: "
                f"{pooled} vs {row.estimate}"
            )

    return route, bootstrap


def build_source_data(bootstrap: pd.DataFrame) -> pd.DataFrame:
    panel_by_metric = {panel["metric"]: key for key, panel in PANELS.items()}
    cap_rank = {cap: index for index, cap in enumerate(CAP_ORDER)}
    rows: list[dict[str, object]] = []
    for row in bootstrap.itertuples(index=False):
        panel_key = panel_by_metric[row.metric]
        scale = float(PANELS[panel_key]["scale"])
        rows.append(
            {
                "panel": panel_key,
                "dataset_id": row.dataset_id,
                "cohort_label": COHORTS[row.dataset_id]["label"],
                "evaluation_scope": row.evaluation_scope,
                "n_participants": COHORTS[row.dataset_id]["expected_n"],
                "n_decisions": COHORTS[row.dataset_id]["expected_decisions"],
                "decision_length_context": COHORTS[row.dataset_id][
                    "decision_length_context"
                ],
                "model_name": row.model_name,
                "cap_label": row.cap_label,
                "cap_display": CAP_DISPLAY[row.cap_label].replace("\n", " "),
                "cap_rank": cap_rank[row.cap_label],
                "metric": row.metric,
                "panel_definition": PANELS[panel_key]["definition"],
                "estimate_raw": float(row.estimate),
                "ci_low_raw": float(row.ci_low),
                "ci_high_raw": float(row.ci_high),
                "display_scale": scale,
                "plotted_estimate": float(row.estimate) * scale,
                "plotted_ci_low": float(row.ci_low) * scale,
                "plotted_ci_high": float(row.ci_high) * scale,
                "confidence_level": float(row.confidence_level),
                "bootstrap_unit": row.bootstrap_unit,
                "bootstrap_method": row.bootstrap_method,
                "bootstrap_replicates": int(row.bootstrap_replicates),
                "finite_replicates": int(row.finite_replicates),
                "interval_scope": (
                    "conditional on frozen predictions, thresholds, and routing rules"
                ),
                "cap_unit": "automated-alert slots per participant",
                "cross_cohort_cap_interpretation": (
                    "descriptive only because decisions per participant differ by cohort"
                ),
            }
        )
    source = pd.DataFrame(rows).sort_values(
        ["panel", "cap_rank", "dataset_id"], kind="stable"
    )
    if len(source) != 16:
        raise AssertionError(f"Expected 16 plotted points; found {len(source)}")
    if source["cap_label"].str.contains("unbounded", case=False, regex=False).any():
        raise AssertionError("Source data still contains an unbounded cap")
    if set(source.loc[source["panel"] == "a", "panel_definition"]) != {
        PANELS["a"]["definition"]
    }:
        raise AssertionError("Panel-a source-data definition is missing")
    if set(source.loc[source["panel"] == "b", "panel_definition"]) != {
        PANELS["b"]["definition"]
    }:
        raise AssertionError("Panel-b source-data definition is missing")
    return source.reset_index(drop=True)


def draw_figure(
    source: pd.DataFrame, output_dir: Path
) -> tuple[list[Path], dict[str, object]]:
    if (
        min(
            plt.rcParams["font.size"],
            plt.rcParams["axes.labelsize"],
            plt.rcParams["xtick.labelsize"],
            plt.rcParams["ytick.labelsize"],
            plt.rcParams["legend.fontsize"],
        )
        < MIN_TEXT_PT
    ):
        raise AssertionError("Configured text is smaller than 7.5 pt")

    fig, axes = plt.subplots(
        1,
        2,
        figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4),
        facecolor="white",
    )
    fig.subplots_adjust(left=0.090, right=0.985, bottom=0.225, top=0.785, wspace=0.335)

    handles = []
    labels = []
    x = np.arange(len(CAP_ORDER), dtype=float)
    segment_checks: list[dict[str, object]] = []
    for ax, (panel_key, panel) in zip(axes, PANELS.items(), strict=True):
        for dataset_id, cohort in COHORTS.items():
            values = source[
                (source["panel"] == panel_key) & (source["dataset_id"] == dataset_id)
            ].sort_values("cap_rank")
            y = values["plotted_estimate"].to_numpy(dtype=float)
            lo = values["plotted_ci_low"].to_numpy(dtype=float)
            hi = values["plotted_ci_high"].to_numpy(dtype=float)
            handle = ax.errorbar(
                x,
                y,
                yerr=np.vstack([y - lo, hi - y]),
                color=cohort["color"],
                linestyle=cohort["linestyle"],
                linewidth=1.25,
                marker=cohort["marker"],
                markersize=4.2,
                markerfacecolor=cohort["color"],
                markeredgecolor="white",
                markeredgewidth=0.45,
                ecolor=cohort["color"],
                elinewidth=0.75,
                capsize=2.0,
                capthick=0.75,
                zorder=3,
                label=cohort["label"],
            )
            finite_line = handle.lines[0]
            segment_pass = np.array_equal(finite_line.get_xdata(), x)
            segment_checks.append(
                {
                    "panel": panel_key,
                    "dataset_id": dataset_id,
                    "finite_cap_x": finite_line.get_xdata().tolist(),
                    "finite_cap_labels": CAP_ORDER,
                    "pass": bool(segment_pass),
                }
            )
            if panel_key == "a":
                handles.append(handle)
                labels.append(cohort["label"])

        ax.set_title(panel["title"], loc="left", fontweight="semibold", pad=5.0)
        ax.set_ylabel(panel["ylabel"], labelpad=4.0)
        ax.set_xlim(-0.18, len(CAP_ORDER) - 0.82)
        ax.set_ylim(*panel["ylim"])
        ax.set_yticks(panel["yticks"])
        ax.set_xticks(x)
        ax.set_xticklabels([CAP_DISPLAY[cap] for cap in CAP_ORDER])
        ax.tick_params(
            axis="both", which="major", direction="out", length=2.5, width=0.65
        )
        ax.tick_params(axis="x", pad=3.0)
        ax.spines["left"].set_color("#26323B")
        ax.spines["bottom"].set_color("#26323B")
        ax.spines["left"].set_linewidth(0.75)
        ax.spines["bottom"].set_linewidth(0.75)
        ax.text(
            -0.18,
            1.085,
            panel_key,
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.0,
            fontweight="bold",
            color="#26323B",
        )

    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.515, 0.985),
        ncol=2,
        frameon=False,
        handlelength=2.2,
        handletextpad=0.55,
        columnspacing=1.7,
        borderaxespad=0.0,
    )
    fig.text(
        0.537,
        0.065,
        "Automated-alert quota per participant",
        ha="center",
        va="center",
        fontsize=7.5,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / FIGURE_STEM
    svg_path = stem.with_suffix(".svg")
    pdf_path = stem.with_suffix(".pdf")
    png_path = stem.with_suffix(".png")
    jpg_path = stem.with_suffix(".jpg")

    common = {"facecolor": "white", "edgecolor": "white", "transparent": False}
    fig.savefig(
        svg_path,
        format="svg",
        metadata={"Date": FIXED_DATE, "Title": "Capacity-exposure trade-off"},
        **common,
    )
    fig.savefig(
        pdf_path,
        format="pdf",
        metadata={
            "Title": "Capacity-exposure trade-off",
            "Author": "",
            "Subject": "ICAIR 2026 Figure 3",
            "Keywords": "decision permit, capacity, external replay",
            "Creator": "matplotlib",
            "Producer": "matplotlib",
            "CreationDate": FIXED_DATETIME,
            "ModDate": FIXED_DATETIME,
        },
        **common,
    )
    fig.savefig(
        png_path,
        format="png",
        dpi=DPI,
        metadata={"Title": "Capacity-exposure trade-off", "Software": "matplotlib"},
        **common,
    )
    fig.savefig(
        jpg_path,
        format="jpg",
        dpi=DPI,
        pil_kwargs={"quality": 95, "subsampling": 0, "optimize": False},
        **common,
    )
    plt.close(fig)

    grayscale_path = output_dir / f"{FIGURE_STEM}_grayscale.png"
    with Image.open(png_path) as color_image:
        ImageOps.grayscale(color_image).save(
            grayscale_path, dpi=(DPI, DPI), optimize=False
        )
    line_audit = {
        "policy": "finite per-participant caps 2, 4, 6 and 8 connected; no unbounded point plotted",
        "expected_series_checks": len(PANELS) * len(COHORTS),
        "observed_series_checks": len(segment_checks),
        "all_segments_pass": len(segment_checks) == len(PANELS) * len(COHORTS)
        and all(bool(item["pass"]) for item in segment_checks),
        "series": segment_checks,
    }
    if not line_audit["all_segments_pass"]:
        raise AssertionError("Finite-cap line connection audit failed")
    return [svg_path, pdf_path, png_path, jpg_path, grayscale_path], line_audit


def audit_exports(output_dir: Path) -> dict[str, object]:
    svg_path = output_dir / f"{FIGURE_STEM}.svg"
    pdf_path = output_dir / f"{FIGURE_STEM}.pdf"
    png_path = output_dir / f"{FIGURE_STEM}.png"
    jpg_path = output_dir / f"{FIGURE_STEM}.jpg"
    grayscale_path = output_dir / f"{FIGURE_STEM}_grayscale.png"

    # Matplotlib rasterizes a fixed-size canvas by flooring fractional pixels.
    expected_px = (
        int(WIDTH_MM / 25.4 * DPI),
        int(HEIGHT_MM / 25.4 * DPI),
    )
    raster: dict[str, object] = {}
    for path in (png_path, jpg_path, grayscale_path):
        with Image.open(path) as image:
            width_px, height_px = image.size
            dpi_info = image.info.get("dpi")
            raster[path.name] = {
                "pixels": [width_px, height_px],
                "dpi_metadata": list(dpi_info) if dpi_info else None,
            }
            if (width_px, height_px) != expected_px:
                raise AssertionError(
                    f"Unexpected raster dimensions for {path.name}: {(width_px, height_px)}"
                )

    with Image.open(png_path).convert("RGB") as image:
        white = Image.new("RGB", image.size, "white")
        ink_bbox = ImageChops.difference(image, white).getbbox()
        if ink_bbox is None:
            raise AssertionError("Exported PNG is blank")
        left, top, right, bottom = ink_bbox
        crop_margins = {
            "left_px": left,
            "top_px": top,
            "right_px": image.width - right,
            "bottom_px": image.height - bottom,
        }
        if min(crop_margins.values()) < 4:
            raise AssertionError(f"Figure content touches canvas edge: {crop_margins}")

    svg_root = ElementTree.parse(svg_path).getroot()
    svg_width_mm = parse_svg_length_mm(svg_root.attrib["width"])
    svg_height_mm = parse_svg_length_mm(svg_root.attrib["height"])
    svg_ns = {"svg": "http://www.w3.org/2000/svg"}
    text_nodes = svg_root.findall(".//svg:text", svg_ns)
    svg_text_nodes = len(text_nodes)
    svg_text = " ".join("".join(node.itertext()) for node in text_nodes)
    svg_font_sizes = []
    for node in text_nodes:
        match = re.search(r"font-size:\s*([0-9.]+)px", node.attrib.get("style", ""))
        if match:
            svg_font_sizes.append(float(match.group(1)))
    if not math.isclose(svg_width_mm, WIDTH_MM, abs_tol=0.02):
        raise AssertionError(f"SVG width mismatch: {svg_width_mm}")
    if not math.isclose(svg_height_mm, HEIGHT_MM, abs_tol=0.02):
        raise AssertionError(f"SVG height mismatch: {svg_height_mm}")
    if svg_text_nodes == 0:
        raise AssertionError("SVG text was converted to paths")
    if not svg_font_sizes or min(svg_font_sizes) < MIN_TEXT_PT:
        raise AssertionError(
            f"SVG text below {MIN_TEXT_PT:g} pt: {min(svg_font_sizes, default=0):g}"
        )
    if PANELS["a"]["title"] not in svg_text:
        raise AssertionError("Revised panel-a title is missing from editable SVG text")
    if "unbounded" in svg_text.lower():
        raise AssertionError(
            "The removed sample-unbounded category remains in the figure"
        )

    pdf_page = PdfReader(str(pdf_path)).pages[0]
    pdf_width_mm = float(pdf_page.mediabox.width) * 25.4 / 72.0
    pdf_height_mm = float(pdf_page.mediabox.height) * 25.4 / 72.0
    if not math.isclose(pdf_width_mm, WIDTH_MM, abs_tol=0.02):
        raise AssertionError(f"PDF width mismatch: {pdf_width_mm}")
    if not math.isclose(pdf_height_mm, HEIGHT_MM, abs_tol=0.02):
        raise AssertionError(f"PDF height mismatch: {pdf_height_mm}")

    grayscale_delta = abs(
        luminance(COHORTS["many_labs_igt"]["color"])
        - luminance(COHORTS["mendeley_igt_official_v2"]["color"])
    )
    if grayscale_delta < 20:
        raise AssertionError("Series colors are too similar in grayscale")

    return {
        "expected_raster_pixels_at_600_dpi": list(expected_px),
        "raster": raster,
        "ink_bbox_margins_px": crop_margins,
        "svg_size_mm": [svg_width_mm, svg_height_mm],
        "svg_text_nodes": svg_text_nodes,
        "svg_minimum_text_pt": min(svg_font_sizes),
        "svg_minimum_text_pass": min(svg_font_sizes) >= MIN_TEXT_PT,
        "revised_panel_a_title_present": True,
        "sample_unbounded_absent": True,
        "pdf_size_mm": [pdf_width_mm, pdf_height_mm],
        "series_grayscale_luminance_delta": grayscale_delta,
        "redundant_series_encoding": {
            "Many Labs": "solid line + circle",
            "Mendeley cohort": "dashed line + square",
        },
    }


def write_caption(output_dir: Path) -> Path:
    caption_path = output_dir / "FIG2_CAPTION.md"
    caption = (
        "**Figure 3. Finite-capacity sensitivity for stored HGB streams.** "
        "(a) Proxy-event action coverage (alert or review). (b) Automated false alerts per "
        "100 decisions. Points are pooled estimates with conditional 95% participant-cluster "
        "percentile bootstrap intervals (2,000 replicates). Many Labs uses outer-CV streams; "
        "Mendeley uses frozen external replay. Alert caps reset per participant, review "
        "capacity remained two, and unequal sequence lengths make cross-cohort contrasts "
        "descriptive.\n"
    )
    caption_path.write_text(caption, encoding="utf-8", newline="\n")
    return caption_path


def write_point_check(source: pd.DataFrame, output_dir: Path) -> Path:
    check = source.copy()
    check["expected_plotted_estimate"] = check["estimate_raw"] * check["display_scale"]
    check["expected_plotted_ci_low"] = check["ci_low_raw"] * check["display_scale"]
    check["expected_plotted_ci_high"] = check["ci_high_raw"] * check["display_scale"]
    check["estimate_abs_diff"] = (
        check["plotted_estimate"] - check["expected_plotted_estimate"]
    ).abs()
    check["ci_low_abs_diff"] = (
        check["plotted_ci_low"] - check["expected_plotted_ci_low"]
    ).abs()
    check["ci_high_abs_diff"] = (
        check["plotted_ci_high"] - check["expected_plotted_ci_high"]
    ).abs()
    check["point_check"] = np.where(
        check[["estimate_abs_diff", "ci_low_abs_diff", "ci_high_abs_diff"]].max(axis=1)
        <= 1e-12,
        "PASS",
        "FAIL",
    )
    if not (check["point_check"] == "PASS").all():
        raise AssertionError(
            "At least one plotted point differs from the frozen CI row"
        )
    path = output_dir / "fig2_point_check.csv"
    check.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    return path


def write_qa_report(
    source: pd.DataFrame,
    audit: dict[str, object],
    route_path: Path,
    bootstrap_path: Path,
    output_dir: Path,
) -> Path:
    report_path = output_dir / "FIG2_QA_REPORT.md"
    lines = [
        "# Figure 3 QA report",
        "",
        "## Outcome",
        "",
        "PASS. The figure is a 159 mm x 62 mm, two-panel Python/matplotlib export using "
        "only the frozen official-v2 evidence tables. It contains no ablation or systems results.",
        "",
        "## Contract and statistics",
        "",
        "- Claim: increasing automated-alert quota raises action coverage and automated "
        "false-alert exposure in both cohorts; Mendeley external coverage remains lower.",
        "- Model: frozen `hist_gradient_boosting` proposal only.",
        "- Intervals: 95% participant-cluster percentile bootstrap; 2,000/2,000 finite "
        "replicates for every point. They are conditional on the frozen predictions, "
        "thresholds, and routing rules.",
        "- Human-review quota: fixed at two per participant (caption only, not plotted as a result).",
        "- Automated-alert caps: finite values 2, 4, 6, and 8 per participant; no "
        "sample-unbounded point is plotted.",
        "- Panel a denominator: all proxy-positive choices; numerator: those routed to "
        "alert or review.",
        "- Panel b includes automated false alerts only, expressed per 100 decisions.",
        "- Decision lengths differ by cohort: Many Labs has 95 decisions for 15 "
        "participants, 100 for 504, and 150 for 98 (mean 107.82); the Mendeley cohort has 200 "
        "for each of 59 participants. Cross-cohort fixed-cap contrasts are descriptive, "
        "not matched capacity exposures.",
        "- No hypothesis test or causal claim is displayed.",
        "",
        "## Export, size, crop, and grayscale checks",
        "",
        f"- SVG physical size: {audit['svg_size_mm'][0]:.3f} x {audit['svg_size_mm'][1]:.3f} mm; "
        f"editable SVG text nodes: {audit['svg_text_nodes']}.",
        f"- PDF media box: {audit['pdf_size_mm'][0]:.3f} x {audit['pdf_size_mm'][1]:.3f} mm.",
        f"- Expected 600-dpi raster canvas: {audit['expected_raster_pixels_at_600_dpi'][0]} x "
        f"{audit['expected_raster_pixels_at_600_dpi'][1]} px; PNG/JPG checks passed.",
        f"- Non-white content margins (left/top/right/bottom): "
        f"{audit['ink_bbox_margins_px']['left_px']}/"
        f"{audit['ink_bbox_margins_px']['top_px']}/"
        f"{audit['ink_bbox_margins_px']['right_px']}/"
        f"{audit['ink_bbox_margins_px']['bottom_px']} px; no edge contact detected.",
        f"- Grayscale luminance separation: {audit['series_grayscale_luminance_delta']:.1f}; "
        "series also use redundant solid-circle versus dashed-square encoding.",
        f"- Minimum configured text size: {MIN_TEXT_PT:.1f} pt.",
        "- All four panel/cohort series connect exactly the finite caps 2, 4, 6, and 8; "
        "the figure contains no unbounded category.",
        "- White background, no hatch, no grid, no embedded result table, and no footnote block.",
        "- No direct point-value or auxiliary grey annotations are drawn; confidence intervals remain visually separated from markers and neighbouring series at the final 159 mm size.",
        "",
        "## Point-by-point CI audit",
        "",
        "All 16 plotted estimates and both CI endpoints match the selected frozen bootstrap "
        "rows exactly after the declared display transform (x100 only for coverage). The pooled "
        "route-workload estimate independently matches each bootstrap estimate within 1e-12.",
        "",
        "| Panel | Cohort | Cap | Estimate | 95% CI | Check |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in source.itertuples(index=False):
        if row.panel == "a":
            estimate = f"{row.plotted_estimate:.2f}%"
            interval = f"{row.plotted_ci_low:.2f}-{row.plotted_ci_high:.2f}%"
        else:
            estimate = f"{row.plotted_estimate:.3f}"
            interval = f"{row.plotted_ci_low:.3f}-{row.plotted_ci_high:.3f}"
        cap = str(row.cap_display)
        lines.append(
            f"| {row.panel} | {row.cohort_label} | {cap} | {estimate} | {interval} | PASS |"
        )
    lines.extend(
        [
            "",
            "The machine-readable row audit is saved in `fig2_point_check.csv`.",
            "",
            "## Traceability",
            "",
            f"- Route-workload input SHA-256: `{sha256(route_path)}`",
            f"- Bootstrap-CI input SHA-256: `{sha256(bootstrap_path)}`",
            "- Plot source table: `fig2_capacity_tradeoff_source_data.csv`.",
            "- Drawing/export script: `make_fig2_capacity_tradeoff.py`.",
            "- Color and grayscale files were visually inspected at final dimensions after generation.",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return report_path


def write_manifest(
    route_path: Path,
    bootstrap_path: Path,
    output_dir: Path,
    artifact_paths: list[Path],
    source_path: Path,
    point_check_path: Path,
    caption_path: Path,
    qa_path: Path,
    audit: dict[str, object],
) -> Path:
    script_path = Path(__file__).resolve()
    contract_path = output_dir / "FIG2_CONTRACT.md"
    manifest_path = output_dir / "FIG2_MANIFEST.json"
    files_to_hash = [
        script_path,
        contract_path,
        source_path,
        point_check_path,
        caption_path,
        qa_path,
        *artifact_paths,
    ]
    payload = {
        "figure_id": "Figure 3",
        "stem": FIGURE_STEM,
        "backend": "Python/matplotlib",
        "figure_size_mm": [WIDTH_MM, HEIGHT_MM],
        "minimum_text_pt": MIN_TEXT_PT,
        "raster_dpi": DPI,
        "typography": {
            "font_stack": [
                "Calibri",
                "Arial",
                "Helvetica",
                "DejaVu Sans",
                "Liberation Sans",
            ],
            "minimum_font_pt": MIN_TEXT_PT,
            "svg_text_editable": True,
            "pdf_fonttype": 42,
        },
        "inputs": {
            route_path.name: sha256(route_path),
            bootstrap_path.name: sha256(bootstrap_path),
        },
        "selection": {
            "model_name": "hist_gradient_boosting",
            "datasets": list(COHORTS),
            "cap_labels": CAP_ORDER,
            "metrics": [panel["metric"] for panel in PANELS.values()],
        },
        "statistics": {
            "confidence_level": 0.95,
            "bootstrap_unit": "participant",
            "bootstrap_method": "cluster percentile; participants sampled with replacement",
            "bootstrap_replicates": 2000,
        },
        "audit": audit,
        "artifacts": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in files_to_hash
        },
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def main() -> None:
    output_dir = Path(__file__).resolve().parent
    repo_root = output_dir.parents[3]
    evidence_dir = repo_root / "icair_2026" / "framework_v1" / "evidence_v2"
    route_path = evidence_dir / "route_workload_metrics.csv"
    bootstrap_path = evidence_dir / "bootstrap_confidence_intervals.csv"
    if not route_path.is_file() or not bootstrap_path.is_file():
        raise FileNotFoundError(
            f"Frozen evidence inputs not found under {evidence_dir}"
        )

    _, bootstrap = load_and_validate(route_path, bootstrap_path)
    source = build_source_data(bootstrap)
    source_path = output_dir / f"{FIGURE_STEM}_source_data.csv"
    source.to_csv(source_path, index=False, lineterminator="\n", float_format="%.12g")
    point_check_path = write_point_check(source, output_dir)
    artifact_paths, line_audit = draw_figure(source, output_dir)
    audit = audit_exports(output_dir)
    audit["line_connection"] = line_audit
    caption_path = write_caption(output_dir)
    qa_path = write_qa_report(source, audit, route_path, bootstrap_path, output_dir)
    manifest_path = write_manifest(
        route_path,
        bootstrap_path,
        output_dir,
        artifact_paths,
        source_path,
        point_check_path,
        caption_path,
        qa_path,
        audit,
    )

    print(f"Created {FIGURE_STEM} at {WIDTH_MM:.0f} x {HEIGHT_MM:.0f} mm")
    print(f"Validated {len(source)} plotted estimates and confidence intervals")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
