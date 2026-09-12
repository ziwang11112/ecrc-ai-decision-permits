# R2 documentation correction

Each 36-run dataset has 36 direct final client/sink pairs and 126 checkpoint backup pairs: 90 non-final snapshots and 36 backups in snapshots/final. Final-state backups are therefore included in the checkpoint count. The older term "126 intermediate pairs" was overly broad; no saved database, audit count or result is changed by this correction.

The retained second run and its independently constructed 36-row identity comparison are in portable_reproduction/. Each run still counts once in its own 36-run dataset. The repeat supports reproducibility and is not an additional primary sample.

The frozen source, historical generated snippets, original reports and PORTABLE_VERIFICATION.json remain as recorded. Their hashes are preserved. Use this correction, the current supplement and manuscript for the counting terminology. The scientific rows and aggregate audit checks are unchanged.
