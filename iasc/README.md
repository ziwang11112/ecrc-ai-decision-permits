# Current IASC source mirror

These selected files are byte-identical to the matching paths in the public
reproducibility archive. SOURCE_MIRROR_MANIFEST.json maps every mirrored file.
The complete artifact, including primary and repeated SQLite databases, is a
versioned Release asset. Follow the repository root README to download it.
Some historical reports and figure builders refer to evidence only present in
that full artifact; use the extracted artifact for complete reproduction.

end_to_end/ contains the full 34-file frozen code/input set and can run the S8
formal suite in a new output directory. statistics/ and calibration/ retain
their full small input/output bundles. Original src/ and icair_2026/ at the
repository root remain the historical simulator, distinct from these extensions.
