# home-agent

A self-hosted Hermes Agent deployment for a single user's home network.
One container runs the agent; a local HTTP bridge forwards **GroupMe**
messages to it and streams cron/background output back as GroupMe notifications.
Search is provided by a bundled SearXNG instance.

---

## Architecture

```
           ┌──────────────┐        8443 (bridge, loopback)      ┌───────────────┐
  You →    │ hermes-agent │ ←── POST /notify {text} ───────────→ │ bridge.py     │
  GroupMe   │  (Hermes)    │                                     │ (groupme-… )   │
           └──────┬───────┘                                      └───────────────┘
                  │ runs `hermes gateway` + `python3 /bridge/bridge.py &`
                  │
        8443 mapped to host for the Tailscale dashboard
```

- **hermes** — the Hermes Agent container. Builds from `Dockerfile`, boots
  `hermes gateway run`, and (via the entrypoint) installs Git/GitHub auth once.
- **searxng** — a hardened self-hosted search engine at `127.0.0.1:8888`.
- **bridge** — pure-Python outbound-only notifier. Accepts JSON posts on
  `/notify`, forwards to GroupMe's API, and watches cron output for alerts.

### How the round trip works

1. You send a message in GroupMe → the `groupme-webhook` path enforces the
   allowed sender/group, then queues it into Hermes.
2. Hermes replies (via Ollama / your configured provider); the reply is cleaned
  of ANSI/reasoning noise by the bridge.
3. Background/cron work that wants to reach you calls:

   ```bash
   curl -s -X POST http://127.0.0.1:8443/notify \
        -H 'Content-Type: application/json' \
        -d '{"text": "YOUR MESSAGE HERE"}'
   ```

   Loopback-only (non-local callers get `403`). See the bundled `groupme-notify`
   skill for the full guidance.

---

## Quick start

### Prerequisites

- Docker + `docker compose` (or `docker-stack`) on your host.
- A GroupMe bot you control (create one at groupme.com → "My Bots").
- An optional but recommended GitHub Personal Access Token (repo scope).

### 1. Clone and configure

```bash
git clone <this-repo> && cd home-agent
cp .env.example .env        # fill in your values
```

### 2. GroupMe bot credentials

In `.env`:

- `GROUPME_BOT_ID` — from the bot's API (check a bot message payload).
- `GROUPME_ALLOWED_GROUP_ID` — the group ID of this bot's conversation.
- `GROUPME_ALLOWED_USER_ID` — your user/group sender ID to whitelist.

### 3. GitHub auth (optional, one-time)

Pass `GITHUB_TOKEN=...` when you launch so the entrypoint logs into `gh` and
writes both `GITHUB_TOKEN` and `GH_TOKEN` into `/home/hermes/.hermes/.env`.
After this first boot, set `GITHUB_TOKEN=` in `.env` to stop re-running it.

### 4. Launch

```bash
docker compose up -d
docker compose logs -f hermes   # watch bootstrap + bridge output
```

Verify the bridge is listening:

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8443/notify -X POST \
    -H 'Content-Type: application/json' --data '{"text":"ping"}'
# expect 200 (message queued to GroupMe) — not a real reply here
```

---

## Configuration reference

| Variable                   | Required by bridge? | Purpose                                  |
|----------------------------|---------------------|------------------------------------------|
| `GITHUB_TOKEN`             | no (first boot only)| Logs into `gh`; written to Hermes `.env`. |
| `GROUPME_BOT_ID`           | yes                 | GroupMe API: who receives the message.   |
| `GROUPME_ALLOWED_GROUP_ID` | yes                 | Sender group whitelist.                  |
| `GROUPME_ALLOWED_USER_ID`  | yes                 | Allowed sender ID.                       |

### Ports

- `127.0.0.1:8443 → 8443` — GroupMe bridge (loopback inbound/outbound).
- `127.0.0.1:8888 → 8080` — SearXNG search.

---

## Project structure

```
bridge/
  bridge.py                  # GroupMe <-> Hermes HTTP bridge + cron watcher
  groupme-notify-skill.md    # Skill: how to send an outbound GroupMe alert
entrypoint.sh               # Boot-time Git/GitHub/Hermes .env setup
Dockerfile                  # python:3.11 image + Hermes/Playwright/gh/tailscale
docker-compose.yaml         # searxng + hermes services + volumes/networks
.env.example                # Template (never commit real .env)
```

## Data & volumes

| Mount                        | Purpose                                  |
|------------------------------|------------------------------------------|
| `./searxng`                  | SearXNG config + cache.                  |
| `./hermes-data`              | Persistent Hermes profile/state/skills.  |
| `./workspace`                | Agent working directory (git mounts).     |
| `./bridge`                   | Bridge source, read-only.                |

## Notes / TODOs for future work

- Consider adding an auto-provision step that derives `GROUPME_*` values or
  prompts the user instead of hand-editing `.env`.
- The `/notify` handler is intentionally loopback-only; document (or wire a
  secure) way to call it from cron/monitoring.
