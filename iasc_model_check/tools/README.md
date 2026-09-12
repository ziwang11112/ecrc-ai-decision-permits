# Pinned local TLA+ toolchain

Windows PATH/common Java locations and WSL Ubuntu-24.04 PATH plus `/usr/lib/jvm` had no available Java. A portable Windows x64 Eclipse Temurin JRE was downloaded into this directory; no installer ran, and PATH/registry were not changed.

| Tool | Pinned version | Download SHA256 |
|---|---|---|
| Eclipse Temurin JRE | `21.0.12.1+1-LTS` | `d35f31e712f0fcf6ac5a093edc90204fbff22f720ba3950bd09d331d5e621636` |
| Official `tla2tools.jar` | stable release `v1.7.4`; TLC `2.19 of 08 August 2024` | `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88` |

`TOOLCHAIN.json` records exact download URLs, official release metadata, versions, hashes and full Java/TLC output. The JRE checksum matches both the official release asset digest and downloaded checksum text. The TLC release supplies no asset digest; its recorded hash identifies the bytes obtained over HTTPS from the official `tlaplus/tlaplus` release. No independent TLC signature/checksum verification is claimed. `TLAPLUS_LICENSE` and the JRE's bundled legal files are retained.

From the model-study directory, this command prints TLC help without running a model:

```powershell
python tools/run_tlc.py -- -help
```

TLC v1.7.4's normal help exits with code **1**. Expected help/version text was verified; this exit code is recorded in the manifest. Java `-version` exits with zero. No model or new experiment was executed during toolchain preparation.

For a separately prepared model/configuration, run from their directory and supply their actual names:

```powershell
& 'D:/AIR-014_ECRC_Paper_Clean_2026-08-16/research_pilots/iasc_model_check_2026-09-12/tools/java/jdk-21.0.12.1+1-jre/bin/java.exe' -Xmx2g -cp 'D:/AIR-014_ECRC_Paper_Clean_2026-08-16/research_pilots/iasc_model_check_2026-09-12/tools/tla2tools.jar' tlc2.TLC -workers 1 -config Model.cfg Model.tla
```

The equivalent wrapper is `python /absolute/path/to/tools/run_tlc.py -- -workers 1 -config Model.cfg Model.tla`. It verifies the Java executable and JAR hashes, uses a 2 GiB Java heap, preserves the caller's working directory and forwards TLC arguments without a shell. Model/configuration/state-output paths and model-checking settings remain the study author's responsibility. Tool startup has been checked; no claim about a model's correctness follows from this preparation.
