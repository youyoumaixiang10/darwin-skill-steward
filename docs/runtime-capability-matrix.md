# Runtime capability matrix

Darwin Core governs evidence, evaluation, approval, promotion, and rollback. A runtime adapter supplies only the operations that its host exposes.

| Runtime | Discovery | Candidate package | Observation | Apply | Rollback | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Codex | Implemented | Planned in adapter | Hook translation implemented | Existing Codex workflow | Existing Codex workflow | Core extraction in progress |
| Claude Code / Cowork | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Planned |
| WorkBuddy | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Planned |
| Doubao client | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable | Planned |

An unavailable capability is recorded as unavailable. Darwin does not infer usage, success, installation, or mutation from missing runtime signals.
