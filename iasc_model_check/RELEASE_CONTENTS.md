# Current S10 portability revision and historical contents

The current PUBLIC_MANIFEST.json describes the separate portability-revision ZIP.
It keeps the original frozen study and repairs only the post-study wrapper plus
its documentation. Original wrapper bytes, original public manifest and the
original POSIX error are retained in portability_revision/. New verification
does not rerun TLC or change runs/v1.

The Git-only packaging_reproduction/ files below remain the original Windows
reproduction from the first S10 release. They predate this portability repair;
they are not the new Linux verification records. The following earlier contents
note is retained as historical documentation:

# S10 release contents

The fixed release ZIP supplies 75 files (74 source/evidence/license files plus PUBLIC_MANIFEST.json). Java, the TLC jar and TLC scratch state directories are excluded; exact official download URLs, hashes and licensing provenance are retained. No manuscript PDF, Overleaf source or preliminary manuscript text is included.

This Git directory additionally retains the separate post-study artifact reproduction under packaging_reproduction/, its original command and PORTABLE_ARCHIVE_VERIFICATION.json. That successful reproduction ran from the extracted public ZIP and reused the unchanged frozen model and exact engine. It is a packaging check, not a third independent checker or another scientific sample. PUBLIC_MANIFEST.json covers only the fixed ZIP's files; these Git-only verification additions are identified here.

The primary evidence remains runs/v1. Absolute paths in historical commands are provenance. For verification or another reproduction, use portable_reproduce.py and PORTABLE_REPRODUCTION.md. Earlier S1–S8 and S9 tags/assets remain unchanged.
