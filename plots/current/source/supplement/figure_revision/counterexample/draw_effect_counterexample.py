"""Redraw one archived TLC counterexample; never run an experiment or a model.

All plotted counts/sets come from the copied TLC stdout, checked against the
archived independent-replay JSON and CSV. No normal/corrected branch is drawn.
Run: python draw_effect_counterexample.py
Requires matplotlib. Outputs the paper PDF and trace/provenance diagnostics.
"""
import csv
import hashlib
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


HERE = Path(__file__).resolve().parent
PAPER = HERE.parents[2]
assert (PAPER / "figures").is_dir(), "Keep the extracted figure-source directory layout"
FILES = {
    "S10_COUNTEREXAMPLE.csv": "runs/v1/COUNTEREXAMPLE.csv",
    "S10_TLC_COUNTEREXAMPLE_REPLAY.json": "runs/v1/TLC_COUNTEREXAMPLE_REPLAY.json",
    "S10_UNSAFE_TLC_STDOUT.txt": "runs/v1/tlc/unsafe_2_1/stdout.txt",
    "S10_ECRCLifecycle.tla": "runs/v1/tlc/unsafe_2_1/ECRCLifecycle.tla",
    "S10_unsafe_2_1.cfg": "runs/v1/tlc/unsafe_2_1/unsafe_2_1.cfg",
}
BLACK = "#000000"
LEDGER_BACKGROUND = "#EDF5FC"
EFFECT_BACKGROUND = "#F3EEFA"
SELECTED = (4, 7, 8, 10, 13)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_trace():
    replay = json.loads((HERE / "S10_TLC_COUNTEREXAMPLE_REPLAY.json").read_text(encoding="utf-8"))
    assert replay["status"] == "PASS" and replay["transition_count"] == 12 and replay["states"] == 13
    assert sha(HERE / "S10_UNSAFE_TLC_STDOUT.txt") == replay["source_tlc_log_sha256"]
    assert sha(HERE / "S10_ECRCLifecycle.tla") == replay["model_sha256"]
    cfg = (HERE / "S10_unsafe_2_1.cfg").read_text(encoding="utf-8")
    assert re.search(r"N\s*=\s*2\b", cfg) and re.search(r"Capacity\s*=\s*1\b", cfg)
    assert "AllowUnsafeRelease = TRUE" in cfg
    raw = (HERE / "S10_UNSAFE_TLC_STDOUT.txt").read_text(encoding="utf-8")
    blocks = re.findall(r"State (\d+): <([^\n]+)>\n(.*?)(?=\nState \d+:|\nThe coverage statistics)", raw, re.S)
    assert len(blocks) == 13
    rows = list(csv.DictReader((HERE / "S10_COUNTEREXAMPLE.csv").open(encoding="utf-8", newline="")))
    trace = []
    for (number, label, body), archived, row in zip(blocks, replay["trace"], rows):
        state = {}
        for key, value in re.findall(r"^/\\ (\w+) = (.+)$", body, re.M):
            if value.startswith("{"):
                state[key] = sorted(int(x.strip()) for x in value[1:-1].split(",") if x.strip())
            elif value in ("TRUE", "FALSE"):
                state[key] = value == "TRUE"
            else:
                state[key] = int(value)
        number = int(number)
        assert number == archived["tlc_state"] == int(row["state"])
        assert label == archived["label"] and state == archived["state"]
        s, c, x = state["heldCount"], state["committedCount"], len(state["effects"])
        assert (s, c, x) == tuple(int(row[k]) for k in ("held_count", "committed_count", "effect_count"))
        assert state["held"] == json.loads(row["held"])
        assert state["effects"] == json.loads(row["effects"])
        assert state["acknowledgements"] == json.loads(row["pending_acks"])
        action = "Init" if number == 1 else label.split()[0]
        assert action == row["action"]
        trace.append({"tlc_state": number, "transition_index": number - 1,
                      "action": action, "operation": int(row["operation"]) if row["operation"] else None,
                      "S": s, "C": c, "X": x, "K": 1, "held": state["held"],
                      "committed": state["committed"], "effects": state["effects"],
                      "acknowledgements": state["acknowledgements"], "receipts": state["receipts"],
                      "ledger_bound_holds": s + c <= 1, "count_backing_holds": x <= s + c,
                      "identity_effect_backing_holds": set(state["effects"]) <= set(state["held"]) | set(state["committed"]),
                      "effect_limit_holds": x <= 1})
    assert len(rows) == len(trace) == 13
    assert all(t["ledger_bound_holds"] and t["C"] == 0 and not t["receipts"] for t in trace)
    assert next(t["tlc_state"] for t in trace if not t["count_backing_holds"]) == 8
    assert next(t["tlc_state"] for t in trace if not t["effect_limit_holds"]) == 13
    assert next(t["tlc_state"] for t in trace if not t["identity_effect_backing_holds"]) == 8
    assert all(not t["identity_effect_backing_holds"] for t in trace[7:])
    assert all(t["action"] != "LoseAcknowledgement" for t in trace)
    assert len(replay["edges"]) == 12
    assert all(t["independent_guard_and_successor_match"] for t in replay["edges"])
    return trace


def draw(trace):
    plt.rcParams.update({"font.family": "Arial", "font.size": 10,
                         "pdf.fonttype": 42, "ps.fonttype": 42,
                         "svg.fonttype": "none", "text.color": BLACK,
                         "savefig.facecolor": "white"})
    width, height = 16.51, 6.7
    fig = plt.figure(figsize=(width / 2.54, height / 2.54), facecolor="white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set(xlim=(0, width), ylim=(0, height)); ax.axis("off")
    texts = []
    def text(x, y, value, size=10, weight="normal", ha="center"):
        t = ax.text(x, y, value, fontsize=size, color=BLACK, weight=weight,
                    ha=ha, va="center", linespacing=1.15)
        texts.append(t)
        return t
    margin, data_left, data_right = .30, 3.25, 16.21
    # Background-only grouping: client ledger in blue; service effects in purple.
    # Original foreground labels, positions, rules and data remain unchanged.
    for low, high, fill in ((4.43, 5.06, LEDGER_BACKGROUND),
                            (3.87, 4.43, EFFECT_BACKGROUND),
                            (3.27, 3.87, LEDGER_BACKGROUND),
                            (2.67, 3.27, EFFECT_BACKGROUND)):
        ax.add_patch(Rectangle((margin, low), data_right-margin, high-low,
                               facecolor=fill, edgecolor="none", linewidth=0,
                               zorder=-1))
    col_width = (data_right - data_left) / len(SELECTED)
    centers = [data_left + col_width * (i + .5) for i in range(len(SELECTED))]
    text(margin, 6.28, "TLC state", 11, "bold", "left")
    text(margin, 5.66, "Event", 10.5, "bold", "left")
    titles = ["A armed", "A's effect\npersists", "Release A's unit\n(unsafe)",
              "Reserve unit\nfor B", "B's effect\npersists"]
    for i, state_id in enumerate(SELECTED):
        text(centers[i], 6.28, str(state_id), 11, "bold")
        text(centers[i], 5.66, titles[i], 10)
        if i:
            ax.add_patch(FancyArrowPatch((centers[i-1] + .38, 6.28),
                                        (centers[i] - .38, 6.28), arrowstyle="-|>",
                                        mutation_scale=9, linewidth=.8, color=BLACK))
    ax.plot([margin, data_right], [5.06, 5.06], color=BLACK, lw=.8)
    labels = [("Held units, S", 4.69), ("Effect count, X", 4.17),
              ("Held IDs", 3.54), ("Effect IDs", 3.00)]
    for label, y in labels:
        text(margin, y, label, 10, ha="left")
    ax.plot([margin, data_right], [3.87, 3.87], color=BLACK, lw=.5)
    ax.plot([margin, data_right], [2.67, 2.67], color=BLACK, lw=.8)
    def aliases(values):
        return "{" + ", ".join({1: "A", 2: "B"}[v] for v in values) + "}" if values else "{}"
    for i, state_id in enumerate(SELECTED):
        row = trace[state_id-1]
        text(centers[i], 4.69, str(row["S"]), 10.5,
             "bold" if state_id == 8 else "normal")
        text(centers[i], 4.17, str(row["X"]), 10.5,
             "bold" if state_id in (8, 13) else "normal")
        text(centers[i], 3.54, aliases(row["held"]))
        text(centers[i], 3.00, aliases(row["effects"]))
    for i, y in ((2, 4.48), (2, 3.96), (4, 3.96)):
        ax.plot([centers[i]-.35, centers[i]+.35], [y, y], color=BLACK, lw=1.5)
    text(centers[0], 2.15, "No effect yet")
    text(centers[1], 2.15, "ACK pending")
    text(centers[2], 2.24, "Backing fails", 10.5, "bold")
    text(centers[2], 1.78, "X > S + C", 10)
    text(centers[3], 2.24, "Counts match;", 10)
    text(centers[3], 1.78, "A unbacked", 10)
    text(centers[4], 2.24, "Limit exceeded", 10.5, "bold")
    text(centers[4], 1.78, "X > K", 10)
    ax.plot([margin, data_right], [1.20, 1.20], color=BLACK, lw=.5)
    text(margin, .70, "Committed units, C = 0; no receipts.  K = 1.", 10, ha="left")
    text(data_right, .70, "A = operation 1; B = operation 2", 10, ha="right")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    outside = [t.get_text() for t in texts if not (
        canvas.contains(t.get_window_extent(renderer).x0, t.get_window_extent(renderer).y0)
        and canvas.contains(t.get_window_extent(renderer).x1, t.get_window_extent(renderer).y1))]
    assert not outside, "Text falls outside the figure: " + repr(outside)
    output = PAPER / "figures/effect_counterexample.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    svg = output.with_suffix(".svg")
    fig.savefig(output, metadata={"Title": "Archived S10 unsafe-release model counterexample",
        "Subject": "Discrete selected TLC states; not elapsed time or a Python implementation failure"})
    fig.savefig(svg)
    fig.savefig(HERE / "effect_counterexample_preview.png", dpi=180)
    plt.close(fig)
    return output, {"size_cm": [width, height], "minimum_source_font_pt": 10,
                    "font_family": "Arial", "all_foreground_color": "#000000",
                    "background_row_fills": {
                        "Held units, S": LEDGER_BACKGROUND,
                        "Held IDs": LEDGER_BACKGROUND,
                        "Effect count, X": EFFECT_BACKGROUND,
                        "Effect IDs": EFFECT_BACKGROUND},
                    "background_meaning": {"blue": "Client ledger", "purple": "Service effects"},
                    "layout": "Aligned discrete state columns; no time axis or colored cards",
                    "intended_print_width_cm": 16.51,
                    "minimum_font_at_intended_width_pt": 10,
                    "selected_tlc_states": list(SELECTED),
                    "selected_state_transition_counts": [3, 1, 2, 3],
                    "omitted_initial_transition_indices": [1, 2, 3],
                    "svg_path_relative_to_paper": str(svg.relative_to(PAPER)).replace("\\", "/"),
                    "svg_sha256": sha(svg),
                    "visual_scope": "Only the archived unsafe-release trace; discrete column spacing is not elapsed time"}


def main():
    trace = read_trace()
    output, drawing = draw(trace)
    save_json("effect_counterexample_trace.json", {"trace": trace, "plotted_states": list(SELECTED)})
    sources = []
    for name, original in FILES.items():
        original_path = PAPER.parent / "iasc_overleaf/supplement/S10_model_check" / original
        expected = sha(HERE / name)
        if original_path.exists():
            assert sha(original_path) == expected, "Source copy differs from preserved original"
        sources.append({"copy": name, "sha256": expected,
                        "original_workspace_path": "output/iasc_overleaf/supplement/S10_model_check/" + original})
    save_json("EFFECT_COUNTEREXAMPLE_PROVENANCE.json", {
        "kind": "visual_reanalysis_of_archived_model_counterexample", "new_experiments": 0,
        "new_api_calls": 0, "new_model_check_runs": 0, "original_sources_modified": False,
        "source_files": sources, "drawing": drawing, "source_script_sha256": sha(Path(__file__)),
        "pdf_path_relative_to_paper": str(output.relative_to(PAPER)).replace("\\", "/"),
        "pdf_sha256": sha(output), "raw_stdout_matches_archived_replay_and_csv": True,
        "full_trace_states": 13, "full_trace_transitions": 12,
        "first_X_exceeds_S_plus_C_state": 8, "first_X_exceeds_K_state": 13,
        "first_identity_effect_backing_failure_state": 8,
        "ledger_bound_holds_at_all_13_states": True, "C_zero_and_receipts_empty_at_all_13_states": True,
        "acknowledgement_loss_steps": 0,
        "not_claimed": ["Python/SQLite failure", "new application trial", "normal branch observation",
                        "ACK loss in this trace", "first backing failure only at the last state"]})
    print(json.dumps({"output": str(output), "trace_states": 13, "transitions": 12,
                      "first_count_backing_failure": 8, "first_effect_limit_failure": 13,
                      "minimum_font_pt": drawing["minimum_source_font_pt"]}))


if __name__ == "__main__":
    main()
