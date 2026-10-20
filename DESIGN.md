# Hospital GTM Team Design

## Purpose and decision
Build a small agent team that helps a founder investigate whether a hospital is a suitable discovery customer for an ER bed availability product. The prototype turns evidence and customer feedback into a sourced opportunity brief, a proposed discovery or pilot approach, and an outreach draft.

Use Band Desktop as the coordination surface and Cognee Open Source as shared persistent memory. Begin with one hospital and three agents. A separate web application is optional.

This is a design for a prototype. It does not claim that the integrations have been implemented or that hospitals have validated the product.

## Product hypothesis
The founder is exploring software that could predict ED demand, staffed bed availability, and discharge timing to support operational planning. Customer discovery must establish the actual bottleneck, who owns it, whether suitable data exists, and what a useful pilot would measure.

Possible bottlenecks include ED treatment space, staffing, inpatient boarding, and discharge coordination. The team must not assume these are interchangeable.

## User and value
The initial user is a founder evaluating hospital customer opportunities. The output should help the founder decide whom to speak with, what to ask, and whether to pursue a pilot.

The commercial hypothesis is that healthcare startup teams could pay for researched opportunities and maintained customer knowledge. The hospital is a potential buyer of the future ER product. The founder is the user of this GTM prototype. Neither business model is validated by the demo.

## Hackathon requirements
| Requirement | Implementation | Visible proof |
| --- | --- | --- |
| Band Desktop shared room | Three agents in one hospital room | Room participants and activity |
| Shared plan and board | Strategist creates and delegates tasks | Tasks moving to completion |
| Direct handoffs | Agents mention the next agent with context | Research to strategy to outreach |
| Human decision | Founder approves a discovery direction | Approval and changed downstream draft |
| Usage visibility | Use native per-agent session and cost views | Show required views during recording |
| Cognee working memory | Write evidence, feedback, and decisions during execution | Successful write and record identity |
| Persistent recall | Fresh agent session retrieves prior feedback | Revised strategy explains remembered evidence |
| Deep integration | Decisions and research flow through shared coordination and memory | No separate orchestrator or hidden context copying |

The brief calls the client jam. Current Band documentation calls its bundled CLI band and describes the background daemon as jamd. Verify the installed version and organizer expectations before recording. Do not invent command names or approval APIs.

## Prototype scope
Include one hospital evaluation, three agents, source provenance, persistent memory, a founder decision, a structured opportunity brief, and an outreach draft.

Start with supplied public sources so the integration can be demonstrated reliably. Add live search after the main workflow works. Public material could include annual reports, strategic plans, official patient flow case studies, and relevant hospital webpages. These are commercial research inputs, not patient records.

Exclude clinical prediction models, EHR connections, bed assignment, patient data, email sending, contact enrichment, bulk prospecting, and a full CRM.

## Architecture
Band Desktop creates and runs the configured Codex or Claude Code agents. Each agent uses the same project directory and can invoke a small Python client for shared memory. Band handles task coordination, messages, human decisions, and observability.

A single local Python memory service owns the Cognee connection and storage. Agents call that service through a thin command-line client or MCP tools. Start with the command-line client because coding agents can invoke it directly.

| Component | Responsibility |
| --- | --- |
| Band Desktop | Agent configuration, room, shared work, handoffs, founder interaction |
| Agent harnesses | Model reasoning and permitted tool execution |
| Memory client | Validated requests to the shared local service |
| Memory service | Cognee writes and reads, write serialization, persistence |
| Canonical record store | Exact source text, provenance, decisions, and output versions |
| Research tools | Optional search and webpage retrieval |
| Output writer | Markdown and JSON opportunity briefs and outreach drafts |

Use SQLite for canonical record metadata and a persistent local Cognee storage directory for graph and retrieval data. SQLite supports exact provenance lookup. Cognee provides semantic recall across findings and decisions. A retrieved record must influence reasoning to demonstrate the memory requirement.

Bind a local service to loopback for the demo. If it is exposed remotely, add authentication. Configure all agents against the same service address.

## Workflow
1. Founder gives the strategist a hospital ID, product hypothesis, and sources.
2. Strategist recalls prior hospital context and creates the shared plan.
3. Researcher claims the research task and retrieves prior evidence.
4. Researcher reads sources, saves findings, and waits for successful indexing.
5. Researcher mentions the strategist with record IDs and open questions.
6. Strategist recalls findings and feedback, then proposes a discovery direction.
7. Strategist asks the founder to approve or change that direction through Band.
8. Founder responds. Strategist saves the decision against a strategy version.
9. Strategist hands the approved approach to the outreach writer.
10. Outreach writer recalls the evidence and decision, writes a draft, and requests review.
11. New customer feedback is stored. A fresh strategist session recalls it and revises the next action.

No approval is implied by elapsed time. A revised strategy invalidates the previous approval for outreach generation until the founder approves the new version.

## Agent responsibilities
The strategist leads the board and evaluates fit. It identifies buyer roles as hypotheses and asks for a meaningful decision before outreach.

The researcher extracts supported information and retains source excerpts. It reports unknowns and contradictory evidence.

The outreach writer converts approved strategy into a concise discovery message. It does not send the message.

Use different supported harnesses if setup is reliable. This can earn extra credit, but a working two-agent integration takes priority over adding runtimes.

## Memory and data model
Each record contains a stable ID, hospital ID, kind, content, evidence status, timestamp, author, source metadata, and links to supporting records.

Kinds are public evidence, hypothesis, discovery feedback, founder decision, strategy, and outreach draft. Evidence status separates sourced, unverified, simulated, and founder-confirmed information.

Example record

```json
{
  "record_id": "feedback_demo_001",
  "hospital_id": "demo",
  "kind": "discovery_feedback",
  "content": "The operations director wants to discuss inpatient bed readiness before ED arrival forecasting.",
  "evidence_status": "simulated",
  "source_file": "fixtures/discovery_note.txt",
  "observed_at": "2026-10-20",
  "author_agent": "strategist",
  "source_record_ids": []
}
```

Use separate hospital datasets or enforced hospital filtering. Include provenance in indexed text and resolve matching evidence back to canonical records. Validate that the installed Cognee API returns enough identifiers for this mapping. If necessary, retain record IDs in ingested content and return only validated matches. A generated answer alone is insufficient provenance.

Record new corrections with supersedes links. Retrieve conflicting and superseded records with status so the agent can explain changes. Do not erase history silently.

## Proposed local API
These endpoints are application contracts to implement, not existing Band or Cognee APIs.

| Endpoint | Request | Response |
| --- | --- | --- |
| POST /memories | Validated record and idempotency key | Record ID and indexing state |
| GET /memories/{id} | Record ID | Canonical record |
| POST /recall | Hospital ID and question | Retrieved evidence and canonical record IDs |
| POST /decisions | Hospital ID, strategy version, options, explicit answer | Decision ID |
| GET /health | No payload | Service and storage availability |

Return indexing states such as pending, ready, and failed. A handoff requiring memory must wait for ready. Serialize writes in the service. Use an idempotency key to prevent duplicate feedback on retries. Do not let an agent overwrite another record accidentally.

The initial client could expose commands such as memory-client remember and memory-client recall. Those are proposed project commands, not commands that currently exist.

## Cognee integration
Use Cognee Open Source in the local service. The current upstream quickstart documents remember(content, dataset_name=...) and recall(query, datasets=[...]). Older installations may expose add, cognify, and search. Pick one installed version, verify its signatures, and lock it before building around it.

Current documentation also describes local extraction and embeddings through the gliner extra, with model downloads on first use. Complete those downloads before the presentation. A configured hosted provider is another option if allowed and tested.

Do not delete or recreate storage during an agent restart. Run the memory service independently from agent sessions. A real recall test must work when the fresh agent has not received the feedback in its prompt.

## Band Desktop setup
Install and sign into the desktop application. Ensure each chosen harness is installed and authenticated. Create three custom agents, choose their runtimes, and set their working directories.

Configure each agent to read AGENTS.md and apply its assigned role. Add role instructions in Band settings if the harness does not automatically load the file.

Use the installed Band integration for messaging, task operations, and decisions. Validate each operation with a small task before adding domain logic. The exact room invitation and approval affordances depend on the installed release. A text request in a room should be demonstrated as a recorded human decision if no structured product-choice approval control exists.

Verify the required session, token, and cost views before recording. If the installed release lacks a required view, ask the event team how to satisfy that requirement.

## Outputs
The opportunity brief includes hospital identity, supported observations, product-fit hypotheses, likely buyer roles, unknowns, discovery questions, proposed pilot, source references, and the founder decision.

The pilot proposal specifies the question to test, data to assess, operational owner to verify, scope, and a success measure to agree with the customer. Do not invent a quantitative improvement target.

The outreach draft asks for a discovery conversation and references only supported details. Its status remains draft until reviewed.

A learning summary shows the prior recommendation, new feedback, retrieved records, and revised recommendation.

## Demo plan
Use Demo Hospital for a fully synthetic run, or a real hospital with public research and explicitly simulated discovery feedback.

During preparation, create an initial recommendation. During the recording show the following in two to three minutes.

- Show the Band room, shared plan, board, and distinct agents.
- Show a researcher handoff and a completed task.
- Add a simulated customer note that changes the priority from arrivals to inpatient bed readiness.
- Show the successful Cognee write.
- Start a fresh strategist session with only the hospital ID and request to prepare the next meeting.
- Show its recall and the resulting revised proposal.
- Make an explicit founder decision in Band.
- Show the outreach handoff, draft, and native usage view.

Do not paste the discovery feedback into the fresh strategist prompt. That would weaken the demonstration of persistent recall.

## Implementation plan
Phase 1 proves integration. Connect two Band agents and complete a real handoff. Run a Cognee write and retrieval from separate processes with retained storage.

Phase 2 builds shared tools. Implement validated records, the local memory service, indexing status, canonical provenance lookup, and the client. Add a fictional hospital fixture.

Phase 3 completes the domain workflow. Configure the three roles, approvals, brief generation, and revised strategy after feedback.

Phase 4 improves presentation. Add live research if reliable, polish the outputs, and rehearse the required demo. Add optional features only if the core is stable.

## Verification
| Check | Expected result |
| --- | --- |
| Cross-agent memory | Agent B retrieves a record written by Agent A |
| Fresh session | Strategy changes using memory absent from the new prompt |
| Hospital isolation | Demo Hospital feedback does not appear as another hospital's fact |
| Provenance | Every factual claim resolves to a supplied or fetched source |
| Human decision | Dependent outreach waits for explicit approval |
| Version change | New strategy requires a corresponding decision |
| Failed indexing | Task remains blocked with a useful error |
| Duplicate retry | Same idempotency key creates no duplicate record |
| Simulation labels | Fictional feedback remains labeled in all outputs |

Run these focused checks and one full workflow. Prefer a small number of meaningful integration checks over extensive mock tests.

## Optional integrations
Flexprice can meter completed opportunity briefs or evaluated hospitals. Use a real metering event and a defined plan if implemented. Agent runtime costs and customer charges are separate quantities.

Snyk can scan the code and dependencies. A security agent may report findings through Band, block completion until addressed, and store recurring lessons in Cognee. Optional integrations must not displace mandatory coordination and memory work.

## Risks and fallbacks
Public hospital evidence can be sparse. Return unknowns and discovery questions. If live search fails, use a prepared source pack and disclose it.

Memory processing can be slow. Prewarm models and keep ingestion small. If Cognee fails, show the error and fix it before presenting a successful memory demo.

Agents can repeat or conflict. Use explicit task owners, versioned outputs, bounded retries, and one owner for shared code changes.

The product may become a generic lead generator. Preserve the differentiating behavior of revising a healthcare product hypothesis and pilot proposal from accumulated customer learning.

## References
Hackathon brief supplied by the founder
https://docs.google.com/document/d/1EPVITpZuETrKNxLSDIuqP6qKw3FiYdXpByN0eocZnqw/edit

Band Desktop setup and custom agents
https://docs.band.ai/band-desktop

Band coordination examples
https://www.band.ai/hacker-guide

Cognee Open Source and current quickstart
https://github.com/topoteretes/cognee

Documentation was consulted on October 20 2026. Verify installed versions during implementation.

