# Deploy-secret hardening

How the Render Deploy Hook and the GitHub token are stored, how they are kept out
of logs and history, and what a leaked hook can actually do.

This document is the operator-facing half of the change. The code is in
`backend/scripts/secret_store.py` (the encrypted store), `backend/scripts/check_secrets.py`
(the leak scanner) and `backend/scripts/render_deploy.py` (the deploy path that reads
from the store).

---

## 1. The problem this closes

A Deploy Hook URL is a bearer credential: whoever holds it can deploy the service.
A GitHub token is worse — it can push code. Until this change both were expected to
live in a plaintext environment variable or a shell profile, which means they end up
in shell history, in `ps` output, in a CI log, in a backup, or in a screenshot of
someone's terminal.

Encryption at rest does not stop a secret being *used* — it stops a copy of the file
being *useful*. That is the specific threat it addresses: a backup, a synced folder,
a stolen laptop's disk.

---

## 2. The encrypted store

### Cryptography

Deliberately boring, because custom crypto is how this goes wrong:

| Piece | Choice | Why |
|---|---|---|
| Cipher | **AES-256-GCM** | Authenticated: a modified ciphertext fails to decrypt rather than decrypting to garbage. |
| KDF | **scrypt** (n=2¹⁵, r=8, p=1) | Memory-hard (~32 MB per guess), so a stolen file cannot be brute-forced cheaply on a GPU. |
| Library | `cryptography` | The standard, widely reviewed implementation. No hand-rolled construction. |
| Header binding | GCM associated data | The KDF parameters and salt are authenticated, so an attacker cannot rewrite `n` down to 2 to make the key cheap. |

The file is **self-describing**: every field needed to decrypt travels with the
ciphertext, so a store written today still opens after the defaults are raised.

### The one rule that makes it worth anything

**The passphrase is never stored beside the ciphertext.** A key next to the file it
unlocks protects against nothing. This is enforced in code, not just documented:
`assert_key_not_beside_store()` refuses to run if the passphrase file sits in the same
directory as the store. A passphrase file that is group- or world-readable is also
refused, with the exact `chmod 600` command in the error.

### CLI

```bash
# Store the hook. The value is read from the environment, never the command line,
# because a command line lands in shell history and in `ps`.
export RENDER_DEPLOY_HOOK_URL='<paste the hook URL>'
python scripts/secret_store.py set --name RENDER_DEPLOY_HOOK_URL --from-env RENDER_DEPLOY_HOOK_URL
unset RENDER_DEPLOY_HOOK_URL

python scripts/secret_store.py list                       # names only, never values
python scripts/secret_store.py get --name RENDER_DEPLOY_HOOK_URL
python scripts/secret_store.py rotate                     # re-encrypt under a new passphrase
python scripts/secret_store.py remove --name RENDER_DEPLOY_HOOK_URL
```

The passphrase is read from `RAKHO_SECRET_PASSPHRASE`, or the file named by
`RAKHO_SECRET_PASSPHRASE_FILE`, or `~/.config/rakho/secret.key`. The store path is
`RAKHO_SECRET_STORE` or `backend/.secrets/deploy.enc`. Both the CLI and the deploy
script honour the same variables, so they can never disagree about which store they
mean.

`rotate` re-encrypts with a **fresh salt and nonce**, so the old and new files cannot
be compared to confirm a guess. It requires the old passphrase, which is what makes it
safe: it cannot be used to overwrite a store the caller cannot already read.

### How the deploy path uses it

`render_deploy.py` resolves the hook in this order:

1. `--hook-url` (local mocks only),
2. the **encrypted store** (preferred — keeps the credential off disk in plaintext and
   out of the process environment),
3. the `RENDER_DEPLOY_HOOK_URL` environment variable (fallback, so an existing
   deployment that has not migrated yet keeps working).

A store that **exists but will not open** is not silently skipped. That is a real
problem (wrong passphrase, tampered file) and falling through to the environment would
hide it, so the run stops and says so.

---

## 3. Leak prevention

Three layers, each catching a different moment:

| Layer | Where | What it catches |
|---|---|---|
| **pre-commit hook** | `.githooks/pre-commit` | Before the secret is written to a git object — the only moment it can still be stopped cheaply. Enable once per clone: `git config core.hooksPath .githooks`. |
| **CI job** | `.github/workflows/ci.yml` → `secrets` | On every push, over every tracked file **and the full git history**. A hook can be bypassed with `--no-verify` or simply not installed; this is the guarantee. |
| **`.gitignore`** | repo root | The store, the passphrase, plaintext hook files and real `.env` files are never tracked. |

The scanner (`check_secrets.py`) matches credential **shapes** — issuer prefixes
(`ghp_`, `github_pat_`, `AKIA…`, `xox…`, `AIza…`), Render hook URLs with a real key,
and private-key headers — rather than guessing entropy in prose. It is deliberately
low-false-positive: a scanner that cries wolf gets disabled, and a disabled scanner
protects nothing. The documented placeholder `srv-XXXXXXXX?key=YYYYYYYY` is explicitly
**not** a finding.

Findings are reported **redacted** (`ghp_AbCdEf12…p6 (40 chars)`), so the scanner's own
output never becomes the leak.

### Redaction in the deploy path

`render_deploy.py` scrubs credentials from everything it prints, in two layers: the
exact values it holds (catches a traceback quoting the URL it was handed) and the
credential shapes (catches a token that was never in this process at all). The verdict
file written by `--write-markdown` is redacted on the way out too, because a verdict
file is exactly the kind of artefact that gets pasted into a report.

---

## 4. What a leaked hook can and cannot do

**It can:** trigger a deploy of the **current `main`**. That is the whole of it.

**It cannot:** read code, read the database, exfiltrate data, change the repository, or
deploy anything other than what is already on `main`. The hook is a trigger, not a
credential to the application.

That is a real but bounded blast radius. The worst case is a denial-of-service by
repeated deploys, or a deploy of a commit that is already public.

### Mitigations

- **Rotate if it was ever exposed.** Render dashboard → the `rakho-api` service →
  **Settings → Deploy Hook → Regenerate**. The old URL stops working immediately.
  Then re-store the new one with `secret_store.py set`.
- **Restrict who holds it.** It is a bearer credential: anyone with the URL can deploy.
  Treat it like a password, not like a config value.
- **Protect `main`.** Require status checks to pass and block force-push, so a leaked
  *GitHub* token cannot rewrite history or push unreviewed code. (This is a GitHub
  repository setting; it is a recommendation here, not something this change configures.)
- **Prefer the encrypted store over the environment variable**, so the credential is
  not sitting in a process environment that a crash dump or a debug endpoint might
  expose.

### Status for this conversation

**No real hook URL or GitHub token was pasted into this chat.** The only hook-shaped
strings in the repository are documentation placeholders (`srv-...?key=...`), which the
scanner correctly ignores. **No rotation is required as a result of this conversation.**
The rotation steps above are standing guidance for the day a real value is exposed.

---

## 5. Verification

All results below are from commands actually run against this repository.

| Check | Result |
|---|---|
| New tests (`inventory.tests.test_secret_store`) | **48 pass** |
| Full suite | **475 pass** (up from 424) |
| `ruff check .` | All checks passed |
| `black --check .` | 91 files unchanged |
| Plaintext in the ciphertext file | **none** (grep for the hook and its key: 0 hits) |
| Store file mode | `600` |
| Hook in script stdout/stderr | **absent** (asserted by test) |
| Hook in the verdict file | **absent** (asserted by test) |
| Git history scan | **clean** (asserted by test) |

The tests are written against the real thing rather than mocks, because a mock would
assert that a call was made while the real object asserts what the call *did*:

- **The store really encrypts** — not just round-trips. The tests assert the plaintext
  is absent from the file's bytes, that a wrong passphrase fails, that a flipped
  ciphertext bit fails, and that **downgrading the KDF cost fails** (the header is
  authenticated, so an attacker cannot make the key cheap).
- **The guards really guard** — the scanner is run against a real temporary git
  repository with a real committed-then-removed credential, because a scanner tested
  only on strings it is handed proves nothing about whether it reads git correctly.
- **The deploy script really redacts** — the hook is passed in and the script's own
  stdout and stderr are captured and searched for it.

---

## 6. One-time setup

```bash
# 1. Create the passphrase, somewhere that is NOT the store's directory.
mkdir -p ~/.config/rakho && chmod 700 ~/.config/rakho
python -c "import secrets; print(secrets.token_urlsafe(48))" > ~/.config/rakho/secret.key
chmod 600 ~/.config/rakho/secret.key

# 2. Store the hook (value from the environment, never the command line).
export RENDER_DEPLOY_HOOK_URL='<paste the hook URL>'
python backend/scripts/secret_store.py set --name RENDER_DEPLOY_HOOK_URL --from-env RENDER_DEPLOY_HOOK_URL
unset RENDER_DEPLOY_HOOK_URL

# 3. Enable the pre-commit guard in this clone.
git config core.hooksPath .githooks

# 4. Deploy and verify.
python backend/scripts/render_deploy.py --expect-commit "$(git rev-parse HEAD)"
```

For CI, save the hook as a repository secret named `RENDER_DEPLOY_HOOK_URL`
(repo → Settings → Secrets and variables → Actions). The `deploy` workflow uses it
when present and reports a skip when it is not, so a missing credential never blocks
a merge.
