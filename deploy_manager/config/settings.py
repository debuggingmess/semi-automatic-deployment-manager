# =============================================================================
# settings.py — TEMPLATE / DEFAULTS  (do not put real server config here)
# =============================================================================
# Copy this file to settings.deploy and edit that instead.
# settings.deploy is git-ignored and overrides every value defined below.
# =============================================================================

# SRC_BASE = "/home/linux"
# DEPLOY_BASES = {
#     "fastapi": "/srv/fastapi",
#     "nodeapi": "/srv/nodeapi",
#     "nextapp": "/srv/nextapp",
#     "react":   "/srv/react",
#     "compose": "/srv/compose",
# }
# BACKUP_BASE = "/srv/bak"

# GLOBAL_RSYNC_EXCLUDES = [
#     ".git", ".env", ".env.*", "__pycache__/", "*.pyc",
#     ".DS_Store", "thumbs.db", ".vscode/", ".idea/",
# ]

# TYPE_RSYNC_EXCLUDES = {
#     "fastapi": ["venv/", ".venv/", "*.egg-info/"],
#     "nodeapi": ["node_modules/", "dist/"],
#     "nextapp": ["node_modules/", ".next/"],
#     "react":   ["node_modules/", "build/", "dist/"],
#     "compose": [],
# }

# runtime: python | node | compose
# server:  uvicorn | node | npm | nginx-static | docker-compose
# TYPE_META = {
#     "fastapi": {"runtime": "python",  "server": "uvicorn",        "needs_build": False, "needs_service": True},
#     "nodeapi": {"runtime": "node",    "server": "node",           "needs_build": False, "needs_service": True},
#     "nextapp": {"runtime": "node",    "server": "npm",            "needs_build": True,  "needs_service": True},
#     "react":   {"runtime": "node",    "server": "nginx-static",   "needs_build": True,  "needs_service": False},
#     "compose": {"runtime": "compose", "server": "docker-compose", "needs_build": False, "needs_service": True},
# }

# BACKUP_RETENTION = 5

# SYSTEMD_DIR = "/etc/systemd/system"
# SERVICE_DIR  = "/srv/service"   # flat dir where generated .service files are stored before linking

# DEFAULT_NODE_BIN = "/usr/bin/node"
# DEFAULT_NPM_BIN = "/usr/bin/npm"
# DEFAULT_PYTHON_BIN = "/usr/bin/python3"

# NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
# NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
# NGINX_RATE_LIMIT_ZONE = "deploy_rl"
# NGINX_RATE_LIMIT_RATE = "30r/s"
# NGINX_RATE_LIMIT_BURST = 60

# ALLOWED_PROD_BRANCHES = ["main", "master", "production", "release"]

# DEFAULT_SHELL_SERVICE = "/usr/sbin/nologin"
# DEFAULT_SHELL_HUMAN = "/bin/bash"

# REACT_BUILD_OUTPUT_CANDIDATES = ["build", "dist"]

# --- projects ---
# type: fastapi | django | nodeapi | nextapp | react | compose
#
# common fields:
#   name, type, user, service, port, domain, extra_excludes, rotate_keys
#
# python (fastapi/django):
#   entry_point, python_reqs, wsgi_module, django_settings,
#   run_migrate, run_collectstatic
#
# node (nodeapi/nextapp):
#   entry_point, npm_script, build_cmd,
#   pkg_cmd  — command to use: "npm" | "pnpm" | "bun" | any binary path (default: "npm")
#   app_dir  — subdir inside the project to run pkg_cmd in, e.g. "apps/web" for monorepos
#              (leave empty to run at project root)
#
# compose:
#   compose_file  — filename of the compose file (default: "docker-compose.yml")
#                   docker compose always runs from the project root (/srv/compose/<name>/)
#   app_dir       — subdir to run pkg_cmd in for host-side builds (e.g. "apps/web")
#                   only needed if you build on the host before docker compose
#   pkg_cmd       — package manager for host-side install/build (e.g. "pnpm", "bun")
#
# PROJECTS = [
#     {
#         "name": "my-node-api",
#         "type": "nodeapi",
#         "user": "nodeapi",
#         "service": "my-node-api.service",
#         "entry_point": "src/index.js",
#         "port": 4001,
#         "domain": "api.example.com",
#         "pkg_cmd": "npm",
#         "rotate_keys": ["JWT_SECRET"],
#     },
#     {
#         "name": "my-next-app",
#         "type": "nextapp",
#         "user": "nextapp",
#         "service": "my-next-app.service",
#         "port": 3000,
#         "domain": "app.example.com",
#         "pkg_cmd": "pnpm",       # or "bun", "npm"
#         "app_dir": "apps/web",   # omit if package.json is at project root
#         "rotate_keys": ["NEXTAUTH_SECRET"],
#     },
#     {
#         "name": "my-fastapi",
#         "type": "fastapi",
#         "user": "fastapi",
#         "service": "my-fastapi.service",
#         "entry_point": "app.main:app",
#         "port": 8000,
#         "domain": "api.example.com",
#         "rotate_keys": ["SECRET_KEY"],
#     },
#     {
#         "name": "my-react-app",
#         "type": "react",
#         "user": "react",
#         "service": "",           # no service — nginx serves static files
#         "port": 0,
#         "domain": "app.example.com",
#         "build_output": "dist",  # or "build" for CRA
#         "pkg_cmd": "npm",
#     },
#     {
#         "name": "my-stack",
#         "type": "compose",
#         "user": "ubuntu",
#         "service": "my-stack.service",
#         "compose_file": "docker-compose.yml",
#         "docker_mode": "rootful",   # "rootful" (default) | "rootless"
#                                     # rootful:  Requires=docker.service, user must be in docker group
#                                     # rootless: uses DOCKER_HOST=unix:///run/user/<UID>/docker.sock
#         "port": 8080,
#         "domain": "stack.example.com",
#         # only set app_dir + pkg_cmd if you need host-side install/build:
#         # "app_dir": "apps/web",
#         # "pkg_cmd": "pnpm",
#     },
# ]

# SUPPORTED_TYPES = list(TYPE_META.keys())

# ---------------------------------------------------------------------------
# Local override loader — do NOT edit below this line
# ---------------------------------------------------------------------------
# If deploy_manager/config/settings.deploy exists, every variable defined
# in that file overrides the corresponding default above.
# settings.deploy is git-ignored — it is the file you should actually edit.
# ---------------------------------------------------------------------------
import importlib.machinery as _ilm
import importlib.util as _ilu
import os as _os

_deploy_cfg = _os.path.join(_os.path.dirname(__file__), "settings.deploy")
if _os.path.isfile(_deploy_cfg):
    _loader = _ilm.SourceFileLoader("_settings_deploy", _deploy_cfg)
    _spec = _ilu.spec_from_file_location("_settings_deploy", _deploy_cfg, loader=_loader)
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    for _k, _v in vars(_mod).items():
        if not _k.startswith("_"):
            globals()[_k] = _v
    del _mod, _spec, _loader, _k, _v
del _ilm, _ilu, _os, _deploy_cfg
