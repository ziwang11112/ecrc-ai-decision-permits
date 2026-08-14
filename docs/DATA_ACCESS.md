# Data access and attribution

## Many Labs IGT

The development cohort is the public dataset described by Steingroever et al.
(2015), *Data from 617 Healthy Participants Performing the Iowa Gambling Task:
A “Many Labs” Collaboration*, DOI 10.5334/jopd.ak, repository
https://osf.io/8t7rm. The publisher's dataset description identifies the
dataset licence as [CC BY-SA
4.0](https://creativecommons.org/licenses/by-sa/4.0/).

Download the source CSV matrices (`choice_*`, `wi_*`, `lo_*`, `index_*`) from
the upstream repository and place them under:

`data/raw/external/many_labs_igt/extracted/IGTdataSteingroever2014/`

Then normalize them without adding EEG or clinical fields:

```bash
python scripts/prepare_many_labs_igt_behavior.py   --input-dir data/raw/external/many_labs_igt/extracted/IGTdataSteingroever2014   --output-csv data/raw/external/many_labs_igt/many_labs_igt_behavior_long.csv
```

The expected normalized file size and SHA-256 are recorded in
`icair_2026/framework_v1/evidence_v2/input_hashes.csv`.

## Mendeley IGT version 2

The same-task external cohort is Chávez-Sánchez et al. (2026), Mendeley Data
version 2, DOI 10.17632/2pw2m39yct.2, licensed under [CC BY
4.0](https://creativecommons.org/licenses/by/4.0/). Only the 59 behavioural
`IGT.csv` files are used; no EEG or participant clinical file is requested.

```bash
python scripts/download_mendeley_v2_igt.py   --target-root data/raw/external/mendeley_igt_v2_behavior_only
```

The downloader enforces an exact filename/folder inventory, file-size ceiling,
and public-API SHA-256 checks.

## Redistribution boundary

This anonymous repository does not redistribute raw data, row-level predictions
or routes, participant-level workload exports, or fitted model files.  It
contains code, input hashes and aggregate results. Aggregate tables are
statistical transformations and figures are visualisations created for this
study; both are attributed to the upstream datasets above and separately
licensed as described in `LICENSES.md`. Users obtain upstream data under the
licensors' terms and regenerate row-level intermediates locally.
