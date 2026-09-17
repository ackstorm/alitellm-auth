# SPDX-License-Identifier: Apache-2.0
import time

from authlib.jose import JsonWebKey, jwt

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
