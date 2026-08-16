# AI Reliability Lab

> Don't just generate. Verify.

Paste model output — or give a prompt and let the lab generate first. Every sentence is
broken into individually checkable claims, each claim is checked against a fixed evidence
corpus, and the verdict is signed with Ed25519 so it can be proved months later.

A working slice of Project Sentinel's **Level 4 — Verified**. The module numbers throughout
(MP-04, MP-09, MP-11, MP-12, MP-15…) are the same catalogue IDs used in the Sentinel brief,
so this pipeline maps onto the larger build rather than being a separate demo artefact.

---

## The one thing that matters

A client asks this within ninety seconds:

> *"Your verifier is the same model that hallucinated. Why trust the second answer more?"*

The answer is that most of the verdict doesn't come from a model. Three layers, in order of
authority, and every claim records which one ruled it (`decided_by`):

| Layer | What it is | Can a model override it? |
|---|---|---|
| `deterministic` | Date arithmetic against a reference clock. Figure comparison with unit normalisation. Whether a cited document exists at all. | No. Hard verdict. |
| `grounded` | The deciding source passage is fetched and shown next to the claim, with document, section and page. | No — the reader adjudicates. |
| `judge` | Entailment between evidence and claim, strict rubric, reasoning always recorded. | Only for fuzzy prose, and **never alone for a BLOCK**. |

That last constraint is enforced in code, not policy: decision rule `R-JUDGE-ONLY` routes an
output to human REVIEW when the only thing condemning it is the judge model's opinion with no
deterministic check agreeing. See [`app/pipeline/decision.py`](app/pipeline/decision.py).

## Four things it deliberately won't do

1. **Won't guess.** No retrievable evidence → `UNKNOWN`, shown amber, never red.
2. **Won't call an opinion wrong.** "My name might be Mark" → `NOT_APPLICABLE`. Crying wolf
   on someone's own name is how a validator loses its audience.
3. **Won't print one score and stop.** The ledger is the result; the number is derived from it
   and shown second.
4. **Won't hide its own failures.** Judge unreachable → affected claims say so, run marked
   degraded. An outage must never look like a gap in the evidence.

---

## Run it locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```

Copy `.env.example` to `.env.local` and fill in `GEMINI_API_KEY`. Then generate a signing
identity and build the retrieval index:

```bash
.venv/Scripts/python scripts/gen_keys.py
```

```bash
.venv/Scripts/python scripts/build_corpus.py
```

Two processes in development — API and Vite dev server, which proxies `/api` to the API:

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8008
```

```bash
cd web && npm install && npm run dev
```

Or one process, exactly like production: `npm run build` in `web/`, then start uvicorn — it
serves `web/dist` itself.

Smoke-test the whole pipeline, with or without a model key:

```bash
.venv/Scripts/python scripts/smoke.py
```

## Deploy

```bash
vercel --prod
```

Vercel serves `web/dist` from its CDN and runs `api/index.py` as a Python function for
`/api/*`. Set these in the project's environment — never commit them:

| Variable | Needed for |
|---|---|
| `GEMINI_API_KEY` | generation, claim extraction, entailment judge |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | the audit log |
| `SIGNING_SEED` | a stable certificate identity (else an ephemeral key is used and reported as such) |
| `REFERENCE_CLOCK` | optional: pins the temporal validator's "now" so the future-event demo stays reproducible |

## Layout

```
app/
  contracts.py          MP-03  the shapes every module passes
  main.py                      FastAPI surface — the only thing the browser talks to
  settings.py                  env config; secrets never reach the client
  corpus.py             MP-40/42  front-matter parsing, page-aware chunking
  trace.py              MP-24  event stream (what the tape renders, verbatim)
  certs.py              MP-33  Ed25519 signing; certificates verify offline
  store.py                     Supabase audit log over PostgREST
  presets.py                   the rehearsed demo cases
  adapters/gemini.py    MP-02  REST, with thinking-level and parse-retry fallbacks
  pipeline/
    claims.py           MP-04/05  extraction with span grounding, rule-first classification
    retrieval.py        MP-06/44  hybrid BM25 + vector, reciprocal rank fusion
    quantities.py              unit normalisation — where the deterministic layer lives
    temporal.py         MP-12  future events, supersession, staleness
    citation.py         MP-11  resolvability + figure agreement
    contradiction.py    MP-10  conflicts between sources
    verdict.py          MP-09  five-value support, deterministic-first
    certainty.py        new    expressed vs supported confidence
    reliability.py      MP-13  the ledger
    decision.py         MP-14/15  risk, then a literal decision table
    safe_response.py    MP-16  what the human actually reads
    run.py                     orchestration
corpus/
  reference/                   public factual records — makes walk-up prompts checkable
  matter/                      a fictional customer's own documents — we own the ground truth
web/                           Vite + React + TS, on the Sentinel brief's design tokens
```

## Not in v1

No embeddings are required (BM25 alone still catches every deterministic failure). No auth or
permission filtering — that is Sentinel MP-18/41, Level 3, and the obvious next step. MP-16
ships the deterministic template without the PRD's LLM fluency pass, because the guard that
would verify the facts survived that pass does not exist yet, and a refusal message is the
worst place to add an unverified model call.
