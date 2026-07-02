# Deploying day-forge

Target: `dayforge.habitreward.org` on the shared habitreward DigitalOcean droplet,
behind the central Caddy that already lives in the **habit_reward** repo's compose.

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
| `SSH_USER` | e.g. `deploy` — must own `$DEPLOY_PATH` and be able to `mkdir`/`scp` there (see §3b one-time `chown`) |
| `DEPLOY_PATH` | e.g. `/home/deploy/day-forge` |
| `DJANGO_SECRET_KEY` | 50+ random chars |
| `ALLOWED_HOSTS` | `dayforge.habitreward.org` |
| `CSRF_TRUSTED_ORIGINS` | `https://dayforge.habitreward.org` |
| `CALDAV_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `TODOIST_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
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
> **All four** `GOOGLE_OAUTH_*` vars (client id, client secret, redirect uri, token
> key) are **required** for a `DEBUG=0` boot even if nobody connects Google
> Calendar — `gcal_sync.E001` blocks startup if any is unset/malformed (a
> stricter divergence from CalDAV/Todoist, whose checks cover only the
> encryption key). A Google-less prod env must still set all four.

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
Push to `main` (or run the **Deploy** workflow manually). CI tests → builds →
pushes to GHCR → SSHes in → writes `.env` → `docker compose pull && up -d` →
health-checks `https://dayforge.habitreward.org/accounts/login/`.

## Rollback

On the droplet, pin the previous image tag in `.env` (`DOCKER_IMAGE=...`) and run
`docker compose pull && docker compose up -d`.

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
