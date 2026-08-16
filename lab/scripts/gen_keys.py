"""Generate the Ed25519 signing identity.

Run once. Put SIGNING_SEED in .env.local and in the Vercel environment; the public key is
safe to publish and is what an auditor uses to check a certificate we issued.

    python scripts/gen_keys.py

Without a configured seed the app still signs, using an ephemeral key generated at startup —
and reports `ephemeral: true` so nobody mistakes a throwaway identity for a real one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from app.certs import b64u_encode  # noqa: E402


def main() -> None:
    seed = os.urandom(32)
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public_raw = private.public_key().public_bytes_raw()

    print("SIGNING_SEED=" + b64u_encode(seed))
    print()
    print("# public key (safe to publish)")
    print("public_key=" + b64u_encode(public_raw))
    print("key_id=ed25519:" + public_raw.hex()[:16])


if __name__ == "__main__":
    main()
