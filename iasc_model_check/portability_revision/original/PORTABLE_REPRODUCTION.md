# Portable S10 verification and reproduction

`portable_reproduce.py` is a post-hoc public-archive wrapper. It is **not** one of the 15 files frozen before historical run `v1`. It requires Python 3.10+ and only the Python standard library. Run it from any current directory; paths to retained evidence are resolved from the wrapper's location.

The default performs no enumeration, invokes no Java process, downloads nothing and writes nothing:

```console
python /path/to/M/portable_reproduce.py
```

It verifies the pinned historical `FREEZE.json`, all 15 frozen sources, both historical `START.json` freeze bindings, the pinned final audit and its retained evidence hashes, copied model/configuration files, exact-checker source bindings, TLC stdout/stderr hashes, positive state/transition/depth counts, nine-invariant result summaries, and all 17 normal action families with zero unsafe edges. It confirms the retained negative counterexample endpoint and first positive-model rejection. Missing or mismatched evidence causes a nonzero exit with an explicit error. This verifier does not re-enumerate the state graph or independently replay every witness transition.

To save this verification report, select a new file outside `M`:

```console
python /path/to/M/portable_reproduce.py --report /path/to/new-verification.json
```

`ARTIFACT_BASELINE.json` remains hash-verified metadata. Its 205 targets belong to the author workspace outside the S10 archive and are explicitly **NOT_CHECKED** here, even if a local folder happens to contain similarly named files. Historical preservation findings remain historical evidence. Absolute paths in retained commands and logs are provenance, not paths used by this wrapper.

To perform a new reproduction, supply Java and the frozen TLC jar yourself. The jar must have SHA256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88` (the retained `tools/TOOLCHAIN.json` records its release). The wrapper does not fetch or install either tool. Java defaults to the original executable hash in that metadata; on another platform, provide the expected hash of your selected executable explicitly. That hash pins the supplied executable, not the whole JRE distribution or its publisher authenticity. The new run records Java's version, executable hash and whether it matches the historical executable.

```console
python /path/to/M/portable_reproduce.py --execute --output /path/to/new-s10-reproduction --java /path/to/java --java-sha256 EXPECTED_64_HEX_DIGEST --jar /path/to/tla2tools.jar
```

The output directory must not exist and must be outside `M`. The wrapper never overwrites or resumes a run. It first verifies retained evidence, then runs all fixed cases (`normal_2_1`, `normal_3_2`, `unsafe_2_1`) with their original 600/600/120-second limits. TLC uses the historical options:

```console
java -Xmx2g -cp tla2tools.jar tlc2.TLC -workers 1 -fp 0 -coverage 1 -metadir NEW_CASE_DIR/states -config CASE.cfg ECRCLifecycle.tla
```

No `-deadlock`, depth/state constraint, GC override or warning suppression is added. The retained garbage-collector advisory is nonblocking. Executable paths and temporary state-directory paths naturally differ from `v1`.

The wrapper imports the hash-verified frozen `exact_check.py` without creating archive bytecode and calls its `check_case(case, new_directory)` API. It neither edits that engine nor calls the original workspace-bound command-line runners. Each new run retains `START.json`, Java version, TLC commands/stdout/stderr/results, exact stdout/results/witnesses, and `SUMMARY.json` on success or `ERROR.json` on failure. Failures and incomplete searches remain saved; there is no automatic retry or substitution of smaller cases. All new output is marked `POST_HOC_PORTABLE_REPRODUCTION`; it does not replace `v1`.

Positive acceptance requires complete TLC/exact count and action-coverage agreement and the historical totals: 684 and 21,960 distinct states, with 2,673 and 122,089 generated states including the initial state. The negative case only requires the expected counterexample; both searches stop early, and partial discovery/processing counts are not required to match. No claim of exhaustive negative exploration is made.

Hash checks establish consistency with the retained digest values, not cryptographic authorship. Reusing the exact engine is reproduction, not a third independent enumerator. The result remains finite-model evidence under the declared message, payload, durability and deduplication abstractions; it does not establish unbounded safety, code refinement, liveness, statistical inference or implementation superiority.
