# Band coordination setup

PR2 uses the installed Band CLI as the coordination surface. The Python package
does not create a second task system or copy room state into local files.

## Configure the agents

In Band Desktop, create three custom agents that use the same repository working
directory:

- `GTM Strategist`: use `prompts/strategist.md` and give it ownership of the plan.
- `Hospital Researcher`: use `prompts/researcher.md`.
- `Outreach Writer`: use `prompts/outreach_writer.md`.

The PR2 acceptance slice uses only the strategist and researcher. Add the
outreach writer after the two-agent handoff works. Use the actual handles shown
by Band; the logical role names are not platform identifiers.

The Codex runtime must have the repository as its working directory. Keep
approval requests enabled while validating commands. The strategist should be
allowed to use Band task, plan, message, and human-question tools, but no
external sending or unrelated filesystem access is required.

## Actual CLI smoke test

Verify the installed CLI and daemon before creating a room:

```bash
band --version
band preflight
band chat new --with OWNER/hospital-gtm-researcher --bind
```

The last command prints the room ID. Substitute that ID and the real strategist
handle in the following commands:

```bash
band plan set ROOM_ID plans/hospital-evaluation.md --snapshot --as OWNER/hospital-gtm-strategist
band work assign ROOM_ID "Research hospital patient-flow priorities" \
  --detail "Write sourced memory and return record IDs and unknowns." \
  --component research --component memory_service \
  --as OWNER/hospital-gtm-strategist
band work board ROOM_ID --json --as OWNER/hospital-gtm-strategist
band work take ROOM_ID '#1' --as OWNER/hospital-gtm-researcher
band work room-status ROOM_ID '#1' in_progress --as OWNER/hospital-gtm-researcher
band send ROOM_ID '@OWNER/hospital-gtm-strategist Research handoff: ...' \
  --as OWNER/hospital-gtm-researcher
band work room-status ROOM_ID '#1' completed --as OWNER/hospital-gtm-researcher
band ask --prompt 'Approve the current strategy?' \
  --option approved --option revise --json \
  --as OWNER/hospital-gtm-strategist
```

The shared board and messages are authoritative. `band plan set` stores a room
plan, `work assign/take/room-status` manages shared work, `send` routes a room
message, and `ask` waits for a human answer through Band's HITL path.

## Implemented adapter

`hospital_gtm.band.BandClient` wraps those documented commands and fails closed
on a non-zero exit or invalid JSON. `BandCoordinator` provides the PR2 slice:

1. Strategist publishes the plan and adds the researcher.
2. Strategist assigns a research task.
3. Researcher takes it, marks it in progress, and writes memory independently.
4. Researcher sends an explicit handoff with record IDs and completion evidence.
5. Strategist requests founder approval and validates the strategy version before
   any downstream outreach handoff.

## Capabilities and limits observed

The installed Band 0.4.16 CLI provides rooms, participants, shared plans, shared
task boards, peer messages, human questions, runtime status, and usage views.
It does not provide hospital roles, memory persistence, Cognee provenance,
strategy-version validation, or an external messaging integration. Those remain
application contracts in this repository or explicit future work. `band ask`
supports selectable options, but the application still validates the returned
answer against the current strategy version.

No command in this PR sends email, enriches contacts, accesses patient data, or
connects to a CRM. If a Band command or integration is unavailable, report the
blocker rather than simulating a completed handoff.
