"""Portable, data-backed journal redraw of ECRC Figures 1 and 4.

Dependencies: Python 3, matplotlib, numpy, Pillow. Optional PyMuPDF for PDF QA.
Capture once: python build_fig1_fig4.py --capture-from PATH_TO_REPOSITORY
Rebuild from packaged snapshots: python build_fig1_fig4.py
No model fitting, simulation, or experiment is performed.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
BLUE = "#24557A"
BLACK = "#000000"
GRAY = "#666666"
WIDTH = 6.5
FONT = "Arial"
FIXED_DATE = datetime(2026, 9, 11, tzinfo=timezone.utc)
DISPLAY = {
    "Ordinary log": "Typed-record\nbaseline",
    "Claim/evidence binding off": "Claim/evidence\nbinding off",
    "Receipt/state off": "Receipt/state off",
    "Full ECRC": "Full ECRC",
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))

def setup():
    font_path = font_manager.findfont(font_manager.FontProperties(family=FONT), fallback_to_default=False)
    plt.rcParams.update({
        "font.family": FONT, "font.size": 9, "axes.labelsize": 9,
        "axes.titlesize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "legend.fontsize": 8, "axes.linewidth": 0.6,
        "lines.linewidth": 0.8, "lines.markersize": 4,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "text.color": BLACK, "axes.labelcolor": BLACK,
        "xtick.color": BLACK, "ytick.color": BLACK,
        "axes.edgecolor": BLACK, "figure.facecolor": "white",
        "savefig.facecolor": "white", "legend.frameon": False,
        "svg.fonttype": "none", "pdf.fonttype": 42,
        "ps.fonttype": 42, "svg.hashsalt": "iasc-ecrc-journal-redraw-2026-09-11",
        "mathtext.fontset": "custom", "mathtext.rm": FONT,
        "mathtext.it": f"{FONT}:italic", "mathtext.bf": f"{FONT}:bold",
    })
    return font_path

def capture(root, data):
    root = Path(root).resolve()
    data.mkdir(parents=True, exist_ok=True)
    src = root / "figures_current/Figure_4/fig4_runtime_validation_source_data.csv"
    shutil.copyfile(src, data / "fig4_source_data.csv")
    provenance = {"aggregate_source": str(src.relative_to(root)), "aggregate_sha256": sha(src), "sources": []}
    records = read_csv(src)
    for rel in sorted({row["source_file"] for row in records}):
        source = root / "experiment_reproducibility" / rel
        expected = {row["source_sha256"] for row in records if row["source_file"] == rel}
        assert expected == {sha(source)}, f"Frozen source hash mismatch: {source}"
        target = data / "upstream" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        provenance["sources"].append({"original": str(source.relative_to(root)), "snapshot": str(target.relative_to(data)), "sha256": sha(source)})
    for name in ["03_method.tex", "04_evaluation.tex"]:
        original = root / "output/iasc_overleaf/content" / name
        shutil.copyfile(original, data / name)
        provenance[name] = {"original": str(original.relative_to(root)), "sha256": sha(original)}
    (data / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf8")

def validate_sources(data):
    records = read_csv(data / "fig4_source_data.csv")
    checks = []
    for row in records:
        upstream = data / "upstream" / row["source_file"]
        assert sha(upstream) == row["source_sha256"], upstream
        kind = row["record_type"]
        def same(field, expected):
            assert abs(float(row[field]) - float(expected)) <= 0.00000051, (row["selector"], field, row[field], expected)
        if upstream.suffix == ".csv":
            selection = dict(item.split("=", 1) for item in row["selector"].split(";"))
            selected = [r for r in read_csv(upstream) if all(r[k] == v for k, v in selection.items())]
            assert selected, row
            if kind == "fault_detection":
                assert len(selected) == 1
                same("numerator", selected[0]["n_detected"])
                same("denominator", selected[0]["n_cases"])
            elif kind == "clean_control":
                assert len(selected) == 1
                n = int(selected[0]["n_clean_records"])
                same("denominator", n)
                same("numerator", n - int(selected[0]["n_clean_failures"]))
            elif kind == "capacity_integrity":
                values = [int(r["reservation_counts.committed"]) for r in selected]
                same("numerator", statistics.median(values))
                same("denominator", selected[0]["capacity"])
                same("minimum", min(values)); same("median", statistics.median(values)); same("maximum", max(values))
                same("repetitions", len(selected))
                assert all(int(r["oversubscription_count"]) == 0 for r in selected)
            elif kind == "tail_latency":
                assert len(selected) == 1
                for field in ["minimum", "median", "maximum"]:
                    same(field, selected[0][f"end_to_end_latency.p95_ms.{field}"])
                same("workers", selected[0]["workers"])
                same("repetitions", selected[0]["repetitions"])
        else:
            raw = json.loads(upstream.read_text(encoding="utf8"))
            if kind == "bridge_agreement":
                count, mismatch = row["selector"].split("+")
                same("numerator", raw[count]); same("denominator", raw[count] + raw[mismatch])
            elif kind == "capacity_integrity":
                assert raw["barrier_forced_interleaving"]
                same("numerator", raw["logical_acceptances"])
                same("denominator", raw["capacity"])
                same("workers", len(raw["attempts"]))
        if row["ratio"]:
            same("ratio", float(row["numerator"]) / float(row["denominator"]))
        checks.append({"selector": row["selector"], "source_file": row["source_file"], "hash_verified": True, "numeric_fields_verified": True})
    return records, checks

def arrow(ax, start, end):
    ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "lw": 0.6, "color": BLACK, "shrinkA": 0, "shrinkB": 0, "mutation_scale": 7})

def box(ax, x, y, w, h, text, fs=9):
    ax.add_patch(Rectangle((x, y), w, h, facecolor="white", edgecolor=BLACK, linewidth=0.6))
    ax.text(x+w/2, y+h/2, text, ha="center", va="center", fontsize=fs, linespacing=1.18)

def figure1():
    fig = plt.figure(figsize=(WIDTH, 3.5))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set(xlim=(0, WIDTH), ylim=(0, 3.5)); ax.axis("off")
    ax.text(0.06, 3.38, "(a) Development and frozen operating point", fontsize=9, fontweight="bold", va="top")
    xs, widths = [0.08, 2.31, 4.56], [1.88, 1.88, 1.86]
    labels = ["Development predictions\n(training partitions)", "Training-only selection\nof threshold τ", "Frozen policy for replay\nτ; prespecified δ, γ and caps"]
    for x, w, text in zip(xs, widths, labels): box(ax, x, 2.79, w, 0.40, text, 8.5)
    arrow(ax, (1.99, 2.99), (2.27, 2.99)); arrow(ax, (4.22, 2.99), (4.52, 2.99))
    ax.text(0.06, 2.54, "(b) Episode-level permission", fontsize=9, fontweight="bold", va="top")
    ax.text(6.40, 2.54, "Inputs: proposal, evidence, policy and ledger", fontsize=8, ha="right", va="top")
    bx = [0.08, 1.76, 3.43, 5.10]
    bw = [1.31, 1.31, 1.31, 1.32]
    bl = ["Evidence admission\nAdmitted and used sets", "Candidate routing\nOne of four routes", "Capacity reservation\nor route fallback", "Claim closure\nPermit registration"]
    for x, w, text in zip(bx, bw, bl): box(ax, x, 1.94, w, 0.40, text, 8.5)
    for i in range(3): arrow(ax, (bx[i]+bw[i]+0.03, 2.14), (bx[i+1]-0.04, 2.14))
    ax.text(0.08, 1.80, "Only alert and review reserve capacity; exhaustion applies the route-specific fallback.", fontsize=8, va="top")
    ax.text(0.08, 1.61, "Unsupported action claims release the reservation before fallback and registration.", fontsize=8, va="top")
    ax.text(0.06, 1.31, "(c) Single-use enforcement", fontsize=9, fontweight="bold", va="top")
    cl = ["Registered permit\nand any reservation", "Enforcement guard\nContent, policy and state", "Atomic consume + reconcile\nAppend hash-chained receipt"]
    for x, w, text in zip(xs, widths, cl): box(ax, x, 0.64, w, 0.46, text, 8.5)
    arrow(ax, (1.99, 0.87), (2.27, 0.87)); arrow(ax, (4.22, 0.87), (4.52, 0.87))
    ax.text(3.25, 0.50, "Invalid or reused permit: reject", ha="center", va="top", fontsize=8)
    ax.text(0.08, 0.15, "Reservation transitions: reserve, commit or release;  0 ≤ reserved + committed ≤ limit.", fontsize=8, va="bottom")
    return fig

def tidy(ax):
    for side in ["top", "right"]: ax.spines[side].set_visible(False)
    ax.tick_params(pad=2)
    return ax

def figure4(records):
    fig = plt.figure(figsize=(WIDTH, 3.5))
    fig.text(0.014, 0.955, "(a) Fault detection", fontweight="bold", fontsize=9)
    fig.text(0.505, 0.955, "(b) Capacity", fontweight="bold", fontsize=9)
    fig.text(0.79, 0.955, "(c) Tail latency", fontweight="bold", fontsize=9)
    a = fig.add_axes([0.012, 0.19, 0.465, 0.68]); a.axis("off"); a.set(xlim=(0,1), ylim=(0,1))
    a.text(0.64, 0.97, "Claim/\nevidence", ha="center", va="top", fontsize=8)
    a.text(0.88, 0.97, "Receipt/\nstate", ha="center", va="top", fontsize=8)
    a.plot([0, 1], [0.79, 0.79], color=BLACK, lw=0.6)
    for y, series in zip([0.69, 0.51, 0.33, 0.15], DISPLAY):
        a.text(0.015, y, DISPLAY[series], ha="left", va="center", fontsize=8)
        for x, metric in [(0.64, "Claim/evidence faults"), (0.88, "Receipt/state faults")]:
            row = next(r for r in records if r["record_type"] == "fault_detection" and r["series"] == series and r["metric"] == metric)
            a.text(x, y, f'{int(float(row["numerator"]))}/{int(float(row["denominator"]))}', ha="center", va="center", fontsize=9)
    a.plot([0,1], [0.04,0.04], color=BLACK, lw=0.6)
    clean = [r for r in records if r["record_type"] == "clean_control"]
    clean_pairs = {(int(float(r["numerator"])), int(float(r["denominator"]))) for r in clean}
    assert len(clean_pairs) == 1
    passed, count = next(iter(clean_pairs))
    fig.text(0.017, 0.11, f"Clean controls: {passed}/{count} passed under every validator.", fontsize=8)
    b = tidy(fig.add_axes([0.545, 0.30, 0.18, 0.57]))
    cap = [r for r in records if r["record_type"] == "capacity_integrity"]
    for i, row in enumerate(cap):
        actual, limit = float(row["numerator"]), float(row["denominator"])
        b.plot([i-0.24, i+0.24], [limit, limit], lw=1.0, color=GRAY, zorder=1)
        b.plot(i, actual, marker="o", ms=4, color=BLUE, zorder=2)
        b.text(i, actual+0.48, f"{int(actual)}/{int(limit)}", ha="center", fontsize=8)
    b.set(xlim=(-0.55, len(cap)-0.45), ylim=(0, max(float(r["denominator"]) for r in cap)+2))
    b.set_xticks(range(len(cap)), ["Race\nwitness"]+[f'ECRC\ncap {int(float(r["denominator"]))}' for r in cap[1:]])
    b.set_yticks([0, 2, 4, 6, 8, 10]); b.set_ylabel("Capacity-bearing routes", fontsize=8, labelpad=3)
    fig.text(0.51, 0.06, "Point: admitted\nLine: limit", fontsize=8, linespacing=1.2)
    c = tidy(fig.add_axes([0.813, 0.30, 0.172, 0.57]))
    lat = sorted((r for r in records if r["record_type"] == "tail_latency"), key=lambda r: float(r["workers"]))
    workers = np.array([float(r["workers"]) for r in lat])
    med = np.array([float(r["median"]) for r in lat]); low = np.array([float(r["minimum"]) for r in lat]); high = np.array([float(r["maximum"]) for r in lat])
    c.errorbar(workers, med, yerr=np.stack([med-low, high-med]), fmt="o-", color=BLUE, ecolor=GRAY, lw=0.8, ms=4, elinewidth=0.7, capsize=2, capthick=0.7)
    c.set_xscale("log", base=2); c.set_yscale("log")
    c.set_xticks(workers, [str(int(x)) for x in workers]); c.set_yticks([10,100,1000], ["10","100","1000"])
    c.set_ylim(10, 2000); c.set_xlim(0.82,19.5); c.minorticks_off()
    c.set_xlabel("Workers", fontsize=8); c.set_ylabel("p95 latency (ms, log scale)", fontsize=8, labelpad=2)
    reps = {int(float(r["repetitions"])) for r in lat}; assert len(reps)==1
    fig.text(0.787, 0.06, f"Median and range\n({next(iter(reps))} repetitions)", fontsize=8, linespacing=1.2)
    return fig

def export(fig, path):
    outputs = {}
    for ext in ["pdf", "svg", "png", "tiff"]:
        kwargs = {"dpi": 1200 if ext == "tiff" else 600}
        if ext == "pdf": kwargs["metadata"]={"CreationDate": FIXED_DATE, "ModDate": FIXED_DATE, "Creator": "Matplotlib; local frozen-data journal redraw"}
        elif ext == "svg": kwargs["metadata"]={"Date": "2026-09-11"}
        elif ext == "tiff": kwargs["pil_kwargs"]={"compression":"tiff_lzw"}
        target = path.with_suffix("."+ext)
        fig.savefig(target, **kwargs)
        outputs[ext] = {"path": target.name, "sha256": sha(target)}
    text_items = [item for item in fig.findobj(matplotlib.text.Text) if item.get_text() and item.get_visible()]
    text_sizes = [item.get_fontsize() for item in text_items]
    assert min(text_sizes) >= 8, min(text_sizes)
    assert all(matplotlib.colors.to_hex(item.get_color()) == BLACK for item in text_items)
    plt.close(fig)
    with Image.open(path.with_suffix(".png")) as raster:
        raster.convert("L").save(path.with_name(path.name+"_grayscale").with_suffix(".png"))
    qa = {"outputs":outputs, "minimum_font_pt":min(text_sizes), "width_inches":WIDTH, "all_text_black":True}
    try:
        import pymupdf
        with pymupdf.open(path.with_suffix(".pdf")) as doc:
            page=doc[0]
            fonts=[{"name":f[3],"embedded":bool(doc.extract_font(f[0])[3])} for f in page.get_fonts()]
            assert all(f["embedded"] for f in fonts)
            page.get_pixmap(matrix=pymupdf.Matrix(2,2)).save(path.with_name(path.name+"_proof").with_suffix(".png"))
            qa.update({"fonts":fonts,"raster_images_in_pdf":len(page.get_images()),"page_size_points":list(page.rect)})
    except ImportError:
        qa["pdf_font_check"]="Install PyMuPDF to run the optional PDF check."
    return qa

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--capture-from", type=Path); parser.add_argument("--data",type=Path,default=HERE/"data/fig1_fig4"); parser.add_argument("--out",type=Path,default=HERE); args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.capture_from: capture(args.capture_from,args.data)
    font_path=setup(); rows,checks=validate_sources(args.data)
    plot_rows=[dict(row, display_series=DISPLAY.get(row["series"], row["series"]).replace("\n", " ")) for row in rows if row["record_type"] != "bridge_agreement"]
    for row in plot_rows:
        if row["series"] == "Non-atomic witness": row["display_series"]="Race witness"
    plot_source=args.out/"fig4_source_data.csv"
    with plot_source.open("w",newline="",encoding="utf8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(plot_rows[0]));writer.writeheader();writer.writerows(plot_rows)
    manifest={"style":{"font":FONT,"font_path_at_build":str(font_path),"width_inches":WIDTH,"base_font_pt":9,"minimum_font_pt":8,"data_blue":BLUE,"text_color":BLACK},"data_sha256":sha(args.data/"fig4_source_data.csv"),"provenance":json.loads((args.data/"provenance.json").read_text(encoding="utf8")),"upstream_checks":checks,"display_mapping":DISPLAY,"fig1_is_schematic":True,"fig1_method_source":"data/fig1_fig4/03_method.tex","fig1_selection_source":"data/fig1_fig4/04_evaluation.tex","no_experiment_rerun":True,"script_sha256":sha(__file__)}
    manifest["plot_source_data"]={"path":plot_source.name,"sha256":sha(plot_source),"rows":len(plot_rows)}
    manifest["capacity_label_mapping"]={"Non-atomic witness":"Race witness (forced non-atomic interleaving)"}
    manifest["fig1"]=export(figure1(),args.out/"fig1")
    manifest["fig4"]=export(figure4(rows),args.out/"fig4")
    (args.out/"fig1_fig4_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf8")
    print(json.dumps({"source_rows_verified":len(checks),"fig1":manifest["fig1"],"fig4":manifest["fig4"]},indent=2))

if __name__=="__main__": main()
