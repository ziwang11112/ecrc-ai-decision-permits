"""Figure 6 from completed local-service results; never runs an experiment.

python build_fig6.py --results ../out --out .
Required CSVs: performance_summary.csv, recovery_results.csv.
Optional performance_runs.csv enables independent aggregate verification.
The output inputs/ directory is a portable data snapshot for the same command.
Style/export settings derive from the previously reviewed Figures 4/5 builder.
Current source overlay omits standalone manuscript-caption prose and its output;
plotting, input validation and measurements remain unchanged.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from PIL import Image

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 6.5, 4.0
BLACK, BLUE, GRAY = "#000000", "#24557A", "#777777"
ARMS = ("ecrc", "ordinary")
ARM_STYLE = {
    "ecrc": dict(label="ECRC adapter", color=BLUE, marker="o", offset=-0.09),
    "ordinary": dict(label="Ordinary outbox", color=GRAY, marker="s", offset=0.09),
}
WORKERS = (1, 4, 8)
REPS = 5
TIMED_ACTIONS = 64
SCENARIOS = (
    "normal", "crash_after_intent", "crash_after_ack", "drop_after_commit",
    "crash_before_local_commit", "crash_after_local_commit", "concurrent_retries",
    "sink_restart_after_lost_ack", "temporary_outage",
)
FIXED_DATE = datetime(2026, 9, 11, tzinfo=timezone.utc)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf8")


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def integer(row, key):
    value = float(row[key])
    if not math.isfinite(value) or not value.is_integer():
        raise ValueError(f"Expected finite integer {key}: {row}")
    return int(value)


def one(rows, **criteria):
    selected = [row for row in rows if all(str(row.get(k)) == str(v) for k, v in criteria.items())]
    if len(selected) != 1:
        raise ValueError(f"Expected exactly one row for {criteria}; found {len(selected)}")
    return selected[0]


def validate(performance, recovery, runs=None):
    expected_perf = {(arm, w) for arm in ARMS for w in WORKERS}
    actual_perf = [(r["arm"], integer(r, "workers")) for r in performance]
    if len(actual_perf) != len(expected_perf) or set(actual_perf) != expected_perf:
        raise ValueError("Performance summary must contain the six declared arm/worker cells, once each")
    plotted = []
    for arm in ARMS:
        for workers in WORKERS:
            row = one(performance, arm=arm, workers=workers)
            if integer(row, "repetitions") != REPS:
                raise ValueError("Figure 6 protocol requires five repetitions per cell")
            med, low, high = [float(row[f"p95_latency_ms_{k}"]) for k in ("median", "min", "max")]
            if not all(math.isfinite(v) for v in (med, low, high)) or not 0 < low <= med <= high:
                raise ValueError(f"Invalid p95 latency summary: {row}")
            plotted.append(dict(arm=arm, workers=workers, run_p95_median_ms=med,
                                run_p95_min_ms=low, run_p95_max_ms=high, repetitions=REPS,
                                source="performance_summary.csv"))
    expected_recovery = {(arm, s, rep) for arm in ARMS for s in SCENARIOS for rep in range(1, REPS + 1)}
    actual_recovery = [(r["arm"], r["scenario"], integer(r, "rep")) for r in recovery]
    if len(actual_recovery) != len(expected_recovery) or set(actual_recovery) != expected_recovery:
        raise ValueError("Recovery input must contain all 90 declared arm/scenario/repetition cases, once each")
    error_columns = ("duplicate_effects", "omitted_effects", "receipt_mismatches", "oversubscription")
    for row in recovery:
        for key in error_columns:
            if integer(row, key) < 0:
                raise ValueError(f"Negative integrity counter: {row}")
    totals = {key: sum(integer(r, key) for r in recovery) for key in error_columns}
    expected_final = dict(final_effects=1, final_receipts=1, final_reserved=0, final_committed=1)
    final_expected = sum(all(integer(r, k) == v for k, v in expected_final.items()) for r in recovery)
    hold_scenarios = set(SCENARIOS) - {"normal", "concurrent_retries", "crash_after_local_commit"}
    uncertain_rows = [r for r in recovery if r["scenario"] in hold_scenarios]
    held_expected = sum(integer(r, "intermediate_reserved") == 1
                        and integer(r, "intermediate_receipts") == 0 for r in uncertain_rows)
    checks = dict(performance_cells=6, performance_repetitions_per_cell=REPS,
                  recovery_cases=len(recovery), recovery_scenarios=len(SCENARIOS),
                  recovery_repetitions_per_arm_scenario=REPS,
                  recovery_error_counter_totals=totals,
                  final_expected_state_cases=final_expected,
                  held_uncertain_cases=held_expected, expected_uncertain_cases=len(uncertain_rows),
                  integrity_counters_are_input_results_not_new_experiments=True,
                  p95_aggregation="median/min/max of five per-run p95 latency estimates",
                  bars_are="observed min-max ranges; not confidence intervals",
                  raw_performance_aggregate_check=False,
                  timed_actions_per_run=TIMED_ACTIONS,
                  timed_actions_source="fixed protocol; checked against raw runs when supplied")
    if runs is not None:
        expected_runs = {(a, w, r) for a in ARMS for w in WORKERS for r in range(1, REPS + 1)}
        keys = [(r["arm"], integer(r, "workers"), integer(r, "rep")) for r in runs]
        if len(keys) != len(expected_runs) or set(keys) != expected_runs:
            raise ValueError("Raw performance runs must contain all 30 declared cases")
        if any(integer(r, "n_timed_requests") != TIMED_ACTIONS for r in runs):
            raise ValueError("Expected 64 timed preissued actions per run")
        for row in plotted:
            selected = [float(r["p95_latency_ms"]) for r in runs
                        if r["arm"] == row["arm"] and integer(r, "workers") == row["workers"]]
            for key, value in (("run_p95_median_ms", statistics.median(selected)),
                               ("run_p95_min_ms", min(selected)), ("run_p95_max_ms", max(selected))):
                if not math.isclose(row[key], value, rel_tol=1e-10, abs_tol=1e-9):
                    raise ValueError(f"Aggregate differs from raw performance runs: {row['arm']}, {row['workers']}, {key}")
        checks["raw_performance_aggregate_check"] = True
    return plotted, checks


def setup():
    font_path = font_manager.findfont(font_manager.FontProperties(family="Arial"), fallback_to_default=False)
    plt.rcParams.update({
        "font.family": "Arial", "font.size": 9, "axes.labelsize": 9,
        "axes.titlesize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.fontsize": 8, "axes.linewidth": 0.6, "lines.linewidth": 0.8,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "text.color": BLACK, "axes.labelcolor": BLACK,
        "xtick.color": BLACK, "ytick.color": BLACK, "axes.edgecolor": BLACK,
        "figure.facecolor": "white", "savefig.facecolor": "white", "legend.frameon": False,
        "svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.hashsalt": "iasc-ecrc-journal-redraw-2026-09-11",
    })
    return font_path


def arrow(ax, start, end):
    ax.annotate("", xy=end, xytext=start,
                arrowprops=dict(arrowstyle="->", color=BLACK, lw=0.8,
                                mutation_scale=9, shrinkA=0, shrinkB=0))


def draw_figure(plotted):
    fig = plt.figure(figsize=(WIDTH, HEIGHT))
    diagram = fig.add_axes([0, 0, 1, 1])
    diagram.set(xlim=(0, 1), ylim=(0, 1))
    diagram.axis("off")
    fig.text(.025, .958, "(a) Authorization and recovery boundary", fontsize=9, fontweight="bold", va="top")
    boxes = [
        (.025, "Client DB: arm", "Validate permit and reservation\nPersist immutable delivery intent", "#EAF1F6"),
        (.363, "Independent HTTP / sink DB", "Atomically commit effect\nand key / payload binding", "#F0F0F0"),
        (.701, "Client DB: reconcile", "Receipt + capacity commitment\n+ completed intent, atomically", "#EAF1F6"),
    ]
    width = .274
    for x, title, body, fill in boxes:
        diagram.add_patch(Rectangle((x, .724), width, .168,
                                    facecolor=fill, edgecolor=BLACK, linewidth=.6))
        fig.text(x + width / 2, .864, title, ha="center", va="top", fontsize=8.6, fontweight="bold")
        fig.text(x + width / 2, .801, body, ha="center", va="top", fontsize=8, linespacing=1.4)
    arrow(diagram, (.303, .803), (.357, .803))
    arrow(diagram, (.641, .803), (.695, .803))
    fig.text(.162, .700, "Authorization linearization point\n(irrevocable grant)", ha="center", va="top", fontsize=8, linespacing=1.15)
    fig.text(.500, .700, "Same key / payload on retry", ha="center", va="top", fontsize=8)
    fig.text(.838, .700, "Use the durable service\nacknowledgement", ha="center", va="top", fontsize=8, linespacing=1.15)
    diagram.add_patch(Rectangle((.025, .560), .95, .072, facecolor="white", edgecolor=GRAY, linewidth=.6))
    fig.text(.500, .597, "Outcome unknown: retain reservation; retry the same key and payload.",
             ha="center", va="center", fontsize=8.5)
    fig.text(.025, .505, "(b) Delivery latency", fontsize=9, fontweight="bold", va="top")
    ax = fig.add_axes([.115, .145, .64, .315])
    ax.spines[["top", "right"]].set_visible(False)
    maximum = max(r["run_p95_max_ms"] for r in plotted)
    ax.set_xlim(-.35, 2.35)
    ax.set_ylim(0, maximum * 1.13)
    ax.set_xticks(range(len(WORKERS)), [str(w) for w in WORKERS])
    ax.set_xlabel("Concurrent workers", fontsize=8, labelpad=3)
    ax.set_ylabel("p95 latency (ms)", fontsize=8, labelpad=3)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(nbins=4))
    ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    ax.grid(axis="y", color="#DDDDDD", lw=.45, zorder=0)
    for arm in ARMS:
        style = ARM_STYLE[arm]
        values = [one(plotted, arm=arm, workers=w) for w in WORKERS]
        xs = [i + style["offset"] for i in range(len(WORKERS))]
        med = [r["run_p95_median_ms"] for r in values]
        yerr = [[r["run_p95_median_ms"] - r["run_p95_min_ms"] for r in values],
                [r["run_p95_max_ms"] - r["run_p95_median_ms"] for r in values]]
        ax.errorbar(xs, med, yerr=yerr, fmt=style["marker"], color=style["color"],
                    ecolor=style["color"], ms=4.3, elinewidth=.9, capsize=3,
                    capthick=.8, mfc=style["color"], mec=style["color"], zorder=3)
    handles = [Line2D([], [], color=ARM_STYLE[a]["color"], marker=ARM_STYLE[a]["marker"],
                      lw=0, ms=4.3, label=ARM_STYLE[a]["label"]) for a in ARMS]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(.779, .452),
               borderaxespad=0, handletextpad=.5, handlelength=1.0, labelspacing=.7)
    fig.text(.786, .293, "5 runs per cell\n64 preissued\nactions per run", fontsize=8, va="top", linespacing=1.35)
    fig.text(.025, .034, "Points: median of run-level p95; bars: minimum-maximum across five runs.", fontsize=8)
    return fig


def export(fig, path):
    # Match the stable metadata and resolutions of the reviewed earlier figures.
    outputs = {}
    fig.canvas.draw()
    text_items = [item for item in fig.findobj(matplotlib.text.Text) if item.get_text() and item.get_visible()]
    if min(t.get_fontsize() for t in text_items) < 8:
        raise ValueError("A visible text item is below 8 pt")
    if any(matplotlib.colors.to_hex(t.get_color()) != BLACK for t in text_items):
        raise ValueError("All figure text must be black")
    bounds = fig.bbox
    outside = [t.get_text() for t in text_items if not bounds.fully_contains(*t.get_window_extent().get_points()[0])
               or not bounds.fully_contains(*t.get_window_extent().get_points()[1])]
    if outside:
        raise ValueError(f"Text outside figure bounds: {outside}")
    for ext in ("pdf", "svg", "png", "tiff"):
        kwargs = dict(dpi=1200 if ext == "tiff" else 600)
        if ext == "pdf":
            kwargs["metadata"] = dict(CreationDate=FIXED_DATE, ModDate=FIXED_DATE,
                                       Creator="Matplotlib; local frozen-data journal redraw")
        elif ext == "svg":
            kwargs["metadata"] = dict(Date="2026-09-11")
        elif ext == "tiff":
            kwargs["pil_kwargs"] = dict(compression="tiff_lzw")
        target = path.with_suffix("." + ext)
        fig.savefig(target, **kwargs)
        outputs[ext] = dict(path=target.name, sha256=sha(target))
    plt.close(fig)
    with Image.open(path.with_suffix(".png")) as raster:
        png_dimensions = list(raster.size)
        raster.convert("L").save(path.with_name(path.name + "_grayscale").with_suffix(".png"))
    qa = dict(outputs=outputs, minimum_font_pt=min(t.get_fontsize() for t in text_items),
              width_inches=WIDTH, height_inches=HEIGHT, all_text_black=True,
              text_within_figure=True, png_dimensions=png_dimensions)
    try:
        import pymupdf
        with pymupdf.open(path.with_suffix(".pdf")) as doc:
            page = doc[0]
            fonts = [dict(name=f[3], embedded=bool(doc.extract_font(f[0])[3])) for f in page.get_fonts()]
            if not all(f["embedded"] for f in fonts):
                raise ValueError("PDF contains unembedded fonts")
            if page.get_images():
                raise ValueError("Expected an entirely vector PDF")
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(path.with_name(path.name + "_proof").with_suffix(".png"))
            qa.update(fonts=fonts, raster_images_in_pdf=0, page_size_points=list(page.rect))
    except ImportError:
        qa["pdf_font_check"] = "Install PyMuPDF for the PDF font and vector check."
    return qa


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path,
                        help="Completed result directory containing the two required CSVs")
    parser.add_argument("--out", required=True, type=Path, help="Figure and portable input snapshot directory")
    args = parser.parse_args()
    source = args.results.resolve()
    required = ("performance_summary.csv", "recovery_results.csv")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        parser.error("Completed inputs are required; missing: " + ", ".join(missing))
    performance, recovery = [read_csv(source / name) for name in required]
    runs_path = source / "performance_runs.csv"
    plotted, checks = validate(performance, recovery, read_csv(runs_path) if runs_path.is_file() else None)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = out / "inputs"
    data.mkdir(exist_ok=True)
    provenance = []
    for name in (*required, "performance_runs.csv", "manifest.json"):
        original = source / name
        if original.is_file():
            target = data / name
            if original.resolve() != target.resolve():
                shutil.copyfile(original, target)
            provenance.append(dict(source=str(original), snapshot="inputs/" + name, sha256=sha(target)))
    # The protocol is optional when rebuilding a portable snapshot, but capture it when available.
    protocol_sources = [source / "PROTOCOL.md", source.parent / "PROTOCOL.md"]
    for original in protocol_sources:
        if original.is_file():
            target = data / "PROTOCOL.md"
            if original.resolve() != target.resolve():
                shutil.copyfile(original, target)
            provenance.append(dict(source=str(original), snapshot="inputs/PROTOCOL.md", sha256=sha(target)))
            break
    font = setup()
    write_csv(out / "fig6_plot_values.csv", plotted)
    write_json(out / "validation_checks.json", checks)
    qa = export(draw_figure(plotted), out / "fig6")
    manifest = dict(python=platform.python_version(), matplotlib=matplotlib.__version__,
                    style=dict(font="Arial", font_path_at_build=str(font), text_color=BLACK,
                               width_inches=WIDTH, height_inches=HEIGHT, minimum_font_pt=8,
                               data_colors=[BLUE, GRAY], png_dpi=600, tiff_dpi=1200),
                    style_source="Previously reviewed build_fig4_fig5.py / journal_style.py export settings",
                    provenance=provenance, validation=checks, figure=qa,
                    script_sha256=sha(__file__), plot_values_sha256=sha(out / "fig6_plot_values.csv"),
                    validation_sha256=sha(out / "validation_checks.json"),
                    experiments_or_models_run=False)
    write_json(out / "fig6_manifest.json", manifest)
    print(json.dumps(dict(figure=qa, validation=checks), indent=2))


if __name__ == "__main__":
    main()
