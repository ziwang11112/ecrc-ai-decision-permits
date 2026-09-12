# Pre-execution clarifications

Before any run, scenario 6's response-loss injection is refined to an actual client read timeout: the shared service delays its success response for 1 second after the durable effect transaction returns; that worker has a 0.2-second HTTP timeout. The harness must independently confirm the effect exists before calling this an accepted timeout. Normal requests retain a 5-second timeout. This changes no state contract, case count or expected outcome. The original locked PROTOCOL.md SHA-256 is d618e794fc6ba5f785147f6796e09e548c28045aa105416c092bf3d400c34537.

Input constructors may use frozen typed schemas to serialize shared declarative JSON, but never call an adjudicator. Ordinary issuance must still implement every semantic decision without ECRC imports. Only a paused worker undergoing termination needs checkpoint messages; its parent independently backs up the databases after the process exits.
