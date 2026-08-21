import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from config import settings


PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000
ACCESS_TOKEN_PREFIX = "tf1"
ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24
AUTH_SECRET_NOT_CONFIGURED_MESSAGE = (
    "Server auth secret is not configured. Set SECRET_KEY before using authentication."
)

_UNSET_SECRET_KEYS = {
    "",
    "replace-with-random-secret-key",
    "change-this-secret-key",
    "generate-with-openssl-rand-hex-32",
}


@dataclass(frozen=True)
class TokenPayload:
    user_id: int
    email: str
    expires_at: int
    token_version: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str, *, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    if iterations <= 0:
        raise ValueError("Password hash iterations must be positive")

    salt = secrets.token_urlsafe(24)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    encoded_digest = _base64url_encode(digest)
    return f"{PASSWORD_HASH_ALGORITHM}${iterations}${salt}${encoded_digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except (ValueError, AttributeError):
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM or iterations <= 0:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(_base64url_encode(actual_digest), expected_digest)


def create_access_token(
    user_id: int,
    email: str,
    *,
    token_version: int = 0,
    now: int | None = None,
) -> str:
    secret_key = _require_secret_key()
    issued_at = int(now if now is not None else time.time())
    payload = {
        "sub": str(user_id),
        "email": normalize_email(email),
        "ver": int(token_version),
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_TTL_SECONDS,
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _sign(encoded_payload, secret_key)
    return f"{ACCESS_TOKEN_PREFIX}.{encoded_payload}.{signature}"


def verify_access_token(token: str, *, now: int | None = None) -> TokenPayload:
    secret_key = _require_secret_key()

    try:
        prefix, encoded_payload, signature = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("Invalid access token") from exc

    if prefix != ACCESS_TOKEN_PREFIX:
        raise ValueError("Invalid access token")

    expected_signature = _sign(encoded_payload, secret_key)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Invalid access token")

    try:
        payload = json.loads(_base64url_decode(encoded_payload))
        user_id = int(payload["sub"])
        email = normalize_email(str(payload["email"]))
        token_version = int(payload["ver"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid access token") from exc

    current_time = int(now if now is not None else time.time())
    if expires_at <= current_time:
        raise ValueError("Access token expired")

    return TokenPayload(
        user_id=user_id,
        email=email,
        expires_at=expires_at,
        token_version=token_version,
    )


def is_secret_key_configured() -> bool:
    return settings.secret_key.strip() not in _UNSET_SECRET_KEYS


def _require_secret_key() -> str:
    secret_key = settings.secret_key.strip()
    if secret_key in _UNSET_SECRET_KEYS:
        raise RuntimeError(AUTH_SECRET_NOT_CONFIGURED_MESSAGE)
    return secret_key


def _sign(encoded_payload: str, secret_key: str) -> str:
    signature = hmac.new(
        secret_key.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(signature)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
