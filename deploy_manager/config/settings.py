SRC_BASE = "/home/linux"
DEPLOY_BASES = {
    "fastapi": "/srv/fastapi",
    "django":  "/srv/django",
    "nodeapi": "/srv/nodeapi",
    "nextapp": "/srv/nextapp",
    "react":   "/srv/react",
}
BACKUP_BASE = "/srv/bak"

GLOBAL_RSYNC_EXCLUDES = [
    ".git", ".env", ".env.*", "__pycache__/", "*.pyc",
    ".DS_Store", "thumbs.db", ".vscode/", ".idea/",
]

TYPE_RSYNC_EXCLUDES = {
    "fastapi": ["venv/", ".venv/", "*.egg-info/"],
    "django":  ["venv/", ".venv/", "*.egg-info/", "staticfiles/", "media/"],
    "nodeapi": ["node_modules/", "dist/"],
    "nextapp": ["node_modules/", ".next/"],
    "react":   ["node_modules/", "build/", "dist/"],
}

# runtime: python | node | static
# server:  uvicorn | gunicorn | node | npm | nginx-static
TYPE_META = {
    "fastapi": {"runtime": "python",  "server": "uvicorn",      "needs_build": False, "needs_service": True},
    "django":  {"runtime": "python",  "server": "gunicorn",     "needs_build": False, "needs_service": True},
    "nodeapi": {"runtime": "node",    "server": "node",         "needs_build": False, "needs_service": True},
    "nextapp": {"runtime": "node",    "server": "npm",          "needs_build": True,  "needs_service": True},
    "react":   {"runtime": "node",    "server": "nginx-static", "needs_build": True,  "needs_service": False},
}

BACKUP_RETENTION = 5

SYSTEMD_DIR = "/etc/systemd/system"

DEFAULT_NODE_BIN = "/usr/bin/node"
DEFAULT_NPM_BIN = "/usr/bin/npm"
DEFAULT_PYTHON_BIN = "/usr/bin/python3"

NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
NGINX_RATE_LIMIT_ZONE = "deploy_rl"
NGINX_RATE_LIMIT_RATE = "30r/s"
NGINX_RATE_LIMIT_BURST = 60

ALLOWED_PROD_BRANCHES = ["main", "master", "production", "release"]

DEFAULT_SHELL_SERVICE = "/usr/sbin/nologin"
DEFAULT_SHELL_HUMAN = "/bin/bash"

DJANGO_DEFAULT_WSGI = "config.wsgi:application"

REACT_BUILD_OUTPUT_CANDIDATES = ["build", "dist"]

# --- projects ---
# type: fastapi | django | nodeapi | nextapp | react
# python: python_reqs, wsgi_module, django_settings, run_migrate, run_collectstatic
# node: npm_script, build_cmd, build_output
PROJECTS = [
    # {
    #     "name": "backend",
    #     "type": "nodeapi",
    #     "user": "nodeapi",
    #     "service": "backend.service",
    #     "entry_point": "src/index.js",
    #     "port": 4001,
    #     "domain": "backend-api.com",
    #     "extra_excludes": ["/dir"],
    #     "rotate_keys": ["JWT_SECRET", "API_KEY"],   # env var names eligible for rotation
    # },
    # {
    #     "name": "chatbot",
    #     "type": "fastapi",
    #     "user": "fastapi",
    #     "service": "chatbot.service",
    #     "entry_point": "app.main:app",
    #     "port": 8001,
    #     "domain": "chatbot.com",
    #     "extra_excludes": [],
    #     "rotate_keys": ["SECRET_KEY", "OPENAI_API_KEY"],
    # },
    # {
    #     "name": "next",
    #     "type": "nextapp",
    #     "user": "nextapp",
    #     "service": "next.service",
    #     "entry_point": "npm start",
    #     "port": 3000,
    #     "domain": "next.com",
    #     "extra_excludes": [],
    #     "build_required": True,
    #     "rotate_keys": ["NEXTAUTH_SECRET"],
    # },
    # {
    #     "name": "my-django-app",
    #     "type": "django",
    #     "user": "django",
    #     "service": "my-django-app.service",
    #     "wsgi_module": "config.wsgi:application",
    #     "django_settings": "config.settings.production",
    #     "port": 8010,
    #     "domain": "django-app.com",
    #     "extra_excludes": ["media/"],
    #     "run_migrate": True,
    #     "run_collectstatic": True,
    #     "rotate_keys": ["SECRET_KEY", "DB_PASSWORD"],
    # },
    # {
    #     "name": "my-react-frontend",
    #     "type": "react",
    #     "user": "react",
    #     "service": "",          # React has NO service — served by nginx
    #     "port": 0,              # No port — static files
    #     "domain": "app.com",
    #     "extra_excludes": [],
    #     "build_output": "dist", # or "build" for CRA
    #     "rotate_keys": [],
    # },
]

SUPPORTED_TYPES = list(TYPE_META.keys())
