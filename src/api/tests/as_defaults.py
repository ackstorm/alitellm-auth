# SPDX-License-Identifier: Apache-2.0
"""Front-door settings every test app needs.

The OAuth front door is no longer optional (app/main.py mounts it
unconditionally), so Settings refuses to build without its four secrets. Every
test factory folds AS_TEST_DEFAULTS in rather than repeating them.

The RSA key is generated ONCE at import: a 2048-bit keygen per factory call
would dominate the suite's runtime.
"""

from __future__ import annotations

from authlib.jose import JsonWebKey
from cryptography.fernet import Fernet

_SIGNING_KEY_PEM = (
    JsonWebKey.generate_key("RSA", 2048, is_private=True).as_pem(is_private=True).decode()
)
_KEY_ENCRYPTION_KEY = Fernet.generate_key().decode()

AS_TEST_DEFAULTS = {
    "as_redis_url": "memory://",
    "as_signing_key_pem": _SIGNING_KEY_PEM,
    "as_key_encryption_key": _KEY_ENCRYPTION_KEY,
    "internal_token": "test-internal-token",
}
