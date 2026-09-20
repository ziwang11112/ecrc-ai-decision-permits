"""File/fixture plumbing only; frozen actors and policy remain external."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
PILOTS = ROOT.parent
OLD = PILOTS / "ecrc_component_ablation_dev_2026-09-15"
PREVIOUS = PILOTS / "ecrc_native_record_coverage_2026-09-15"
sys.path.insert(0, str(OLD))
import run_ablation as inherited

ARMS = ["direct_native_dispatch", "qualification_ecrc", "existing_rules_only",
        "without_claim_evidence_requirement"]
DATA = inherited.VENDOR / "data/tau2/domains/airline"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.suffix == ".gz":
        # Stable fixture bytes: gzip embeds neither wall time nor source filename.
        path.write_bytes(gzip.compress(content, compresslevel=1, mtime=0))
    else:
        path.write_bytes(content)


def within(base, relative):
    path = (Path(base) / relative).resolve()
    if not path.is_relative_to(Path(base).resolve()):
        raise ValueError("Fixture path leaves its declared root")
    return path


def apply_patch(base, patch):
    """Replace only present dictionary keys/list entries, with exact before binding."""
    if set(patch) != {"operations"} or not isinstance(patch["operations"], list):
        raise ValueError("Unexpected patch schema")
    result = deepcopy(base)
    seen = set()
    for operation in patch["operations"]:
        if set(operation) != {"path", "before", "after"} or not operation["path"]:
            raise ValueError("Unexpected replacement schema")
        keys = operation["path"]
        token = tuple(keys)
        if token in seen:
            raise ValueError("Repeated replacement path")
        seen.add(token)
        parent = result
        for key in keys[:-1]:
            parent = parent[key]
        last = keys[-1]
        # Indexing first rejects absent keys; do not accept an implicit addition.
        actual = parent[last]
        if actual != operation["before"]:
            raise ValueError("Patch before value mismatch: " + repr(keys))
        parent[last] = deepcopy(operation["after"])
    return result


def fixture_environment(before):
    """Official constructor accepts a fresh typed DB; no frozen module patching."""
    from tau2.domains.airline.data_model import FlightDB
    from tau2.domains.airline.environment import get_environment
    return get_environment(db=FlightDB.model_validate(deepcopy(before)))


def manifest():
    frozen = read(OLD / "review/prerun_01/FREEZE.json")
    sources = dict(frozen["sources"])
    for name, expected in sources.items():
        if sha(name) != expected:
            raise RuntimeError("Prior frozen source changed: " + name)
    for name, expected in frozen["vendor_sources"].items():
        if sha(inherited.VENDOR / name) != expected:
            raise RuntimeError("Pinned native source changed: " + name)
    paths = [*ROOT.glob("*.py"), ROOT / "PROTOCOL.md", ROOT / "README.md",
             ROOT / "CASE_SPECS.json", ROOT / "EXPECTED_BOUNDARIES.json",
             ROOT / "REQUESTS.json", ROOT / "FIXTURE_INDEX.json", ROOT / "BASE_DB.json.gz",
             PREVIOUS / "COHORT_SELECTION.json", PREVIOUS / "run_coverage.py",
             PREVIOUS / "review/postrun_01/audit_outputs.py",
             OLD / "review/postrun_01/audit_outputs.py"]
    workspace = ROOT.parents[1]
    review = workspace / "qa/iasc_followup_experiments_2026-09-16"
    paths += [review / "independent_audit.py", review / "independent_audit_v2.py"]
    paper = workspace / "output/iasc_comparator_revision_2026-09-16"
    paths += [paper / "main.tex", paper / "main.pdf", *sorted((paper / "content").glob("*.tex")),
              *sorted((paper / "tables").glob("*.tex")), *sorted((paper / "figures").glob("*.pdf"))]
    paths += list((ROOT / "fixtures").rglob("*.json")) + list((ROOT / "fixtures").rglob("*.json.gz"))
    for path in paths:
        sources[str(path.resolve())] = sha(path)
    return sources, frozen["vendor_sources"]
