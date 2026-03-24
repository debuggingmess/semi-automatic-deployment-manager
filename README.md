# SADM — Server Application Deploy Manager

A single-file Python deployment manager for self-hosted Linux servers. Handles full deploy pipelines for FastAPI, Django, Node.js API, Next.js, and React projects — including rsync, dependency install, builds, systemd service management, nginx config generation, backups, rollbacks, and secret rotation.

NOTE : I made the initial version myself with git pull , rsync + directory exclusion , dependencies install , systemd restar , permission change and basic basic things ( it was perfect for my purpose ) after that i extended it using AI tested basic things but give it  a read before using.
---

## Requirements

- Python 3.8+
- Root / sudo access
- `git`, `rsync`, `systemd`
- `nginx` (optional, for reverse proxy/static config)
- `certbot` (optional, for SSL)
- `python3-venv` for Python projects
- `node` / `npm` for Node projects

---

## Installation

```bash
sudo cp sadm.py /usr/local/bin/sadm
sudo chmod +x /usr/local/bin/sadm
```

---

## Configuration

All project config lives at the top of the script. Edit the `PROJECTS` list and the path constants before first use.

### Path Constants

| Constant | Default | Purpose |
|---|---|---|
| `SRC_BASE` | `/home/linux` | Where git repos live |
| `DEPLOY_BASES` | `/srv/<type>` | Where projects are deployed to |
| `BACKUP_BASE` | `/srv/bak` | Backup root |
| `BACKUP_RETENTION` | `5` | Number of backups to keep per project |

### Adding a Project

Uncomment and fill in one of the template entries in `PROJECTS`:

```python
PROJECTS = [
    {
        "name": "my-api",           # Must match repo dir name under SRC_BASE
        "type": "fastapi",          # fastapi | django | nodeapi | nextapp | react
        "user": "fastapi",          # System user that runs the service
        "service": "my-api.service",
        "entry_point": "app.main:app",
        "port": 8000,
        "domain": "api.example.com",
        "extra_excludes": [],       # Extra rsync excludes
    },
]
```

**Django extra fields:**

```python
{
    "wsgi_module": "config.wsgi:application",
    "django_settings": "config.settings.production",
    "run_migrate": True,
    "run_collectstatic": True,
}
```

**React extra fields:**

```python
{
    "service": "",          # No service — served by nginx directly
    "port": 0,
    "build_output": "dist", # or "build" for CRA
}
```

---

## Usage

### Interactive Menu

```bash
sudo sadm
```

Launches a numbered menu covering all operations.

### CLI Flags

```bash
# Deploy a project (pulls latest from current branch)
sudo sadm --deploy my-api

# Deploy a specific branch
sudo sadm --deploy my-api --branch main

# Deploy a pinned commit
sudo sadm --deploy my-api --commit a3f9c1d

# Force deploy a non-production branch
sudo sadm --deploy my-api --branch dev --force-branch

# Rollback to last backup
sudo sadm --rollback my-api

# Show all project status
sudo sadm --status

# List configured projects
sudo sadm --list
```

---

## Supported Project Types

| Type | Runtime | Server | Build Step | Systemd Service |
|---|---|---|---|---|
| `fastapi` | Python | uvicorn | No | Yes |
| `django` | Python | gunicorn | No | Yes |
| `nodeapi` | Node | node / npm | No | Yes |
| `nextapp` | Node | npm start | Yes | Yes |
| `react` | Node | nginx (static) | Yes | No |

---

## Full Deploy Pipeline

Running a full deploy (`--deploy` or menu option 1) executes these steps in order:

1. **Backup** — rsync snapshot of current deployed dir to `BACKUP_BASE`
2. **Git pull / checkout** — fetch latest or pin to branch/commit
3. **Rsync** — sync source to deploy dir, excluding build artifacts and secrets
4. **Fix Ownership** — `chown -R user:user` on deploy dir
5. **Install Dependencies** — `pip install -r requirements.txt` (Python venv) or `npm ci` (Node)
6. **Django Migrate** *(Django only)*
7. **Django Collectstatic** *(Django only)*
8. **Build** *(Next.js / React only)* — `npm run build`
9. **Restart Service** — `systemctl restart <service>` with health check
10. **Nginx Reload** — if an nginx config exists for the project

If any step fails, you're prompted to roll back to the pre-deploy backup automatically.

---

## Menu Reference

```
 DEPLOY
  1) Full deploy              2) Deploy with branch
  3) Deploy pinned commit     4) First-time setup

 STEPS
  5) git pull                 6) git checkout branch
  7) rsync                    8) Install deps
  9) Build                   10) chown
 11) Restart service         12) Django migrate
 13) Django collectstatic

 SERVICES & NGINX
 14) Create systemd service  15) View logs
 16) Create nginx config     17) Remove nginx config

 BACKUP
 18) Create backup           19) Rollback
 20) List backups

 OTHER
 21) Rotate secret           22) Create user
 23) List users              24) Status
```

---

## First-Time Setup

Use option **4** or run the interactive menu and select a project. The setup flow will:

1. Clone the repo if it doesn't exist at `SRC_BASE/<name>`
2. Create the system user if needed
3. Rsync, install deps, run migrations/build as appropriate
4. Optionally create the systemd service unit
5. Optionally generate and enable an nginx config
6. Optionally run certbot for SSL

Ensure your `.env` file is in place at the deploy directory before starting the service.

---

## Nginx

SADM generates production-ready nginx configs with:

- Security headers (`X-Frame-Options`, `X-Content-Type-Options`, etc.)
- Rate limiting (`30r/s` default, configurable)
- gzip compression
- `proxy_pass` with keepalive upstream (for API types)
- `try_files` with SPA fallback + long-lived asset caching (for React)
- Optional certbot SSL integration

Configs are written to `/etc/nginx/sites-available/<name>` and symlinked into `sites-enabled`.

---

## Systemd Services

Generated unit files include:

- `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`
- Restart on failure with burst limiting
- `EnvironmentFile` support for `.env`
- Logging to `journald`

View logs for any project via menu option **15** or:

```bash
journalctl -u my-api.service -n 100 -f
```

---

## Backups & Rollback

Backups are rsync snapshots stored at `BACKUP_BASE/<type>/<name>/<timestamp>/`. Each backup includes a `.deploy-meta.json` with git commit, branch, timestamp, and who deployed.

The last `BACKUP_RETENTION` (default 5) backups are kept; older ones are pruned automatically.

To rollback interactively, use menu option **19**. To rollback via CLI:

```bash
sudo sadm --rollback my-api
```

---

## Secret Rotation

Option **21** lets you rotate any key in a project's `.env` file:

- Lists all keys with masked values; marks likely secrets with `*`
- Auto-generates a cryptographically random secret or accepts manual input
- Backs up `.env` before writing
- Restarts the service; auto-restores `.env` if restart fails

---

## User Management

SADM can create both human (bash shell, SSH key, home dir) and service (nologin) accounts, and manage group memberships across all configured project users.

```
22) Create user     23) List users
```

---

## Production Branch Enforcement

By default, deploys are only allowed from branches named `main`, `master`, `production`, or `release`. Deploying any other branch requires explicit confirmation, or the `--force-branch` flag in CLI mode.

---

## Rsync Excludes

Global excludes (applied to all projects):

```
.git  .env  .env.*  __pycache__/  *.pyc  .DS_Store  .vscode/  .idea/
```

Type-specific excludes (e.g. `node_modules/`, `venv/`, `dist/`) are added automatically. Per-project excludes can be added via `extra_excludes` in the project config.

---
