# SADM (Deploy Manager v4.0)

SADM is a robust, zero-downtime deployment automation script designed for Linux servers. It handles the entire lifecycle of hosting web applications, from pulling code and installing dependencies to configuring systemd services, setting up Nginx reverse proxies, and managing SSL certificates via Certbot.

## Features

* **Multi-Stack Support:** Natively supports FastAPI, Django, Node.js APIs, Next.js, and static React applications.
* **Automated Backups & Rollbacks:** Automatically creates localized backups before deploying and allows instant rollbacks if a deployment fails.
* **Systemd Integration:** Automatically generates, enables, and restarts `systemd` services to keep your apps running in the background.
* **Nginx & SSL Auto-Config:** Generates secure Nginx server blocks (with built-in rate limiting and security headers) and optionally provisions Let's Encrypt SSL certificates.
* **Security First:** Runs applications under dedicated, unprivileged system users/groups and includes an interactive `.env` secret rotation tool.
* **Git Management:** Deploy from specific branches or pin deployments to specific Git commit hashes.
* **Interactive & CLI Modes:** Offers a user-friendly interactive menu or can be driven entirely via command-line arguments for CI/CD pipelines.

---

## Supported Frameworks

| Type | Runtime | Server | Build Req? | Features |
| :--- | :--- | :--- | :--- | :--- |
| `fastapi` | Python | Uvicorn | No | Venv setup, pip install, proxy config. |
| `django` | Python | Gunicorn | No | Auto-migrate, auto-collectstatic. |
| `nodeapi` | Node.js | Node/npm | No | `npm ci`, npm cache handling. |
| `nextapp` | Node.js | npm | Yes | `npm run build`, Next.js specific proxy. |
| `react` | Static | Nginx | Yes | `npm run build`, static Nginx hosting. |

---

## Prerequisites

This script is built for Debian/Ubuntu-based systems. Ensure your server has the following installed:

```bash
sudo apt update
sudo apt install git rsync nginx certbot python3-venv nodejs npm
