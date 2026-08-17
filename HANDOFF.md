# HANDOFF — AI Reliability Lab, v1.1

**This is the only document you need to start.** Everything required to work is below; the
other files in this folder are depth, not prerequisites.

---

## 1. What you're doing

You are picking up a working, deployed product and implementing **v1.1**. v1 works and is live.
A first real user session exposed a class of bug the tests could not see: asked to verify
`4 plus 3 equals 23`, the lab returned `UNKNOWN` and cited **a photosynthesis paper** as the
source. It was honest — it did not guess — but it reads as incompetence, which for a trust
product is the same thing as being incompetent.

Your job is §6 below, in the order given.

**First three commands** (cwd `AEGIS 3\lab`), to confirm the build is healthy before you change
anything:

```bash
.venv/Scripts/python.exe scripts/test_deterministic.py
```

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8008
```

```bash
cd web && npm run dev
```

Then open `http://localhost:5173`, click the **Mixed paragraph** preset, and hit Run. If you see
a verdict with a ledger and a green `✓ signature verified`, everything works and you can begin.

---

## 2. Every document in this folder

Path root: `C:\Users\chait\Downloads\TOO MUCH\RESEARCH 2\AEGIS 3`

| File | What it is | Do you need it? |
|---|---|---|
| **`HANDOFF.md`** | This file. Self-contained brief. | **Start here.** |
| `03-diagnosis-and-plan.md` | Full diagnosis with log evidence, seven workstreams, **five mermaid diagram specs (§4)**, four-beat client demo script (§5), opinions on what to add and refuse (§6). | **Yes** — open it when you reach W6; §4 is copy-paste material. Otherwise §6 below is the condensed version. |
| `02-build-notes.md` | What v1 actually shipped, and the seven traps hit while building it. | Skim once. The traps are reproduced in §9 below. |
| `01-v1-plan.md` | The original v1 plan. Historical. | Only for *why* decisions were made. Not for *what* to do. |
| `lab/README.md` | Run and deploy instructions, layout, what's deliberately out of scope. | Yes, briefly. |
| `lab/scripts/schema.sql` | The Supabase schema. Already applied. | Reference only. |

There is no other documentation. Code comments carry the rest, and they are dense on purpose —
`quantities.py`, `contradiction.py` and `verdict.py` each explain why their rules exist, because
every one of those rules is there because of a real false positive.

---

## 3. What the product is

Paste model output — one per line, one tile each — or give it a prompt and let it generate
first. Every sentence is split into individually checkable claims, each claim is checked against
evidence, and the verdict is signed with Ed25519 and logged.

It is a working slice of a larger system called **Project Sentinel**, specifically Sentinel's
"Level 4 — Verified". Module numbers in the code (`MP-04`, `MP-09`, `MP-11`, `MP-12`, `MP-15`…)
are catalogue IDs from the Sentinel specification. **Keep the MP numbering** when you add or
move things — it is how this code connects to the commercial story it is sold with.

### The one idea everything rests on

A client asks within ninety seconds: *"your verifier is the same model that hallucinated — why
trust the second answer?"*

The answer is that most of the verdict comes from **code, not a model**. Three layers, and every
claim records which one decided it in its `decided_by` field:

| Layer | What it is | Can a model overrule it? |
|---|---|---|
| `deterministic` | Date arithmetic against a reference clock. Figure comparison with unit normalisation. Whether a cited document exists. | **No.** Hard verdict. |
| `grounded` | The deciding passage is fetched and displayed with document, section and page. | No — the reader adjudicates. |
| `judge` | LLM entailment on fuzzy prose, strict rubric, reasoning always recorded. | Only for prose, and **never alone enough to BLOCK**. |

That last constraint is enforced in code, not policy: decision rule `R-JUDGE-ONLY` in
`app/pipeline/decision.py` routes an output to human REVIEW when the only thing condemning it is
the judge model's opinion.

**Every design decision follows from this.** If a change would make a model the sole authority
for a strong action, it is the wrong change.

---

## 4. Where everything is

| | |
|---|---|
| Project root | `C:\Users\chait\Downloads\TOO MUCH\RESEARCH 2\AEGIS 3` |
| Code | `AEGIS 3\lab\` — this is the **git root** and the **Vercel root** |
| Git remote | `https://github.com/chaithanya812/AEGI.git`, branch `main` |
| Live | <https://reliability-lab.vercel.app> |
| Vercel project | `chaithanya812s-projects/reliability-lab` — CLI already logged in |
| Supabase | ref `nzxxhcigxzkmynnsuayy` · pooler `aws-0-ap-southeast-2.pooler.supabase.com:5432` · user `postgres.nzxxhcigxzkmynnsuayy` |
| Python | `AEGIS 3\lab\.venv\Scripts\python.exe` — **use this, never global python** |
| Model | `gemini-3.1-flash-lite`; embeddings `gemini-embedding-001` at 768 dims |

The repo is spelled **`AEGI`**, not `AEGIS`. That may or may not be intentional; it is what
exists, so don't "fix" it without asking.

**Secrets** are in `lab/.env.local` — already populated with the Gemini key, Supabase URL and
secret key, and the Ed25519 signing seed. It is gitignored. Never commit it, never print its
values, never send them to the browser. The same values are already set in Vercel's environment
for production and preview.

### Architecture

```
Browser (Vite + React + TS)  ──/api/*──▶  FastAPI  ──▶  Gemini 3.1 Flash-Lite
  one seam: web/src/api/client.ts             │
                                              ├──▶ BM25 + embeddings over corpus/index.json
                                              ├──▶ deterministic checkers (dates, figures, citations)
                                              └──▶ Supabase (runs, claims, events, certificates)
```

Locally: either one process (uvicorn serves the built SPA from `web/dist`) or two (uvicorn plus
the Vite dev server, which proxies `/api`). In production Vercel serves `web/dist` from its CDN
and runs `api/index.py` as a Python function for `/api/*` only.

---

## 5. The bug you are fixing, with evidence

Two inputs broke it:

```
4 plus 3 equals 23.
Adolf Hitler and Albert Einstein were good friends.
```

Both returned `UNKNOWN`, and the explanation cited the photosynthesis paper as the source for
the arithmetic claim.

### Root cause: reciprocal rank fusion throws away the similarity score

Top-evidence score from the audit log, grouped by verdict:

| Verdict | n | avg | min | max |
|---|---|---|---|---|
| CONTRADICTED | 30 | 0.02180 | 0.01639 | 0.03279 |
| SUPPORTED | 8 | 0.02459 | 0.01639 | 0.03279 |
| PARTIALLY_SUPPORTED | 7 | 0.01874 | 0.01639 | 0.03279 |
| UNKNOWN | 3 | 0.02168 | 0.01639 | 0.03226 |

**Identical ranges to five decimals.** `reciprocal_rank_fusion` scores purely by rank position:
`1 / (60 + rank + 1)`. Rank 0 is always `0.016393`; rank 0 in both rankers is always `0.032787`.
Match quality never enters the number.

RRF is a good **ordering** function and a useless **confidence** function. And `relevance` is
computed as `score / best`, so the top hit always displays **1.00** — which is how a
photosynthesis paper was presented as a perfectly relevant source for `4 + 3`.

> There is currently no number anywhere in the system that can say *"this evidence is
> irrelevant."* Every downstream honesty guarantee assumes one exists.

### The five defects

| # | Defect | Where | Severity |
|---|---|---|---|
| **D1** | No abstention signal — RRF discards cosine and BM25 magnitude | `pipeline/retrieval.py` | **critical** |
| **D2** | `UNKNOWN` claims still cite irrelevant evidence as "(source: …)" | `pipeline/safe_response.py` `_cite()` | **critical** — actively untrue |
| **D3** | No arithmetic checker, so `4 + 3 = 23` needs RAG it should never touch | missing module | high |
| **D4** | MP-11 treats arithmetic operands as measurable figures | `pipeline/citation.py` | medium |
| **D5** | `relevance` shown as `score/best`, always 1.00 for the top hit | `pipeline/retrieval.py` | medium |

**D2 is the one to feel bad about.** *"Could not be checked either way (source: Photosynthesis —
process summary)"* implies we consulted that document as evidence about arithmetic. We didn't.
Retrieval handed it over and the judge dismissed it. Printing it as a source is the only thing
currently on screen that is not merely unhelpful but false.

---

## 6. What to build, in this order

### W1 — Give retrieval an abstention signal *(D1, D5 — unblocks everything)*

In `pipeline/retrieval.py`, keep the raw scores alongside the rank score. Use RRF for
**ordering** and raw signals for **abstention**. Two independent signals; both must fail before
abstaining, so we stay conservative and don't lose real catches:

| Signal | Meaning | Provisional floor |
|---|---|---|
| `cosine` | Embedding similarity of the best chunk | `< 0.55` |
| `coverage` | Fraction of the claim's distinctive terms present in the chunk | `< 0.30` |

`coverage` is deliberately interpretable — *"this passage contains none of the words the claim is
about"* is something you can say to a client; a cosine value isn't.

On abstention: return `evidence = []`, status `UNKNOWN`, `decided_by = deterministic`, and
reasoning that names the situation:

> *"Nothing in the indexed corpus addresses this claim — the closest passage matched 0.21
> against a 0.55 floor. Reported as outside the corpus rather than judged."*

Store both raw signals on `EvidenceItem` (add fields in `contracts.py`, mirror in
`web/src/api/types.ts`) and **replace `relevance` with the real cosine**. No more 1.00 by
construction.

`0.55` comes from published guidance, not from our corpus. Treat it as a starting point and
measure it in W2.

### W2 — Calibrate the floors instead of guessing (MP-46)

Build the retrieval evaluation harness. ~40 golden pairs: half that should retrieve a named
document, half that should abstain (`4 plus 3 equals 23`, `who is my landlord`, `is Pluto a
planet`). Plot the two score distributions, put the threshold in the gap, and record recall@k
and abstention precision in the test script.

**Every threshold in the system is currently a guess** — including the source authority weights
and the `0.35` relative relevance cutoff. This harness is what makes them defensible.

### W3 — Checkers that need no corpus at all *(D3, D4)*

New file `app/pipeline/arithmetic.py`. All deterministic, all `decided_by = deterministic`:

- **Arithmetic** — `4 plus 3 equals 23`, `4 + 3 = 23`, `12 times 12 is 140`, `half of 80 is 45`.
  Parse, evaluate exactly, compare. → `CONTRADICTED`, stating the true value.
- **Percentage consistency** — *"revenue was GBP 2.8bn, up 33% from GBP 2.1bn"*. Check
  `2.1 × 1.33 ≈ 2.8`. Very common in real business writing, and nobody checks it by hand.
- **Internal self-contradiction** — the output disagreeing with *itself*: "it remains the tallest
  structure at over 500 metres … the Burj Khalifa is the tallest tower". Needs no corpus.
- **Unit and magnitude sanity** — a person weighing 700 kg, a contract running 400 years, a
  percentage above 100 where it cannot be.

Then fix D4: exclude arithmetic operands from MP-11's figure comparison. The `4` in `4 plus 3` is
an operand, not a measurement.

> Strategically this is the highest-value workstream. It makes the lab sharp on exactly what a
> client tries first — mental arithmetic and self-contradiction — and it works with retrieval
> switched off entirely, which is the demo beat that reframes the product.

### W4 — Never cite evidence the verdict didn't rest on *(D2)*

In `safe_response._cite()`: cite only when the verdict actually rests on that passage
(`decided_by` is `grounded` or `deterministic` **and** the firing check names it). For `UNKNOWN`,
print no source and say plainly that the claim is outside the corpus. Apply the same rule in the
UI — an `UNKNOWN` claim should render a "nothing retrieved above the floor" state, not an
evidence card.

Small change, and it removes the only untrue thing on screen. Do it right after W1.

### W5 — Certificates a human can read

The current download is raw JSON with no explanation of what it attests to. The user could not
open it and could not tell what it was for. Both fair.

1. **On-screen certificate that reads like a document** — plain English above the hex: what was
   checked, what was found, which validators ran, what this proves, what it does *not* prove,
   who signed it, how to verify it independently.
2. **Download a self-verifying HTML file.** One file, no dependencies, that renders readably
   *and* carries a **Verify** button re-checking the Ed25519 signature in the browser via
   WebCrypto — offline, no server, nothing to install. The verification code already exists in
   `web/src/api/client.ts` (`verifySignature`); embed the same logic plus the payload.
3. **Keep the JSON** as a clearly-labelled secondary "machine-readable" download.

Order the content: *What text was checked? What did we conclude? On what basis — code or model?
Which validators were on? What evidence was used? When, by whom, and how do I check you aren't
lying?*

> This is the highest impact-per-hour item in the product. A compliance officer opens an email
> attachment in any browser with wifi off, sees `✓ signature valid`, and reads a plain-English
> account of a decision from eight months earlier. No competitor demo tells that story.

### W6 — Explain the Method page, and add the diagrams

The pipeline diagram is currently unlabelled boxes. Add prose for every stage, and a glossary
for terms that mean nothing to an outsider: *claim, span, entailment, ledger, decided-by, band,
rule, trace, certificate, abstention*.

Five diagrams to build. **The mermaid specs are written and ready to copy from
`03-diagnosis-and-plan.md` §4:** pipeline dataflow annotated, three layers of authority,
retrieval-with-abstention decision tree, certificate chain of custody, and same-claim-different-
domain risk.

### W7 — Three evidence modes, including "your documents"

The commercial unlock. Our corpus is 16 documents we wrote, so anything a client cares about is
outside it — which makes the corpus look like a limitation when it should be the product.

```
┌─ EVIDENCE SOURCE ──────────────────────────────────────────────┐
│  ● Demo pack (16 docs)   ○ Your documents   ○ Off — logic only  │
└────────────────────────────────────────────────────────────────┘
```

| Mode | What it does |
|---|---|
| **Demo pack** | Current bundled corpus. Keeps rehearsed cases deterministic. |
| **Your documents** | Paste or upload → chunk → embed → index in-session. **Show the chunks** so they see how their file was read. |
| **Off — logic only** | No retrieval. Arithmetic, dates, units, self-contradiction, false certainty still run. |

Reuse `corpus.py`'s chunker rather than writing a second one. Session-scoped storage is fine —
do not build multi-tenant persistence for v1.1.

**Do not add a RAG framework** (LangChain, LlamaIndex, RAGFlow as a dependency). The
verification chain is the product; a framework buries it and makes the pipeline harder to
explain, and explaining it *is* the sale. Worth *reading* for the ingestion shape:
[ragflow](https://github.com/infiniflow/ragflow) — steal the chunk visualisation;
[rag.computer](https://github.com/bigint/rag.computer) — closest upload→chunk→embed→search REST
shape.

### Effort

W1 + W4 together are roughly a day and fix everything the user saw. W3 and W5 are what change
how the demo lands. W7 is the commercial unlock but needs W1 working first.

---

## 7. File map

Line counts as of handoff, so you can gauge what you're opening.

### `lab/app/` — backend

| File | Lines | Owns | v1.1 |
|---|---|---|---|
| `contracts.py` | 200 | **MP-03.** Every shape the pipeline passes. **Read this first — it's the dictionary.** | **edit** — abstention fields |
| `settings.py` | 59 | Env config. All reads whitespace-stripped. | maybe |
| `main.py` | 201 | FastAPI surface, all endpoints, static SPA mount. | **edit** — upload endpoints |
| `corpus.py` | 215 | **MP-40/42.** Front-matter parsing, page-aware chunking, authority tiers, supersession map. | **edit** — W7 |
| `trace.py` | 88 | **MP-24.** Event stream. The on-screen tape renders this verbatim. | no |
| `certs.py` | 169 | **MP-33.** Ed25519 signing, canonical JSON, offline verification. | **edit** — W5 |
| `store.py` | 195 | Supabase audit log over PostgREST. **A write failure never fails a run.** | maybe |
| `presets.py` | 105 | Rehearsed demo cases, server-side so UI and tests share one list. | **edit** — logic-only presets |
| `adapters/base.py` | 40 | **MP-02** interface, `ModelError`. | no |
| `adapters/gemini.py` | 227 | **MP-02.** Raw REST not the SDK. Retries, thinking-level fallback, JSON parse retry. | no |

### `lab/app/pipeline/` — the validator chain

| File | Lines | Owns | v1.1 |
|---|---|---|---|
| `retrieval.py` | 230 | **MP-06/44.** BM25 (hand-rolled), vector search, RRF, per-claim query rewriting. | **REWRITE — W1, the main job** |
| `claims.py` | 328 | **MP-04/05.** Sentence segmentation with real offsets, LLM extraction with **span grounding** (unlocatable claims are dropped), rule-first classification. | no |
| `quantities.py` | 383 | Unit normalisation and figure comparison. **Where the deterministic layer's credibility lives.** Every rule exists because of a real false positive — read the comments. | **edit** — D4 |
| `temporal.py` | 206 | **MP-12.** Future events, supersession, staleness, negation handling. | no |
| `citation.py` | 183 | **MP-11.** Citation resolvability + figure agreement across all retrieved passages. | **edit** — D4 |
| `contradiction.py` | 164 | **MP-10.** Conflicts between sources. Heavily gated for precision. | no |
| `verdict.py` | 251 | **MP-09.** Five-value support. **Deterministic checks run first and settle without the model — the order here is the product.** | **edit** — abstention path |
| `certainty.py` | 114 | Expressed vs evidence-supported confidence. The false-certainty detector. Ours, not a Sentinel module. | no |
| `reliability.py` | 112 | **MP-13.** The ledger, the band, the subordinate score. | no |
| `decision.py` | 206 | **MP-14/15.** Risk classification and a literal versioned decision table. `R-JUDGE-ONLY` lives here. | no |
| `safe_response.py` | 82 | **MP-16.** What the human reads when something is caught. Never a bare error code. | **edit — W4** |
| `run.py` | 369 | Orchestrator: stage order, concurrency (fanout 3), trace emission. | **edit** |
| *`arithmetic.py`* | — | **New in W3.** | **create** |

### `lab/web/src/` — frontend

| File | Lines | Owns | v1.1 |
|---|---|---|---|
| `App.tsx` | 902 | All four pages: Lab, Corpus, Audit log, Method. Presets, the rig, tiles, counters. | **edit** — W6, W7 |
| `api/client.ts` | 168 | **The one seam.** Also browser-side Ed25519 verification via WebCrypto. | **edit** |
| `api/types.ts` | 199 | Hand-written mirror of `contracts.py`. Keep in sync. | **edit** |
| `components/VerdictPanel.tsx` | 259 | Band, ledger, annotated text, claim rows with evidence and checks. | **edit** |
| `components/CertificateCard.tsx` | 120 | The certificate block. | **REWRITE — W5** |
| `components/PipelineGraph.tsx` | 146 | SVG pipeline, lit from real trace events — never a timer. | **edit** — W6 |
| `components/TraceTape.tsx` | 67 | The event tape. | no |
| `components/useTraceReplay.ts` | 55 | Replays a completed trace at its **real** relative timings, compressed. Read the docstring. | no |
| `styles/lab.css` | 1020 | All styling. Tokens lifted from the Project Sentinel brief. | **edit** |

**Design constraint: white paper, black ink, single theme.** Charter serif for prose, mono for
labels, 1px black rules, hatched fills instead of colour for the middle state. It must look
identical on a projector, on a phone at night, and photocopied. **Do not introduce a colour
palette or a dark mode** — the client has already seen the matching document and the family
resemblance is deliberate.

### `lab/` — scripts and config

| File | What it does |
|---|---|
| `scripts/test_deterministic.py` | **Run constantly.** ~45 model-free assertions over the layer carrying the product's credibility. Fast, no API key, no network. Every past bug is a case here. |
| `scripts/smoke.py` | Full pipeline over 7 cases, with or without a model key. ~2–4 min with the judge live. |
| `scripts/build_corpus.py` | Chunks the corpus and embeds it into `corpus/index.json`. `--no-embed` for keyword-only. **Re-run after any corpus edit.** |
| `scripts/gen_keys.py` | Generates an Ed25519 identity. Already done — **do not regenerate**, or previously issued certificates stop matching the published key. |
| `scripts/schema.sql` | Supabase schema: `runs`, `claims`, `events`, `certificates`. Already applied. No RLS — server-only access with the secret key. |
| `vercel.json` | `"framework": null` is **load-bearing**. See traps. |
| `requirements.txt` | Ranges, not pins. See traps. |

---

## 8. Invariants — breaking these is a correctness bug

Each exists because of a real failure.

1. **Never guess.** No retrievable evidence → `UNKNOWN`, amber, never red. Absence of evidence is
   not evidence of error.
2. **Never flag an opinion as wrong.** *"My name might be Mark"* → `NOT_APPLICABLE`. Hedged and
   unfalsifiable statements are settled by rule in `claims.py:classify()` **before any model sees
   them**. A validator that cries wolf on someone's own name gets switched off.
3. **False positives are worse than misses.** The worst bug so far: a model answered a 2027 World
   Cup question correctly and carefully — *"has not taken place, no winner to report"* — and the
   lab BLOCKed it, because the temporal checker matched "winner" beside a future year and was
   blind to negation. Punishing careful behaviour destroys the reason the product exists.
4. **Never cite evidence the verdict didn't rest on.** Currently violated — that's D2.
5. **The ledger leads, the score follows.** Counts are the result; the single number is derived
   and subordinate. Do not "simplify" into one percentage, however often it's suggested.
6. **Report our own failures as ours.** Judge unreachable → claims say so and the run is marked
   `degraded`. An outage on our side must never look identical to a gap in the evidence.
7. **The certificate records which validators were on.** A verdict produced with a validator
   disabled must never be indistinguishable from a full run.
8. **One seam.** The browser talks only to our FastAPI, through `web/src/api/client.ts`. No
   component fetches Supabase or Gemini directly. No secret reaches the client.

---

## 9. Traps — each already cost real time

1. **`"framework": null` in `vercel.json`.** Vercel autodetects FastAPI from `requirements.txt`
   and its preset builds one lambda owning every route, silently overriding `functions` and
   `rewrites`. The failure is vicious: nothing errors, `/api/health` returns **200 with
   `index.html`**, and the frontend fails at JSON.parse somewhere unrelated.
2. **Vercel ignores `.python-version`.** It resolved CPython 3.14. Pinned deps with no wheel for
   that version fall back to compiling Rust and the build dies in cargo. Keep ranges.
3. **Env values set via CLI pipe carry a trailing newline**, making an API key an invalid HTTP
   header value, with an error pointing nowhere near the cause. `settings.py` strips everything.
4. **The Supabase direct DB host is IPv6-only.** DDL must go via the pooler
   (`aws-0-ap-southeast-2`) or the SQL editor. PostgREST over HTTPS is fine at runtime.
5. **Python's `re` requires fixed-width lookbehind.** Sentence segmentation is procedural for
   this reason — don't "simplify" it back into a regex.
6. **Judge concurrency.** Fanout above ~3 fires every judge call inside one second and trips the
   per-minute quota; claims then come back `UNKNOWN` for reasons unrelated to the claims. If you
   see unexplained `UNKNOWN`s, check quota before suspecting logic.
7. **Documents that quote a wrong figure in order to deny it get mined as asserting it.** A board
   pack saying *"any claim of GBP 4.2bn is not supported"* was read as stating 4.2bn. Directly
   relevant to W7 — rebuttals, FAQs and errata all contain the false claim they exist to correct.
8. **`vercel link` appends to `.env.local`** and rewrites `.gitignore`. Harmless, but check.

---

## 10. Deploy and verify

```bash
vercel --prod --yes
```

Rebuild the index after editing anything under `corpus/`:

```bash
.venv/Scripts/python.exe scripts/build_corpus.py
```

Check production health:

```bash
curl https://reliability-lab.vercel.app/api/health
```

---

## 11. Definition of done

- `scripts/test_deterministic.py` passes, **with new cases for every bug you fix.** The
  regression suite is as much the deliverable as the fix.
- `scripts/smoke.py` reports `failures: 0`.
- These four inputs behave correctly **on the deployed URL**:

| Input | Required behaviour |
|---|---|
| `4 plus 3 equals 23.` | `CONTRADICTED` via **deterministic**, no corpus involved, **no source cited** |
| `Adolf Hitler and Albert Einstein were good friends.` | `UNKNOWN`, stated as *outside the corpus*, **no source cited** |
| *"The 2027 Women's World Cup has not taken place yet; there is no winner to report."* | `VERIFIED` / `ALLOW` — must **not** be flagged |
| `Argentina won the 2027 FIFA World Cup, beating Brazil 3-1.` | `CONTRADICTED` via **deterministic** |

- A downloaded certificate opens in a browser, reads as a document a non-engineer understands,
  and verifies its own signature offline with no network.
- Commit messages explain **why**, not what. Read `git log` first — the existing history is the
  standard to match.

---

## 12. Do not

- Add a RAG framework as a dependency.
- Build the Fine-tune / Geo / Sheets tabs — they are deliberately `PLANNED` stubs, visible so the
  product's shape is legible.
- Add a chat interface. This is an inspection tool; a chat box invites people to judge it as an
  assistant.
- Regenerate the signing key.
- Relax the gates in `contradiction.py` or the non-checkable rules in `claims.py` without reading
  why they're there. Both are tight because loose versions produced confident nonsense.
- Replace the ledger with a single score.
- Introduce colour or a dark mode.
