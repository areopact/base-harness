# Memory Routing

The lane follows the kind of information, and the page type follows the claim. Memory is personal; global truths become rules; shared project knowledge is docs. No lane is the default home for anything interesting. Lane paths come from `harness/registry/structure.json`; this page names lanes, never folders.

## Why

When the same topic lands in several lanes as the same prose, every later edit has to find every copy, and the copies drift the first time one is missed. When a dated event is filed as a belief, the belief cannot be updated without losing the evidence. When a belief is filed as a record, it sits frozen while the world moves. Each lane answers one question, and a page that answers the wrong question for its lane is a page the next session will misread.

## Application

### Routing table

| Information | Lane |
|---|---|
| Who the agent is, how it works, its voice and anti-patterns; who the operator is and how they prefer to work | identity |
| A cross-session belief, hypothesis, mental model, or operating fact that another task or runtime would benefit from | knowledge |
| A session note, a daily entry, a half-thought, a pointer to triage later | journal |
| A one-way door: what was chosen, the options considered, the risks accepted | decisions |
| An event with a date: a meeting, a call, a chat, a session, a research run, an incident | records |
| Current status, plans, architecture, living reference pages, reusable frameworks and templates | docs |
| Always-on agent behavior that must bind in every session | `harness/rules/` (a rule, not memory) |
| A fact the code, tests, or README already state | nowhere; fix the source instead |

### The four-layer test

When the same topic appears in several lanes, each page must answer a different question:

- Record: what happened?
- Knowledge: what is believed now because of it?
- Decision: what was chosen?
- Docs: what governs or can be reused now?

Do not copy the same prose into every layer. Link forward from evidence to synthesis and from synthesis to the governing page.

### Knowledge gate

The cross-context test: would a future session on a different task, or in a different runtime, act differently for knowing this? If yes, the knowledge lane may hold it. If no, keep it with the subject in docs or records.

### Maturity vocabulary

A knowledge page carries one of four maturity values:

- `working`: a material validation gap remains; an open question or an evidence path is stated.
- `standing`: the belief may be relied on within a clearly stated scope.
- `promoted`: the belief became a rule, a docs page, or a reusable asset; the page points at its destination.
- `superseded`: a successor page replaced it; the page points at the successor.

Evidence quality, contradiction handling, and scope decide maturity. A fixed observation count never does. Promotion requires the destination's own quality and approval gate.

### Hygiene

| Signal | Action |
|---|---|
| The journal lane holds an untriaged entry for more than two weeks | Route it to its lane or discard it |
| A knowledge page has not been reassessed in a quarter and its subject is volatile | Reassess before relying on it |
| A working belief has no open question or evidence path | Clarify it, promote it to standing, or archive it |
| A promoted or superseded page still reads as current | Add its pointer and move it to the lane's archive |

Identity changes follow an explicit approval protocol with the operator; the identity lane is never edited as a side effect of another task.
