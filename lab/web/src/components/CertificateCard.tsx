/** The signed verdict receipt.
 *
 *  The signature is checked in the browser, against the key embedded in the certificate.
 *  We never display "verified" on the strength of the server saying so about its own
 *  signature — that is a claim, not a proof, and this whole product is about the difference.
 */

import { useEffect, useState } from "react";

import { downloadCertificate, verifySignature, type SignatureCheck } from "../api/client";
import type { Certificate } from "../api/types";

const LABEL: Record<SignatureCheck["state"], string> = {
  valid: "signature verified",
  invalid: "SIGNATURE INVALID",
  checking: "checking signature",
  unsupported: "signature not checked locally",
};

export function CertificateCard({
  certificate,
  logged,
  logError,
}: {
  certificate: Certificate;
  logged: boolean;
  logError: string | null;
}) {
  const [check, setCheck] = useState<SignatureCheck>({
    state: "checking",
    detail: "verifying in the browser",
  });

  useEffect(() => {
    let live = true;
    setCheck({ state: "checking", detail: "verifying in the browser" });
    verifySignature(certificate).then((result) => {
      if (live) setCheck(result);
    });
    return () => {
      live = false;
    };
  }, [certificate]);

  const payload = certificate.payload as Record<string, any>;
  const layers = (payload.layers_enabled ?? {}) as Record<string, boolean>;
  const offLayers = Object.entries(layers)
    .filter(([, on]) => !on)
    .map(([name]) => name);

  return (
    <div className="cert">
      <div className="cert-h">
        <span>Verdict certificate</span>
        <b>{certificate.algorithm}</b>
        <span className="right">
          <span className="sigstate" data-state={check.state}>
            {check.state === "valid" ? "✓ " : check.state === "invalid" ? "✗ " : ""}
            {LABEL[check.state]}
          </span>
        </span>
      </div>
      <div className="cert-b">
        <p className="small">
          {check.state === "valid" ? (
            <>
              This verdict was signed the moment it was created, and the signature was just
              checked <b>in your browser</b> against the public key carried inside the
              certificate — not by asking our server to vouch for itself. Alter one character
              of the payload and this turns red.
            </>
          ) : (
            check.detail
          )}
        </p>

        <div className="cert-row">
          <span className="l">Key</span>
          <span>{certificate.key_id}</span>
        </div>
        <div className="cert-row">
          <span className="l">Issued</span>
          <span>{certificate.issued_at}</span>
        </div>
        <div className="cert-row">
          <span className="l">Binds to</span>
          <span>sha256:{String(payload.output_sha256 ?? "").slice(0, 32)}…</span>
        </div>
        <div className="cert-row">
          <span className="l">Payload</span>
          <span>sha256:{certificate.payload_sha256.slice(0, 32)}…</span>
        </div>
        <div className="cert-row">
          <span className="l">Signature</span>
          <span>{certificate.signature.slice(0, 44)}…</span>
        </div>
        <div className="cert-row">
          <span className="l">Audit log</span>
          <span>
            {logged
              ? "stored, replayable by trace id"
              : `not stored — ${logError ?? "audit log unavailable"}`}
          </span>
        </div>

        {offLayers.length > 0 ? (
          <div className="notice" data-soft="true">
            <span className="tag">Rig</span>
            <span>
              This certificate records that <b>{offLayers.join(", ")}</b> {offLayers.length === 1 ? "was" : "were"}{" "}
              switched off for this run. A verdict produced with a validator disabled must not
              be indistinguishable from one produced with everything running.
            </span>
          </div>
        ) : null}

        <div className="chipset">
          <button className="btn tiny ghost" type="button" onClick={() => downloadCertificate(certificate)}>
            Download certificate
          </button>
        </div>
        <p className="small">
          The certificate is self-contained: it carries its own public key and canonical
          payload, so an auditor can verify it offline, years later, without our servers being
          reachable.
        </p>
      </div>
    </div>
  );
}
