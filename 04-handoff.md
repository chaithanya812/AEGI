# Handoff — AI Reliability Lab

**Paste everything below the line into a fresh agent session.** It assumes no prior context.

---

## Your assignment

You are picking up a working, deployed product called the **AI Reliability Lab** and
implementing v1.1. The v1 build works; a first real user session exposed a class of bug the
tests could not see. Your job is the seven workstreams in
`AEGIS 3/03-diagnosis-and-plan.md`, in the order given at the end of that file.

**Read these three files first, in this order, before touching code:**

1. `AEGIS 3/03-diagnosis-and-plan.md` — what is broken, why, and the plan. **This is your spec.**
2. `AEGIS 3/02-build-notes.md` — the seven traps already hit. Re-hitting one wastes a day.
3. `AEGIS 3/lab/README.md` — how to run and deploy.

`AEGIS 3/01-v1-plan.md` is the original plan and is now historical. Useful for the *why*, not
the *what*.

## Where everything is

| | |
|---|---|
| Project root | `C:\Users\chait\Downloads\TOO MUCH\RESEARCH 2\AEGIS 3` |
| Code | `AEGIS 3\lab\` — this is the git root **and** the Vercel root |
| Git remote | `https://github.com/chaithanya812/AEGI.git`, branch `main` (repo is spelled `AEGI`, not `AEGIS` — intentional or not, it's what exists) |
| Live | <https://reliability-lab.vercel.app> |
| Vercel project | `chaithanya812s-projects/reliability-lab`, CLI already logged in |
| Supabase | project ref `nzxxhcigxzkmynnsuayy`; pooler `aws-0-ap-southeast-2.pooler.supabase.com:5432`, user `postgres.nzxxhcigxzkmynnsuayy` |
| Python venv | `AEGIS 3\lab\.venv\Scripts\python.exe` — **use this, not global python** |

Secrets live in `lab/.env.local`, which is gitignored and already populated (Gemini key,
Supabase URL + secret key, Ed25519 signing seed). Never commit it, never print its values, and
never send them to the browser.

## What this product is

Paste model output — or give it a prompt and let it generate — and it splits every sentence
into individually checkable claims, checks each against evidence, and signs the verdict.

It is a working slice of a larger system called **Project Sentinel**, specifically Sentinel's
"Level 4 — Verified". Module numbers throughout the code (`MP-04`, `MP-09`, `MP-11`, `MP-12`,
`MP-15`…) are catalogue IDs from the Sentinel specification, so this pipeline maps onto the
bigger build. **Keep the MP numbering when you add or move things** — it is how the code
connects to the commercial story.

### The one idea the whole product rests on

A client asks within ninety seconds: *"your verifier is the same model that hallucinated — why
trust the second answer?"* The answer is that most of the verdict comes from **code, not a
model**. Three layers, and every claim records which one decided it in `decided_by`:

- `deterministic` — date arithmetic, figure comparison with unit normalisation, whether a
  citation resolves. A model cannot overrule these.
- `grounded` — the deciding passage is fetched and shown, so the reader adjudicates.
- `judge` — LLM entailment on fuzzy prose only, and **never alone sufficient for a BLOCK**
  (enforced by decision rule `R-JUDGE-ONLY` in `app/pipeline/decision.py`).

Every design decision follows from this. If a change would make a model the sole authority for
a strong action, it is the wrong change.

## Non-negotiable invariants

Breaking any of these is a correctness bug, not a style question. Each exists because of a real
failure.

1. **Never guess.** No retrievable evidence → `UNKNOWN`, displayed amber, never red. Absence of
   evidence is not evidence of error.
2. **Never flag an opinion as wrong.** *"My name might be Mark"* → `NOT_APPLICABLE`. Hedged and
   unfalsifiable statements are settled by rule in `app/pipeline/claims.py:classify()` **before
   any model sees them**. A validator that cries wolf on someone's own name gets switched off.
3. **False positives are worse than misses.** The worst bug found so far: a model answered a
   2027 World Cup question correctly and carefully, and the lab BLOCKed it. Punishing careful
   behaviour destroys the product's reason to exist.
4. **Never cite evidence the verdict did not rest on.** Currently violated — see D2 in the plan.
5. **The ledger leads, the score follows.** Counts of verified / partial / unknown / unsupported
   / contradicted are the result. The single number is derived and subordinate. Do not
   "simplify" this into one percentage, however often it is suggested.
6. **Report our own failures as ours.** Judge unreachable → claims say so and the run is marked
   `degraded`. An outage on our side must never look identical to a gap in the evidence.
7. **The certificate records which validators were on.** A verdict produced with a validator
   disabled must never be byte-indistinguishable from a full run.
8. **One seam.** The browser talks only to our FastAPI. No component fetches Supabase or Gemini
   directly; no secret reaches the client. Everything goes through `web/src/api/client.ts`.

## Architecture

```
Browser (Vite + React + TS)  ──/api/*──▶  FastAPI  ──▶  Gemini 3.1 Flash-Lite
   one seam: web/src/api/client.ts            │
                                              ├──▶ BM25 + embeddings over corpus/index.json
                                              ├──▶ deterministic checkers (dates, figures, citations)
                                              └──▶ Supabase (runs, claims, events, certificates)
```

Locally you can run one process (uvicorn serves the built SPA) or two (uvicorn + Vite dev
server proxying `/api`). In production Vercel serves `web/dist` from its CDN and runs
`api/index.py` as a Python function for `/api/*` only.

## File map

Every file, what it owns, and whether v1.1 touches it.

### Backend — `lab/app/`

| File | Lines | Owns | v1.1 |
|---|---|---|---|
| `contracts.py` | 200 | **MP-03.** Every shape the pipeline passes: `Claim`, `EvidenceItem`, `CheckResult`, `Ledger`, `ReliabilityReport`, `Decision`, `Event`, `Certificate`, `RunResult`. Read this first — it is the dictionary. | **edit** — add abstention fields to `EvidenceItem` |
| `settings.py` | 59 | Env config. All reads are whitespace-stripped (piped env values arrive with trailing newlines). | maybe |
| `main.py` | 201 | FastAPI surface. All endpoints. Static SPA mount. | **edit** — upload endpoints |
| `corpus.py` | 215 | **MP-40/42.** Front-matter parsing, page-aware chunking, authority tiers, supersession map. | **edit** — accept user docs |
| `trace.py` | 88 | **MP-24.** Event stream. The tape on screen renders this verbatim. | no |
| `certs.py` | 169 | **MP-33.** Ed25519 signing, canonical JSON, offline verification. | **edit** — W5 |
| `store.py` | 195 | Supabase audit log over PostgREST. **A write failure never fails a run.** | maybe |
| `presets.py` | 105 | The rehearsed demo cases, server-side so UI and tests share one list. | **edit** — add logic-only presets |
| `adapters/base.py` | 40 | **MP-02** interface + `ModelError`. | no |
| `adapters/gemini.py` | 227 | **MP-02.** Raw REST, not the SDK. Retries, thinking-level fallback, JSON parse retry. | no |

### The validator chain — `lab/app/pipeline/`

| File | Lines | Owns | v1.1 |
|---|---|---|---|
| `claims.py` | 328 | **MP-04/05.** Sentence segmentation with real offsets, LLM extraction with **span grounding** (a claim not findable in the source is dropped), rule-first classification. | no |
| `retrieval.py` | 230 | **MP-06/44.** BM25 (hand-rolled), vector search, reciprocal rank fusion, per-claim query rewriting. | **REWRITE — W1, the main job** |
| `quantities.py` | 383 | Unit normalisation and figure comparison. **Where the deterministic layer's credibility lives.** Densely commented; every rule is there because of a real false positive. | **edit** — exclude arithmetic operands |
| `temporal.py` | 206 | **MP-12.** Future events, supersession, staleness, negation handling. | no |
| `citation.py` | 183 | **MP-11.** Citation resolvability + figure agreement across *all* retrieved passages. | **edit** — D4 |
| `contradiction.py` | 164 | **MP-10.** Conflicts between sources. Heavily gated for precision — read the comments before loosening anything. | no |
| `verdict.py` | 251 | **MP-09.** Five-value support. **Deterministic checks run first and settle without the model.** The order here is the product. | **edit** — abstention path |
| `certainty.py` | 114 | Expressed vs evidence-supported confidence. The false-certainty detector. Not a Sentinel module — ours. | no |
| `reliability.py` | 112 | **MP-13.** The ledger, the band, and the subordinate score. | no |
| `decision.py` | 206 | **MP-14/15.** Risk classification and a literal, versioned decision table. `R-JUDGE-ONLY` lives here. | no |
| `safe_response.py` | 82 | **MP-16.** What the human reads when something is caught. Never a bare error code. | **edit — W4** |
| `run.py` | 369 | Orchestrator. Stage order, concurrency (fanout 3 — higher trips the quota), trace emission. | **edit** |

### Frontend — `lab/web/src/`

| File | Lines | Owns | v1.1 |
|---|---|---|---|
| `App.tsx` | 902 | All four pages: Lab, Corpus, Audit log, Method. Presets, the rig, tiles, counters. | **edit** — modes, upload, W6 |
| `api/client.ts` | 168 | **The one seam.** Also browser-side Ed25519 verification via WebCrypto. | **edit** |
| `api/types.ts` | 199 | Hand-written mirror of `contracts.py`. Keep them in sync. | **edit** |
| `components/VerdictPanel.tsx` | 259 | Band, ledger, annotated text, claim rows with evidence and checks. | **edit** |
| `components/CertificateCard.tsx` | 120 | The certificate block. | **REWRITE — W5** |
| `components/PipelineGraph.tsx` | 146 | SVG pipeline, lit from real trace events — never a timer. | **edit** — W6 labels |
| `components/TraceTape.tsx` | 67 | The event tape. | no |
| `components/useTraceReplay.ts` | 55 | Replays a completed trace at its **real** relative timings, compressed. Read the docstring — it explains what is real and what is paced. | no |
| `styles/lab.css` | 1020 | All styling. Design tokens lifted from the Project Sentinel brief. | **edit** |

**Design constraint: white paper, black ink, single theme.** Charter serif for prose, mono for
labels, 1px black rules, hatched fills instead of colour for the middle state. It should look
identical on a projector, on a phone at night, and photocopied. Do not introduce a colour
palette or a dark mode — the client has already seen the matching document and the family
resemblance is the point.

### Scripts and config — `lab/`

| File | What it does |
|---|---|
| `scripts/test_deterministic.py` | **Run this constantly.** ~45 model-free assertions over the layer that carries the product's credibility. Fast, no API key, no network. Every past bug is a case here. |
| `scripts/smoke.py` | Full pipeline over 7 cases, with or without a model key. Takes ~2–4 min with the judge live. |
| `scripts/build_corpus.py` | Chunks the corpus and embeds it into `corpus/index.json`. `--no-embed` for keyword-only. **Re-run after any corpus edit.** |
| `scripts/gen_keys.py` | Generates an Ed25519 signing identity. Already done; don't regenerate or old certificates stop matching the published key. |
| `scripts/schema.sql` | Supabase schema — `runs`, `claims`, `events`, `certificates`. Already applied. No RLS: server-only access with the secret key. |
| `vercel.json` | `"framework": null` is **load-bearing** — see traps. |
| `requirements.txt` | Ranges, not pins — see traps. |

## How to run

Everything below assumes cwd `AEGIS 3\lab`.

```bash
.venv/Scripts/python.exe scripts/test_deterministic.py
```

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8008
```

```bash
cd web && npm run dev
```

One process instead, exactly like production:

```bash
cd web && npm run build
```

Then start uvicorn as above and open `http://localhost:8008` — it serves `web/dist` itself.

Deploy:

```bash
vercel --prod --yes
```

Rebuild the index after editing anything in `corpus/`:

```bash
.venv/Scripts/python.exe scripts/build_corpus.py
```

## Traps — each of these already cost real time

1. **`"framework": null` in `vercel.json`.** Vercel autodetects FastAPI from `requirements.txt`
   and its preset builds one lambda that owns every route, silently overriding `functions` and
   `rewrites`. The failure mode is vicious: nothing errors, and `/api/health` returns **200 with
   `index.html`**, so the frontend parses HTML as JSON and every call fails somewhere else.
2. **Vercel ignores `.python-version`.** It resolved CPython 3.14. Pinned deps with no wheel for
   that version fall back to compiling Rust and the build dies in cargo. Keep ranges.
3. **Env values set through a CLI pipe carry a trailing newline**, which makes an API key an
   invalid HTTP header value and produces an error pointing nowhere near the cause. `settings.py`
   strips everything; keep it that way.
4. **The Supabase direct DB host is IPv6-only.** DDL must go through the pooler
   (`aws-0-ap-southeast-2`) or the SQL editor. PostgREST over HTTPS is fine for runtime.
5. **Python's `re` requires fixed-width lookbehind.** Sentence segmentation is procedural for
   this reason; don't "simplify" it back into a regex.
6. **Judge concurrency.** Fanout above ~3 fires every claim's judge call inside one second and
   trips the per-minute quota, and claims come back `UNKNOWN` for reasons unrelated to the
   claims. If you see unexplained `UNKNOWN`s, check for quota before suspecting logic.
7. **Documents that quote a wrong figure in order to deny it get mined as asserting it.** A
   board pack saying *"any claim of GBP 4.2bn is not supported"* was read as stating 4.2bn.
   Relevant to user-uploaded documents: rebuttals, FAQs and errata all contain the false claim
   they exist to correct.
8. **`vercel link` appends to `.env.local`.** It adds a `VERCEL_OIDC_TOKEN` and rewrites
   `.gitignore`. Harmless, but check the file afterwards.

## Definition of done

- `scripts/test_deterministic.py` passes, **with new cases for every bug you fix.** The
  regression suite is the deliverable as much as the fix is.
- `scripts/smoke.py` reports `failures: 0`.
- These four inputs behave correctly end to end on the deployed URL:

| Input | Required behaviour |
|---|---|
| `4 plus 3 equals 23.` | `CONTRADICTED` via **deterministic**, no corpus involved, **no source cited** |
| `Adolf Hitler and Albert Einstein were good friends.` | `UNKNOWN`, stated as *outside the corpus*, **no source cited** |
| *"The 2027 Women's World Cup has not taken place yet; there is no winner to report."* | `VERIFIED` / `ALLOW` — must **not** be flagged |
| `Argentina won the 2027 FIFA World Cup, beating Brazil 3-1.` | `CONTRADICTED` via **deterministic** |

- A downloaded certificate opens in a browser, reads as a document a non-engineer understands,
  and verifies its own signature offline.
- Commit messages explain **why**, not what. The existing history is the standard to match —
  read `git log` before writing one.

## Things not to do

- Do not add a RAG framework as a dependency. The verification chain is the product; a framework
  buries it and makes the pipeline harder to explain, and explaining it is the sale.
- Do not build the Fine-tune / Geo / Sheets tabs. They are deliberately `PLANNED` stubs.
- Do not add a chat interface. This is an inspection tool.
- Do not regenerate the signing key.
- Do not relax the gates in `contradiction.py` or the non-checkable rules in `claims.py` without
  reading why they are there. Both are tight because loose versions produced confident nonsense.
- Do not replace the ledger with a single score.
