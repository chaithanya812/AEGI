# AI Reliability Lab — version 1 build plan

**Goal:** a small web app you can open in front of a client, type any prompt into, and watch it catch a
lie the model just told — with the evidence, the trace and the decision visible. Built so the engine
underneath is the same shape as Sentinel's verification chain, so a "build it for our company" contract
is an extension, not a rewrite.

Written 2026-08-16 against the Project Sentinel brief v1.3 (artifact `d8976a1f`), Sheets 01–06.

**Decisions locked 2026-08-16:** scope is the Reliability Lab alone, other three tabs as `PLANNED` nav
stubs (§2). Stack is FastAPI + Vite/React/TS, one deploy (§3). Open: headline score vs ledger (§6), and
whether the repo name `AEGI` is intended (§9).

> **Status: built and deployed 2026-08-16.** All three milestones shipped. Live at
> <https://reliability-lab.vercel.app>, code in [`lab/`](lab/), what actually happened —
> including the seven bugs worth remembering — in [02-build-notes.md](02-build-notes.md).
> Two things went beyond this plan: a Supabase audit log with replay-by-trace-id, and
> Ed25519 verdict certificates that verify in the browser. The §6 recommendation was taken —
> the ledger leads, the score is subordinate.

---

## 1. The one thing that decides whether this demo works

A sharp client will ask this within ninety seconds:

> "Your verifier is the same model that hallucinated. Why do you trust the second answer more than the first?"

If the answer is "it's another Gemini call with a better prompt", the demo is dead. Everything below is
organised around having a real answer.

**The answer: most of the verdict comes from code, not from a model.** Three layers, in order of how much
weight they carry:

| Layer | What it is | Can a model's opinion override it? |
|---|---|---|
| **Deterministic** | Date arithmetic against a reference clock. Number extraction + unit normalisation. Does the cited document/page exist in the corpus at all. | No. Hard verdict. |
| **Grounded** | The cited span is fetched and shown next to the claim. The client reads both. | No — the reader adjudicates. |
| **Judged** | Entailment between evidence text and claim text, with a strict rubric, reasoning always logged. | Only for genuinely fuzzy prose, and never as the sole basis for a BLOCK. |

This is exactly the split Sentinel's brief already argues for — MP-15 is specified as *"deliberately boring
code — a decision table, not a model"* because *"the neural network decided" is not an answer that survives
that meeting.* Version 1 honours that from day one.

**Consequence: we control the evidence corpus.** v1 ships with a small bundled document set (~30 docs with
page/section coordinates) standing in for the customer's knowledge base. That is what makes citation
validation *resolvable* — we can show the actual source text — and it makes the three demo scenarios
deterministic instead of lucky. Disclosed openly on screen: *"this is the customer's document set in the
real deployment."*

---

## 2. Scope: one lab, built properly

Your note floated a four-tab "AI Engineering Playground" (Reliability / Fine-Tune / Geo / SheetAI).
**Recommendation: v1 is the Reliability Lab alone.** Reasons, in order:

1. **Only one of the four is a product.** Fine-Tune Studio, Bhoomi Watch and SheetAI already exist and
   already have their numbers — they're portfolio pieces. Re-skinning them as tabs makes you look like a
   generalist for hire. One deep lab makes you the person who solves *this* problem.
2. **It's the tab that maps to the contract.** A client who wants the big build wants verification,
   governance and audit — Sentinel Levels 3–5. Satellite change detection does not lead there.
3. **Four shallow tabs = four demos that break.** One tab survives a hostile question.

**But the option stays open:** the shell ships with the four-item nav, three marked `PLANNED`. Turning one
on later is an afternoon, because the tab is a route and a component, not an architecture change.

---

## 3. Architecture

```
Vite + React + TS  ──HTTP──▶  FastAPI  ──▶  Gemini 3.1 Flash-Lite (adapter)
   (one seam:                   │
    api/client.ts)              ├─▶ BM25 over bundled corpus   (no vector DB in v1)
                                ├─▶ deterministic checkers      (dates, numbers, resolvability)
                                └─▶ trace event stream → JSONL on disk
```

**Why FastAPI and not all-TypeScript:** the verification engine is the deliverable, and it needs to be
liftable straight into the real Sentinel build — which is already Python (`AEGIS/sentinel`). Date parsing,
unit normalisation and entailment plumbing are also simply nicer in Python. Production is still *one*
deploy: FastAPI serves the built SPA as static files.

**One seam, same rule as the Sentinel console:** every screen reads through a typed API client. No
component imports a fixture. That's what lets the mock/canned mode below exist without a second UI.

---

## 4. Modules in v1, mapped to Sentinel MP numbers

Each is 30–80 lines. The mapping is the point — the demo doubles as evidence that the 63-module
decomposition is real and that you've already built the hard middle of it.

| MP | Module | v1 implementation |
|---|---|---|
| 03 | Common Data Contracts | Pydantic: `Request, Claim, EvidenceItem, ValidationResult, ReliabilityReport, Decision, Event`. Written first. |
| 01 | AI Gateway (thin) | Stamps `request_id` / `trace_id`. One door. |
| 02 | Model Adapter Layer | One adapter (Gemini). Interface ready for a second so "model-agnostic" is demonstrable, not claimed. |
| 04 | Claim Extraction | Constrained-JSON Gemini call **plus a deterministic post-pass that rejects any claim whose text isn't a real span of the response.** |
| 05 | Claim Classification | Rules first (has a number → NUMERIC, has a date → TEMPORAL, hedge verb → OPINION), model for the remainder. Opinions are never flagged unsupported. |
| 06 | Evidence Retrieval | Per-claim query rewrite, BM25 over the corpus. Note: this is *not* the answering retrieval — it asks "what would refute this proposition". |
| 07 | Evidence Quality | Authority tier from a source registry + recency + relevance. Config-driven, transparent. |
| 09 | Support Verdict | Five values (`SUPPORTED / PARTIALLY / UNSUPPORTED / CONTRADICTED / UNKNOWN`), reasoning always returned. |
| 10 | Contradiction Engine | Pairwise numeric/date comparison across the evidence set, with normalisation *before* comparison. Severity MINOR/MODERATE/SEVERE. |
| 11 | Citation Validator | Resolve → compare. Numbers deterministically, prose by entailment. Unresolvable citation = hard fail. |
| 12 | Temporal Validator | Reference clock. Future-event-described-as-concluded, superseded-by-newer, timeframe conflict. **Pure code.** |
| 13 | Reliability Report | The claim ledger. See §6 on why not a single percentage. |
| 14 | Risk Classification | LOW / MEDIUM / HIGH / CRITICAL, with a domain sensitivity multiplier in config. |
| 15 | Decision Engine | A literal decision table. `ALLOW / ALLOW_WITH_WARNING / REVIEW / BLOCK / REFUSE`, emitting every input that produced it. |
| 16 | Safe Response | Templated refusal that quotes the actual reason. Never a bare error code. |
| 24 | Trace Engine | Every stage emits an event. Retrieve and replay any past run by `trace_id`. |
| — | **False-Certainty Detector** *(new)* | Expressed confidence (hedging-lexicon analysis of the prose) vs evidence-supported confidence (from the verdicts). **The gap is the finding.** This is your original idea and it's the most distinctive thing in the demo. |

Out of scope for v1, stated plainly: no embeddings or vector store (BM25 only), no auth or permission
filtering (that's MP-18/41 — Sentinel Level 3, and the obvious v2), no database (JSONL on disk), no token
streaming, none of the other three playground tabs.

---

## 5. The three scenarios — rigged to be deterministic, not lucky

"Give it a bad prompt and hope it hallucinates" fails on stage roughly one run in four. Each preset is
built so a checker that cannot fail carries the moment:

| Preset | Prompt | What guarantees the outcome |
|---|---|---|
| 🟢 **Safe** | *"What is photosynthesis?"* | Corpus contains supporting material. Verdicts land SUPPORTED. |
| 🔴 **Hallucination** | *"Who won the 2027 FIFA World Cup?"* | The date is in the future. The temporal checker fires on arithmetic, **whatever the model says.** Guaranteed. |
| 🟠 **Citation mismatch** | A revenue question about a company that exists **only in our corpus** | We own the ground truth — the document says $2.8B. Number comparison is arithmetic. Guaranteed. |

Then the fourth mode, which is the one that actually closes: **"now type anything you want."** Unrehearsed,
live, labelled as such. It only works because the deterministic layer carries it — which is the whole
argument of §1, demonstrated rather than asserted.

Plus the control borrowed from Sentinel's own playground screen: **switch a layer off and watch what slips
through.** Turn the citation validator off, re-run, watch the bad citation sail past. That single toggle
explains the product better than any diagram.

---

## 6. One place I'd push back on the sketch

Your mockup shows `FINAL RELIABILITY SCORE 94/100`. Sentinel's own MP-13 says the opposite, and it's right:
*"deliberately not a single percentage — '87% reliable' is meaningless and quietly trains everyone to ignore it."*

**Recommendation:** the primary display is the ledger — `4 verified · 1 uncertain · 2 unsupported · 0 contradicted`
— with a headline **band** (`VERIFIED / QUALIFIED / UNRELIABLE`) above it. A number is still computed and
available, just subordinate. You keep the at-a-glance hit a client wants without shipping a metric your
own brief calls meaningless. Easy to change either way; say the word.

---

## 7. Layout

Black-and-white printed-document aesthetic, reusing the v1.3 brief's exact CSS tokens (Charter serif,
mono labels, `--ink`/`--paper`, 1px black rules, the `mark` badges). The demo should look like it came out
of the same drawer as the brief.

```
┌─ AI RELIABILITY LAB ─────────────────────────────────────────────────────┐
│  RELIABILITY  ·  fine-tune PLANNED · geo PLANNED · sheets PLANNED        │
├──────────────────────────┬──────────────────┬────────────────────────────┤
│ PROMPT                   │  PIPELINE        │  TRACE                     │
│ [_____________________]  │                  │  21:54:02 request received │
│  safe · halluc · cite    │   USER           │  21:54:02 response gen'd   │
│  [ RUN VERIFICATION ]    │    ▼             │  21:54:03 7 claims         │
│                          │   LLM            │  21:54:03 factuality       │
│ GENERATED ANSWER         │    ▼             │  21:54:04 citations        │
│ ...                      │  VALIDATOR       │  21:54:04 confidence       │
│                          │  ╱   │   ╲       │  21:54:05 complete         │
│ CLAIM LEDGER             │ fact cite cert   │                            │
│ ▸ claim 1  SUPPORTED     │  ╲   │   ╱       │  TRACE ID  8F29A1          │
│ ▸ claim 2  CONTRADICTED  │  CONSENSUS       │  [ replay ]                │
│   evidence: "...$2.8B"   │    ▼             │                            │
│                          │  DECISION        │  RIG                       │
│ ⚠ FALSE CERTAINTY        │  BLOCK           │  ☑ citations ☑ temporal    │
│   expressed HIGH         │                  │  ☑ contradiction ☑ judge   │
│   supported  LOW         │                  │                            │
└──────────────────────────┴──────────────────┴────────────────────────────┘
```

The pipeline graph lights up stage by stage as the run proceeds — same node, same MP number, so the
diagram in the brief and the diagram in the demo are the same diagram.

---

## 8. Milestones

| | Ships | Demoable state |
|---|---|---|
| **M1 — Spine** | Contracts, gateway, Gemini adapter, claim extraction, trace stream, UI shell with live tape | Prompt → answer → claims listed → trace runs. No verdicts yet. |
| **M2 — Verdicts** | Corpus + BM25, temporal, numeric/citation, entailment, ledger, decision table, safe response | All three scenarios work end to end. **This is the client-ready point.** |
| **M3 — Polish** | Live-lighting architecture graph, layer toggles, trace replay, canned-run fallback, free-prompt mode | Survives hotel wifi and a hostile question. |

---

## 9. Practical notes

- **Model:** `gemini-3.1-flash-lite` (GA since 2026-05-07). Thinking levels `minimal → high` via
  `thinkingConfig`: `minimal` for generation, `low`/`medium` for judge calls. ~$0.25 in / $1.50 out per 1M
  tokens, so a full run with ~5 calls lands well under a cent.
- **The API key came through redacted** (`AIzaSyD8•••…`) — only the first eight characters arrived. Paste it
  into `.env.local` yourself; it will be gitignored and never committed. That's the right handling anyway,
  since the repo is going public-adjacent.
- **Offline fallback is a requirement, not a nicety.** Every rehearsed run is recorded to disk; if the API
  is unreachable the lab replays the recording and says so on screen. A demo that dies on conference wifi
  is worse than no demo.
- **Repo:** `github.com/chaithanya812/AEGI.git` exists and is currently **empty** (zero refs). Note it's
  spelled `AEGI`, not `AEGIS` — worth confirming that's intended before the first push.
