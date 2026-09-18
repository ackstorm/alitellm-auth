# SPDX-License-Identifier: Apache-2.0
"""Mint and publish the front door's access tokens.

One RSA key, from AS_SIGNING_KEY_PEM, identical on every replica so the JWKS
is stable. `kid` is the RFC 7638 thumbprint, so rotating the PEM rotates the
`kid` and a verifier that caches the old JWKS refetches on the unknown `kid`.
"""

from __future__ import annotations

import secrets
import time

from authlib.jose import JsonWebKey, jwt


class Signer:
    def __init__(self, pem: str) -> None:
        self._key = JsonWebKey.import_key(pem, {"kty": "RSA"})
        self.kid = self._key.thumbprint()

    def issue(
        self,
        *,
        issuer: str,
        audience: str,
        sub: str,
        scope: str,
        client_id: str,
        ttl: int,
    ) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "kid": self.kid, "typ": "JWT"}
        claims = {
            "iss": issuer,
            "aud": audience,
            "sub": sub,
            "iat": now,
            "exp": now + ttl,
            # A broker spends a login_hint by its jti (single use); every token
            # gets one so a hint is not a special shape.
            "jti": secrets.token_urlsafe(16),
            "scope": scope,
            "client_id": client_id,
            "token_use": "user",
        }
        return jwt.encode(header, claims, self._key).decode()

    def jwks(self) -> dict:
        public = self._key.as_dict(is_private=False)
        return {"keys": [{**public, "kid": self.kid, "use": "sig", "alg": "RS256"}]}
