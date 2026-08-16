/** One output's verdict: band, ledger, the annotated text, and every claim with its evidence.
 *
 *  The ledger is the primary display and the single score sits beside it, smaller. That
 *  ordering is MP-13's instruction, not a style preference — a lone percentage is what trains
 *  people to stop reading.
 */

import { useState } from "react";

import type { Claim, RunResult, Support } from "../api/types";
import { CertificateCard } from "./CertificateCard";

const STATUS_WORD: Record<Support, string> = {
  SUPPORTED: "verified",
  PARTIALLY_SUPPORTED: "partial",
  UNSUPPORTED: "unsupported",
  CONTRADICTED: "contradicted",
  UNKNOWN: "unknown",
  NOT_APPLICABLE: "not checkable",
};

const DECIDED_WORD: Record<string, string> = {
  deterministic: "arithmetic — no model involved",
  grounded: "a fetched source passage",
  judge: "the entailment model alone",
  none: "nothing to decide",
};

/** Splits the output text so each claim's span can be marked in place. */
function annotate(text: string, claims: Claim[]) {
  const spans = claims
    .filter((c) => c.source_span)
    .map((c) => ({ ...c.source_span!, status: c.status, index: c.claim_index }))
    .sort((a, b) => a.start - b.start);

  const parts: Array<{ text: string; status: Support | null; index: number | null }> = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) continue; // overlapping spans — keep the first
    if (span.start > cursor) {
      parts.push({ text: text.slice(cursor, span.start), status: null, index: null });
    }
    parts.push({ text: text.slice(span.start, span.end), status: span.status, index: span.index });
    cursor = span.end;
  }
  if (cursor < text.length) {
    parts.push({ text: text.slice(cursor), status: null, index: null });
  }
  return parts;
}

function markBand(status: Support): string {
  if (status === "CONTRADICTED" || status === "UNSUPPORTED") return "bad";
  if (status === "NOT_APPLICABLE") return "na";
  if (status === "SUPPORTED") return "ok";
  return "mid";
}

function ClaimRow({ claim, open, onToggle }: { claim: Claim; open: boolean; onToggle: () => void }) {
  return (
    <div className="claim" data-open={open ? "true" : "false"}>
      <button className="claim-btn" type="button" onClick={onToggle} aria-expanded={open}>
        <span className="idx mono">#{claim.claim_index}</span>
        <span className="txt">{claim.text}</span>
        <span className="status" data-s={claim.status}>
          {STATUS_WORD[claim.status]}
        </span>
      </button>
      <div className="claim-detail">
        <div className="inner">
          <div className="body">
            <span className="decided" data-by={claim.decided_by}>
              decided by <b>{DECIDED_WORD[claim.decided_by] ?? claim.decided_by}</b>
              {" · "}
              {claim.claim_type.toLowerCase()}
              {claim.hedged ? " · hedged" : ""}
            </span>

            {claim.reasoning ? <p>{claim.reasoning}</p> : null}

            {claim.checks.length > 0 ? (
              <div className="checks">
                {claim.checks.map((check, i) => (
                  <div className="check" key={`${check.name}-${i}`} data-o={check.outcome}>
                    <span className="o">{check.outcome}</span>
                    <span className="d">
                      <b>{check.module}</b> {check.name}
                      {check.deterministic ? " (code)" : " (model)"} — {check.detail}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}

            {claim.evidence.map((item) => (
              <div className="evidence" key={`${item.doc_id}-${item.page}-${item.section}`}>
                <div className="evidence-h">
                  <b>{item.doc_id}</b>
                  <span>{item.section}</span>
                  <span>p{item.page}</span>
                  <span className="right">
                    {item.collection} · authority {item.authority.toFixed(2)}
                    {item.recency_days !== null ? ` · ${item.recency_days}d old` : ""}
                  </span>
                </div>
                <div className="evidence-q">{item.quote}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function VerdictPanel({
  run,
  logged,
  logError,
}: {
  run: RunResult;
  logged: boolean;
  logError: string | null;
}) {
  const [openClaim, setOpenClaim] = useState<number | null>(null);
  const rel = run.reliability;
  const led = rel.ledger;
  const parts = annotate(run.output_text, run.claims);

  return (
    <div className="stack">
      <div className="fig">
        <div className="fig-head">
          <span>Verdict</span>
          <b>{run.mode === "generate" ? "generated then verified" : "verified as given"}</b>
          <span className="right mono">{run.latency_ms} ms</span>
        </div>
        <div className="fig-body stack">
          <div className="verdict-head">
            <span className="score mono">{rel.score}</span>
            <span className="band" data-band={rel.band}>
              {rel.band}
            </span>
            <span className="small">
              decision <b>{run.decision.outcome}</b> · risk {run.decision.risk} · rule{" "}
              <span className="mono">{run.decision.rule_id}</span>
            </span>
          </div>

          <div className="ledger">
            {(
              [
                ["verified", led.supported, false],
                ["partial", led.partially_supported, false],
                ["unknown", led.unknown, false],
                ["unsupported", led.unsupported, led.unsupported > 0],
                ["contradicted", led.contradicted, led.contradicted > 0],
                ["not checkable", led.not_applicable, false],
              ] as Array<[string, number, boolean]>
            ).map(([label, value, hot]) => (
              <div className="cell" key={label} data-hot={hot ? "true" : "false"}>
                <span className="v mono">{value}</span>
                <span className="l">{label}</span>
              </div>
            ))}
          </div>
          <p className="small">
            The ledger is the result. The number beside the band is derived from it and shown
            second on purpose — a single percentage is the thing people learn to ignore.
          </p>

          <div className="outputquote">
            {parts.map((part, i) =>
              part.status ? (
                <mark key={i} data-band={markBand(part.status)} title={`#${part.index} ${part.status}`}>
                  {part.text}
                </mark>
              ) : (
                <span key={i}>{part.text}</span>
              ),
            )}
          </div>

          {rel.false_certainty ? (
            <div className="notice">
              <span className="tag">False certainty</span>
              <span>
                Confidence expressed by the text: <b>{rel.expressed_confidence}</b>. Confidence
                supported by evidence: <b>{rel.supported_confidence}</b>. {rel.certainty_note}
              </span>
            </div>
          ) : (
            <p className="small">
              Confidence expressed <b>{rel.expressed_confidence}</b>, supported{" "}
              <b>{rel.supported_confidence}</b>. {rel.certainty_note}
            </p>
          )}

          {run.degraded && run.degraded_reason ? (
            <div className="notice" data-soft="true">
              <span className="tag">Degraded</span>
              <span>
                {run.degraded_reason}. Reported rather than hidden — an outage on our side must
                not look the same as a gap in the evidence.
              </span>
            </div>
          ) : null}
        </div>
      </div>

      {run.safe_response ? (
        <div className="fig">
          <div className="fig-head">
            <span>What the user is shown instead</span>
            <b>MP-16</b>
          </div>
          <div className="fig-body">
            <p style={{ whiteSpace: "pre-wrap", fontSize: "0.94rem", lineHeight: 1.55 }}>
              {run.safe_response}
            </p>
          </div>
          <div className="fig-cap">
            Never a bare error code. A blocked output that does not explain itself teaches
            people to route around the system, which is worse than not having one.
          </div>
        </div>
      ) : null}

      <div className="fig">
        <div className="fig-head">
          <span>Claims</span>
          <b>{run.claims.length}</b>
          <span className="right">click any claim for its evidence and checks</span>
        </div>
        <div className="fig-body">
          <div className="claims">
            {run.claims.map((claim) => (
              <ClaimRow
                key={claim.claim_index}
                claim={claim}
                open={openClaim === claim.claim_index}
                onToggle={() =>
                  setOpenClaim(openClaim === claim.claim_index ? null : claim.claim_index)
                }
              />
            ))}
          </div>
        </div>
      </div>

      {run.contradictions.length > 0 ? (
        <div className="fig">
          <div className="fig-head">
            <span>Sources disagree with each other</span>
            <b>MP-10</b>
            <span className="right">{run.contradictions.length} found</span>
          </div>
          <div className="fig-body stack">
            {run.contradictions.map((pair, i) => (
              <p className="small" key={i}>
                <span className="mark" data-t={pair.severity === "SEVERE" ? "solid" : "hatch"}>
                  {pair.severity}
                </span>{" "}
                {pair.detail}
              </p>
            ))}
          </div>
          <div className="fig-cap">
            Found independently of any claim. A conflict between two of the customer's own
            documents is a result in its own right — usually one nobody was looking for.
          </div>
        </div>
      ) : null}

      {run.certificate ? (
        <CertificateCard certificate={run.certificate} logged={logged} logError={logError} />
      ) : null}
    </div>
  );
}
