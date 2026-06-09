"""WebSocket $connect Lambda authorizer.

Validates Cognito JWT tokens passed as a query string parameter.
WebSocket APIs don't support Authorization headers from browsers,
so the token is passed as ?token=<jwt>.

Uses python-jose for full cryptographic signature verification against
Cognito's JWKS public keys.

Origin lockdown: when ORIGIN_VERIFY_SECRET is set (staging/prod), the
authorizer also verifies the X-Origin-Verify header injected by CloudFront.
Requests without a valid header are denied — preventing direct WebSocket
connections to the raw API Gateway endpoint.
"""
import hmac
import json
import os
import logging
import urllib.request
import time

from jose import jwt, JWTError

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

COGNITO_USER_POOL_ID = os.environ['COGNITO_USER_POOL_ID']
COGNITO_CLIENT_ID = os.environ['COGNITO_CLIENT_ID']
AWS_REGION = os.environ.get('AWS_REGION', 'us-west-2')
COGNITO_ISSUER = (
    f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
)

# Cache JWKS keys
_jwks_cache = None
_jwks_cache_time = 0
JWKS_CACHE_TTL = 3600  # 1 hour

# Origin lockdown: in staging/prod, CloudFront injects X-Origin-Verify header.
ORIGIN_VERIFY_SECRET = os.environ.get('ORIGIN_VERIFY_SECRET', '')


def get_jwks():
    """Fetch and cache Cognito JWKS public keys."""
    global _jwks_cache, _jwks_cache_time

    if _jwks_cache and (time.time() - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    jwks_url = f"{COGNITO_ISSUER}/.well-known/jwks.json"
    with urllib.request.urlopen(jwks_url, timeout=5) as resp:
        _jwks_cache = json.loads(resp.read())
        _jwks_cache_time = time.time()

    return _jwks_cache


def _get_signing_key(token):
    """Find the JWKS key matching the token's kid header."""
    import base64

    # Decode header without verification to get kid
    header_segment = token.split('.')[0]
    header_segment += '=' * (4 - len(header_segment) % 4)
    header = json.loads(base64.urlsafe_b64decode(header_segment))
    kid = header.get('kid')

    if not kid:
        raise ValueError('Token header missing kid')

    jwks = get_jwks()
    for key in jwks.get('keys', []):
        if key['kid'] == kid:
            return key

    raise ValueError(f'Public key not found for kid: {kid}')


def validate_token(token):
    """Validate a Cognito JWT token with full signature verification.

    Verifies:
    - Cryptographic signature against Cognito JWKS public keys
    - Issuer matches our Cognito User Pool
    - Audience matches our app client ID
    - Token is not expired
    - token_use is 'id'

    Returns the decoded payload if valid, raises on failure.
    """
    signing_key = _get_signing_key(token)

    # Verify signature and decode claims
    payload = jwt.decode(
        token,
        signing_key,
        algorithms=['RS256'],
        audience=COGNITO_CLIENT_ID,
        issuer=COGNITO_ISSUER,
        options={
            'verify_at_hash': False,  # ID tokens may not have at_hash
        },
    )

    # Additional check: token_use must be 'id'
    token_use = payload.get('token_use')
    if token_use != 'id':
        raise ValueError(f"Invalid token_use: {token_use}")

    return payload


def generate_policy(principal_id, effect, resource, context=None):
    """Generate an IAM policy document for API Gateway."""
    policy = {
        'principalId': principal_id,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Action': 'execute-api:Invoke',
                    'Effect': effect,
                    'Resource': resource,
                }
            ],
        },
    }
    if context:
        policy['context'] = context
    return policy


def lambda_handler(event, context):
    """Authorize WebSocket $connect requests.

    Expects token in query string: ?token=<jwt>
    Verifies X-Origin-Verify header when ORIGIN_VERIFY_SECRET is set (staging/prod).
    """
    logger.info('Authorizer invoked')

    try:
        # Origin lockdown: verify request came through CloudFront.
        # WebSocket API Gateway preserves original header casing in the
        # authorizer event (unlike HTTP API v2 which lowercases all keys).
        # CloudFront sends the header as "X-Origin-Verify", so we normalize
        # to lowercase for a reliable lookup.
        if ORIGIN_VERIFY_SECRET:
            headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
            header_value = headers.get('x-origin-verify', '')
            if not hmac.compare_digest(header_value, ORIGIN_VERIFY_SECRET):
                logger.warning('Origin verification failed — request did not come through CloudFront')
                raise ValueError('Unauthorized')

        # Extract token from query string
        query_params = event.get('queryStringParameters') or {}
        token = query_params.get('token', '')

        if not token:
            logger.warning('No token provided')
            raise ValueError('Unauthorized')

        # Validate the token (full signature verification)
        payload = validate_token(token)

        # Extract user info for context
        user_email = payload.get('email', 'unknown')
        user_sub = payload.get('sub', 'unknown')

        logger.info(f'Authorized user: {user_email}')

        # Build the method ARN for the policy
        method_arn = event.get('methodArn', '*')

        return generate_policy(
            principal_id=user_sub,
            effect='Allow',
            resource=method_arn,
            context={
                'email': user_email,
                'sub': user_sub,
            },
        )

    except (JWTError, ValueError) as e:
        logger.warning(f'Authorization failed: {e}')
        raise Exception('Unauthorized')
    except Exception as e:
        logger.error(f'Unexpected authorizer error: {e}', exc_info=True)
        raise Exception('Unauthorized')
