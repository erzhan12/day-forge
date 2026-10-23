# Deploying day-forge

Target: `dayforge.habitreward.org` on the shared habitreward DigitalOcean droplet,
behind the central Caddy that already lives in the **habit_reward** repo's compose.

The production image starts `day_forge.asgi:application` with uvicorn. The Deploy workflow calls `.github/workflows/ci.yml` before image build and push. That reusable workflow runs backend lint and tests, frontend type checking and tests, a production build, a production dependency audit, and the SSH host-key pinning check. The Docker entrypoint applies existing migrations and collects static files on each start; it does not create migrations. Run `make makemigrations` during development when models change and include the resulting migration files in the image.

## First deploy order (blocking)

Complete **before** expecting a green CI health-check:

1. DNS A record (`dayforge` → droplet IP)
2. GitHub Actions secrets (below)
3. Droplet firewall + **DOCKER-USER** iptables (restrict public `:8006`; ufw alone is insufficient)
4. **Bind-mount ownership** — `sudo chown -R 1000:1000 "$DEPLOY_PATH/data" "$DEPLOY_PATH/staticfiles"` (container uid `app` = 1000; required for SQLite + collectstatic)
5. **Central Caddy block** in habit_reward + reload (§4 below)
6. Push to `main` or run **Deploy** workflow manually

Steps 1–5 are required: the workflow's HTTPS probe hits Caddy, not the app port
directly. §3b bind-mount ownership is a **one-time** host prep step before first deploy.

## One-time setup

### 1. DNS (Namecheap)
Add an **A record**: host `dayforge` → the droplet's public IP. (Subdomain of
`habitreward.org`, so it inherits the zone.)

### 2. GitHub Actions secrets (repo → Settings → Secrets → Actions)
| Secret | Example / note |
|---|---|
| `SSH_PRIVATE_KEY` | deploy key for the droplet |
| `SERVER_HOST` | droplet public IP |
| `SSH_KNOWN_HOSTS` | verified pinned SSH host key(s), keyed by the exact `SERVER_HOST` value |
| `SSH_USER` | e.g. `deploy` — must own `$DEPLOY_PATH` and be able to `mkdir`/`scp` there (see §3b one-time `chown`) |
| `DEPLOY_PATH` | e.g. `/home/deploy/day-forge` |
| `DJANGO_SECRET_KEY` | 50+ random chars |
| `ALLOWED_HOSTS` | `dayforge.habitreward.org` |
| `CSRF_TRUSTED_ORIGINS` | `https://dayforge.habitreward.org` |
| `CALDAV_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `TODOIST_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HABITICA_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HABITICA_CLIENT_ID` | maintainer Habitica user ID for the `x-client` header (`{HABITICA_CLIENT_ID}-DayForge`) |
| `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS` | external task + calendar background refresh interval in seconds; default `60`, set `0` to disable |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` / `GOOGLE_OAUTH_REDIRECT_URI` | from the Google Cloud console OAuth (Web) client; redirect URI = `https://dayforge.habitreward.org/api/calendar/google/callback/` |
| `GOOGLE_OAUTH_TOKEN_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `LLM_API_KEY` | OpenRouter key |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | OpenRouter model id (command/chat) |
| `LLM_DRAFT_MODEL` | OpenRouter model id (draft) |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | admin login — `$` and `'` are fine (CI writes single-quoted `.env` with `\'` escaping) |

> `CALDAV_ENCRYPTION_KEY` is **required** for a `DEBUG=0` boot even if nobody uses
> Apple Calendar (`calendar_sync.E001` blocks startup otherwise).
> `TODOIST_ENCRYPTION_KEY` is also **required** for a `DEBUG=0` boot even if nobody
> uses Todoist (`todoist_sync.E001` blocks startup otherwise).
> `HABITICA_ENCRYPTION_KEY` and `HABITICA_CLIENT_ID` are **required** for a
> `DEBUG=0` boot even if nobody uses Habitica (`habitica_sync.E001` blocks startup
> otherwise).
> Polling was renamed from `TODOIST_POLL_INTERVAL_SECONDS` to
> `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS`; unset env now defaults to `60`, so set
> `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS=0` explicitly to keep polling off.
> **All four** `GOOGLE_OAUTH_*` vars (client id, client secret, redirect uri, token
> key) are **required** for a `DEBUG=0` boot even if nobody connects Google
> Calendar — `gcal_sync.E001` blocks startup if any is unset/malformed (a
> stricter divergence from CalDAV/Todoist, whose checks cover only the
> encryption key). A Google-less prod env must still set all four.

#### `SSH_KNOWN_HOSTS` host-key pin

**Pin the Ed25519 key alone (recommended):** modern OpenSSH always offers it, and one
verified line is easy to inspect and rotate. Capture exactly that one key **once** to a
file, using the exact value stored in `SERVER_HOST`, and fingerprint **that same file** —
never a second live scan (re-scanning would fingerprint a different capture than the one
you paste, so an intermittent on-path attacker could poison the stored line while a later
clean scan passes the check):

```bash
ssh-keyscan -t ed25519 "$SERVER_HOST" > /tmp/dayforge_known_hosts   # capture ONCE, ed25519 only
ssh-keygen -lf /tmp/dayforge_known_hosts                            # fingerprint the captured file
```

Read the authoritative fingerprint **on the droplet itself** — reached via an
already-trusted SSH session or, if you have no prior trusted connection, the provider
console (DigitalOcean web console):

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Compare only the `SHA256:…` field of each fingerprint (the trailing comment differs —
the captured line is keyed by IP, the droplet's `.pub` carries a host comment — so the
full lines will not be byte-identical even for a matching key). The `SHA256:…` values
must match before you paste the **exact contents of `/tmp/dayforge_known_hosts`** (the
single verified `<ip> ssh-ed25519 AAAA...` line) into the secret. Do not capture the key
over an untrusted network and pin it without this check — that only bakes in TOFU once.

Only pin ECDSA/RSA in addition if the client might negotiate them; if you do, scan those
types **into the same file** and **verify every added line's `SHA256:` fingerprint**
against the droplet's `/etc/ssh/ssh_host_ecdsa_key.pub` / `ssh_host_rsa_key.pub` before
pasting. Never paste an unverified line — an unverified ECDSA/RSA entry captured over a
hostile network becomes a second, un-attested trust anchor, reintroducing the TOFU gap
this pin removes.

Each entry's host field must be the exact `SERVER_HOST` string used by the workflow
(the droplet IP on implicit port 22); hostname-keyed or `[host]:port` entries will not
match and will block deployment. Hashed (`ssh-keyscan -H`) entries are supported, but
plaintext IP entries are easier to inspect and rotate. Runtime `ssh-keyscan` is
forbidden in the deploy workflow.

Treat host-key rotation like `SSH_PRIVATE_KEY` rotation, in this order:

1. On the droplet, regenerate the host keys (`sudo rm /etc/ssh/ssh_host_*_key* && sudo
   ssh-keygen -A`) and **reload sshd so the new keys take effect** (`sudo systemctl
   restart ssh`) — until sshd restarts it keeps serving the *old* key from memory.
2. Recapture from a trusted machine and verify the new fingerprints (same capture-once /
   fingerprint-the-file / compare-`SHA256` procedure as above).
3. Replace the `SSH_KNOWN_HOSTS` secret with the new line(s).
4. Run the next deployment.

Between the sshd restart (step 1) and the secret update (step 3) the droplet presents a
key the pinned secret does not list, so any deploy in that window **fails closed** at
host-key verification — this is the intended safety behavior, not a bug. Keep the window
short (do steps 1–3 back to back) and avoid triggering a deploy mid-rotation.

Provision `SSH_KNOWN_HOSTS` **before the first deploy**: the deploy job's very first
remote action (the §3b `mkdir`/`chown` directory setup over SSH) already runs under the
pinned host key, so a missing pin fails the job before any droplet setup happens.

### 3. Restrict public access to `:8006` (ufw + DOCKER-USER)

The web container publishes `8006:8006` on `0.0.0.0` so the central Caddy can reach
`host.docker.internal:8006` via the Docker bridge gateway. **Do not** switch to
`127.0.0.1:8006:8006` as the primary fix — on Linux, Caddy in habit_reward's compose
reaches the host through the bridge gateway, not loopback, and localhost-only binds
break the Caddy → app path.

**UFW alone is not enough:** Docker publishes ports through iptables (`DOCKER` chain)
and traffic to `droplet-ip:8006` often bypasses ufw entirely. Keep ufw for SSH/80/443,
then add **DOCKER-USER** rules (evaluated before Docker's own ACCEPT rules):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw deny 8006/tcp        # belt-and-suspenders; pair with DOCKER-USER below
sudo ufw enable

# Allow established/related, loopback, and Docker-private-source → host :8006 (Caddy path).
# habit_reward's central Caddy runs on a Compose `br-*` bridge, NOT `docker0` — use
# source-CIDR allow (covers default bridge + user-defined compose networks).
# Drop other inbound to host :8006 (internet scanners).
sudo iptables -I DOCKER-USER 1 -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
sudo iptables -I DOCKER-USER 2 -i lo -j RETURN
sudo iptables -I DOCKER-USER 3 -s 172.16.0.0/12 -p tcp --dport 8006 -j RETURN
sudo iptables -I DOCKER-USER 4 -p tcp --dport 8006 -j DROP

# Persist across reboot (pick what the droplet already uses):
#   Debian/Ubuntu: sudo apt install -y iptables-persistent && sudo netfilter-persistent save
#   or document equivalent in habit_reward's droplet runbook.
```

**Verify from off-host** (laptop, not SSH'd into the droplet):

```bash
curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://<DROPLET_IP>:8006/accounts/login/
# Expected: timeout or connection refused — NOT 200/301 from Django.

curl -fsS -o /dev/null -w "%{http_code}\n" https://dayforge.habitreward.org/accounts/login/
# Expected: 200 — Caddy → host.docker.internal:8006 still works after the DROP rule.
```

### 3b. Bind-mount permissions

The container runs as **uid 1000** (`app`). Ensure `$DEPLOY_PATH/data` (and
`staticfiles`) are writable by that uid on the host, e.g.:

```bash
mkdir -p "$DEPLOY_PATH/data" "$DEPLOY_PATH/staticfiles"
sudo chown -R 1000:1000 "$DEPLOY_PATH/data" "$DEPLOY_PATH/staticfiles"
```

### 4. Wire the subdomain into the central Caddy (habit_reward repo)
Paste the block from `deployment/caddy/dayforge.caddy` into habit_reward's
`Caddyfile`, commit/deploy there (or edit on the droplet), then reload:
```bash
docker exec habit_reward_caddy caddy reload --config /etc/caddy/Caddyfile
```

## Deploying

Push to `main` or run the **Deploy** workflow manually. Shared CI validation must pass before the workflow builds and pushes the image to GHCR. The deploy job connects over pinned SSH, writes `.env`, then runs `docker compose pull` and `docker compose up -d`. The final job checks `https://dayforge.habitreward.org/accounts/login/`.

After the container starts, the deploy removes old local Day Forge images. It
keeps the running SHA-tagged image and the two newest SHA-tagged images for
rollback. The `latest` tag, manually named tags, and images from other apps are
left alone. Cleanup errors are logged without failing the deploy; the next
deploy retries. GHCR tags are unaffected. Check host usage with `df -h /` and
`docker system df` after deployment.

## Frontend release identity

The frontend build receives `RELEASE_VERSION` from the workflow's full Git SHA. Vite embeds it in the JS bundle and writes `.vite/release.json`; Django uses that packaged identity for Inertia and API compatibility checks. Production startup refuses missing or incomplete build assets. Runtime `.env` does not select the release identity.

For a manual image build from a clean checkout matching the chosen commit:

```sh
docker build -f deployment/docker/Dockerfile --build-arg RELEASE_VERSION=<commit-sha> -t day-forge:<commit-sha> .
```

Use the same image for backend and frontend. Keep the baked metadata directory with the image; it is read from `frontend/dist`, not the staticfiles bind mount. Content-hashed files receive immutable cache headers. Returning to an earlier image restores its identity and asset references, even while newer hashed files remain in staticfiles.

An old tab refreshes on its next Inertia navigation. A stale JSON request returns `409 frontend_outdated` before its view executes; the new UI offers Reload and warns about unsent text. The action is not repeated automatically. Legacy headerless writes are also refused. See [the local release rehearsal](../docs/FRONTEND_RELEASE_VERIFICATION.md).

## Rollback

On the droplet, pin the previous image tag in `.env` (`DOCKER_IMAGE=...`) and run
`docker compose pull && docker compose up -d`.

Check schema compatibility before returning an older image. An image rollback
does not reverse migrations or undo writes made after deployment. Do not run a
backward migration on the working database merely to match an older tag. If a
release needs database restoration, plan for writes made since the backup.

### Rolling back across the durable-chat boundary (PR #252)

Keep `ai_chatrequest` and migration `ai.0007_chatrequest` when rolling back the
image. Never reverse this migration after request identities have been used.
A pre-252 image does not implement durable request recovery, even if the table
is still present. Set `LLM_API_KEY=` for that temporary rollback and recreate the
web container. Manual schedule writes remain available; AI returns 503. Do not
retry unresolved AI turns through the old protocol. Restore the configured key
when returning to a release that supports durable request IDs, then recover the
original frozen request. The frontend-version guard rejects a new bundle's writes
against the old release, but a freshly loaded old bundle cannot enforce the new
chat contract itself.

The isolated rehearsal verifies migration 0006 → 0007, exact HTTP replay, a
different-body conflict, AI-disabled image rollback, preserved receipts and manual
writes, and replay after returning to the new image. Build an old image from
`7a86acac2b83d1ced1485292de8a0b3b222a895d` and a new image from the desired release,
using the production Dockerfile and each source commit's full `RELEASE_VERSION`.
Then run:

```sh
uv run python deployment/scripts/rehearse_chat_requests.py \
  --source-db db/day_forge.db --output-dir /tmp/day-forge-chat-rehearsal-example \
  --old-image day-forge-rehearsal:pr252-old \
  --old-version 7a86acac2b83d1ced1485292de8a0b3b222a895d \
  --new-image day-forge-rehearsal:pr252-new --new-version <new-image-commit-sha>
```

The source must be a local SQLite file. The runner backs it up without changing
it and requires a new private directory under `/tmp`. To create a real pending
migration from an already-migrated source, it reverses 0007 only in the sandbox
and only when that copied request table is empty; otherwise it refuses the run.
The copied database, secrets and logs stay private. Only sanitized `evidence.json`
belongs in the report. Containers use uvicorn, Redis and an internal network with
a fixed local AI fixture; no paid provider calls or production connections occur.
Only the proxy is exposed on `127.0.0.1:8010`. Containers stop after the run.

PR #245 adds no migration. Rollback to PR #244 retains saved writes, but that old
backend has no frontend-version API guard. Refresh open tabs before continuing
to write after returning to a pre-245 image. Two releases with the new guard
negotiate stale tabs in both directions.

### Container rehearsal on a database copy

The pending-intent boundary adds `ai.0008_pendingintent`. Keep this table when
rolling back an image. A release without `ai/pending_intents.py` cannot enforce
saved continuation scopes, even if it supports durable request IDs. Pause AI
with `LLM_API_KEY=` while running that older release, and restore the key only
after returning to compatible code. A reverse migration deletes saved intents;
it is not part of image rollback. The pending-intent change has a local schema
upgrade check and browser verification, but needs its own container/production
rehearsal after deployment. See [the report](../docs/AI_PENDING_INTENT_VERIFICATION.md).

Start Docker and build the images before running the rehearsal. GHCR images may
require separate package-read credentials; local builds use the same production
Dockerfile. These commands use PR #244, PR #245, and a second release identity
of the PR #245 source:

```sh
mkdir /tmp/day-forge-pr244-source
git archive a0fed3845f1bf01b6f50f9f0100f4355faaeec64 | tar -x -C /tmp/day-forge-pr244-source
mkdir /tmp/day-forge-pr245-source
git archive afc94f658f4f09e293bfd922fdc6aca271da8ffb | tar -x -C /tmp/day-forge-pr245-source
docker build -f /tmp/day-forge-pr244-source/deployment/docker/Dockerfile \
  -t day-forge-rehearsal:pr244 /tmp/day-forge-pr244-source
docker build -f /tmp/day-forge-pr245-source/deployment/docker/Dockerfile \
  --build-arg RELEASE_VERSION=afc94f658f4f09e293bfd922fdc6aca271da8ffb \
  -t day-forge-rehearsal:pr245 /tmp/day-forge-pr245-source
docker build -f /tmp/day-forge-pr245-source/deployment/docker/Dockerfile \
  --build-arg RELEASE_VERSION=rehearsal-compatible \
  -t day-forge-rehearsal:compatible /tmp/day-forge-pr245-source
docker pull redis:7-alpine
docker pull caddy:2-alpine
uv run python deployment/scripts/rehearse_release.py \
  --source-db db/day_forge.db --output-dir /tmp/day-forge-rehearsal-example \
  --old-image day-forge-rehearsal:pr244 \
  --new-image day-forge-rehearsal:pr245 \
  --new-version afc94f658f4f09e293bfd922fdc6aca271da8ffb \
  --compatible-image day-forge-rehearsal:compatible \
  --compatible-version rehearsal-compatible
```

Build PR #245 from its exact source when reproducing the recorded release. Do
not label later application code with that SHA. Use a new output directory under
`/tmp`; the runner refuses to overwrite one. It reads the source through SQLite's
backup API and writes only inside the private output directory. The source can
be a local database or an already-downloaded backup; it is never a production
connection.

The runner starts uvicorn with the image entrypoint, real Redis, a shared
staticfiles directory, and the production 250 MiB web memory limit. Only the
proxy is published on `127.0.0.1:8009`. The web and Redis containers use an
internal network, AI and polling are disabled, and integration keys are dummy
values. The localhost HTTP proxy supplies the HTTPS-forwarding header so the
application keeps its production cookie and redirect settings. This does not
test TLS termination; the public deployment probe covers actual HTTPS.

The checks cover legacy upgrade, compatible rollback, explicit legacy-image
rollback, authenticated writes, stale/headerless write rejection, session
continuity, Logout, asset availability, and preservation of original rows. A
separate database copy rehearses migration 0009 → 0010 and idempotent startup.
That migration exercise is independent of the image rollback.

Add `--keep-running` to inspect the sandbox in a browser. It prints the local
test login and the exact Compose cleanup command. Open its `127.0.0.1` URL to
keep browser cookies separate from a development app on `localhost`.
Without that flag, or after a failure, the runner stops its containers.
The output directory retains a
database copy and private logs: remove it when finished. Only the sanitized
`evidence.json` belongs in a report. See [the recorded rehearsal](../docs/DEPLOYMENT_REHEARSAL_PR245.md).

## Backups (manual)

Copying SQLite while the app is writing can corrupt the file. Prefer stopping
the stack or using SQLite's backup API:

```bash
# Option A: stop web, then scp
ssh <user>@<host> 'cd <DEPLOY_PATH> && docker compose stop web'
scp <user>@<host>:<DEPLOY_PATH>/data/day_forge.db ./day_forge-$(date +%F).db
ssh <user>@<host> 'cd <DEPLOY_PATH> && docker compose start web'

# Option B: online backup via Python stdlib (container running; no sqlite3 CLI in image)
# Write inside the container, copy to host /tmp, then scp — do NOT `docker cp ... -` to stdout
# (that streams a tar archive; redirecting to a .db file yields invalid SQLite).
ssh <user>@<host> 'docker exec day_forge_web python -c "
import sqlite3
from pathlib import Path
src = Path(\"/app/db/day_forge.db\")
dst = Path(\"/tmp/day_forge.db\")
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
"'
ssh <user>@<host> 'docker cp day_forge_web:/tmp/day_forge.db /tmp/day_forge-pull.db'
scp <user>@<host>:/tmp/day_forge-pull.db ./day_forge-$(date +%F).db
ssh <user>@<host> 'rm -f /tmp/day_forge-pull.db && docker exec day_forge_web rm -f /tmp/day_forge.db'
```
