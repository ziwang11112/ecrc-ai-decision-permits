# Literature source versions and scope

Checked 12 September 2026 against the following primary versions.

## Exact primary versions

| Key | Primary source and reviewed locations | Scope of comparison |
| --- | --- | --- |
| `chen2026cordon` | [Cordon v1](https://arxiv.org/html/2606.17573v1), §§3.3–3.4, 4.4–4.6; [metadata](https://arxiv.org/abs/2606.17573v1) | Lineage, release boundary and recovery. Existing seven-author entry agrees with arXiv metadata. Do not turn reported idempotency metadata into a guarantee for arbitrary remote services. |
| `ye2026contracts` | [Agent Contracts v3](https://arxiv.org/html/2601.08815v3), §§4.3, 6.1, 7.1–7.3; [metadata](https://arxiv.org/abs/2601.08815v3) | Activation, budgets and practical enforcement. Existing Qing Ye / Jing Tan entry and title agree with the abstract page; HTML appends “(Full)”.  |
| `peng2026masugate` | [MasuGate v2](https://arxiv.org/html/2608.02764v2), §§3.3–3.4, 4.4–4.5, 6 “External Effects”; [metadata](https://arxiv.org/abs/2608.02764v2) | PSS and recovery scope. Exact authors: Yuxiang Peng, Xiaodi Wu; exact title: *Stateful Governance for Concurrent Agentic Systems*; v2 dated 10 August 2026; DOI `10.48550/arXiv.2608.02764`. |
| `lavi2026right` | [Right-to-Act v1](https://arxiv.org/html/2604.24153v1), §4 and §12.4; [metadata](https://arxiv.org/abs/2604.24153v1) | Abstract pre-execution rule. HTML uses a different displayed title; the existing bibliography follows the official abstract-page title. |
| `uchibeke2026before` | [Before the Tool Call v1](https://arxiv.org/html/2603.20953v1), §§3.2–3.5, 4, 9 | Passport/hook and signed decision evidence. Avoid equating the signed authorization record with confirmed remote execution. |

The table and prose summarise the reviewed versions; they do not infer absence of unreported capabilities. No external performance numbers are transferred to the manuscript. PSS means policy-state serializability and is expanded in the manuscript. All existing citation keys are retained; only `peng2026masugate` is new.

## Critical semantic distinction

MasuGate's formal comparison uses a legal serial position, not a simultaneous wall-clock read. ECRC's arm contract and conditional counting argument do not establish PSS. No dominance ranking is supported.

## Implementation boundaries

- [S6 protocol](../../runtime/PROTOCOL.md): preissued permits, irrevocable arm, independent service, uncertain delivery and reconciliation.
- [S8 protocol](../../end_to_end/PROTOCOL.md): raw-request journal, outer issuance transaction and serialized unarmed cleanup.
- [Conditional accounting](CONDITIONAL_ACCOUNTING.md): current sufficient assumptions and argument, with source mappings in the companion registry.
