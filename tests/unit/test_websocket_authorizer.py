"""Unit tests for the WebSocket $connect Lambda authorizer.

Real RS256 crypto: an RSA keypair is generated with `cryptography`, a Cognito-
shaped JWK is derived from it, and tokens are minted and verified for real. No
network and no mocking of the verification itself — `get_jwks` is patched to
return the locally-generated JWK so the test needs no Cognito.
"""

import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import jwt
from jwt.algorithms import RSAAlgorithm

import os

# The authorizer reads Cognito config from the environment at import time, so
# these must be set before importing it. The token claims below reuse the
# module's resolved COGNITO_CLIENT_ID / COGNITO_ISSUER, so they always match.
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-west-2_testpool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client-id")
os.environ.setdefault("AWS_REGION", "us-west-2")

from websocket_handlers import authorizer  # noqa: E402

KID = "test-key-1"


@pytest.fixture(scope="module")
def rsa_key():
    """A real RSA-2048 private key for signing test tokens."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwk(rsa_key):
    """Cognito-shaped public JWK for the test key."""
    pub = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    pub.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return pub


@pytest.fixture(autouse=True)
def _patch_jwks(monkeypatch, jwk):
    """Serve the locally-generated JWK instead of fetching Cognito's."""
    monkeypatch.setattr(authorizer, "get_jwks", lambda: {"keys": [jwk]})


def _make_token(signing_key, *, kid: str = KID, **overrides) -> str:
    """Mint an RS256 JWT with valid Cognito ID-token claims, overridable."""
    now = int(time.time())
    claims = {
        "sub": "user-123",
        "email": "user@example.com",
        "aud": authorizer.COGNITO_CLIENT_ID,
        "iss": authorizer.COGNITO_ISSUER,
        "token_use": "id",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, signing_key, algorithm="RS256", headers=headers)


class TestValidateToken:
    def test_valid_id_token_returns_payload(self, rsa_key):
        payload = authorizer.validate_token(_make_token(rsa_key))
        assert payload["sub"] == "user-123"
        assert payload["email"] == "user@example.com"

    def test_expired_token_rejected(self, rsa_key):
        past = int(time.time()) - 3600
        token = _make_token(rsa_key, iat=past, exp=past + 10)
        with pytest.raises(jwt.PyJWTError):
            authorizer.validate_token(token)

    def test_wrong_audience_rejected(self, rsa_key):
        with pytest.raises(jwt.PyJWTError):
            authorizer.validate_token(_make_token(rsa_key, aud="some-other-client"))

    def test_wrong_issuer_rejected(self, rsa_key):
        with pytest.raises(jwt.PyJWTError):
            authorizer.validate_token(_make_token(rsa_key, iss="https://evil.example.com"))

    def test_non_id_token_use_rejected(self, rsa_key):
        # token_use is checked after signature/claims verification.
        with pytest.raises(ValueError, match="Invalid token_use"):
            authorizer.validate_token(_make_token(rsa_key, token_use="access"))

    def test_tampered_signature_rejected(self):
        # Signed by a different key but advertising the JWKS kid: the real public
        # key won't verify the forged signature.
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(jwt.PyJWTError):
            authorizer.validate_token(_make_token(attacker_key))

    def test_missing_kid_rejected(self, rsa_key):
        with pytest.raises(ValueError, match="kid"):
            authorizer.validate_token(_make_token(rsa_key, kid=None))

    def test_unknown_kid_rejected(self, rsa_key):
        with pytest.raises(ValueError, match="Public key not found"):
            authorizer.validate_token(_make_token(rsa_key, kid="nonexistent"))


class TestLambdaHandler:
    def test_valid_token_returns_allow(self, rsa_key):
        event = {
            "queryStringParameters": {"token": _make_token(rsa_key)},
            "methodArn": "arn:aws:execute-api:us-west-2:123:api/$connect",
        }
        resp = authorizer.lambda_handler(event, None)
        assert resp["principalId"] == "user-123"
        assert resp["policyDocument"]["Statement"][0]["Effect"] == "Allow"
        assert resp["context"]["email"] == "user@example.com"

    def test_missing_token_denies(self):
        with pytest.raises(Exception, match="Unauthorized"):
            authorizer.lambda_handler({"queryStringParameters": {}}, None)

    def test_malformed_token_denies(self):
        with pytest.raises(Exception, match="Unauthorized"):
            authorizer.lambda_handler({"queryStringParameters": {"token": "not.a.jwt"}}, None)

    def test_origin_verify_missing_header_denies(self, rsa_key, monkeypatch):
        monkeypatch.setattr(authorizer, "ORIGIN_VERIFY_SECRET", "s3cret")
        event = {"queryStringParameters": {"token": _make_token(rsa_key)}, "headers": {}}
        with pytest.raises(Exception, match="Unauthorized"):
            authorizer.lambda_handler(event, None)

    def test_origin_verify_valid_header_allows(self, rsa_key, monkeypatch):
        monkeypatch.setattr(authorizer, "ORIGIN_VERIFY_SECRET", "s3cret")
        event = {
            "queryStringParameters": {"token": _make_token(rsa_key)},
            "headers": {"X-Origin-Verify": "s3cret"},
            "methodArn": "arn:aws:execute-api:us-west-2:123:api/$connect",
        }
        resp = authorizer.lambda_handler(event, None)
        assert resp["policyDocument"]["Statement"][0]["Effect"] == "Allow"
