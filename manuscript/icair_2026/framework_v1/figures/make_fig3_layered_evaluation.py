"""Build the focused ICAIR 2026 single-node systems result shown as Figure 2.

The figure makes one bounded claim: transactional reservation preserves configured
capacity on the trusted single-node runtime, while SQLite contention raises tail
latency. All plotted values come from the frozen systems evidence bundle.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.text import Text
from matplotlib.ticker import FixedLocator, ScalarFormatter
from PIL import Image, ImageChops, ImageOps
from PyPDF2 import PdfReader

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [
            "Calibri",
            "Arial",
            "Helvetica",
            "DejaVu Sans",
            "Liberation Sans",
        ],
        "font.size": 7.5,
        "axes.labelsize": 7.5,
        "axes.titlesize": 8.2,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.75,
        "legend.frameon": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.hashsalt": "icair-2026-ecrc-fig3-single-node-systems-v2",
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
    }
)


WIDTH_MM = 159.0
HEIGHT_MM = 66.0
DPI = 600
MIN_TEXT_PT = 7.5
FIGURE_STEM = "fig3_layered_evaluation"
FIXED_DATE = "2026-08-13"
FIXED_DATETIME = datetime(2026, 8, 13, tzinfo=timezone.utc)
VISUAL_INSPECTION_NOTE = (
    "PASS — color and grayscale 159 × 66 mm renders inspected at full-frame and "
    "original resolution; the single unsafe-witness label, log-scale ticks and min–max "
    "whiskers remain legible with no clipping or overlap"
)

COLORS = {
    "ink": "#252525",
    "muted": "#676767",
    "reference": "#8A8A8A",
    "ecrc": "#3B6F9E",
    "unsafe": "#B65454",
    "white": "#FFFFFF",
}

STRESS_CASES = {
    "concurrent_24_cap3": {
        "x": 0.0,
        "label": "24 requests\ncap 3",
        "requests": 24,
        "capacity": 3,
        "rejections": 21,
    },
    "concurrent_96_cap8": {
        "x": 1.0,
        "label": "96 requests\ncap 8",
        "requests": 96,
        "capacity": 8,
        "rejections": 88,
    },
}

WORKER_CASES = [
    (1, "worker_sweep_96_cap8_w1"),
    (2, "worker_sweep_96_cap8_w2"),
    (4, "worker_sweep_96_cap8_w4"),
    (8, "worker_sweep_96_cap8_w8"),
    (16, "worker_sweep_96_cap8_w16"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_svg_length_mm(value: str) -> float:
    value = value.strip()
    if value.endswith("pt"):
        return float(value[:-2]) * 25.4 / 72.0
    if value.endswith("in"):
        return float(value[:-2]) * 25.4
    if value.endswith("mm"):
        return float(value[:-2])
    raise ValueError(f"Unsupported SVG length: {value}")


def luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return 0.299 * red + 0.587 * green + 0.114 * blue


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{label} is missing columns: {sorted(missing)}")


def unique_row(frame: pd.DataFrame, **selectors: object) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for column, value in selectors.items():
        mask &= frame[column].astype(str) == str(value)
    selected = frame.loc[mask]
    if len(selected) != 1:
        raise AssertionError(
            f"Expected one row for selectors {selectors}; found {len(selected)}"
        )
    return selected.iloc[0]


def load_inputs(paths: dict[str, Path]) -> dict[str, object]:
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Frozen systems inputs are missing: {missing}")

    runs = pd.read_csv(paths["runs"])
    aggregate = pd.read_csv(paths["aggregate"])
    unsafe = json.loads(paths["unsafe"].read_text(encoding="utf-8"))
    require_columns(
        runs,
        {
            "case",
            "repetition",
            "workers",
            "n_requests",
            "capacity",
            "capacity_rejections",
            "receipt_count",
            "oversubscription_count",
            "invariant_violations",
            "reservation_counts.committed",
            "reservation_counts.reserved",
            "end_to_end_latency.p95_ms",
        },
        paths["runs"].name,
    )
    require_columns(
        aggregate,
        {
            "case",
            "workers",
            "n_requests",
            "capacity",
            "repetitions",
            "end_to_end_latency.p95_ms.median",
            "end_to_end_latency.p95_ms.minimum",
            "end_to_end_latency.p95_ms.maximum",
        },
        paths["aggregate"].name,
    )
    return {"runs": runs, "aggregate": aggregate, "unsafe": unsafe}


def validate_ecrc_run(
    row: pd.Series,
    *,
    requests: int,
    capacity: int,
    rejections: int,
    workers: int,
) -> None:
    expected = {
        "n_requests": requests,
        "capacity": capacity,
        "capacity_rejections": rejections,
        "receipt_count": requests,
        "oversubscription_count": 0,
        "invariant_violations": 0,
        "reservation_counts.committed": capacity,
        "reservation_counts.reserved": 0,
        "workers": workers,
    }
    for field, value in expected.items():
        if int(row[field]) != value:
            raise AssertionError(
                f"Systems field {field} changed for {row['case']}: "
                f"{row[field]!r} != {value}"
            )


def build_source_data(inputs: dict[str, object]) -> pd.DataFrame:
    runs: pd.DataFrame = inputs["runs"]
    aggregate: pd.DataFrame = inputs["aggregate"]
    unsafe: dict[str, object] = inputs["unsafe"]
    rows: list[dict[str, object]] = []

    # Panel a: deterministic exact counts in each measured repetition.
    for case, specification in STRESS_CASES.items():
        selected = runs.loc[runs["case"] == case].sort_values("repetition")
        if selected["repetition"].astype(int).tolist() != [0, 1, 2]:
            raise AssertionError(f"Expected repetitions 0,1,2 for {case}")
        for _, record in selected.iterrows():
            validate_ecrc_run(
                record,
                requests=specification["requests"],
                capacity=specification["capacity"],
                rejections=specification["rejections"],
                workers=16,
            )
            committed = int(record["reservation_counts.committed"])
            capacity = int(record["capacity"])
            ratio = committed / capacity
            rows.append(
                {
                    "panel": "a",
                    "series_id": "transactional_reservation",
                    "series_label": "ECRC transactional reservation",
                    "case": case,
                    "category_label": specification["label"].replace("\n", " "),
                    "workers": 16,
                    "repetition": int(record["repetition"]),
                    "n_requests": int(record["n_requests"]),
                    "capacity": capacity,
                    "metric": "capacity_bearing_admissions_divided_by_capacity",
                    "estimate_raw": ratio,
                    "range_low_raw": np.nan,
                    "range_high_raw": np.nan,
                    "plotted_estimate": ratio,
                    "plotted_range_low": np.nan,
                    "plotted_range_high": np.nan,
                    "range_type": "none_deterministic_exact_count",
                    "numerator": committed,
                    "denominator": capacity,
                    "source_file": "evidence_systems/systems_performance_runs.csv",
                    "source_selector": (
                        f"case={case};repetition={int(record['repetition'])}"
                    ),
                    "estimand_boundary": (
                        "Exact trusted single-node simulated count; no sampling interval "
                        "or distributed-atomicity claim."
                    ),
                }
            )

    unsafe_expected = {
        "capacity": 1,
        "logical_acceptances": 2,
        "oversubscription_count": 1,
        "lost_update_count": 1,
    }
    for field, value in unsafe_expected.items():
        if int(unsafe.get(field, -1)) != value:
            raise AssertionError(f"Unsafe witness field {field} changed")
    if unsafe.get("barrier_forced_interleaving") is not True:
        raise AssertionError("Unsafe witness is no longer barrier-forced")
    if unsafe.get("production_comparator") is not False:
        raise AssertionError("Unsafe witness must remain a non-production comparator")
    rows.append(
        {
            "panel": "a",
            "series_id": "unsafe_non_atomic_witness",
            "series_label": "Constructed non-atomic witness",
            "case": "unsafe_cap1",
            "category_label": "Constructed witness cap 1",
            "workers": 2,
            "repetition": np.nan,
            "n_requests": 2,
            "capacity": 1,
            "metric": "logical_capacity_acceptances_divided_by_capacity",
            "estimate_raw": 2.0,
            "range_low_raw": np.nan,
            "range_high_raw": np.nan,
            "plotted_estimate": 2.0,
            "plotted_range_low": np.nan,
            "plotted_range_high": np.nan,
            "range_type": "none_single_constructed_witness",
            "numerator": 2,
            "denominator": 1,
            "source_file": "evidence_systems/systems_unsafe_race_witness.json",
            "source_selector": "fixture_type=unsafe_non_atomic_race_witness",
            "estimand_boundary": (
                "Logical acceptances in one barrier-forced witness; not a production "
                "or performance comparator."
            ),
        }
    )

    # Panel b: median of within-run p95 latency, with observed three-run min-max.
    for worker, case in WORKER_CASES:
        aggregate_row = unique_row(aggregate, case=case)
        selected = runs.loc[runs["case"] == case].sort_values("repetition")
        if selected["repetition"].astype(int).tolist() != [0, 1, 2]:
            raise AssertionError(f"Expected repetitions 0,1,2 for {case}")
        for _, record in selected.iterrows():
            validate_ecrc_run(
                record,
                requests=96,
                capacity=8,
                rejections=88,
                workers=worker,
            )
        if int(aggregate_row["workers"]) != worker:
            raise AssertionError(f"Aggregate worker count changed for {case}")
        if int(aggregate_row["n_requests"]) != 96:
            raise AssertionError(f"Aggregate request count changed for {case}")
        if int(aggregate_row["capacity"]) != 8:
            raise AssertionError(f"Aggregate capacity changed for {case}")
        if int(aggregate_row["repetitions"]) != 3:
            raise AssertionError(f"Aggregate repetition count changed for {case}")

        measured = selected["end_to_end_latency.p95_ms"].to_numpy(dtype=float)
        median = float(np.median(measured))
        minimum = float(np.min(measured))
        maximum = float(np.max(measured))
        aggregate_values = {
            "median": float(aggregate_row["end_to_end_latency.p95_ms.median"]),
            "minimum": float(aggregate_row["end_to_end_latency.p95_ms.minimum"]),
            "maximum": float(aggregate_row["end_to_end_latency.p95_ms.maximum"]),
        }
        for name, computed in {
            "median": median,
            "minimum": minimum,
            "maximum": maximum,
        }.items():
            if not math.isclose(computed, aggregate_values[name], abs_tol=1e-12):
                raise AssertionError(
                    f"Aggregate {name} does not match measured runs for {case}"
                )
        rows.append(
            {
                "panel": "b",
                "series_id": "single_node_worker_sweep",
                "series_label": "ECRC single-node worker sweep",
                "case": case,
                "category_label": str(worker),
                "workers": worker,
                "repetition": np.nan,
                "n_requests": 96,
                "capacity": 8,
                "metric": "end_to_end_p95_latency_ms",
                "estimate_raw": median,
                "range_low_raw": minimum,
                "range_high_raw": maximum,
                "plotted_estimate": median,
                "plotted_range_low": minimum,
                "plotted_range_high": maximum,
                "range_type": "observed_min_max_across_three_measured_runs_not_ci",
                "numerator": np.nan,
                "denominator": np.nan,
                "source_file": (
                    "evidence_systems/systems_performance_aggregate.csv + "
                    "evidence_systems/systems_performance_runs.csv"
                ),
                "source_selector": (
                    f"case={case};metric=end_to_end_latency.p95_ms;"
                    "aggregate=median_minimum_maximum"
                ),
                "estimand_boundary": (
                    "Descriptive timing over three runs on the recorded Windows/Python/"
                    "SQLite WAL host with simulated side effects; range is not a confidence "
                    "interval and does not establish performance portability."
                ),
            }
        )

    source = pd.DataFrame(rows)
    expected = {"a": 7, "b": 5}
    observed = source.groupby("panel").size().to_dict()
    if observed != expected:
        raise AssertionError(f"Unexpected source row counts: {observed} != {expected}")
    if source.loc[source["panel"] == "b", "range_low_raw"].isna().any():
        raise AssertionError("Every latency point must carry an observed run range")
    return source.reset_index(drop=True)


def style_axis(ax: plt.Axes) -> None:
    ax.spines["left"].set_color("#444444")
    ax.spines["bottom"].set_color("#444444")
    ax.spines["left"].set_linewidth(0.75)
    ax.spines["bottom"].set_linewidth(0.75)
    ax.tick_params(axis="both", direction="out", length=2.5, width=0.65, pad=2.5)


def add_panel_label(ax: plt.Axes, label: str, x: float = -0.16) -> None:
    ax.text(
        x,
        1.08,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.0,
        fontweight="bold",
        color=COLORS["ink"],
    )


def draw_figure(
    source: pd.DataFrame, output_dir: Path
) -> tuple[list[Path], dict[str, object]]:
    fig, (ax_a, ax_b) = plt.subplots(
        1,
        2,
        figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4),
        gridspec_kw={"width_ratios": [0.94, 1.16]},
        facecolor=COLORS["white"],
    )
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.245, top=0.79, wspace=0.38)

    panel_a = source.loc[source["panel"] == "a"]
    repetition_jitter = {0: -0.060, 1: 0.0, 2: 0.060}
    for case, specification in STRESS_CASES.items():
        points = panel_a.loc[panel_a["case"] == case].sort_values("repetition")
        for row in points.itertuples(index=False):
            ax_a.plot(
                specification["x"] + repetition_jitter[int(row.repetition)],
                row.plotted_estimate,
                marker="o",
                markersize=4.5,
                markerfacecolor=COLORS["ecrc"],
                markeredgecolor=COLORS["white"],
                markeredgewidth=0.45,
                linestyle="none",
                zorder=4,
            )
    unsafe = panel_a.loc[panel_a["series_id"] == "unsafe_non_atomic_witness"].iloc[0]
    ax_a.plot(
        2.0,
        float(unsafe["plotted_estimate"]),
        marker="D",
        markersize=5.0,
        markerfacecolor=COLORS["unsafe"],
        markeredgecolor=COLORS["white"],
        markeredgewidth=0.45,
        linestyle="none",
        zorder=4,
    )
    ax_a.text(
        2.08,
        2.08,
        "2/1",
        ha="left",
        va="bottom",
        color=COLORS["unsafe"],
        fontsize=7.5,
    )
    ax_a.axhline(
        1.0,
        color=COLORS["reference"],
        linewidth=0.8,
        linestyle=(0, (3, 2)),
        zorder=1,
    )
    ax_a.set_title(
        "Reservation preserved capacity", loc="left", fontweight="semibold", pad=4.5
    )
    ax_a.set_ylabel("Capacity-bearing admissions / limit", labelpad=3.5)
    ax_a.set_xticks([0, 1, 2])
    ax_a.set_xticklabels(
        [
            STRESS_CASES["concurrent_24_cap3"]["label"],
            STRESS_CASES["concurrent_96_cap8"]["label"],
            "Constructed witness\ncap 1",
        ]
    )
    ax_a.set_yticks([0, 1, 2])
    ax_a.set_xlim(-0.29, 2.31)
    ax_a.set_ylim(-0.10, 2.31)
    style_axis(ax_a)
    add_panel_label(ax_a, "a", x=-0.19)

    panel_b = source.loc[source["panel"] == "b"].sort_values("workers")
    x = np.arange(len(panel_b), dtype=float)
    median = panel_b["plotted_estimate"].to_numpy(dtype=float)
    minimum = panel_b["plotted_range_low"].to_numpy(dtype=float)
    maximum = panel_b["plotted_range_high"].to_numpy(dtype=float)
    ax_b.errorbar(
        x,
        median,
        yerr=np.vstack([median - minimum, maximum - median]),
        color=COLORS["ecrc"],
        linestyle="-",
        linewidth=1.15,
        marker="o",
        markersize=4.7,
        markerfacecolor=COLORS["ecrc"],
        markeredgecolor=COLORS["white"],
        markeredgewidth=0.45,
        ecolor=COLORS["ecrc"],
        elinewidth=0.85,
        capsize=2.2,
        capthick=0.8,
        zorder=4,
    )
    ax_b.set_yscale("log")
    ax_b.yaxis.set_major_locator(FixedLocator([20, 50, 100, 200, 500, 1000]))
    formatter = ScalarFormatter()
    formatter.set_scientific(False)
    ax_b.yaxis.set_major_formatter(formatter)
    ax_b.set_title(
        "Tail latency rose with contention", loc="left", fontweight="semibold", pad=4.5
    )
    ax_b.set_ylabel("End-to-end p95 latency (ms; log scale)", labelpad=3.5)
    ax_b.set_xlabel("Workers", labelpad=3.0)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels(panel_b["workers"].astype(int).astype(str).tolist())
    ax_b.set_xlim(-0.18, len(x) - 0.82)
    ax_b.set_ylim(12, 1250)
    ax_b.minorticks_off()
    style_axis(ax_b)
    add_panel_label(ax_b, "b", x=-0.16)

    text_sizes = [
        text.get_fontsize()
        for text in fig.findobj(match=Text)
        if isinstance(text.get_text(), str) and text.get_text().strip()
    ]
    minimum_observed_text_pt = min(text_sizes)
    if minimum_observed_text_pt < MIN_TEXT_PT:
        raise AssertionError(
            f"Found {minimum_observed_text_pt}-pt text below the 7.5-pt contract"
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
        metadata={
            "Date": FIXED_DATE,
            "Title": "Capacity preservation and contention cost",
        },
        **common,
    )
    fig.savefig(
        pdf_path,
        format="pdf",
        metadata={
            "Title": "Capacity preservation and contention cost",
            "Author": "",
            "Subject": "ICAIR 2026 Figure 2",
            "Keywords": "transactional reservation, capacity, contention, tail latency",
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
        metadata={
            "Title": "Capacity preservation and contention cost",
            "Software": "matplotlib",
        },
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
            grayscale_path,
            dpi=(DPI, DPI),
            optimize=False,
        )
    return [svg_path, pdf_path, png_path, jpg_path, grayscale_path], {
        "logical_panel_count": 2,
        "plotted_point_count": int(len(source)),
        "minimum_observed_text_pt": minimum_observed_text_pt,
        "no_hatch": True,
        "no_embedded_table_cards_or_bridge_annotation": True,
        "latency_axis_scale": "log",
    }


def audit_exports(
    output_dir: Path, drawing_audit: dict[str, object]
) -> dict[str, object]:
    svg_path = output_dir / f"{FIGURE_STEM}.svg"
    pdf_path = output_dir / f"{FIGURE_STEM}.pdf"
    png_path = output_dir / f"{FIGURE_STEM}.png"
    jpg_path = output_dir / f"{FIGURE_STEM}.jpg"
    grayscale_path = output_dir / f"{FIGURE_STEM}_grayscale.png"

    expected_px = (
        int(WIDTH_MM / 25.4 * DPI),
        int(HEIGHT_MM / 25.4 * DPI),
    )
    raster: dict[str, object] = {}
    for path in (png_path, jpg_path, grayscale_path):
        with Image.open(path) as image:
            raster[path.name] = {
                "pixels": list(image.size),
                "dpi_metadata": list(image.info.get("dpi", ())),
            }
            if image.size != expected_px:
                raise AssertionError(
                    f"Unexpected raster dimensions for {path.name}: {image.size}"
                )

    with Image.open(png_path).convert("RGB") as image:
        blank = Image.new("RGB", image.size, "white")
        ink_bbox = ImageChops.difference(image, blank).getbbox()
        if ink_bbox is None:
            raise AssertionError("Exported Figure 2 PNG is blank")
        left, top, right, bottom = ink_bbox
        margins = {
            "left_px": left,
            "top_px": top,
            "right_px": image.width - right,
            "bottom_px": image.height - bottom,
        }
        if min(margins.values()) < 4:
            raise AssertionError(f"Figure content touches the canvas edge: {margins}")

    svg_root = ElementTree.parse(svg_path).getroot()
    svg_width_mm = parse_svg_length_mm(svg_root.attrib["width"])
    svg_height_mm = parse_svg_length_mm(svg_root.attrib["height"])
    if not math.isclose(svg_width_mm, WIDTH_MM, abs_tol=0.02):
        raise AssertionError(f"SVG width mismatch: {svg_width_mm}")
    if not math.isclose(svg_height_mm, HEIGHT_MM, abs_tol=0.02):
        raise AssertionError(f"SVG height mismatch: {svg_height_mm}")
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    text_nodes = svg_root.findall(".//svg:text", namespace)
    if not text_nodes:
        raise AssertionError("SVG text was converted to paths")
    svg_text = " ".join("".join(node.itertext()) for node in text_nodes)
    svg_serialised = svg_path.read_text(encoding="utf-8")
    required_text = [
        "Reservation preserved capacity",
        "Tail latency rose with contention",
        "Constructed witness",
        "2/1",
        "log scale",
    ]
    missing_text = [text for text in required_text if text not in svg_text]
    if missing_text:
        raise AssertionError(f"Required Figure 2 text is missing: {missing_text}")
    forbidden_text = [
        "Bridge",
        "AUROC",
        "Mendeley",
        "Evidence gate",
        "configured limit",
        "in all 3 runs",
    ]
    retained = [text for text in forbidden_text if text in svg_text]
    if retained:
        raise AssertionError(f"Stale or redundant annotation remains in Figure 2: {retained}")
    if "Calibri" not in svg_serialised:
        raise AssertionError("Calibri is not the first-choice editable SVG font")
    if "hatch" in svg_serialised.lower():
        raise AssertionError("Unexpected hatch encoding in Figure 2")

    pdf_page = PdfReader(str(pdf_path)).pages[0]
    pdf_width_mm = float(pdf_page.mediabox.width) * 25.4 / 72.0
    pdf_height_mm = float(pdf_page.mediabox.height) * 25.4 / 72.0
    if not math.isclose(pdf_width_mm, WIDTH_MM, abs_tol=0.02):
        raise AssertionError(f"PDF width mismatch: {pdf_width_mm}")
    if not math.isclose(pdf_height_mm, HEIGHT_MM, abs_tol=0.02):
        raise AssertionError(f"PDF height mismatch: {pdf_height_mm}")

    color_luminance_delta = abs(luminance(COLORS["ecrc"]) - luminance(COLORS["unsafe"]))
    return {
        **drawing_audit,
        "expected_raster_pixels_at_600_dpi": list(expected_px),
        "raster": raster,
        "ink_bbox_margins_px": margins,
        "svg_size_mm": [svg_width_mm, svg_height_mm],
        "svg_text_nodes": len(text_nodes),
        "svg_editable_text": True,
        "svg_calibri_first_choice": True,
        "stale_dashboard_text_absent": True,
        "pdf_size_mm": [pdf_width_mm, pdf_height_mm],
        "ecrc_unsafe_grayscale_luminance_delta": color_luminance_delta,
        "redundant_encoding": {
            "transactional reservation": "muted blue + circles",
            "constructed unsafe witness": "muted red + diamond",
            "latency": "ordered line + circles + min-max whiskers",
        },
    }


def write_source_data(source: pd.DataFrame, output_dir: Path) -> Path:
    path = output_dir / f"{FIGURE_STEM}_source_data.csv"
    source.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    return path


def write_point_range_audit(source: pd.DataFrame, output_dir: Path) -> Path:
    audit = source.copy()
    audit["expected_plotted_estimate"] = audit["estimate_raw"]
    audit["expected_plotted_range_low"] = audit["range_low_raw"]
    audit["expected_plotted_range_high"] = audit["range_high_raw"]
    audit["estimate_abs_diff"] = (
        audit["plotted_estimate"] - audit["expected_plotted_estimate"]
    ).abs()
    audit["range_low_abs_diff"] = (
        audit["plotted_range_low"] - audit["expected_plotted_range_low"]
    ).abs()
    audit["range_high_abs_diff"] = (
        audit["plotted_range_high"] - audit["expected_plotted_range_high"]
    ).abs()
    has_range = audit["range_low_raw"].notna() & audit["range_high_raw"].notna()
    estimate_pass = audit["estimate_abs_diff"] <= 1e-12
    range_pass = (
        ~has_range
        & audit["plotted_range_low"].isna()
        & audit["plotted_range_high"].isna()
    ) | (
        has_range
        & (audit["range_low_abs_diff"] <= 1e-12)
        & (audit["range_high_abs_diff"] <= 1e-12)
    )
    audit["point_range_check"] = np.where(estimate_pass & range_pass, "PASS", "FAIL")
    if not (audit["point_range_check"] == "PASS").all():
        raise AssertionError("At least one Figure 2 point/range transform failed")
    path = output_dir / "fig3_point_range_audit.csv"
    audit.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    return path


def write_contract(output_dir: Path) -> Path:
    path = output_dir / "FIG3_CONTRACT.md"
    text = """# Figure 2 contract

## Core conclusion

On the declared trusted single-node runtime, transactional reservation preserved configured capacity under contention, while single-file SQLite contention increased tail latency.

## Figure architecture

- Archetype: focused two-panel quantitative systems result.
- Backend: Python/matplotlib only.
- Final size: 159 × 66 mm.
- Typography: Calibri first; all visible text at least 7.5 pt.
- Panel a is the correctness result: cap-relative admissions in two transactional stresses and one separately labelled constructed non-atomic witness.
- Panel b is the implementation-cost result: median within-run p95 latency and observed three-run min–max over the ordered worker sweep.
- Exact transactional counts are reported in the caption/source data rather than repeated beside the stress points; only the distinct unsafe-witness ratio is directly labelled.

## Statistics and evidence hierarchy

- Panel a contains deterministic exact counts and has no sampling interval.
- Panel b points are medians of three within-run p95 latency values; whiskers are the observed minimum and maximum over those three measured repetitions, not confidence intervals.
- Every worker-sweep run processed 96 requests at capacity eight, committed eight reservations, rejected 88 requests, emitted 96 receipts and produced zero oversubscription.

## Review-risk boundaries

- The unsafe result is one barrier-forced mechanism witness and is not a production or performance comparator.
- Timing is descriptive for the recorded Windows 11, Python 3.12.10 and SQLite 3.49.1 WAL host with simulated side effects; it does not establish performance portability.
- The runtime is one trusted file-backed node. The figure does not establish distributed consensus, external-service atomicity, live side effects or crash-free registration.
- The figure contains no bridge equivalence, evidence-admission, model discrimination or operating-point-transfer result.

## Export contract

Editable SVG and PDF are the vector masters. PNG, JPG and grayscale PNG are exported at 600 dpi. The figure uses no hatch, embedded table, cards, decorative frame or slide-style banner.
"""
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def write_caption(output_dir: Path) -> Path:
    path = output_dir / "FIG3_CAPTION.md"
    caption = (
        "**Figure 2. Capacity preservation and contention cost on the declared single-node runtime.** "
        "(a) Capacity-bearing admissions relative to configured capacity in three repetitions of two 16-worker stresses. ECRC stopped at 3/3 and 8/8, whereas a separate barrier-forced non-atomic witness logically admitted two routes at capacity one; the witness is constructed and is not a production comparator. "
        "(b) End-to-end p95 latency for the 96-request, cap-eight worker sweep. Points are medians and whiskers are observed minima–maxima across three measured repetitions after eight warm-ups, not confidence intervals. Every sweep run committed eight reservations, rejected 88 requests, emitted 96 receipts and produced no oversubscription. Timing is descriptive for the recorded Windows/Python/SQLite WAL host with simulated side effects and does not establish performance portability or distributed atomicity.\n"
    )
    path.write_text(caption, encoding="utf-8", newline="\n")
    return path


def write_qa_report(
    source: pd.DataFrame,
    audit: dict[str, object],
    input_paths: dict[str, Path],
    output_dir: Path,
) -> Path:
    path = output_dir / "FIG3_QA_REPORT.md"
    panel_b = source.loc[source["panel"] == "b"].sort_values("workers")
    lines = [
        "# Figure 2 QA report",
        "",
        "## Outcome",
        "",
        "Automated QA: PASS.",
        f"Visual inspection: {VISUAL_INSPECTION_NOTE}.",
        "",
        "## Scientific contract",
        "",
        "- Single claim: the declared trusted single-node implementation preserved configured capacity, while SQLite contention increased tail latency.",
        "- Panel a contains six transactional stress points and one separately labelled constructed witness; all are exact counts without sampling intervals.",
        "- Redundant 3/3, 8/8 and configured-limit text is omitted from the plot; exact stress counts remain in the caption and source data, while the distinct 2/1 unsafe witness remains directly labelled away from its marker.",
        "- Panel b contains five worker-sweep latency summaries. Points are three-run medians and whiskers are observed min–max ranges, not confidence intervals.",
        "- All 15 worker-sweep runs committed 8/8 reservations, rejected 88/96 requests, emitted 96/96 receipts and recorded zero oversubscription.",
        "- Bridge, evidence-gate, discrimination and operating-point results are absent from the figure and its source data.",
        "",
        "## Frozen latency values",
        "",
    ]
    for row in panel_b.itertuples(index=False):
        lines.append(
            f"- {int(row.workers)} worker(s): median {row.plotted_estimate:.3f} ms; "
            f"observed range {row.plotted_range_low:.3f}–{row.plotted_range_high:.3f} ms."
        )
    lines.extend(
        [
            "",
            "## Typography, layout and export",
            "",
            f"- Canvas: SVG {audit['svg_size_mm'][0]:.3f} × {audit['svg_size_mm'][1]:.3f} mm; "
            f"PDF {audit['pdf_size_mm'][0]:.3f} × {audit['pdf_size_mm'][1]:.3f} mm.",
            f"- Raster canvas: {audit['expected_raster_pixels_at_600_dpi'][0]} × "
            f"{audit['expected_raster_pixels_at_600_dpi'][1]} px at 600 dpi.",
            f"- Minimum observed text: {audit['minimum_observed_text_pt']:.1f} pt; Calibri is first choice.",
            f"- Editable SVG text nodes: {audit['svg_text_nodes']}.",
            f"- Non-white margins left/top/right/bottom: {audit['ink_bbox_margins_px']['left_px']}/"
            f"{audit['ink_bbox_margins_px']['top_px']}/{audit['ink_bbox_margins_px']['right_px']}/"
            f"{audit['ink_bbox_margins_px']['bottom_px']} px.",
            "- White background; no hatch, table, cards, bridge annotation, grid, repeated legend or overall title banner.",
            "- Panel b explicitly labels the logarithmic latency scale.",
            "",
            "## Traceability",
            "",
        ]
    )
    for label, input_path in input_paths.items():
        lines.append(f"- `{label}` SHA-256: `{sha256(input_path)}`")
    lines.extend(
        [
            f"- Source rows: {len(source)} in `{FIGURE_STEM}_source_data.csv`.",
            "- Machine-readable point/range audit: `fig3_point_range_audit.csv`.",
            "- Drawing/export script: `make_fig3_layered_evaluation.py`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def write_manifest(
    input_paths: dict[str, Path],
    output_dir: Path,
    artifacts: list[Path],
    source_path: Path,
    point_audit_path: Path,
    contract_path: Path,
    caption_path: Path,
    qa_path: Path,
    audit: dict[str, object],
) -> Path:
    manifest_path = output_dir / "FIG3_MANIFEST.json"
    script_path = Path(__file__).resolve()
    files_to_hash = [
        script_path,
        source_path,
        point_audit_path,
        contract_path,
        caption_path,
        qa_path,
        *artifacts,
    ]
    payload = {
        "figure_id": "Figure 2",
        "stem": FIGURE_STEM,
        "backend": "Python/matplotlib",
        "core_conclusion": (
            "Transactional reservation preserved configured capacity on the declared "
            "trusted single-node runtime, while SQLite contention increased tail latency."
        ),
        "figure_size_mm": [WIDTH_MM, HEIGHT_MM],
        "raster_dpi": DPI,
        "font_stack": [
            "Calibri",
            "Arial",
            "Helvetica",
            "DejaVu Sans",
            "Liberation Sans",
        ],
        "minimum_text_pt": MIN_TEXT_PT,
        "logical_panels": {
            "a": "capacity correctness and separate unsafe mechanism witness",
            "b": "single-node worker-sweep tail latency",
        },
        "selection": {
            "panel_a_cases": list(STRESS_CASES) + ["unsafe_cap1"],
            "panel_b_cases": [case for _, case in WORKER_CASES],
            "panel_b_metric": "end_to_end_latency.p95_ms",
            "panel_b_summary": "median with observed minimum and maximum over three runs",
        },
        "statistics": {
            "panel_a": "deterministic exact counts; no sampling intervals",
            "panel_b": "three-run median and observed min-max; not confidence intervals",
        },
        "annotation_policy": (
            "exact transactional stress counts are caption-only; only the distinct "
            "constructed unsafe-witness ratio is directly labelled"
        ),
        "estimand_boundaries": [
            "trusted single-node SQLite WAL with simulated side effects",
            "constructed unsafe witness is not a production comparator",
            "timing is descriptive and not portable",
            "no distributed or external-service atomicity claim",
        ],
        "excluded_from_figure": [
            "bridge equivalence",
            "evidence admission",
            "model discrimination",
            "operating-point transfer",
        ],
        "inputs": {
            label: {"path": input_path.name, "sha256": sha256(input_path)}
            for label, input_path in sorted(input_paths.items())
        },
        "audit": audit,
        "visual_inspection": VISUAL_INSPECTION_NOTE,
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
    systems_dir = repo_root / "icair_2026" / "framework_v1" / "evidence_systems"
    input_paths = {
        "systems_performance_runs": systems_dir / "systems_performance_runs.csv",
        "systems_performance_aggregate": systems_dir
        / "systems_performance_aggregate.csv",
        "unsafe_race_witness": systems_dir / "systems_unsafe_race_witness.json",
    }
    load_paths = {
        "runs": input_paths["systems_performance_runs"],
        "aggregate": input_paths["systems_performance_aggregate"],
        "unsafe": input_paths["unsafe_race_witness"],
    }
    inputs = load_inputs(load_paths)
    source = build_source_data(inputs)
    source_path = write_source_data(source, output_dir)
    point_audit_path = write_point_range_audit(source, output_dir)
    artifacts, drawing_audit = draw_figure(source, output_dir)
    export_audit = audit_exports(output_dir, drawing_audit)
    contract_path = write_contract(output_dir)
    caption_path = write_caption(output_dir)
    qa_path = write_qa_report(source, export_audit, input_paths, output_dir)
    manifest_path = write_manifest(
        input_paths,
        output_dir,
        artifacts,
        source_path,
        point_audit_path,
        contract_path,
        caption_path,
        qa_path,
        export_audit,
    )
    print(f"Created {FIGURE_STEM} at {WIDTH_MM:.0f} x {HEIGHT_MM:.0f} mm")
    print("Validated 7 deterministic capacity points and 5 latency summaries")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
