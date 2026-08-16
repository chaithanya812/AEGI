"""MP-03 — Common Data Contracts.

The dictionary every other module imports. Written first, on purpose: if each stage
invents its own shape for "a claim", nothing downstream connects.

One deliberate deviation from the Sentinel PRD, documented here because it matters:
Support has a sixth value, NOT_APPLICABLE. The PRD specifies five. But MP-05 also says
an opinion "needs no evidence at all and must never be flagged as unsupported", and with
only five values there is nowhere to put "this isn't a factual claim, so there is nothing
to verify". Collapsing that into UNSUPPORTED is exactly the false-alarm bug that makes a
validator untrustworthy — it reports "confidently wrong" about someone's opinion.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

PIPELINE_VERSION = "1.0.0"


class ClaimType(str, Enum):
    FACT = "FACT"
    NUMERIC = "NUMERIC"
    TEMPORAL = "TEMPORAL"
    ENTITY = "ENTITY"
    OPINION = "OPINION"
    PREDICTION = "PREDICTION"
    INSTRUCTION = "INSTRUCTION"
    RECOMMENDATION = "RECOMMENDATION"
    UNVERIFIABLE = "UNVERIFIABLE"


#: Claim types that carry no falsifiable assertion. Never scored as wrong.
NON_CHECKABLE: frozenset[ClaimType] = frozenset(
    {
        ClaimType.OPINION,
        ClaimType.PREDICTION,
        ClaimType.INSTRUCTION,
        ClaimType.RECOMMENDATION,
        ClaimType.UNVERIFIABLE,
    }
)


class Support(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DecidedBy(str, Enum):
    """Which layer produced the verdict. Surfaced in the UI because it is the
    answer to "why trust your verifier more than the model that hallucinated?"."""

    DETERMINISTIC = "deterministic"  # arithmetic on dates/numbers, or resolvability
    GROUNDED = "grounded"  # a fetched source span the reader can check
    JUDGE = "judge"  # LLM entailment, fuzzy prose only
    NONE = "none"  # nothing to decide (non-checkable claim)


class Band(str, Enum):
    VERIFIED = "VERIFIED"
    QUALIFIED = "QUALIFIED"
    UNRELIABLE = "UNRELIABLE"


class Risk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Outcome(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_WARNING = "ALLOW_WITH_WARNING"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"
    REFUSE = "REFUSE"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    INCONCLUSIVE = "INCONCLUSIVE"


class Span(BaseModel):
    """Character offsets into the verified output text. A claim without a real span
    was invented by the extractor, and MP-04's post-pass drops it."""

    start: int
    end: int


class EvidenceItem(BaseModel):
    doc_id: str
    doc_title: str
    collection: str  # "reference" (public facts) | "matter" (the customer's own documents)
    section: str
    page: int
    quote: str
    authority: float = Field(ge=0.0, le=1.0)
    recency_days: int | None = None
    relevance: float = 0.0
    score: float = 0.0
    retrieved_by: str = "hybrid"  # bm25 | vector | hybrid
    retrieved_at: str = ""


class CheckResult(BaseModel):
    name: str  # temporal | numeric | citation | contradiction | entailment
    module: str  # MP-12, MP-11, ...
    outcome: CheckOutcome
    detail: str
    deterministic: bool


class Claim(BaseModel):
    claim_index: int
    text: str
    source_span: Span | None = None
    claim_type: ClaimType = ClaimType.FACT
    checkable: bool = True
    hedged: bool = False
    status: Support = Support.UNKNOWN
    decided_by: DecidedBy = DecidedBy.NONE
    reasoning: str = ""
    confidence: float = 0.0
    evidence: list[EvidenceItem] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)


class Ledger(BaseModel):
    """MP-13's primary output. Deliberately not a single percentage — the PRD is explicit
    that "87% reliable" is meaningless and quietly trains everyone to ignore it."""

    supported: int = 0
    partially_supported: int = 0
    unsupported: int = 0
    contradicted: int = 0
    unknown: int = 0
    not_applicable: int = 0

    @property
    def checkable_total(self) -> int:
        return (
            self.supported
            + self.partially_supported
            + self.unsupported
            + self.contradicted
            + self.unknown
        )


class ReliabilityReport(BaseModel):
    ledger: Ledger
    band: Band
    score: int = Field(ge=0, le=100)  # kept for display only, subordinate to the ledger
    evidence_strength: float = 0.0
    source_quality: float = 0.0
    recency: float = 0.0
    expressed_confidence: Confidence = Confidence.MEDIUM
    supported_confidence: Confidence = Confidence.MEDIUM
    false_certainty: bool = False
    certainty_note: str = ""


class Decision(BaseModel):
    outcome: Outcome
    risk: Risk
    rule_id: str
    triggering_factors: list[str] = Field(default_factory=list)
    # Every input that produced the outcome, so any past decision replays exactly.
    inputs: dict[str, Any] = Field(default_factory=dict)
    table_version: str = ""


class Event(BaseModel):
    seq: int
    at: str
    stage: str
    module: str | None = None
    level: str = "info"
    message: str
    data: dict[str, Any] | None = None
    duration_ms: int | None = None


class Certificate(BaseModel):
    trace_id: str
    issued_at: str
    algorithm: str = "ed25519"
    key_id: str
    public_key: str  # base64url raw 32 bytes, embedded so the cert verifies offline
    payload: dict[str, Any]
    payload_sha256: str
    signature: str  # base64url raw 64 bytes


class RunResult(BaseModel):
    trace_id: str
    request_id: str
    created_at: str
    mode: str  # "generate" (we asked the model) | "verify_given" (user pasted the output)
    prompt: str | None = None
    output_text: str
    output_sha256: str
    model_id: str | None = None
    pipeline_version: str = PIPELINE_VERSION
    layers_enabled: dict[str, bool] = Field(default_factory=dict)
    claims: list[Claim] = Field(default_factory=list)
    #: MP-10 findings across the whole evidence set — conflicts between sources, which are
    #: a result in their own right rather than a property of any single claim.
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    reliability: ReliabilityReport
    decision: Decision
    safe_response: str | None = None
    events: list[Event] = Field(default_factory=list)
    certificate: Certificate | None = None
    latency_ms: int = 0
    token_usage: dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
    degraded_reason: str | None = None
    error: str | None = None


class VerifyRequest(BaseModel):
    """One request may carry several outputs — one per line, one tile each."""

    outputs: list[str] = Field(default_factory=list, max_length=25)
    prompt: str | None = None
    mode: str = "verify_given"
    layers: dict[str, bool] | None = None
    domain: str = "general"  # picks MP-14's sensitivity multiplier
