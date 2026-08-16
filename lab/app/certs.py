"""Signed verdict certificates.

Sentinel's MP-33 calls for signed receipts. The shape here is deliberately stronger than a
database row: a certificate carries its own public key and its own canonical payload, so it
verifies **offline**, with no call back to us. That is what makes it evidence rather than a
claim — a customer's auditor can check a verdict we issued eight months ago without our
servers being reachable, and without trusting us at the moment of checking.

It also solves a practical problem: Vercel functions have no persistent disk, so a
self-contained certificate is the only receipt that survives a cold start regardless of
whether the database write succeeded.

The browser verifies with WebCrypto and never asks us to confirm our own signature —
a server that says "trust me, I checked my own signature" proves nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .contracts import Certificate
from .settings import settings
from .trace import utcnow_iso


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def canonical_json(payload: Any) -> bytes:
    """Byte-for-byte reproducible. Key order and spacing must not drift, or a payload
    that is semantically identical produces a different signature and the cert 'fails'
    for no real reason."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


class Signer:
    def __init__(self, seed: bytes | None = None) -> None:
        if seed is None:
            configured = settings().signing_seed
            if configured:
                seed = b64u_decode(configured)
            else:
                # Ephemeral key. Signatures still verify within the process lifetime, and
                # the key_id changes on restart — which is the honest signal that this
                # deployment has no configured identity, rather than pretending it does.
                seed = os.urandom(32)
                self.ephemeral = True
        if len(seed) != 32:
            raise ValueError(f"SIGNING_SEED must decode to 32 bytes, got {len(seed)}")
        if not hasattr(self, "ephemeral"):
            self.ephemeral = False
        self._private = Ed25519PrivateKey.from_private_bytes(seed)
        self._public_raw = self._private.public_key().public_bytes_raw()

    @property
    def public_key_b64u(self) -> str:
        return b64u_encode(self._public_raw)

    @property
    def key_id(self) -> str:
        return "ed25519:" + self._public_raw.hex()[:16]

    def sign(self, trace_id: str, payload: dict[str, Any]) -> Certificate:
        message = canonical_json(payload)
        return Certificate(
            trace_id=trace_id,
            issued_at=utcnow_iso(),
            algorithm="ed25519",
            key_id=self.key_id,
            public_key=self.public_key_b64u,
            payload=payload,
            payload_sha256=hashlib.sha256(message).hexdigest(),
            signature=b64u_encode(self._private.sign(message)),
        )


def verify_certificate(cert: dict[str, Any]) -> tuple[bool, str]:
    """Independent verification. Takes a certificate dict exactly as issued and checks it
    against the public key *embedded in the certificate itself* — so this same function
    works for a cert this process never saw."""
    try:
        public = cert.get("public_key")
        signature = cert.get("signature")
        payload = cert.get("payload")
        if not public or not signature or payload is None:
            return False, "certificate is missing public_key, signature or payload"

        message = canonical_json(payload)

        digest = hashlib.sha256(message).hexdigest()
        if cert.get("payload_sha256") and cert["payload_sha256"] != digest:
            return False, "payload digest does not match payload_sha256 — payload was altered"

        key = Ed25519PublicKey.from_public_bytes(b64u_decode(public))
        key.verify(b64u_decode(signature), message)
    except InvalidSignature:
        return False, "signature does not match payload for this key"
    except Exception as exc:
        return False, f"malformed certificate: {exc}"

    key_id = cert.get("key_id") or ""
    expected = "ed25519:" + b64u_decode(cert["public_key"]).hex()[:16]
    if key_id and key_id != expected:
        return False, f"key_id {key_id} does not match embedded public key ({expected})"

    return True, "signature valid for the embedded key"


_signer: Signer | None = None


def signer() -> Signer:
    global _signer
    if _signer is None:
        _signer = Signer()
    return _signer


def certificate_payload(
    *,
    trace_id: str,
    request_id: str,
    output_text: str,
    output_sha256: str,
    model_id: str | None,
    pipeline_version: str,
    layers_enabled: dict[str, bool],
    band: str,
    score: int,
    ledger: dict[str, int],
    decision: dict[str, Any],
    claims: list[dict[str, Any]],
    expressed_confidence: str,
    supported_confidence: str,
    false_certainty: bool,
    degraded: bool,
    created_at: str,
) -> dict[str, Any]:
    """What gets signed.

    Binds the verdict to *this exact output* via its hash, and records which validators
    were switched on. That second field matters more than it looks: a certificate produced
    with the citation validator disabled must not be indistinguishable from one produced
    with everything running, or the rig becomes a way to launder a weak check.
    """
    return {
        "version": 1,
        "trace_id": trace_id,
        "request_id": request_id,
        "created_at": created_at,
        "output_sha256": output_sha256,
        "output_length": len(output_text),
        "model_id": model_id,
        "pipeline_version": pipeline_version,
        "layers_enabled": dict(sorted(layers_enabled.items())),
        "verdict": {
            "band": band,
            "score": score,
            "ledger": ledger,
            "decision": decision.get("outcome"),
            "risk": decision.get("risk"),
            "rule_id": decision.get("rule_id"),
            "expressed_confidence": expressed_confidence,
            "supported_confidence": supported_confidence,
            "false_certainty": false_certainty,
        },
        "claims": [
            {
                "index": c["claim_index"],
                "text": c["text"],
                "type": c["claim_type"],
                "checkable": c["checkable"],
                "status": c["status"],
                "decided_by": c["decided_by"],
                "evidence": [
                    {"doc_id": e["doc_id"], "section": e["section"], "page": e["page"]}
                    for e in c.get("evidence", [])
                ],
            }
            for c in claims
        ],
        "degraded": degraded,
    }
