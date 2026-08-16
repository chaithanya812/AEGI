/** Mirrors app/contracts.py. Kept hand-written and small rather than generated, so the
 *  shape the UI depends on is reviewable in one screen. */

export type Band = "VERIFIED" | "QUALIFIED" | "UNRELIABLE";

export type Support =
  | "SUPPORTED"
  | "PARTIALLY_SUPPORTED"
  | "UNSUPPORTED"
  | "CONTRADICTED"
  | "UNKNOWN"
  | "NOT_APPLICABLE";

export type DecidedBy = "deterministic" | "grounded" | "judge" | "none";
export type Outcome = "ALLOW" | "ALLOW_WITH_WARNING" | "REVIEW" | "BLOCK" | "REFUSE";
export type Risk = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type CheckOutcome = "PASS" | "FAIL" | "SKIP" | "INCONCLUSIVE";

export interface Span {
  start: number;
  end: number;
}

export interface EvidenceItem {
  doc_id: string;
  doc_title: string;
  collection: string;
  section: string;
  page: number;
  quote: string;
  authority: number;
  recency_days: number | null;
  relevance: number;
  score: number;
  retrieved_by: string;
  retrieved_at: string;
}

export interface CheckResult {
  name: string;
  module: string;
  outcome: CheckOutcome;
  detail: string;
  deterministic: boolean;
}

export interface Claim {
  claim_index: number;
  text: string;
  source_span: Span | null;
  claim_type: string;
  checkable: boolean;
  hedged: boolean;
  status: Support;
  decided_by: DecidedBy;
  reasoning: string;
  confidence: number;
  evidence: EvidenceItem[];
  checks: CheckResult[];
}

export interface Ledger {
  supported: number;
  partially_supported: number;
  unsupported: number;
  contradicted: number;
  unknown: number;
  not_applicable: number;
}

export interface ReliabilityReport {
  ledger: Ledger;
  band: Band;
  score: number;
  evidence_strength: number;
  source_quality: number;
  recency: number;
  expressed_confidence: Confidence;
  supported_confidence: Confidence;
  false_certainty: boolean;
  certainty_note: string;
}

export interface Decision {
  outcome: Outcome;
  risk: Risk;
  rule_id: string;
  triggering_factors: string[];
  inputs: Record<string, unknown>;
  table_version: string;
}

export interface TraceEvent {
  seq: number;
  at: string;
  stage: string;
  module: string | null;
  level: string;
  message: string;
  data: Record<string, unknown> | null;
  duration_ms: number | null;
}

export interface Certificate {
  trace_id: string;
  issued_at: string;
  algorithm: string;
  key_id: string;
  public_key: string;
  payload: Record<string, unknown>;
  payload_sha256: string;
  signature: string;
}

export interface Contradiction {
  left_doc: string;
  right_doc: string;
  left_section: string;
  right_section: string;
  dimension: string;
  left_value: string;
  right_value: string;
  severity: string;
  diff: number;
  governing_doc: string;
  detail: string;
}

export interface RunResult {
  trace_id: string;
  request_id: string;
  created_at: string;
  mode: string;
  prompt: string | null;
  output_text: string;
  output_sha256: string;
  model_id: string | null;
  pipeline_version: string;
  layers_enabled: Record<string, boolean>;
  claims: Claim[];
  contradictions: Contradiction[];
  reliability: ReliabilityReport;
  decision: Decision;
  safe_response: string | null;
  events: TraceEvent[];
  certificate: Certificate | null;
  latency_ms: number;
  token_usage: Record<string, number>;
  degraded: boolean;
  degraded_reason: string | null;
  error: string | null;
}

export interface Persistence {
  trace_id: string;
  logged: boolean;
  error: string | null;
}

export interface VerifyResponse {
  runs: RunResult[];
  persistence: Persistence[];
}

export interface Preset {
  id: string;
  label: string;
  tone: "green" | "amber" | "red";
  mode: "generate" | "verify_given";
  domain: string;
  prompt?: string;
  text?: string;
  expect: string;
  carried_by: string;
}

export interface CorpusDoc {
  doc_id: string;
  title: string;
  collection: string;
  authority_tier: string;
  authority: number;
  effective_date: string | null;
  supersedes: string | null;
  matter: string | null;
}

export interface CorpusSummary {
  documents: number;
  chunks: number;
  collections: Record<string, number>;
  vectors: boolean;
  embed_model: string | null;
  embed_dims: number | null;
  retrieval: string;
}

export interface Health {
  status: string;
  pipeline_version: string;
  model: { configured: boolean; model_id: string | null };
  audit_log: { configured: boolean };
  signing: { algorithm: string; key_id: string; ephemeral: boolean };
  corpus: CorpusSummary;
  decision_table: string;
  layers: Record<string, boolean>;
}

export interface LogRow {
  trace_id: string;
  created_at: string;
  output_text: string;
  band: Band;
  score: number;
  decision: Outcome;
  risk: Risk;
  false_certainty: boolean;
  degraded: boolean;
}
