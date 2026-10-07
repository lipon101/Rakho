#!/usr/bin/env python3
"""Encrypted-at-rest store for deploy secrets (the Render Deploy Hook, tokens).

Why this exists
---------------
The Render Deploy Hook URL is a bearer credential: whoever holds it can deploy
the service. A GitHub token is worse --- it can push code. Both were, until now,
expected to live in a plaintext environment variable or a shell profile, which
means they end up in shell history, in ``ps`` output, in a CI log, in a backup,
or in a screenshot of someone's terminal.

This module stores them encrypted on disk instead, so that a copy of the file
--- a backup, a synced folder, a stolen laptop's disk --- is useless without the
passphrase, which is kept somewhere else entirely.

The cryptography is deliberately boring
---------------------------------------
No custom construction. AES-256-GCM (authenticated encryption: a modified
ciphertext fails to decrypt rather than decrypting to garbage) with a key
derived by scrypt (memory-hard, so a stolen file cannot be brute-forced cheaply
on a GPU). Both come from ``cryptography``, the standard, widely reviewed
library. The header is bound into the ciphertext as associated data, so an
attacker cannot downgrade the KDF parameters or swap the salt without the
decryption failing.

The key is never stored next to the ciphertext
----------------------------------------------
That is the one rule that makes encryption-at-rest worth anything, and it is
enforced rather than merely documented: :func:`assert_key_not_beside_store`
refuses to run if the passphrase file sits in the same directory as the store.
A passphrase file next to the ciphertext is a locked box with the key taped to
the lid.

Usage
-----
    # Store the hook. The value is read from the environment, never the command
    # line, because a command line lands in shell history and in ``ps``:
    export RENDER_DEPLOY_HOOK_URL='https://api.render.com/deploy/srv-...?key=...'
    python scripts/secret_store.py set --name RENDER_DEPLOY_HOOK_URL --from-env RENDER_DEPLOY_HOOK_URL
    unset RENDER_DEPLOY_HOOK_URL

    python scripts/secret_store.py list
    python scripts/secret_store.py get --name RENDER_DEPLOY_HOOK_URL
    python scripts/secret_store.py rotate
    python scripts/secret_store.py remove --name RENDER_DEPLOY_HOOK_URL

The passphrase is read from ``RAKHO_SECRET_PASSPHRASE``, or from the file named
by ``RAKHO_SECRET_PASSPHRASE_FILE``, or from ``~/.config/rakho/secret.key``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

try:  # pragma: no cover - the import itself is trivial; the fallback is tested
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover
    AESGCM = None  # type: ignore[assignment]


# ── Format constants ──────────────────────────────────────────────────────────
#: A self-describing envelope. Every field needed to decrypt is in the file, so
#: a store written today still opens after the defaults below are raised --- the
#: parameters travel with the ciphertext instead of being assumed.
FORMAT = "rakho-secret-store"
FORMAT_VERSION = 1
CIPHER = "AES-256-GCM"
KDF_NAME = "scrypt"
#: n=2**15, r=8, p=1 is the scrypt "interactive" profile: ~32 MB of memory per
#: guess, which is what makes a stolen file expensive to attack rather than
#: merely slow. Recorded in the envelope so it can be raised later without
#: invalidating existing stores.
KDF_PARAMS = {"n": 2**15, "r": 8, "p": 1, "dklen": 32}
NONCE_BYTES = 12
SALT_BYTES = 16
#: scrypt needs 128*n*r bytes; the OpenSSL default cap is 32 MB, which n=2**15
#: exceeds. Stated explicitly so the derivation does not fail on a stricter
#: build of OpenSSL.
MAXMEM = 128 * 1024 * 1024

PASSPHRASE_ENV = "RAKHO_SECRET_PASSPHRASE"
PASSPHRASE_FILE_ENV = "RAKHO_SECRET_PASSPHRASE_FILE"
NEW_PASSPHRASE_ENV = "RAKHO_SECRET_NEW_PASSPHRASE"
#: Relocates the default key file. Useful for a second environment, and for a
#: test that must be hermetic about whether a default key file exists.
KEY_FILE_ENV = "RAKHO_SECRET_KEY_FILE"
DEFAULT_STORE = Path(__file__).resolve().parents[1] / ".secrets" / "deploy.enc"
DEFAULT_KEY_FILE = Path.home() / ".config" / "rakho" / "secret.key"

# ── Canonical secret names ────────────────────────────────────────────────────
#: The names secrets are stored under. Lowercase and stable, deliberately
#: independent of the environment variable that may also carry the value: a
#: variable can be renamed, but a name already written into a store cannot, so
#: the two must not be the same string. Keeping them separate is what lets the
#: store's contents survive a rename of the variable that feeds it.
SECRET_RENDER_DEPLOY_HOOK = "render_deploy_hook"
SECRET_DATABASE_URL = "database_url"
SECRET_SENTRY_DSN = "sentry_dsn"
KNOWN_SECRETS = (SECRET_RENDER_DEPLOY_HOOK, SECRET_DATABASE_URL, SECRET_SENTRY_DSN)

#: Older key names accepted on read, so a store written before the canonical
#: names existed still opens. Read-only: new writes always use the canonical
#: name, so the store converges on one spelling instead of accumulating both.
LEGACY_ALIASES: dict[str, tuple[str, ...]] = {
    SECRET_RENDER_DEPLOY_HOOK: ("RENDER_DEPLOY_HOOK_URL",),
    SECRET_DATABASE_URL: ("DATABASE_URL",),
    SECRET_SENTRY_DSN: ("SENTRY_DSN",),
}

REDACTED = "***REDACTED***"


class SecretStoreError(RuntimeError):
    """A store operation failed in a way the caller must not paper over."""


# ── Redaction ─────────────────────────────────────────────────────────────────
#: Credential shapes worth scrubbing even when the value is not in the store ---
#: a token pasted into a log by some other tool is still a leak. These are
#: deliberately anchored on the issuer's own prefix so they cannot match prose.
_SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"ghu_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    # A Render deploy hook, with or without its key query parameter.
    re.compile(r"https://api\.render\.com/deploy/srv-[A-Za-z0-9]+(?:\?key=[A-Za-z0-9_-]+)?"),
)


def redact(text: str, extra_values: tuple[str, ...] = ()) -> str:
    """Return ``text`` with any credential replaced by ``***REDACTED***``.

    Two layers, because they catch different mistakes. ``extra_values`` scrubs
    the exact secrets this process is holding --- the case where a traceback
    quotes the URL it was given. The patterns scrub credentials that were never
    in this process at all, which is the case a value-only scrubber misses.

    Longest values are replaced first so that a secret which contains another
    secret is not half-replaced, leaving a recognisable fragment behind.
    """
    if not text:
        return text
    for value in sorted((v for v in extra_values if v and len(v) >= 8), key=len, reverse=True):
        text = text.replace(value, REDACTED)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


# ── Key derivation and encryption ─────────────────────────────────────────────


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _require_crypto() -> None:
    if AESGCM is None:
        raise SecretStoreError(
            "The 'cryptography' package is not installed, so the encrypted store cannot be used. "
            "Install it (pip install cryptography) or fall back to the RENDER_DEPLOY_HOOK_URL environment variable."
        )


def derive_key(passphrase: str, salt: bytes, params: dict | None = None) -> bytes:
    """Derive the 32-byte AES key from the passphrase with scrypt.

    The parameters come from the envelope, not from the module defaults, so a
    store written with older parameters still opens after the defaults change.
    """
    params = params or KDF_PARAMS
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=int(params["n"]),
        r=int(params["r"]),
        p=int(params["p"]),
        dklen=int(params["dklen"]),
        maxmem=MAXMEM,
    )


def _header(envelope: dict) -> dict:
    """The fields that are authenticated but not encrypted."""
    return {
        "format": envelope["format"],
        "version": envelope["version"],
        "kdf": envelope["kdf"],
        "cipher": envelope["cipher"],
    }


def _aad(envelope: dict) -> bytes:
    """Associated data: the header, canonically serialised.

    Binding the header means an attacker cannot rewrite ``kdf.n`` to 2 (making
    the key cheap to brute-force) or swap the salt, because the tag would no
    longer verify. Without this, the parameters would be attacker-controlled
    input that the decryption path trusted.
    """
    return json.dumps(_header(envelope), sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_payload(payload: dict, passphrase: str) -> dict:
    """Encrypt ``payload`` into a self-describing envelope."""
    _require_crypto()
    if not passphrase:
        raise SecretStoreError("A passphrase is required to encrypt the store.")
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    envelope = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "kdf": {"name": KDF_NAME, "salt": _b64e(salt), **KDF_PARAMS},
        "cipher": CIPHER,
        "nonce": _b64e(nonce),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    key = derive_key(passphrase, salt, KDF_PARAMS)
    plaintext = json.dumps(payload, sort_keys=True).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _aad(envelope))
    envelope["ciphertext"] = _b64e(ciphertext)
    return envelope


def decrypt_payload(envelope: dict, passphrase: str) -> dict:
    """Decrypt an envelope, raising :class:`SecretStoreError` on any failure.

    A wrong passphrase and a tampered file are reported the same way on purpose:
    GCM cannot tell them apart, and pretending otherwise would be a lie. Both
    mean "this file did not decrypt", which is all the caller can act on.
    """
    _require_crypto()
    if envelope.get("format") != FORMAT:
        raise SecretStoreError(f"Not a {FORMAT} file (found format={envelope.get('format')!r}).")
    if envelope.get("cipher") != CIPHER:
        raise SecretStoreError(f"Unsupported cipher {envelope.get('cipher')!r}; this build only reads {CIPHER}.")
    try:
        salt = _b64d(envelope["kdf"]["salt"])
        nonce = _b64d(envelope["nonce"])
        ciphertext = _b64d(envelope["ciphertext"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SecretStoreError(f"The store file is malformed: {exc}") from exc
    key = derive_key(passphrase, salt, envelope["kdf"])
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _aad(envelope))
    except Exception as exc:  # noqa: BLE001 - InvalidTag and friends all mean "did not decrypt"
        raise SecretStoreError("Could not decrypt the store: the passphrase is wrong, or the file has been modified.") from exc
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecretStoreError(f"The decrypted payload is not valid JSON: {exc}") from exc


# ── Passphrase resolution ─────────────────────────────────────────────────────


def default_key_file() -> Path:
    """The default passphrase file, honouring ``RAKHO_SECRET_KEY_FILE``.

    Every caller that resolves a passphrase without an explicit file must pass
    this, or the documented "just create the default key file" path silently
    fails with "No passphrase found" --- which is exactly the bug this helper
    exists to prevent.
    """
    override = os.environ.get(KEY_FILE_ENV, "").strip()
    return Path(override) if override else DEFAULT_KEY_FILE


def _read_key_file(path: Path) -> str:
    """Read a passphrase file, refusing one that is world- or group-readable."""
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise SecretStoreError(f"Could not read the passphrase file {path}: {exc}") from exc
    if mode & 0o077:
        raise SecretStoreError(f"The passphrase file {path} is readable by other users (mode {oct(mode & 0o777)}). " f"Run: chmod 600 {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise SecretStoreError(f"The passphrase file {path} is empty.")
    return value


def assert_key_not_beside_store(store_path: Path, key_path: Path) -> None:
    """Refuse a passphrase file that lives beside the ciphertext.

    This is the rule that makes encryption-at-rest mean anything. A key stored
    next to the file it unlocks protects against nothing: anyone who can read
    one can read the other. Enforced here rather than left to a README, because
    the convenient thing to do is exactly the wrong thing.
    """
    try:
        same_dir = store_path.resolve().parent == key_path.resolve().parent
    except OSError:  # pragma: no cover - resolve() rarely fails on a real path
        return
    if same_dir:
        raise SecretStoreError(
            f"Refusing to use {key_path} as the passphrase file: it sits in the same directory as the store "
            f"({store_path.parent}). A key stored beside the ciphertext protects nothing. "
            f"Move it elsewhere, e.g. ~/.config/rakho/secret.key."
        )


def resolve_passphrase(
    passphrase_file: str | Path | None = None,
    store_path: Path | None = None,
    env_var: str = PASSPHRASE_ENV,
    file_env: str = PASSPHRASE_FILE_ENV,
    default_path: Path | None = None,
) -> str:
    """Find the passphrase, in order: env var, named file, default file.

    The environment variable wins so a CI job or a one-off command can supply it
    without touching disk. The file paths are checked against the store's own
    directory, so the "never beside the ciphertext" rule holds however the path
    was chosen.
    """
    value = os.environ.get(env_var, "").strip()
    if value:
        return value

    candidate: Path | None = None
    if passphrase_file:
        candidate = Path(passphrase_file)
    elif os.environ.get(file_env, "").strip():
        candidate = Path(os.environ[file_env].strip())
    elif default_path is not None and default_path.exists():
        candidate = default_path

    if candidate is None:
        raise SecretStoreError(f"No passphrase found. Set {env_var}, or point {file_env} at a 0600 file, " f"or create {default_path or DEFAULT_KEY_FILE}.")
    if store_path is not None:
        assert_key_not_beside_store(store_path, candidate)
    return _read_key_file(candidate)


# ── Store I/O ─────────────────────────────────────────────────────────────────


def read_store(store_path: Path, passphrase: str) -> dict:
    """Read and decrypt the store, returning ``{"secrets": {...}}``."""
    if not store_path.exists():
        raise SecretStoreError(f"No store at {store_path}. Create one with: secret_store.py set --name ... --from-env ...")
    try:
        envelope = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretStoreError(f"Could not read the store {store_path}: {exc}") from exc
    payload = decrypt_payload(envelope, passphrase)
    if not isinstance(payload, dict) or not isinstance(payload.get("secrets"), dict):
        raise SecretStoreError(f"The store {store_path} decrypted but does not contain a 'secrets' mapping.")
    return payload


def write_store(store_path: Path, payload: dict, passphrase: str) -> None:
    """Encrypt and write the store, atomically and with 0600 permissions.

    Written to a temporary file in the same directory and then renamed, so a
    crash mid-write cannot leave a truncated store that no longer decrypts ---
    which would lose every secret in it. The mode is set before the rename, so
    the file is never briefly world-readable.
    """
    envelope = encrypt_payload(payload, passphrase)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = store_path.with_suffix(store_path.suffix + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, store_path)
    except OSError as exc:
        raise SecretStoreError(f"Could not write the store {store_path}: {exc}") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # pragma: no cover
                pass


def load_secret(name: str, store_path: Path | None = None, passphrase: str | None = None) -> str | None:
    """Return one secret from the store, or ``None`` if the store is absent.

    ``None`` for a missing store is deliberate: it is what lets the deploy
    script fall back to the environment variable without treating "not set up
    yet" as an error. A store that exists but cannot be decrypted raises, because
    that is a real problem the operator must see rather than silently bypass.
    """
    store_path = store_path or DEFAULT_STORE
    if not store_path.exists():
        return None
    if passphrase is None:
        passphrase = resolve_passphrase(store_path=store_path, default_path=default_key_file())
    payload = read_store(store_path, passphrase)
    value = payload["secrets"].get(name)
    return value if isinstance(value, str) and value else None


def load_secret_with_aliases(name: str, store_path: Path | None = None, passphrase: str | None = None) -> str | None:
    """Load ``name``, falling back to its legacy spellings.

    The canonical name is tried first. The aliases exist only so a store written
    before the canonical names were introduced keeps working; nothing writes
    them any more, so a store converges on the canonical spelling rather than
    accumulating both. Returns ``None`` when the store is absent, exactly like
    :func:`load_secret`, so the caller's env-var fallback still works.
    """
    store_path = store_path or DEFAULT_STORE
    if not store_path.exists():
        return None
    if passphrase is None:
        passphrase = resolve_passphrase(store_path=store_path, default_path=default_key_file())
    payload = read_store(store_path, passphrase)
    secrets = payload["secrets"]
    for candidate in (name, *LEGACY_ALIASES.get(name, ())):
        value = secrets.get(candidate)
        if isinstance(value, str) and value:
            return value
    return None


# ── CLI ───────────────────────────────────────────────────────────────────────


def _resolve_cli_passphrase(args: argparse.Namespace, store: Path) -> str:
    """The passphrase for a CLI invocation, including the default key file.

    The default file (``~/.config/rakho/secret.key``) is passed explicitly here.
    Without it the CLI would only ever look at the environment or an explicit
    ``--passphrase-file``, so the documented "just create the default key file"
    path would fail with "No passphrase found" --- the store would be unusable
    in exactly the setup the README recommends.
    """
    return resolve_passphrase(args.passphrase_file, store, default_path=default_key_file())


def _cmd_set(args: argparse.Namespace) -> int:
    if args.from_env:
        value = os.environ.get(args.from_env, "")
        if not value:
            print(f"error: environment variable {args.from_env} is empty or unset.", file=sys.stderr)
            return 2
    else:
        value = sys.stdin.read().strip()
        if not value:
            print("error: no value on stdin.", file=sys.stderr)
            return 2

    store = _store_from_args(args)
    passphrase = _resolve_cli_passphrase(args, store)
    if store.exists():
        payload = read_store(store, passphrase)
    else:
        payload = {"secrets": {}}
    payload["secrets"][args.name] = value
    write_store(store, payload, passphrase)
    print(f"Stored {args.name} in {store} (encrypted, {len(payload['secrets'])} secret(s) total).")
    return 0


def _cmd_get(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    passphrase = _resolve_cli_passphrase(args, store)
    payload = read_store(store, passphrase)
    value = payload["secrets"].get(args.name)
    if value is None:
        print(f"error: no secret named {args.name} in {store}.", file=sys.stderr)
        return 1
    # The value goes to stdout so it can be piped; the warning goes to stderr so
    # it never contaminates the value.
    print(f"# {args.name} (handle as a credential; do not paste into a ticket or a chat)", file=sys.stderr)
    print(value)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    passphrase = _resolve_cli_passphrase(args, store)
    payload = read_store(store, passphrase)
    names = sorted(payload["secrets"])
    if not names:
        print(f"{store} holds no secrets.")
        return 0
    print(f"{store} holds {len(names)} secret(s):")
    for name in names:
        print(f"  - {name}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    store = _store_from_args(args)
    passphrase = _resolve_cli_passphrase(args, store)
    payload = read_store(store, passphrase)
    if args.name not in payload["secrets"]:
        print(f"error: no secret named {args.name} in {store}.", file=sys.stderr)
        return 1
    del payload["secrets"][args.name]
    write_store(store, payload, passphrase)
    print(f"Removed {args.name} from {store} ({len(payload['secrets'])} secret(s) left).")
    return 0


def _cmd_rotate(args: argparse.Namespace) -> int:
    """Re-encrypt the store under a new passphrase.

    Rotation is a re-encryption, not a re-keying of the same ciphertext: a fresh
    salt and nonce are generated, so the old ciphertext cannot be compared with
    the new one to confirm a guess. The old passphrase is required, which is what
    makes this safe to run --- it cannot be used to overwrite a store the caller
    cannot already read.
    """
    store = _store_from_args(args)
    old = resolve_passphrase(args.passphrase_file, store)
    payload = read_store(store, old)

    new = os.environ.get(NEW_PASSPHRASE_ENV, "").strip()
    if not new and args.new_passphrase_file:
        new = _read_key_file(Path(args.new_passphrase_file))
    if not new:
        print(
            f"error: set {NEW_PASSPHRASE_ENV} (or pass --new-passphrase-file) to the new passphrase.",
            file=sys.stderr,
        )
        return 2
    if new == old:
        print("error: the new passphrase is identical to the old one; nothing to rotate.", file=sys.stderr)
        return 2

    write_store(store, payload, new)
    print(f"Rotated {store}: re-encrypted {len(payload['secrets'])} secret(s) under a new passphrase.")
    return 0


def default_store_path() -> Path:
    """The store path, honouring ``RAKHO_SECRET_STORE`` when it is set.

    The environment variable is consulted here, not only in the deploy script,
    so the CLI and the deploy path can never disagree about which store they
    mean. A CLI that wrote to the default while the deploy script read from the
    override would look like it worked and deploy nothing.
    """
    override = os.environ.get("RAKHO_SECRET_STORE", "").strip()
    return Path(override) if override else DEFAULT_STORE


def _store_from_args(args: argparse.Namespace) -> Path:
    """The store path for a CLI invocation: the flag, else the env var, else the default."""
    return Path(args.store) if args.store else default_store_path()


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--store", default="", help=f"Path to the encrypted store (default: RAKHO_SECRET_STORE or {DEFAULT_STORE}).")
    parent.add_argument("--passphrase-file", default="", help="File holding the current passphrase (0600).")

    parser = argparse.ArgumentParser(description="Encrypted-at-rest store for deploy secrets.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", parents=[parent], help="Add or update a secret.")
    p_set.add_argument("--name", required=True)
    p_set.add_argument("--from-env", default="", help="Read the value from this environment variable (preferred).")
    p_set.set_defaults(func=_cmd_set)

    p_get = sub.add_parser("get", parents=[parent], help="Print one secret to stdout.")
    p_get.add_argument("--name", required=True)
    p_get.set_defaults(func=_cmd_get)

    p_list = sub.add_parser("list", parents=[parent], help="List secret names (never values).")
    p_list.set_defaults(func=_cmd_list)

    p_rm = sub.add_parser("remove", parents=[parent], help="Delete a secret.")
    p_rm.add_argument("--name", required=True)
    p_rm.set_defaults(func=_cmd_remove)

    p_rot = sub.add_parser("rotate", parents=[parent], help="Re-encrypt under a new passphrase.")
    p_rot.add_argument("--new-passphrase-file", default="", help="File holding the new passphrase (0600).")
    p_rot.set_defaults(func=_cmd_rotate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except SecretStoreError as exc:
        # Redacted on the way out: an error message is the most likely place for
        # a credential to escape, because it is the one path nobody reviews.
        print(f"error: {redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
