"""Render current figures offline and compare saved numerical/pixel baselines."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image

import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("figures"))
    parser.add_argument("--require-baseline", action="store_true",
                        help="Fail if primary/supplemental file or pixel digests differ from the saved environment")
    args = parser.parse_args()
    report, _ = verify.verify()
    baseline = json.loads((verify.HERE / "plot_baselines.json").read_text())
    output = args.output_dir.resolve()
    verify.require(output != verify.HERE, "Choose a separate generated-output directory")
    output.mkdir(parents=True, exist_ok=True)
    groups = {"primary": "plot_from_csv.py", "supplemental": "supplemental/plot_supplemental_from_csv.py",
              "counterexample": "counterexample/draw_effect_counterexample.py"}
    for group, script in groups.items():
        subprocess.run([sys.executable, str(verify.HERE / script), "--output-dir", str(output / group)],
                       cwd=output.parent, check=True, capture_output=True, text=True)
    checks = {}
    for group, info in baseline.items():
        for name, expected in info["figures"].items():
            png = output / group / (name + ".png")
            with Image.open(png) as image:
                actual = {"size_pixels": list(image.size),
                          "rgba_pixels_sha256": hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()}
            actual.update({extension + "_sha256": verify.sha(output / group / (name + "." + extension))
                           for extension in ("pdf", "png")})
            checks[name] = {"actual": actual, "matches_baseline": {key: actual[key] == value for key, value in expected.items()}}
    counter = json.loads((output / "counterexample/counterexample_manifest.json").read_text())
    result = {"status": "rendered_and_checked", "API_calls": 0,
              "numeric_reanalysis_status": report["status"],
              "counterexample_saved_state_csv_checks_passed": counter["saved_state_csv_checks_passed"],
              "counterexample_original_stdout_verified": False,
              "counterexample_independent_guard_replay_performed": False,
              "figures": checks,
              "all_baseline_checks_match": all(all(v["matches_baseline"].values()) for v in checks.values())}
    (output / "plot_verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if args.require_baseline:
        verify.require(result["all_baseline_checks_match"], "Figure baseline differs; inspect environment and generated report")


if __name__ == "__main__":
    main()
