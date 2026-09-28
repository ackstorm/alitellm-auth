# SPDX-License-Identifier: Apache-2.0
import time

import pytest
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError

from app.oauth_as.tokens import Signer


def _pem() -> str:
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    return key.as_pem(is_private=True).decode()


def test_issue_produces_a_verifiable_rs256_token_with_the_expected_claims():
    signer = Signer(_pem())
    token = signer.issue(
        issuer="https://as.test",
        audience="alitellm",
        sub="u@x.com",
        scope="alitellm",
        client_id="c1",
        ttl=60,
    )
    claims = jwt.decode(token, signer.jwks())
    claims.validate()
    assert claims["iss"] == "https://as.test"
    assert claims["aud"] == "alitellm"
    assert claims["sub"] == "u@x.com"
    assert claims["client_id"] == "c1"
    assert claims["token_use"] == "user"
    assert claims["exp"] - claims["iat"] == 60
    assert abs(claims["iat"] - time.time()) < 5


def test_jwks_exposes_one_public_rsa_key_with_kid_and_no_private_material():
    signer = Signer(_pem())
    keys = signer.jwks()["keys"]
    assert len(keys) == 1
    key = keys[0]
    assert key["kty"] == "RSA" and key["alg"] == "RS256" and key["use"] == "sig"
    assert key["kid"] == signer.kid
    assert not {"d", "p", "q", "dp", "dq", "qi", "oth"} & key.keys()


def test_same_pem_gives_same_kid():
    pem = _pem()
    assert Signer(pem).kid == Signer(pem).kid


def _issue(signer, **kw):
    args = dict(
        issuer="https://as.test",
        audience="alitellm",
        sub="u@x.com",
        scope="alitellm",
        client_id="c1",
        ttl=60,
    )
    args.update(kw)
    return signer.issue(**args)


def test_verify_returns_the_claims_of_a_valid_token():
    signer = Signer(_pem())
    claims = signer.verify(_issue(signer), issuer="https://as.test", audience="alitellm")
    assert claims["sub"] == "u@x.com" and claims["aud"] == "alitellm"


@pytest.mark.parametrize(
    "token_kw",
    [{"ttl": -60}, {"audience": "other"}, {"issuer": "https://evil.test"}],
    ids=["expired", "wrong-aud", "wrong-iss"],
)
def test_verify_rejects_bad_claims(token_kw):
    signer = Signer(_pem())
    with pytest.raises(JoseError):
        signer.verify(_issue(signer, **token_kw), issuer="https://as.test", audience="alitellm")


def test_verify_rejects_a_token_signed_by_another_key():
    token = _issue(Signer(_pem()))
    with pytest.raises(JoseError):
        Signer(_pem()).verify(token, issuer="https://as.test", audience="alitellm")


def test_verify_rejects_hs256_signed_with_the_public_key():
    # authlib's own jwt.encode() refuses to import a PEM as an HMAC secret
    # (POSSIBLE_UNSAFE_KEYS), so the classic alg-confusion forgery is built by
    # hand here to prove OUR decode-side RS256 restriction, not authlib's
    # encode-side one — a forger who skips authlib wouldn't hit that guard.
    import base64
    import hmac
    import json

    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signer = Signer(_pem())
    public_pem = signer._key.as_pem(is_private=False)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(
        json.dumps(
            {
                "iss": "https://as.test",
                "aud": "alitellm",
                "sub": "u@x.com",
                "exp": int(time.time()) + 60,
            },
            separators=(",", ":"),
        ).encode()
    )
    signature = hmac.new(public_pem, f"{header}.{payload}".encode(), "sha256").digest()
    forged = f"{header}.{payload}.{_b64(signature)}"
    with pytest.raises(JoseError):
        signer.verify(forged, issuer="https://as.test", audience="alitellm")


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c"])
def test_verify_rejects_garbage(garbage):
    with pytest.raises(JoseError):
        Signer(_pem()).verify(garbage, issuer="https://as.test", audience="alitellm")
