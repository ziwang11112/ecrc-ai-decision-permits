"""Plot every saved pacing contrast and interval without estimating new results.

Run: python build_pacing_figure.py [--out NEW_DIRECTORY]
Requires Matplotlib. Source data are resolved relative to this script.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
SOURCE = PACKAGE / "data/fig5_plot_data.csv"
SOURCE_SHA256 = "52d5b047f77348d3a76b864f3b50295acb2311d0dca7a360148fb6b521422249"
INK, TEAL, GREY = "#263640", "#176B70", "#677078"
COHORTS = ("Development", "External")
MODELS = ("hist_gradient_boosting", "regularised_logistic", "history_baseline")
MODEL_LABELS = {"hist_gradient_boosting": "HGB",
                "regularised_logistic": "Logistic", "history_baseline": "History rule"}
BUDGETS = ("eight_per_episode", "eight_per_100_planned")
BUDGET_LABELS = {"eight_per_episode": "Episode", "eight_per_100_planned": "100 planned"}
PANELS = ("alert_precision", "alert_coverage", "budget_utilization")
ESTIMANDS = ("pooled", "participant_equal_common_valid")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PACKAGE / "exports")
    args = parser.parse_args()
    assert sha256(SOURCE) == SOURCE_SHA256, "Saved source bytes changed"
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    conditions = [(c, m, b) for c in COHORTS for m in MODELS for b in BUDGETS]
    expected = {(p, c, m, b, e) for p in PANELS for c, m, b in conditions
                for e in ESTIMANDS if p != "budget_utilization" or e == "pooled"}
    lookup = {}
    for source_index, row in enumerate(rows):
        key = tuple(row[x] for x in ("panel", "cohort", "model_name", "capacity_basis", "estimand"))
        assert key not in lookup, f"Duplicate source key: {key}"
        estimate, low, high = [float(row[x]) for x in ("estimate", "ci_low", "ci_high")]
        assert all(math.isfinite(v) for v in (estimate, low, high)) and low <= estimate <= high
        assert row["units"] == "proportion difference" and int(row["finite_replicates"]) == 2000
        lookup[key] = (source_index, row)
    assert len(rows) == 60 and set(lookup) == expected and len(conditions) == 12

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.6,
                         "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK,
                         "pdf.fonttype": 42, "ps.fonttype": 42,
                         "svg.fonttype": "none", "svg.hashsalt": "ecrc-pacing-20260912"})
    fig = plt.figure(figsize=(6.5, 5.35))
    # Two left text columns preserve natural model names and both budget bases.
    left, bottom, width, height, gap = .305, .145, .184, .738, .046
    axes = [fig.add_axes([left + j * (width + gap), bottom, width, height]) for j in range(3)]
    label_ax = fig.add_axes([.014, bottom, .278, height], sharey=axes[0])
    label_ax.set(xlim=(0, 1), ylim=(13.85, -.55))
    label_ax.axis("off")
    titles = ("(a) Alert precision", "(b) Alert coverage", "(c) Budget use")
    tick_values = ((-.05, 0, .1, .2), (-.06, -.04, -.02, 0), (-.3, -.2, -.1, 0))
    limits = ((-.081, .211), (-.0625, .0095), (-.385, .018))
    plotted = []
    # A blank row divides the two cohorts. All 12 conditions appear in all panels.
    yvalues = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]
    for ax, title, ticks, xlim in zip(axes, titles, tick_values, limits):
        ax.set(ylim=(13.85, -.55), xlim=xlim)
        ax.set_title(title, loc="left", fontsize=9.2, pad=9, weight="bold")
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: "0" if x == 0 else f"{x:.2f}".rstrip("0").rstrip(".")))
        ax.tick_params(axis="x", labelsize=8.4, length=3, pad=4)
        ax.tick_params(axis="y", left=False, labelleft=False)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(GREY)
        ax.spines["bottom"].set_linewidth(.65)
        ax.grid(axis="x", color="#E4E7EA", linewidth=.55)
        ax.axvline(0, color=GREY, linewidth=.85, zorder=2)
        ax.axhline(6.65, color="#CDD4D8", linewidth=.65)
    label_ax.text(0, -.55, "Model", weight="bold", fontsize=8.7, va="bottom")
    label_ax.text(.64, -.55, "8 units per", weight="bold", fontsize=8.7, va="bottom")
    for y, cohort, n in ((.1, "Development", 617), (7.1, "External", 59)):
        label_ax.text(0, y, f"{cohort} (n = {n})", fontsize=9.0, weight="bold", va="center", color=TEAL)
    label_ax.axhline(6.65, color="#CDD4D8", linewidth=.65)

    for condition, y in zip(conditions, yvalues):
        cohort, model, budget = condition
        label_ax.text(0, y, MODEL_LABELS[model], va="center", fontsize=8.6)
        label_ax.text(.64, y, BUDGET_LABELS[budget], va="center", fontsize=8.3)
        for panel_index, (panel, ax) in enumerate(zip(PANELS, axes)):
            for estimand in ESTIMANDS:
                if panel == "budget_utilization" and estimand != "pooled":
                    continue
                key = (panel, cohort, model, budget, estimand)
                source_index, row = lookup[key]
                estimate, low, high = [float(row[x]) for x in ("estimate", "ci_low", "ci_high")]
                pooled = estimand == "pooled"
                mark_y = y if panel == "budget_utilization" else y + (-.16 if pooled else .16)
                color = TEAL if pooled else GREY
                ax.errorbar(estimate, mark_y, xerr=[[estimate - low], [high - estimate]],
                            fmt="o" if pooled else "D", color=color, ecolor=color,
                            markerfacecolor=color if pooled else "white", markeredgewidth=.85,
                            markersize=3.4, elinewidth=.95, capsize=2.0, capthick=.8, zorder=3)
                assert ax.get_xlim()[0] < low <= estimate <= high < ax.get_xlim()[1]
                plotted.append({"source_row_index_zero_based": source_index,
                                "source_row": row, "panel_index": panel_index,
                                "condition_index": conditions.index(condition),
                                "y": mark_y, "plotted_estimate": estimate,
                                "plotted_ci_low": low, "plotted_ci_high": high})

    fig.text(.637, .075, "Pacing − FIFO (proportion difference)", fontsize=9.0, ha="center")
    handles = [Line2D([], [], color=TEAL, marker="o", markersize=4, linewidth=1,
                      label="Pooled"),
               Line2D([], [], color=GREY, marker="D", markerfacecolor="white", markersize=4,
                      linewidth=1, label="Participant-equal (common valid)")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.51, .005),
               ncol=2, frameon=False, fontsize=8.7, handlelength=1.7, columnspacing=2)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for artist in fig.findobj(match=matplotlib.text.Text):
        if artist.get_visible() and artist.get_text():
            box = artist.get_window_extent(renderer)
            assert fig.bbox.contains(box.x0, box.y0) and fig.bbox.contains(box.x1, box.y1), artist.get_text()
    assert len(plotted) == 60 and {r["source_row_index_zero_based"] for r in plotted} == set(range(60))
    args.out.mkdir(parents=True, exist_ok=True)
    for extension in ("pdf", "svg", "png"):
        kw = {"dpi": 240} if extension == "png" else {}
        if extension == "pdf":
            kw["metadata"] = {"CreationDate": None, "ModDate": None,
                              "Creator": "Local Matplotlib plot of all archived pacing estimates and intervals"}
        if extension == "svg":
            kw["metadata"] = {"Date": None}
        fig.savefig(args.out / f"fig5.{extension}", **kw)
    plt.close(fig)
    assert sha256(SOURCE) == SOURCE_SHA256, "Source bytes changed during plotting"
    sidecar = {"source_relative_to_package": SOURCE.relative_to(PACKAGE).as_posix(),
               "source_sha256": SOURCE_SHA256, "script_sha256": sha256(Path(__file__)),
               "source_rows": 60, "unique_conditions": 12,
               "panel_rows": {panel: sum(r["source_row"]["panel"] == panel for r in plotted) for panel in PANELS},
               "intervals": "All saved ci_low/ci_high values; no fitting, estimation or resampling performed.",
               "budget_labels": "Episode = eight_per_episode; 100 planned = eight_per_100_planned. These are source budget bases, not newly estimated capacities.",
               "figure_inches": [6.5, 5.35], "png_dpi": 240,
               "axis_limits": {panel: list(limit) for panel, limit in zip(PANELS, limits)},
               "exports_sha256": {f"fig5.{ext}": sha256(args.out / f"fig5.{ext}") for ext in ("pdf", "svg", "png")},
               "plotted_rows": sorted(plotted, key=lambda r: r["source_row_index_zero_based"])}
    sidecar_path = args.out / "fig5_source.json"
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in sidecar.items() if key != "plotted_rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
