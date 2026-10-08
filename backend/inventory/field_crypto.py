"""Reversible encryption for the few profile fields that must stay readable.

Only one field qualifies today: the drug licence number, which the owner may
view, edit and export, and which an admin must compare against a DGDA record —
so a hash will not do. Everything else the privacy layer stores is either not
sensitive (dropdown answers) or is meant to be aggregate-only (analytics).

Design decisions worth stating once:

* **AES-256-GCM**, not a hand-rolled scheme: authenticated encryption means a
  tampered ciphertext fails loudly instead of decrypting to garbage that then
  gets displayed as a licence number.
* **Key derivation, not a key setting.** The data key is
  ``HMAC-SHA256(PROFILE_ENCRYPTION_KEY or SECRET_KEY, "rakho...")``, so a
  deployment gets real encryption with no new secret to lose, while an operator
  who wants an independent key can set ``PROFILE_ENCRYPTION_KEY`` and rotate it
  without touching Django's ``SECRET_KEY`` (which rotates far more often for
  unrelated reasons — each such rotation would otherwise silently orphan every
  stored licence number).
* **Purpose-bound (AAD).** The field name is authenticated along with the
  ciphertext, so a value written for ``license_no`` cannot be copied into a
  different encrypted column and be accepted there.
* **Versioned prefix** (``v1:``) so a future scheme can be introduced without
  guessing at the format of existing rows.

Ciphertext format: ``v1:<base64url(nonce || ciphertext || tag)>``.
"""

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

VERSION_PREFIX = "v1:"
_NONCE_BYTES = 12  # GCM standard nonce length
_KEY_BYTES = 32  # AES-256


class FieldDecryptError(ValueError):
    """Raised when stored ciphertext cannot be authenticated.

    The realistic causes are a rotated ``PROFILE_ENCRYPTION_KEY`` or manual
    database surgery. Both are operational problems, so the error message says
    so rather than pretending the row is simply missing.
    """


def _derive_key() -> bytes:
    """The 32-byte data key, stable for a given setting/secret."""
    secret = getattr(settings, "PROFILE_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    if not secret:
        raise FieldDecryptError("No PROFILE_ENCRYPTION_KEY or SECRET_KEY is configured; cannot encrypt profile fields.")
    digest = hmac.new(str(secret).encode("utf-8"), b"rakho.profile-field.v1", hashlib.sha256).digest()
    return digest[:_KEY_BYTES]


def encrypt_field(purpose: str, plaintext: str) -> str:
    """Encrypt ``plaintext`` for one named field. Empty stays empty.

    Returning "" for "" (rather than an encrypted empty string) keeps
    "no licence on file" distinguishable from a stored value and keeps the
    column small: a blank answer from a skipped question writes no ciphertext.
    """
    if plaintext == "":
        return ""
    # A fresh random nonce per encryption; GCM's security depends on it never
    # repeating under the same key, so it comes from the OS CSPRNG, not a
    # counter.
    nonce = os.urandom(_NONCE_BYTES)
    aad = purpose.encode("utf-8")
    ciphertext = AESGCM(_derive_key()).encrypt(nonce, plaintext.encode("utf-8"), aad)
    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return VERSION_PREFIX + token


def decrypt_field(purpose: str, token: str) -> str:
    """Reverse :func:`encrypt_field`. Returns "" for an empty column.

    Raises :class:`FieldDecryptError` on a bad key, tampering, or a format the
    app cannot recognise — never silently returns partial data.
    """
    if not token:
        return ""
    if not token.startswith(VERSION_PREFIX):
        raise FieldDecryptError(f"Stored value for '{purpose}' is not in the expected format (missing {VERSION_PREFIX!r}).")
    raw = token[len(VERSION_PREFIX) :]
    try:
        blob = base64.urlsafe_b64decode(raw.encode("ascii"))
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        if len(nonce) != _NONCE_BYTES or not ciphertext:
            raise ValueError("truncated")
        aad = purpose.encode("utf-8")
        plaintext = AESGCM(_derive_key()).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError, UnicodeEncodeError) as exc:
        raise FieldDecryptError(
            f"Could not decrypt '{purpose}': the ciphertext is corrupt or the encryption key has changed. "
            "Check PROFILE_ENCRYPTION_KEY / SECRET_KEY against the value in force when the row was written."
        ) from exc
    return plaintext.decode("utf-8")
