These files are the PayFlow system specification: the frozen contracts the service is built against.

The implementation conforms to them, never the reverse; if a requirement here seems wrong or ambiguous, stop and escalate rather than improvise.

Any change to a contract in this folder is a human decision recorded in an ADR under `docs/adr/`, not an implementation convenience.

The files split by concern: `domain.md`, `state-machine.md`, `api.md`, `invariants.md`, and `constraints.md`.

Note that `generated_specs/` at the repo root is agent OUTPUT (discovered properties), unrelated to this folder.
