# AI Reliability Lab — v1 build notes

Built 2026-08-16. Live at **https://reliability-lab.vercel.app** · repo
**github.com/chaithanya812/AEGI** · code in [`lab/`](lab/).

Plan and locked decisions: [01-v1-plan.md](01-v1-plan.md). This file records what actually
got built, and — more usefully — the bugs found on the way, because most of them are the kind
that recur.

---

## What shipped

All three milestones. Working end to end in production, verified against the live Gemini key
with runs logged to Supabase and certificates verifying in-browser.

| | Built |
|---|---|
| **M1 spine** | MP-03 contracts, MP-01 gateway, MP-02 Gemini adapter (raw REST), MP-04/05 claim extraction with span grounding, MP-24 trace engine, UI shell with the live tape |
| **M2 verdicts** | 16-doc two-collection corpus, hybrid BM25 + `gemini-embedding-001` retrieval with reciprocal rank fusion, MP-09/10/11/12 validators, false-certainty detector, MP-13 ledger, MP-14/15 risk and decision table, MP-16 safe response |
| **M3 polish** | Live-lighting pipeline graph, the rig (per-validator toggles), Ed25519 signed certificates with browser-side WebCrypto verification, Supabase audit log with replay-by-trace-id, six rehearsed presets, corpus and method sheets |

Beyond the plan: **the audit log and signed certificates.** The Supabase credentials arrived
mid-build, which turned "certificates that verify offline" into "certificates that verify
offline *and* are retrievable by `trace_id` years later". The full loop is verified in
production — fetch a stored certificate, check it, then alter one field and watch it fail.

## Deviations from the plan, and why

**Six values in the support enum, not five.** The PRD specifies five. MP-05 also says an
opinion "must never be flagged as unsupported", and with five values there is nowhere to put
"this isn't a factual claim". `NOT_APPLICABLE` is that place. This is the deviation that makes
the tool behave better than the one in the reference screenshots.

**MP-16 ships the deterministic template only.** The PRD wants an LLM fluency pass plus a
check that the template's facts survived it. A refusal message is the worst place in the
pipeline to add an unverified model call, and the guard is not trivial. v2 item, stated openly
in the module docstring rather than quietly skipped.

**The "future event" preset supplies pasted text rather than generating.** See the false
positive below — a current model asked who won the 2027 World Cup usually declines correctly.
The validator has to work on text from any model, including the ones that don't.

---

## The bugs worth remembering

### 1. The false positive — the one that would have killed the demo

The model was asked who won the 2027 World Cup. It answered **correctly and carefully**:
*"has not taken place yet… there is no winner or final score to report."* The lab marked it
UNRELIABLE and BLOCKed it.

Two independent causes, both instructive:

- **Negation blindness.** MP-12 matched the word "winner" next to the year 2027 and concluded
  the claim asserted a completed outcome. It said the opposite. Fixed with a non-occurrence
  check that runs *before* the concluded-verb check, covering negated verbs, determiner
  negation ("**No** Nobel Prize has been awarded … yet"), and "yet to be" — while still
  flagging adversative "yet" ("Argentina won, *yet* Brazil dominated") so the guard can't
  launder a fabrication.
- **A corpus gap.** Our FIFA document conflated the men's and women's tournaments and asserted
  "no World Cup is scheduled for 2027". The Women's World Cup *is* — in Brazil. A true
  statement read as contradicted because our ground truth was wrong.

**A validator that punishes a model for being careful is worse than no validator**, because
people switch it off. Both cases are now permanent regression tests.

### 2. Same dimension is not the same measure

Early runs produced findings like *"REF-FIFA-01 states 48 while REF-EIFFEL-01 states 01
(severe, 97.9% apart)"* — "48 teams" against a fragment of a document ID. And *"300 metres vs
828 metres"*, which is a tower in Paris against a tower in Dubai.

Three fixes: quantities now carry a context-word set and must share a subject noun to be
comparable; unit, scale and locator words are excluded so they can't manufacture a match; and
numbers that are identifiers are skipped entirely (preceded by a hyphen, or by a locator noun
like "clause"). Comparing clause 14.1 against clause 29 arithmetically produced a *confident,
severe, entirely meaningless* contradiction.

The context window then had to widen from two words to four: "Revenue for FY2025 was GBP 2.8
billion" puts the subject three tokens back, and the narrow window missed it — so a claim of
GBP 4.2bn revenue failed to compare against the audited figure at all and the deterministic
catch was silently lost.

### 3. `5mg` parsed as five million grams

The regex alternation matched the "m" of "mg" as a *scale*, leaving "g" as the unit — a factor
of 10⁹ on a drug dose, which is precisely the class of error the module exists to catch. Fixed
with `(?![A-Za-z])` on the single-letter scale forms, plus an explicit rule for the genuine
ambiguity: `$4.2B` and `GBP 5m` are scales, a bare `5 m` is metres.

### 4. MP-11 only checked the top-ranked passage

Retrieval ranks by relevance to the whole proposition, so the passage carrying the decisive
*number* is often second or third. Checking only the first hit lost the deterministic catch
and pushed the claim onto the judge for no reason. Now every retrieved passage is checked, and
the highest-authority disagreement governs.

### 5. A document that denies a figure gets mined as asserting it

Our board pack said *"any statement that revenue was GBP 4.2 billion is not supported"* — and
the extractor read the document as stating 4.2bn. Rephrased to avoid quoting the wrong number.
Worth remembering for real corpora: rebuttals, FAQs and errata all contain the false claim
they exist to correct.

### 6. Concurrency tripped the quota and looked like a coverage gap

At fanout 6, a six-claim paragraph fired every judge call inside one second and exhausted the
per-minute quota; three consecutive claims came back UNKNOWN. Honest, but for a reason that had
nothing to do with the claims. Fanout is now 3, 429s honour the server's `retryDelay`, and
structured-output parse failures retry once. Judge outages now surface as **degraded** — an
outage on our side must never look identical to a gap in the evidence.

### 7. Two deployment traps

- **Vercel's FastAPI preset silently owns every route.** It autodetects from
  `requirements.txt` and builds one lambda that overrides `functions` and `rewrites`. Nothing
  errors: `/api/health` returns **200 with `index.html`**, so the frontend parses HTML as JSON.
  `"framework": null` in `vercel.json` is load-bearing.
- **`.python-version` is ignored by Vercel's builder.** It resolved CPython 3.14; pydantic 2.10
  has no cp314 wheel, so `uv` compiled Rust against a PyO3 capped at 3.13 and the build died in
  cargo. Dependencies are now ranges, not pins.

Also: env values set through a CLI pipe arrive with a trailing newline, which makes an API key
an invalid HTTP header value and fails with an error pointing nowhere near the cause. Every env
read is stripped.

---

## Verified in production

`/api/health` — model configured, audit log configured, `hybrid (bm25 + vector, RRF)`,
16 documents / 47 chunks, non-ephemeral signing key.

| Input | Result |
|---|---|
| Model's **careful refusal** about the 2027 Women's World Cup | `VERIFIED` 100, ALLOW, 3/3 supported — the false positive is gone |
| **Fabricated result**: "Argentina won the 2027 World Cup, beating Brazil 3-1" | `UNRELIABLE` 0, BLOCK/CRITICAL, 3/3 contradicted **via deterministic** — date arithmetic, no model opinion |
| `my name might be mark . tom and jerry is disny show` | sentence 1 `NOT_APPLICABLE`, sentence 2 `CONTRADICTED` — two sentences, two different kinds of answer |
| Eiffel paragraph | `UNRELIABLE` 5, BLOCK/CRITICAL, 4 contradicted / 1 partial / 1 **not checkable** (the hedged Burj Khalifa clause) |
| Generate-then-verify round trip | 30s, logged |
| Certificate fetched back from Supabase | valid; alter one field → `payload digest does not match` |

Those first two rows are the pair to show a client together. Same tournament, same year, same
corpus — and the difference between them is entirely in what the text asserts, not in how
confidently it was written.

## Next, in order

1. **Permissions at ingest and retrieval-time filtering** (MP-41/18). Sentinel Level 3. The
   single thing a regulated customer asks about first, and currently absent.
2. **A retrieval evaluation harness** (MP-46). Every tuning decision here is judgement without
   it, including the authority weights and the relevance cutoff.
3. **MP-16's fluency pass, with the fact-survival guard** that makes it safe.
4. **Real connectors** (MP-39/40). The bundled corpus is the honest limit of the demo; a pilot
   needs the customer's own documents, and that is where enterprise deployments actually stall.
