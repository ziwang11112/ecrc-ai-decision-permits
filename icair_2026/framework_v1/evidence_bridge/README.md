# Official Mendeley-v2 ECRC runtime bridge

Every frozen HGB proposal in the 11,800-decision official Mendeley-v2 replay is
sent, in participant/trial order, through `OrderedAdjudicator`, the trusted
SQLite issued-permit/capacity registry, `PEPSimulator`, and the stateful receipt
verifier. The comparison target is the frozen E1 cap-8/review-2 array router.

The current proxy label is never read by this script and is absent from the
proposal, evidence, and routing payloads. The bridge uses no EEG data. Side
effects are simulated inside SQLite; this is a retrospective technical replay,
not a live participant deployment or evidence of atomicity with an external
alert/ticketing service.
