/** The one seam.
 *
 *  Every screen reads and writes through this module. No component fetches directly and no
 *  component holds a URL, so swapping the backend — or putting a gateway in front of it —
 *  touches this file and nothing else.
 */

import type {
  Certificate,
  CorpusDoc,
  CorpusSummary,
  Health,
  LogRow,
  Preset,
  VerifyResponse,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (error) {
    throw new ApiError(
      `Cannot reach the verification service. ${(error as Error).message}`,
      0,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  presets: () => request<{ presets: Preset[] }>("/api/presets"),

  corpus: () =>
    request<{ summary: CorpusSummary; documents: CorpusDoc[] }>("/api/corpus"),

  verify: (body: {
    outputs: string[];
    prompt?: string | null;
    layers?: Record<string, boolean>;
    domain?: string;
  }) =>
    request<VerifyResponse>("/api/verify", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generate: (body: {
    prompt: string;
    layers?: Record<string, boolean>;
    domain?: string;
  }) =>
    request<VerifyResponse>("/api/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  log: (limit = 40) => request<{ enabled: boolean; runs: LogRow[]; counters: Record<string, number> }>(
    `/api/log?limit=${limit}`,
  ),

  trace: (traceId: string) => request<Record<string, unknown>>(`/api/trace/${traceId}`),

  /** Server-side certificate check. Only a fallback — see verifySignature below. */
  verifyCertificateRemote: (certificate: Certificate) =>
    request<{ valid: boolean; detail: string }>("/api/verify-certificate", {
      method: "POST",
      body: JSON.stringify({ certificate }),
    }),
};

// --- local signature verification -------------------------------------------

function b64uToBytes(value: string): Uint8Array {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

/** Must match app/certs.canonical_json byte for byte, or a valid signature reads as invalid.
 *  Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) produces
 *  the same bytes as this, given the payload contains no floats needing repr differences. */
function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value as Record<string, unknown>).sort();
  const parts = keys.map(
    (key) => `${JSON.stringify(key)}:${canonicalJson((value as Record<string, unknown>)[key])}`,
  );
  return `{${parts.join(",")}}`;
}

export type SignatureState = "valid" | "invalid" | "checking" | "unsupported";

export interface SignatureCheck {
  state: SignatureState;
  detail: string;
}

/** Verifies an Ed25519 certificate **in the browser**, against the public key embedded in
 *  the certificate itself.
 *
 *  This is the whole point of the signed-receipt design: asking the server whether its own
 *  signature is good proves nothing. WebCrypto has native Ed25519 in current Chrome, Safari
 *  and Firefox; where it is missing we say so rather than quietly falling back and calling
 *  it verified. */
export async function verifySignature(certificate: Certificate): Promise<SignatureCheck> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    return { state: "unsupported", detail: "WebCrypto unavailable in this browser" };
  }

  const message = new TextEncoder().encode(canonicalJson(certificate.payload));

  // The digest check is independent of the signature and catches payload edits even if the
  // signature check cannot run.
  const digest = await subtle.digest("SHA-256", message);
  const digestHex = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  if (certificate.payload_sha256 && digestHex !== certificate.payload_sha256) {
    return { state: "invalid", detail: "payload does not match its recorded digest" };
  }

  try {
    const key = await subtle.importKey(
      "raw",
      b64uToBytes(certificate.public_key) as unknown as ArrayBuffer,
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const ok = await subtle.verify(
      { name: "Ed25519" },
      key,
      b64uToBytes(certificate.signature) as unknown as ArrayBuffer,
      message as unknown as ArrayBuffer,
    );
    return ok
      ? { state: "valid", detail: `verified in-browser against ${certificate.key_id}` }
      : { state: "invalid", detail: "signature does not match this payload" };
  } catch {
    // Ed25519 missing from WebCrypto. Digest already checked above; be explicit that the
    // signature itself was not verified locally rather than implying it was.
    return {
      state: "unsupported",
      detail: "this browser's WebCrypto has no Ed25519; digest checked, signature not",
    };
  }
}

export function downloadCertificate(certificate: Certificate): void {
  const blob = new Blob([JSON.stringify(certificate, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${certificate.trace_id}.cert.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
