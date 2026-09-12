"""Independent exact-state BFS for the frozen ECRCLifecycle finite model.

    python exact_check.py --run-id v1
    python exact_check.py --run-id v1 --compare-only

No TLA/helper/client imports or model generation. Packed integers retain every
state bit; Python set membership uses exact integer equality, not fingerprint
equality. Default execution requires FREEZE.json and runs all three fixed cases.
No state/depth limit exists. Time/memory interruption means INCOMPLETE.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
REVIEWED_MODEL_SHA256 = "f6080e07197008430a37b3248bfd29eaf7fc3f97088d36e693bc17b2bef32e2a"
CASES = (
    {"id": "normal_2_1", "n": 2, "capacity": 1, "unsafe": False, "timeout_seconds": 600},
    {"id": "normal_3_2", "n": 3, "capacity": 2, "unsafe": False, "timeout_seconds": 600},
    {"id": "unsafe_2_1", "n": 2, "capacity": 1, "unsafe": True, "timeout_seconds": 120},
)
SET_NAMES = ("received", "issued", "denied", "cancelled", "held", "committed",
             "armed", "expired", "requests", "acknowledgements", "effects", "receipts")
INVARIANTS = ("TypeOK", "Accounting", "BudgetBound", "Lifecycle", "GrantBacking",
              "EffectBacking", "EffectCountBound", "ReceiptSoundness", "NetworkCausality")
ACTIONS = ("ReceiveRaw", "IssueAction", "IssueNoAction", "Arm", "ExpirePermit",
           "CancelUnarmed", "Send", "LoseRequest", "CommitEffect", "DeduplicatedReply",
           "LoseAcknowledgement", "Reconcile", "RepeatedCompletion", "UnsafeReleaseUnknown",
           "CrashClient", "RecoverClient", "CrashSink", "RecoverSink")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1 << 20), b""):
            h.update(data)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")


class FiniteModel:
    """Independent direct interpretation; every TLA variable has its own bits.

    Twelve sets use N bits each, both counters use N.bit_length() bits each,
    and both availability flags use one bit. Explicit counters are retained so
    Accounting can actually be checked rather than assumed by reconstruction.
    """
    def __init__(self, n, capacity, unsafe):
        self.n, self.capacity, self.unsafe = n, capacity, unsafe
        self.set_mask = (1 << n)-1
        self.shifts = tuple(i*n for i in range(12))
        self.counter_bits = n.bit_length()
        self.counter_mask = (1 << self.counter_bits)-1
        self.hc_shift = 12*n
        self.cc_shift = self.hc_shift+self.counter_bits
        self.client_shift = self.cc_shift+self.counter_bits
        self.sink_shift = self.client_shift+1
        self.total_bits = self.sink_shift+1
        if self.total_bits > 64:
            raise ValueError("This exact packed encoding is only configured for the frozen small cases")
        self.hc_unit, self.cc_unit = 1 << self.hc_shift, 1 << self.cc_shift
        self.client_bit, self.sink_bit = 1 << self.client_shift, 1 << self.sink_shift
        self.operation_bits = tuple(tuple(1 << (shift+i) for shift in self.shifts) for i in range(n))
        self.initial = self.client_bit | self.sink_bit

    def decode(self, state):
        return tuple((state >> shift) & self.set_mask for shift in self.shifts) + (
            (state >> self.hc_shift) & self.counter_mask,
            (state >> self.cc_shift) & self.counter_mask,
            bool(state & self.client_bit), bool(state & self.sink_bit))

    def describe(self, state):
        d = self.decode(state)
        answer = {name: [i+1 for i in range(self.n) if d[k] & (1 << i)] for k, name in enumerate(SET_NAMES)}
        answer.update(heldCount=d[12], committedCount=d[13], clientUp=d[14], sinkUp=d[15],
                      local_count=d[12]+d[13], distinct_effect_count=d[10].bit_count(),
                      exact_packed_state=state)
        return answer

    def violations(self, state, d):
        """All nine TLA predicates, checked independently of successor guards."""
        r, i, denied, cancelled, held, committed, armed, expired, req, ack, effects, receipts, hc, cc, client_up, sink_up = d
        failures = 0
        if state < 0 or state >> self.total_bits or hc > self.n or cc > self.n:
            failures |= 1 << 0
        if hc != held.bit_count() or cc != committed.bit_count() or held & committed:
            failures |= 1 << 1
        if hc+cc > self.capacity:
            failures |= 1 << 2
        if ((i | denied) & ~r or i & denied or
                (held | committed | armed | expired) & ~i or
                cancelled & ~(i & expired) or cancelled & (armed | held | committed)):
            failures |= 1 << 3
        if armed & ~(held | committed):
            failures |= 1 << 4
        if effects & ~(held | committed):
            failures |= 1 << 5
        if effects.bit_count() > self.capacity:
            failures |= 1 << 6
        if receipts & ~(effects & armed & committed):
            failures |= 1 << 7
        if (req | ack | effects) & ~armed or ack & ~effects:
            failures |= 1 << 8
        return failures

    def successors(self, state, d=None, unsafe_override=None):
        """Enumerate every enabled action instance, including duplicate targets.

        Operations are labeled 1..N. Action code = family*4 + zero-based op;
        availability actions use the otherwise unused low-bit value 3.
        """
        if d is None:
            d = self.decode(state)
        r, issued, denied, cancelled, held, committed, armed, expired, req, ack, effects, receipts, hc, cc, cu, su = d
        unsafe = self.unsafe if unsafe_override is None else unsafe_override
        for op, bits in enumerate(self.operation_bits):
            bit = 1 << op
            rb, ib, db, cb, hb, sb, ab, xb, qb, kb, eb, tb = bits
            if cu and not r & bit:
                yield op, state | rb
            if cu and r & bit and not (issued | denied) & bit:
                if hc+cc < self.capacity:
                    yield 4+op, (state | ib | hb)+self.hc_unit
                else:
                    yield 8+op, state | db
            if cu and issued & held & bit and not (armed | expired) & bit:
                yield 12+op, state | ab
            if issued & bit and not expired & bit:
                yield 16+op, state | xb
            if cu and issued & expired & held & bit and not armed & bit:
                yield 20+op, ((state | cb) & ~hb)-self.hc_unit
            if cu and armed & bit and not (receipts | req) & bit:
                yield 24+op, state | qb
            if req & bit:
                yield 28+op, state & ~qb
            if su and req & bit and not effects & bit:
                yield 32+op, (state | eb | kb) & ~qb
            if su and req & effects & bit:
                yield 36+op, (state | kb) & ~qb
            if ack & bit:
                yield 40+op, state & ~kb
            if cu and ack & armed & held & bit and not receipts & bit:
                yield 44+op, ((state | sb | tb) & ~hb & ~kb)-self.hc_unit+self.cc_unit
            if cu and ack & receipts & bit:
                yield 48+op, state & ~kb
            if unsafe and cu and expired & armed & held & bit and not receipts & bit:
                yield 52+op, (state & ~hb)-self.hc_unit
        if cu:
            yield 59, state & ~self.client_bit
        else:
            yield 63, state | self.client_bit
        if su:
            yield 67, state & ~self.sink_bit
        else:
            yield 71, state | self.sink_bit

    def critical(self, d):
        r, issued, denied, cancelled, held, committed, armed, expired, req, ack, effects, receipts, hc, cc, cu, su = d
        tests = (
            ("armed_without_effect", armed & ~effects),
            ("effect_without_receipt", effects & ~receipts),
            ("effect_without_receipt_or_pending_ack", effects & ~receipts & ~ack),
            ("expired_unarmed_held", expired & issued & held & ~armed),
            ("expired_armed_unknown_held", expired & armed & held & ~receipts),
            ("cancelled_unarmed", cancelled & ~armed),
            ("receipt_present", receipts), ("request_pending", req), ("ack_pending", ack),
            ("client_down_only", not cu and su), ("sink_down_only", cu and not su),
            ("both_down", not cu and not su), ("capacity_denied", denied),
            ("full_budget_with_armed_unknown", hc+cc == self.capacity and armed & held & ~receipts),
            ("unbacked_armed", armed & ~(held | committed)),
            ("unbacked_effect", effects & ~(held | committed)),
            ("effect_bound_violation_within_local_budget", effects.bit_count() > self.capacity and hc+cc <= self.capacity),
        )
        return (name for name, condition in tests if condition)


def action_description(code):
    family, op = divmod(code, 4)
    return {"name": ACTIONS[family], "operation": op+1 if family < 14 else None}


def reconstruct(index, states, parents, actions, model):
    chain = []
    cursor = index
    while cursor:
        chain.append(cursor)
        cursor = parents[cursor]
    chain.append(0)
    chain.reverse()
    return [{"step": k, "action": {"name": "Init", "operation": None} if k == 0 else action_description(actions[j]),
             "state": model.describe(states[j]),
             "violated_invariants": [name for n, name in enumerate(INVARIANTS) if model.violations(states[j], model.decode(states[j])) & (1 << n)]}
            for k, j in enumerate(chain)]


def first_positive_rejection(trace, model):
    state = model.initial
    for row in trace[1:]:
        action = row["action"]
        family = ACTIONS.index(action["name"])
        code = family*4 + (action["operation"]-1 if action["operation"] is not None else 3)
        targets = [dst for candidate, dst in model.successors(state, unsafe_override=False) if candidate == code]
        expected_target = row["state"]["exact_packed_state"]
        if expected_target not in targets:
            return {"step": row["step"], "action": action, "positive_prefix_state": model.describe(state),
                    "positive_enabled_action_targets": [model.describe(x) for x in targets],
                    "reason": "AllowUnsafeRelease is FALSE" if action["name"] == "UnsafeReleaseUnknown" else "Action or successor differs; investigate correspondence"}
        state = expected_target
    return None


def check_case(case, directory):
    model = FiniteModel(case["n"], case["capacity"], case["unsafe"])
    started = time.perf_counter()
    deadline = started+case["timeout_seconds"]
    # Arrays preserve full states/parents compactly; the set is exact equality.
    states, parents, actions = array("Q", [model.initial]), array("Q", [0]), array("B", [255])
    seen = {model.initial}
    cursor, checked, expanded, generated_edges = 0, 0, 0, 0
    depth, level_end, max_discovered_depth = 0, 1, 0
    depth_histogram = Counter({0: 1})
    edges_by_action, sources_by_action = [0]*len(ACTIONS), [0]*len(ACTIONS)
    invariant_failures = [0]*len(INVARIANTS)
    first_invariant_failure, first_action, first_critical = {}, {}, {}
    counterexample_index, status, reason = None, "INCOMPLETE", None
    next_progress = started+10
    try:
        while cursor < len(states):
            if time.perf_counter() >= deadline:
                reason = "Declared wall-time budget reached before frontier exhaustion"
                break
            if cursor == level_end:
                depth += 1
                level_end = len(states)
            state = states[cursor]
            d = model.decode(state)
            failures = model.violations(state, d)
            checked += 1
            if failures:
                for bit, name in enumerate(INVARIANTS):
                    if failures & (1 << bit):
                        invariant_failures[bit] += 1
                        first_invariant_failure.setdefault(name, cursor)
            for name in model.critical(d):
                first_critical.setdefault(name, cursor)
            target = d[10].bit_count() > case["capacity"] and d[12]+d[13] <= case["capacity"]
            if not case["unsafe"] and failures:
                counterexample_index, status, reason = cursor, "INVARIANT_VIOLATION", "Positive instance violates a configured invariant"
                break
            if case["unsafe"] and failures & 0b111:
                counterexample_index, status, reason = cursor, "UNEXPECTED_INVARIANT_VIOLATION", "Negative control violates TypeOK, Accounting or BudgetBound"
                break
            if case["unsafe"] and target:
                counterexample_index, status, reason = cursor, "EXPECTED_COUNTEREXAMPLE", "Distinct durable effects exceed Capacity while the local count remains within Capacity"
                break
            source_action_mask = 0
            for code, successor in model.successors(state, d):
                family = code//4
                generated_edges += 1
                edges_by_action[family] += 1
                source_action_mask |= 1 << family
                first_action.setdefault(family, (cursor, code, successor))
                if successor not in seen:
                    seen.add(successor)
                    states.append(successor)
                    parents.append(cursor)
                    actions.append(code)
                    depth_histogram[depth+1] += 1
                    max_discovered_depth = max(max_discovered_depth, depth+1)
            for family in range(len(ACTIONS)):
                if source_action_mask & (1 << family):
                    sources_by_action[family] += 1
            expanded += 1
            cursor += 1
            now = time.perf_counter()
            if now >= next_progress:
                print(json.dumps({"case": case["id"], "status": "RUNNING", "distinct_discovered": len(seen), "states_checked": checked,
                                  "frontier": len(states)-cursor, "elapsed_seconds": round(now-started, 3)}), flush=True)
                next_progress = now+10
        else:
            status = "COMPLETE_NO_COUNTEREXAMPLE" if case["unsafe"] else "COMPLETE_PASS"
            reason = "All reachable exact states checked and frontier exhausted"
    except MemoryError:
        status, reason = "INCOMPLETE", "MemoryError; no smaller instance or implicit state cap substituted"
    except Exception as exc:
        status, reason = "ERROR", type(exc).__name__+": "+str(exc)
        write(directory/"ERROR.json", {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
    search_elapsed = time.perf_counter()-started
    complete = cursor == len(states) and checked == expanded == len(states) and len(seen) == len(states)
    if status == "COMPLETE_PASS" and not complete:
        status, reason = "ERROR", "Inconsistent complete-search counters"
    witness_bundle = {"critical_states": {}, "transition_families": {}, "first_invariant_failures": {}}
    if len(states) == len(parents) == len(actions):
        for name, index in first_critical.items():
            witness_bundle["critical_states"][name] = reconstruct(index, states, parents, actions, model)
        for family, (index, code, successor) in first_action.items():
            trace = reconstruct(index, states, parents, actions, model)
            trace.append({"step": len(trace), "action": action_description(code), "state": model.describe(successor),
                          "violated_invariants": [name for bit, name in enumerate(INVARIANTS) if model.violations(successor, model.decode(successor)) & (1 << bit)]})
            witness_bundle["transition_families"][ACTIONS[family]] = trace
        for name, index in first_invariant_failure.items():
            witness_bundle["first_invariant_failures"][name] = reconstruct(index, states, parents, actions, model)
        if counterexample_index is not None:
            trace = reconstruct(counterexample_index, states, parents, actions, model)
            rejection = first_positive_rejection(trace, model) if case["unsafe"] else None
            write(directory/"COUNTEREXAMPLE.json", {"case": case, "trace": trace, "transition_count": len(trace)-1,
                  "shortest_to_target_under_this_frozen_labeled_transition_relation": status == "EXPECTED_COUNTEREXAMPLE",
                  "positive_model_first_rejected_step": rejection,
                  "final_effect_count": trace[-1]["state"]["distinct_effect_count"], "final_local_count": trace[-1]["state"]["local_count"],
                  "limits": "Witness of this finite model; not an implementation trace or a globally minimal trace across other abstractions."})
            if status == "EXPECTED_COUNTEREXAMPLE" and (rejection is None or rejection["action"]["name"] != "UnsafeReleaseUnknown"):
                status, reason = "ERROR", "Negative witness does not first diverge at the single disabled unsafe rule"
    write(directory/"WITNESSES.json", witness_bundle)
    configured = ["TypeOK", "Accounting", "BudgetBound", "EffectCountBound"] if case["unsafe"] else list(INVARIANTS)
    result = {
        "case": case, "status": status, "reason": reason, "search_elapsed_seconds": search_elapsed,
        "time_limit_seconds": case["timeout_seconds"], "complete_reachable_graph": complete,
        "exhaustive_positive": complete and not case["unsafe"] and status == "COMPLETE_PASS",
        "negative_stops_at_first_target": case["unsafe"],
        "unique_labeled_states_discovered": len(seen), "states_checked": checked, "states_expanded": expanded,
        "frontier_states_not_expanded": len(states)-expanded,
        "enabled_action_instance_edges_generated": generated_edges,
        "generated_states_including_initial": generated_edges+1,
        "duplicate_successors": generated_edges-(len(seen)-1),
        "maximum_discovered_shortest_path_depth_edges": max_discovered_depth,
        "discovered_states_by_shortest_path_depth_edges": dict(sorted(depth_histogram.items())),
        "configured_invariants": configured,
        "all_nine_invariants_checked_per_processed_state": True,
        "invariant_state_check_count": checked*len(INVARIANTS),
        "invariant_violating_checked_states": dict(zip(INVARIANTS, invariant_failures)),
        "action_coverage": {name: {"enabled_source_states_expanded": sources_by_action[i], "generated_edges": edges_by_action[i]} for i, name in enumerate(ACTIONS)},
        "critical_states_witnessed": sorted(first_critical),
        "state_encoding": {"set_fields": list(SET_NAMES), "bits_per_set": model.n, "explicit_counter_bits_each": model.counter_bits,
                           "independent_availability_flags": ["clientUp", "sinkUp"], "total_bits": model.total_bits,
                           "equality": "Full packed Python integer equality in set; hash collisions are resolved by equality.",
                           "domain_note": "Set/Boolean typing is structural in the injective encoding; explicit count ranges are still checked."},
        "constraints": {"state_limit": None, "depth_limit": None, "symmetry_reduction": False, "partial_order_reduction": False},
        "counting_conventions": "One initial state; each enabled Next action instance counts as an edge, including duplicate targets. Implicit Spec stutter steps are not enumerated and add no reachable state. Depth counts edges from Init=0. Witnesses are shortest to the first reached state/edge under this BFS order.",
        "source_sha256": {"ECRCLifecycle.tla": sha(HERE/"ECRCLifecycle.tla"), case["id"]+".cfg": sha(HERE/(case["id"]+".cfg")), "exact_check.py": sha(Path(__file__))},
        "python_version": sys.version, "completed_utc": datetime.now(timezone.utc).isoformat(),
        "limitations": ["Finite labeled instances and Boolean message-presence abstraction only.",
                        "Independent implementation can share modeling misunderstandings with the TLA model.",
                        "No Python/SQLite refinement proof, unbounded protocol proof, liveness theorem or implementation-superiority claim.",
                        "State/transition/check counts are tool diagnostics, not independent study samples."]
    }
    write(directory/"RESULT.json", result)
    print(json.dumps({k: result[k] for k in ("case", "status", "unique_labeled_states_discovered", "states_checked", "search_elapsed_seconds")}), flush=True)
    return result


def compare_tlc(run_id):
    rows = []
    for case in CASES:
        own = HERE/"runs"/run_id/"exact"/case["id"]/"RESULT.json"
        log_path = HERE/"runs"/run_id/"tlc"/case["id"]/"stdout.txt"
        tlc_result = log_path.with_name("RESULT.json")
        row = {"case": case["id"], "status": "PENDING", "exact_result_exists": own.is_file(), "tlc_final_result_exists": tlc_result.is_file()}
        if own.is_file() and tlc_result.is_file() and log_path.is_file():
            exact, tlc = read(own), read(tlc_result)
            log = log_path.read_text(encoding="utf-8", errors="replace")
            matches = re.findall(r"([\d,]+) states generated, ([\d,]+) distinct states found, ([\d,]+) states left on queue", log)
            statistics = tuple(int(x.replace(",", "")) for x in matches[-1]) if matches else None
            row.update(exact_status=exact["status"], tlc_status=tlc["status"], tlc_log_sha256=sha(log_path), exact_result_sha256=sha(own))
            if case["unsafe"]:
                found = exact["status"] == "EXPECTED_COUNTEREXAMPLE" and "Invariant EffectCountBound is violated." in log and tlc["status"] == "EXPECTED_COUNTEREXAMPLE"
                row.update(status="BOTH_FOUND_COUNTEREXAMPLE" if found else "NOT_CONFIRMED", negative_state_counts_not_compared="Both searches stop early and can use different BFS action ordering; neither count is exhaustive.")
            elif statistics is not None:
                generated, distinct, pending = statistics
                both_complete = exact["status"] == "COMPLETE_PASS" and exact["complete_reachable_graph"] and pending == 0 and tlc["status"] == "COMPLETE_PASS" and "Model checking completed. No error has been found." in log
                match = distinct == exact["unique_labeled_states_discovered"]
                row.update(status="COMPLETE_STATE_COUNT_MATCH" if both_complete and match else ("STATE_COUNT_MISMATCH" if both_complete else "INCOMPLETE_OR_FAILURE"),
                           tlc_distinct_states=distinct, exact_distinct_states=exact["unique_labeled_states_discovered"], distinct_state_count_equal=match,
                           tlc_generated_states=generated, exact_generated_states_including_initial=exact["generated_states_including_initial"],
                           generated_count_equal=generated == exact["generated_states_including_initial"], tlc_queue_remaining=pending)
            else:
                row.update(status="MISSING_TLC_COMPLETION_STATISTICS")
        rows.append(row)
    complete = all(r["status"] in ("COMPLETE_STATE_COUNT_MATCH", "BOTH_FOUND_COUNTEREXAMPLE") for r in rows)
    report = {"status": "PASS" if complete else ("PENDING" if any(r["status"] == "PENDING" for r in rows) else "NOT_CONFIRMED"), "cases": rows,
              "scope": "Exact labeled-state counts cross-check completed positive cases. Agreement does not eliminate shared modeling errors and is not code refinement."}
    write(HERE/"runs"/run_id/"exact"/"TLC_COMPARISON.json", report)
    return report


def validate_freeze():
    freeze = read(HERE/"FREEZE.json")
    if sha(HERE/"ECRCLifecycle.tla") != REVIEWED_MODEL_SHA256:
        raise ValueError("TLA model differs from the independently reviewed semantics; version and review before running")
    if freeze["cases"] != list(CASES):
        raise ValueError("Frozen cases differ from the exact two positive and one negative instances")
    for name, expected in freeze["source_hashes"].items():
        if sha(HERE/name) != expected:
            raise ValueError("Freeze mismatch: "+name)
    if "exact_check.py" not in freeze["source_hashes"]:
        raise ValueError("Independent enumerator was not included in the source freeze")
    for case in CASES:
        cfg = (HERE/(case["id"]+".cfg")).read_text(encoding="utf-8")
        observed = {key: re.search(r"\b"+key+r"\s*=\s*(\w+)", cfg).group(1) for key in ("N", "Capacity", "AllowUnsafeRelease")}
        expected = {"N": str(case["n"]), "Capacity": str(case["capacity"]), "AllowUnsafeRelease": str(case["unsafe"]).upper()}
        if observed != expected:
            raise ValueError("Configuration constants differ: "+case["id"])
        invariant_names = cfg.split("INVARIANTS", 1)[1].split()
        required = ["TypeOK", "Accounting", "BudgetBound", "EffectCountBound"] if case["unsafe"] else list(INVARIANTS)
        if invariant_names != required:
            raise ValueError("Configured invariants differ: "+case["id"])
        if re.search(r"\b(CONSTRAINT|CONSTRAINTS|SYMMETRY)\b", cfg):
            raise ValueError("Unexpected state constraint/reduction in configuration")
    return freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compare-only", action="store_true", help="Read completed exact/TLC logs and write only TLC_COMPARISON.json; no exploration.")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.run_id):
        parser.error("Simple alphanumeric/underscore run ID required")
    if args.compare_only:
        result = compare_tlc(args.run_id)
        print(json.dumps(result), flush=True)
        return 0 if result["status"] == "PASS" else 1
    validate_freeze()
    directory = HERE/"runs"/args.run_id/"exact"
    directory.mkdir(parents=True, exist_ok=False)
    write(directory/"START.json", {"started_utc": datetime.now(timezone.utc).isoformat(), "freeze_sha256": sha(HERE/"FREEZE.json"), "command": sys.argv})
    results = []
    for case in CASES:
        target = directory/case["id"]
        target.mkdir()
        results.append(check_case(case, target))
    validate_freeze()
    comparison = compare_tlc(args.run_id)
    accepted = all(r["status"] == ("EXPECTED_COUNTEREXAMPLE" if r["case"]["unsafe"] else "COMPLETE_PASS") for r in results)
    write(directory/"SUMMARY.json", {"results": results, "all_declared_searches_accepted": accepted,
          "tlc_comparison_status": comparison["status"], "study_samples": None,
          "interpretation": "Bounded finite-model safety/explanatory evidence only; check counts are not samples; no implementation refinement or superiority conclusion."})
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
