#!/usr/bin/env python3
import argparse
import datetime
import getpass
import json
import os
import pwd
import grp
import re
import secrets
import shutil
import string
import subprocess
import sys
import textwrap

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

DJANGO_DEFAULT_WSGI = "config.wsgi:application"   # common pattern

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
    # },
]

SUPPORTED_TYPES = list(TYPE_META.keys())

class DeployError(Exception):
    pass

def require_root():
    if os.geteuid() != 0:
        print("This script must be run as root (use sudo).")
        sys.exit(1)

def run_cmd(cmd, cwd=None, capture=False, check=True, env=None, timeout=600, run_as=None):
    if run_as:
        cmd = ["sudo", "-H", "-u", run_as, "--"] + cmd
    cmd_str = " ".join(cmd)
    merged_env = {**os.environ, **env} if env else None
    try:
        result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=capture,
                                text=True, env=merged_env, timeout=timeout)
        if check and result.returncode != 0:
            stderr_msg = f"\n  stderr: {result.stderr.strip()}" if capture and result.stderr else ""
            raise DeployError(f"Command failed (exit {result.returncode}): {cmd_str}{stderr_msg}")
        return result
    except FileNotFoundError:
        raise DeployError(f"Command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        raise DeployError(f"Command timed out after {timeout}s: {cmd_str}")

def confirm(prompt, default=False):
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(prompt + suffix).strip().lower()
    return (answer in ("y", "yes")) if answer else default

def get_dest_base(proj_type):
    if proj_type not in DEPLOY_BASES:
        raise DeployError(f"Unknown project type: {proj_type}. Supported: {', '.join(SUPPORTED_TYPES)}")
    return DEPLOY_BASES[proj_type]

def get_dest_dir(proj):
    return os.path.join(get_dest_base(proj["type"]), proj["name"])

def get_src_dir(proj):
    return os.path.join(SRC_BASE, proj["name"])

def get_rsync_excludes(proj):
    excludes = list(GLOBAL_RSYNC_EXCLUDES)
    excludes.extend(TYPE_RSYNC_EXCLUDES.get(proj["type"], []))
    excludes.extend(proj.get("extra_excludes", []))
    return excludes

def get_type_meta(proj):
    return TYPE_META.get(proj["type"], {})

def find_project_by_name(name):
    for proj in PROJECTS:
        if proj["name"].lower() == name.lower():
            return proj
    return None

def ts():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

def ts_iso():
    return datetime.datetime.now().isoformat()

def get_current_user():
    return os.environ.get("SUDO_USER", getpass.getuser())

def get_git_commit_full(src_dir):
    try:
        r = run_cmd(["git", "rev-parse", "HEAD"], cwd=src_dir, capture=True, check=False)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except DeployError:
        return "unknown"

def get_git_branch(src_dir):
    try:
        r = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=src_dir, capture=True, check=False)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except DeployError:
        return "unknown"

def is_python_type(proj):
    return get_type_meta(proj).get("runtime") == "python"

def is_node_type(proj):
    return get_type_meta(proj).get("runtime") == "node"

def needs_service(proj):
    return get_type_meta(proj).get("needs_service", True)

def needs_build(proj):
    meta = get_type_meta(proj)
    return meta.get("needs_build", False) or proj.get("build_required", False)

def get_venv_dir(proj):
    return os.path.join(get_dest_dir(proj), "venv")

def get_venv_bin(proj, binary):
    return os.path.join(get_venv_dir(proj), "bin", binary)

def user_exists(username):
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False

def group_exists(groupname):
    try:
        grp.getgrnam(groupname)
        return True
    except KeyError:
        return False

def ensure_system_user(username):
    if user_exists(username):
        home_dir = f"/var/lib/{username}"
        if not os.path.isdir(home_dir):
            os.makedirs(home_dir, mode=0o750, exist_ok=True)
            run_cmd(["chown", f"{username}:{username}", home_dir])
        return
    home_dir = f"/var/lib/{username}"
    if not group_exists(username):
        run_cmd(["groupadd", "--system", username])
    os.makedirs(home_dir, mode=0o750, exist_ok=True)
    run_cmd(["useradd", "--system", "--gid", username, "--shell", DEFAULT_SHELL_SERVICE,
             "--home-dir", home_dir, "--no-create-home", username])
    run_cmd(["chown", f"{username}:{username}", home_dir])

def create_deploy_user():
    print("\n  Create Deploy User\n")
    username = input("  Username: ").strip()
    if not username:
        return
    if not re.match(r"^[a-z_][a-z0-9_\-]{0,30}$", username):
        print("Invalid username. Use lowercase letters, digits, underscores, hyphens.")
        return
    if user_exists(username):
        print(f"User '{username}' already exists.")
        if not confirm("  Continue to modify group memberships?"):
            return
    else:
        print("  Account type:")
        print("    1) Human (bash shell, home directory)")
        print("    2) Service (nologin, no home)")
        acct_type = input("  Choice [1]: ").strip() or "1"
        if acct_type == "1":
            if not group_exists(username):
                run_cmd(["groupadd", username])
            run_cmd(["useradd", "--gid", username, "--shell", DEFAULT_SHELL_HUMAN, "--create-home", username])
            if confirm("  Set a password?"):
                run_cmd(["passwd", username], capture=False, check=False)
            ssh_key = input("  Paste SSH public key (or Enter to skip): ").strip()
            if ssh_key:
                ssh_dir = f"/home/{username}/.ssh"
                os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
                with open(os.path.join(ssh_dir, "authorized_keys"), "a") as f:
                    f.write(ssh_key.rstrip() + "\n")
                os.chmod(os.path.join(ssh_dir, "authorized_keys"), 0o600)
                run_cmd(["chown", "-R", f"{username}:{username}", ssh_dir])
        elif acct_type == "2":
            ensure_system_user(username)
        else:
            print("  Invalid choice.")
            return

    service_groups = sorted(set(p["user"] for p in PROJECTS))
    print(f"\n  Available service groups: {', '.join(service_groups)}")
    groups_input = input("  Add user to groups (comma-separated, or 'all'): ").strip()
    add_groups = list(set(p["user"] for p in PROJECTS)) if groups_input.lower() == "all" else \
                 [g.strip() for g in groups_input.split(",") if g.strip()] if groups_input else []
    for g in add_groups:
        if not group_exists(g):
            run_cmd(["groupadd", "--system", g])
        run_cmd(["usermod", "-aG", g, username])

def list_deploy_users():
    service_groups = sorted(set(p["user"] for p in PROJECTS))
    print(f"\n  {'Group':<16s} {'Members'}")
    print(f"  {'─' * 60}")
    for g in service_groups:
        try:
            gr = grp.getgrnam(g)
            members = gr.gr_mem if gr.gr_mem else ["(primary only)"]
            print(f"  {g:<16s} {', '.join(members)}")
        except KeyError:
            print(f"  {g:<16s} (group does not exist)")

def choose_project(prompt="Select a project:"):
    print(f"\n{prompt}")
    for i, proj in enumerate(PROJECTS, start=1):
        svc_status = ""
        if needs_service(proj) and proj.get("service"):
            try:
                r = run_cmd(["systemctl", "is-active", proj["service"]], check=False, capture=True)
                state = r.stdout.strip() if r.stdout else "unknown"
                color = "\033[32m" if state == "active" else "\033[31m"
                svc_status = f"  {color}{state}\033[0m"
            except DeployError:
                svc_status = "  \033[33munknown\033[0m"
        elif proj["type"] == "react":
            svc_status = "  \033[36mstatic\033[0m"
        print(f"  {i:2d}) {proj['name']:<40s} [{proj['type']:<8s}]{svc_status}")
    print(f"   0) Cancel")
    while True:
        choice = input("\nEnter choice: ").strip()
        if choice in ("0", ""):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(PROJECTS):
            return PROJECTS[int(choice) - 1]
        print("  Invalid choice.")

def step_git_checkout_branch(proj, branch, force=False):
    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source directory does not exist: {src_dir}")
    run_cmd(["git", "-c", "core.hooksPath=/dev/null", "fetch", "--all", "--prune"], cwd=src_dir)
    result = run_cmd(["git", "branch", "-a", "--list", f"*{branch}*"], cwd=src_dir, capture=True, check=False)
    if not result.stdout.strip():
        raise DeployError(f"Branch '{branch}' does not exist in {proj['name']}")
    if branch not in ALLOWED_PROD_BRANCHES and not force:
        print(f"WARNING: Branch '{branch}' is NOT a production branch.")
        print(f"   Allowed: {', '.join(ALLOWED_PROD_BRANCHES)}")
        if not confirm("  Deploy non-production branch? This is risky.", default=False):
            raise DeployError("Aborted: refused to deploy non-production branch")
    current = get_git_branch(src_dir)
    if current != branch:
        run_cmd(["git", "stash", "--include-untracked"], cwd=src_dir, check=False)
        run_cmd(["git", "-c", "core.hooksPath=/dev/null", "checkout", branch], cwd=src_dir)
    run_cmd(["git", "-c", "core.hooksPath=/dev/null", "pull", "--ff-only"], cwd=src_dir)

def step_git_pin_commit(proj, commit_hash):
    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source directory does not exist: {src_dir}")
    if not re.match(r"^[0-9a-fA-F]{7,40}$", commit_hash):
        raise DeployError(f"Invalid commit hash format: {commit_hash}")
    run_cmd(["git", "-c", "core.hooksPath=/dev/null", "fetch", "--all"], cwd=src_dir)
    result = run_cmd(["git", "cat-file", "-t", commit_hash], cwd=src_dir, capture=True, check=False)
    if result.returncode != 0 or result.stdout.strip() != "commit":
        raise DeployError(f"Commit '{commit_hash}' not found in {proj['name']}")
    run_cmd(["git", "stash", "--include-untracked"], cwd=src_dir, check=False)
    run_cmd(["git", "-c", "core.hooksPath=/dev/null", "checkout", commit_hash], cwd=src_dir)
    print("  WARNING: detached HEAD, checkout a branch later")

def create_backup(proj):
    dest_dir = get_dest_dir(proj)
    if not os.path.isdir(dest_dir):
        print(f"Nothing to back up: {dest_dir}")
        return None
    backup_path = os.path.join(BACKUP_BASE, proj["type"], proj["name"], ts())
    os.makedirs(backup_path, exist_ok=True)
    run_cmd(["rsync", "-a", "--delete", f"{dest_dir}/", f"{backup_path}/"])
    src_dir = get_src_dir(proj)
    meta = {
        "project": proj["name"], "type": proj["type"], "service": proj.get("service", ""),
        "created_at": ts_iso(), "source_dir": dest_dir, "created_by": get_current_user(),
        "git_commit": get_git_commit_full(src_dir) if os.path.isdir(src_dir) else "n/a",
        "git_branch": get_git_branch(src_dir) if os.path.isdir(src_dir) else "n/a",
    }
    with open(os.path.join(backup_path, ".deploy-meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    prune_backups(proj)
    return backup_path

def prune_backups(proj):
    bdir = os.path.join(BACKUP_BASE, proj["type"], proj["name"])
    if not os.path.isdir(bdir):
        return
    backups = sorted(d for d in os.listdir(bdir) if os.path.isdir(os.path.join(bdir, d)) and not d.startswith("."))
    for old in backups[:max(0, len(backups) - BACKUP_RETENTION)]:
        shutil.rmtree(os.path.join(bdir, old), ignore_errors=True)

def list_backups(proj):
    bdir = os.path.join(BACKUP_BASE, proj["type"], proj["name"])
    if not os.path.isdir(bdir):
        return []
    return sorted(os.path.join(bdir, d) for d in os.listdir(bdir)
                  if os.path.isdir(os.path.join(bdir, d)) and not d.startswith("."))

def rollback(proj, backup_path=None):
    if backup_path is None:
        backups = list_backups(proj)
        if not backups:
            raise DeployError(f"No backups found for {proj['name']}")
        backup_path = backups[-1]
    if not os.path.isdir(backup_path):
        raise DeployError(f"Backup directory does not exist: {backup_path}")
    dest_dir = get_dest_dir(proj)
    run_cmd(["rsync", "-a", "--delete", "--exclude", ".deploy-meta.json", "--exclude", ".env",
             f"{backup_path}/", f"{dest_dir}/"])
    fix_ownership(proj)
    if needs_service(proj):
        restart_service(proj)

def step_git_pull(proj):
    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source directory does not exist: {src_dir}")
    run_cmd(["git", "-c", "core.hooksPath=/dev/null", "pull", "--ff-only"], cwd=src_dir)

def step_git_clone(proj, repo_url):
    src_dir = get_src_dir(proj)
    if os.path.isdir(src_dir):
        return
    run_cmd(["git", "clone", "-c", "core.hooksPath=/dev/null", repo_url, src_dir])

def step_rsync(proj):
    src_dir = get_src_dir(proj)
    dest_dir = get_dest_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source does not exist: {src_dir}")
    os.makedirs(dest_dir, exist_ok=True)
    rsync_cmd = ["rsync", "-av", "--delete"]
    for exc in get_rsync_excludes(proj):
        rsync_cmd.extend(["--exclude", exc])
    rsync_cmd.extend([f"{src_dir}/", f"{dest_dir}/"])
    run_cmd(rsync_cmd)

def step_install_deps(proj):
    dest_dir = get_dest_dir(proj)
    if not os.path.isdir(dest_dir):
        raise DeployError(f"Deployment directory does not exist: {dest_dir}")
    user = proj["user"]
    home_dir = f"/var/lib/{user}"

    if is_python_type(proj):
        venv_dir = get_venv_dir(proj)
        reqs_file = proj.get("python_reqs", "requirements.txt")
        reqs_path = os.path.join(dest_dir, reqs_file)
        if not os.path.isfile(reqs_path):
            print(f"No {reqs_file} found, skipping pip install")
            return
        if not os.path.isdir(venv_dir):
            run_cmd([DEFAULT_PYTHON_BIN, "-m", "venv", venv_dir], cwd=dest_dir, run_as=user)
        pip_bin = get_venv_bin(proj, "pip")
        run_cmd([pip_bin, "install", "-r", reqs_path, "--quiet"], run_as=user)

    elif is_node_type(proj):
        lock_file = os.path.join(dest_dir, "package-lock.json")
        npm_env = {"NPM_CONFIG_CACHE": os.path.join(home_dir, ".npm")}
        if os.path.isfile(lock_file):
            run_cmd(["npm", "ci", "--omit=dev", "--ignore-scripts"], cwd=dest_dir,
                    env=npm_env, run_as=user)
        else:
            print("No package-lock.json, falling back to npm install")
            run_cmd(["npm", "install", "--omit=dev", "--ignore-scripts"], cwd=dest_dir,
                    env=npm_env, run_as=user)
        run_cmd(["npm", "rebuild"], cwd=dest_dir, env=npm_env, run_as=user, check=False)

def step_build(proj):
    if not needs_build(proj):
        return
    dest_dir = get_dest_dir(proj)
    if not os.path.isdir(dest_dir):
        raise DeployError(f"Deployment directory does not exist: {dest_dir}")
    user = proj["user"]
    build_cmd = proj.get("build_cmd", "npm run build")
    build_env = {}
    if is_node_type(proj):
        build_env["NPM_CONFIG_CACHE"] = os.path.join(f"/var/lib/{user}", ".npm")
    run_cmd(build_cmd.split(), cwd=dest_dir, env=build_env if build_env else None, run_as=user)

def step_django_migrate(proj):
    if proj["type"] != "django":
        return
    if not proj.get("run_migrate", True):
        return
    dest_dir = get_dest_dir(proj)
    user = proj["user"]
    python_bin = get_venv_bin(proj, "python")
    manage_py = os.path.join(dest_dir, "manage.py")
    if not os.path.isfile(manage_py):
        print("No manage.py found, skipping migration")
        return
    env_vars = {}
    settings = proj.get("django_settings", "")
    if settings:
        env_vars["DJANGO_SETTINGS_MODULE"] = settings
    run_cmd([python_bin, "manage.py", "migrate", "--noinput"], cwd=dest_dir,
            env=env_vars if env_vars else None, run_as=user)

def step_django_collectstatic(proj):
    if proj["type"] != "django":
        return
    if not proj.get("run_collectstatic", True):
        return
    dest_dir = get_dest_dir(proj)
    user = proj["user"]
    python_bin = get_venv_bin(proj, "python")
    manage_py = os.path.join(dest_dir, "manage.py")
    if not os.path.isfile(manage_py):
        print("No manage.py found, skipping collectstatic")
        return
    env_vars = {}
    settings = proj.get("django_settings", "")
    if settings:
        env_vars["DJANGO_SETTINGS_MODULE"] = settings
    run_cmd([python_bin, "manage.py", "collectstatic", "--noinput", "--clear"], cwd=dest_dir,
            env=env_vars if env_vars else None, run_as=user)

def fix_ownership(proj):
    dest_dir = get_dest_dir(proj)
    if not os.path.isdir(dest_dir):
        return
    user = proj["user"]
    run_cmd(["chown", "-R", f"{user}:{user}", dest_dir])

def restart_service(proj):
    if not needs_service(proj):
        return
    service = proj.get("service")
    if not service:
        print(f"No service configured for {proj['name']}")
        return
    run_cmd(["systemctl", "daemon-reload"])
    run_cmd(["systemctl", "restart", service])
    result = run_cmd(["systemctl", "is-active", service], check=False, capture=True)
    state = result.stdout.strip() if result.stdout else "unknown"
    if state != "active":
        print(f"Service {service} is NOT active (state: {state})")
        run_cmd(["journalctl", "-u", service, "-n", "20", "--no-pager"], check=False)
        raise DeployError(f"Service {service} failed to start")

def _build_unit_lines(description, user, working_dir, exec_start, env_file=None, extra_env=None):
    home_dir = f"/var/lib/{user}"
    lines = [
        "[Unit]", f"Description={description}", "After=network.target", "",
        "[Service]", "Type=simple", f"User={user}", f"Group={user}",
        f"WorkingDirectory={working_dir}", f"ExecStart={exec_start}",
        f"Environment=HOME={home_dir}",
    ]
    for k, v in (extra_env or {}).items():
        lines.append(f"Environment={k}={v}")
    if env_file:
        lines.append(f"EnvironmentFile={env_file}")
    rw_paths = f"{working_dir} {home_dir}"
    lines.extend([
        "Restart=on-failure", "RestartSec=5", "StartLimitIntervalSec=60", "StartLimitBurst=5",
        "StandardOutput=journal", "StandardError=journal",
        f"SyslogIdentifier={description}",
        "", "# Hardening", "NoNewPrivileges=true", "ProtectSystem=strict",
        f"ReadWritePaths={rw_paths}", "ProtectHome=true", "PrivateTmp=true",
        "", "[Install]", "WantedBy=multi-user.target",
    ])
    return "\n".join(lines) + "\n"

def generate_service_unit(proj, port, entry_point, workers=2, npm_script=None, env_file=None):
    dest_dir = get_dest_dir(proj)
    ptype = proj["type"]
    desc = proj["name"]
    user = proj["user"]
    home_dir = f"/var/lib/{user}"
    extra_env = {}

    if ptype == "fastapi":
        exec_start = f"{get_venv_bin(proj, 'uvicorn')} {entry_point} --host 0.0.0.0 --port {port} --workers {workers}"

    elif ptype == "django":
        wsgi_module = entry_point
        exec_start = f"{get_venv_bin(proj, 'gunicorn')} {wsgi_module} --bind 0.0.0.0:{port} --workers {workers}"
        settings = proj.get("django_settings", "")
        if settings:
            extra_env["DJANGO_SETTINGS_MODULE"] = settings

    elif ptype == "nodeapi":
        if npm_script:
            exec_start = f"{DEFAULT_NPM_BIN} run {npm_script}"
        else:
            exec_start = f"{DEFAULT_NODE_BIN} {entry_point}"
        extra_env["NODE_ENV"] = "production"
        extra_env["PORT"] = str(port)
        extra_env["NPM_CONFIG_CACHE"] = os.path.join(home_dir, ".npm")

    elif ptype == "nextapp":
        if npm_script:
            exec_start = f"{DEFAULT_NPM_BIN} run {npm_script}"
        else:
            exec_start = f"{DEFAULT_NPM_BIN} start"
        extra_env["NODE_ENV"] = "production"
        extra_env["PORT"] = str(port)
        extra_env["NPM_CONFIG_CACHE"] = os.path.join(home_dir, ".npm")

    else:
        raise DeployError(f"Cannot generate service for type: {ptype}")

    return _build_unit_lines(desc, user, dest_dir, exec_start, env_file, extra_env)

def create_service_file(proj, interactive=True):
    if not needs_service(proj):
        return
    service_name = proj.get("service", "")
    if not service_name:
        raise DeployError("No 'service' name configured.")

    dest_dir = get_dest_dir(proj)
    ptype = proj["type"]
    port = proj.get("port", 3000)
    entry_point = proj.get("entry_point", "") or proj.get("wsgi_module", "")
    env_file_path = os.path.join(dest_dir, proj.get("env_file", ".env"))
    env_file = env_file_path if os.path.isfile(env_file_path) else None
    workers = 2
    npm_script = proj.get("npm_script")

    if interactive:
        print(f"\n  Creating systemd service: {service_name}")
        print(f"  Type: {ptype} | User: {proj['user']} | Dir: {dest_dir}")
        port_input = input(f"  Port [{port}]: ").strip()
        if port_input.isdigit():
            port = int(port_input)

        if ptype == "fastapi":
            default_ep = entry_point or "app.main:app"
            ep_input = input(f"  Uvicorn ASGI app [{default_ep}]: ").strip()
            entry_point = ep_input or default_ep
        elif ptype == "django":
            default_ep = entry_point or proj.get("wsgi_module", DJANGO_DEFAULT_WSGI)
            ep_input = input(f"  Gunicorn WSGI module [{default_ep}]: ").strip()
            entry_point = ep_input or default_ep
        elif ptype in ("nodeapi", "nextapp"):
            default_ep = entry_point or "src/index.js"
            ep_input = input(f"  Entry point [{default_ep}]: ").strip()
            entry_point = ep_input or default_ep
            npm_input = input(f"  Use npm script instead? (e.g. 'start') [leave empty]: ").strip()
            if npm_input:
                npm_script = npm_input

        if is_python_type(proj):
            w_input = input(f"  Workers [{workers}]: ").strip()
            workers = int(w_input) if w_input.isdigit() else workers

    unit_content = generate_service_unit(proj, port, entry_point, workers, npm_script, env_file)
    service_path = os.path.join(SYSTEMD_DIR, service_name)

    if os.path.isfile(service_path) and interactive:
        if not confirm(f"  {service_path} exists. Overwrite?"):
            return

    with open(service_path, "w") as f:
        f.write(unit_content)
    ensure_system_user(proj["user"])
    run_cmd(["systemctl", "daemon-reload"])
    run_cmd(["systemctl", "enable", service_name])

def _nginx_is_installed():
    return run_cmd(["which", "nginx"], check=False, capture=True).returncode == 0

def _certbot_is_installed():
    return run_cmd(["which", "certbot"], check=False, capture=True).returncode == 0

def _ensure_nginx_rate_limit_zone():
    snippet = "/etc/nginx/conf.d/deploy-rate-limit.conf"
    if os.path.isfile(snippet):
        with open(snippet) as f:
            if NGINX_RATE_LIMIT_ZONE in f.read():
                return
    os.makedirs(os.path.dirname(snippet), exist_ok=True)
    with open(snippet, "w") as f:
        f.write(f"# Auto-generated by Deploy Manager\n"
                f"limit_req_zone $binary_remote_addr zone={NGINX_RATE_LIMIT_ZONE}:10m rate={NGINX_RATE_LIMIT_RATE};\n")

def generate_nginx_proxy_config(domain, port, project_name):
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_name)
    return textwrap.dedent(f"""\
        # {project_name} reverse proxy
        # {domain} → localhost:{port}  |  Generated: {ts_iso()}

        upstream {safe}_backend {{
            server 127.0.0.1:{port};
            keepalive 32;
        }}

        server {{
            listen 80;
            listen [::]:80;
            server_name {domain};

            add_header X-Frame-Options "SAMEORIGIN" always;
            add_header X-Content-Type-Options "nosniff" always;
            add_header X-XSS-Protection "1; mode=block" always;
            add_header Referrer-Policy "strict-origin-when-cross-origin" always;

            limit_req zone={NGINX_RATE_LIMIT_ZONE} burst={NGINX_RATE_LIMIT_BURST} nodelay;
            limit_req_status 429;

            gzip on;
            gzip_vary on;
            gzip_proxied any;
            gzip_comp_level 6;
            gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

            client_max_body_size 50M;
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;

            location / {{
                proxy_pass http://{safe}_backend;
                proxy_http_version 1.1;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection "upgrade";
                proxy_buffering on;
                proxy_buffer_size 16k;
                proxy_buffers 4 32k;
            }}

            location /nginx-health {{
                access_log off;
                return 200 "ok";
                add_header Content-Type text/plain;
            }}

            location ~ /\\. {{
                deny all;
                access_log off;
                log_not_found off;
            }}
        }}
    """)

def generate_nginx_static_config(domain, project_name, static_root):
    return textwrap.dedent(f"""\
        # {project_name} static
        # {domain} → {static_root}  |  Generated: {ts_iso()}

        server {{
            listen 80;
            listen [::]:80;
            server_name {domain};

            root {static_root};
            index index.html;

            add_header X-Frame-Options "SAMEORIGIN" always;
            add_header X-Content-Type-Options "nosniff" always;
            add_header X-XSS-Protection "1; mode=block" always;
            add_header Referrer-Policy "strict-origin-when-cross-origin" always;

            limit_req zone={NGINX_RATE_LIMIT_ZONE} burst={NGINX_RATE_LIMIT_BURST} nodelay;
            limit_req_status 429;

            gzip on;
            gzip_vary on;
            gzip_proxied any;
            gzip_comp_level 6;
            gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

                    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {{
                expires 1y;
                add_header Cache-Control "public, immutable";
                access_log off;
            }}

                    location / {{
                try_files $uri $uri/ /index.html;
            }}

            location /nginx-health {{
                access_log off;
                return 200 "ok";
                add_header Content-Type text/plain;
            }}

            location ~ /\\. {{
                deny all;
                access_log off;
                log_not_found off;
            }}
        }}
    """)

def create_nginx_config(proj, interactive=True):
    if not _nginx_is_installed():
        raise DeployError("nginx not installed. Install: apt install nginx")
    domain = proj.get("domain", "")
    port = proj.get("port", 3000)
    enable_ssl = proj.get("ssl", True)
    ptype = proj["type"]

    if interactive:
        print(f"\n  Nginx config for {proj['name']} ({ptype})")
        domain_input = input(f"  Domain [{domain or 'example.com'}]: ").strip()
        if domain_input:
            domain = domain_input
        if not domain:
            raise DeployError("No domain specified")
        if ptype != "react":
            port_input = input(f"  Backend port [{port}]: ").strip()
            if port_input.isdigit():
                port = int(port_input)
        enable_ssl = confirm("  Set up SSL with certbot?", default=enable_ssl)

    if not domain:
        raise DeployError("No domain configured. Set 'domain' in PROJECTS config.")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-\.]*[a-zA-Z0-9]$", domain):
        raise DeployError(f"Invalid domain format: {domain}")

    if ptype == "react":
        dest_dir = get_dest_dir(proj)
        build_output = proj.get("build_output", "dist")
        for candidate in [build_output, "build", "dist"]:
            candidate_path = os.path.join(dest_dir, candidate)
            if os.path.isdir(candidate_path):
                build_output = candidate
                break
        static_root = os.path.join(dest_dir, build_output)
        config_content = generate_nginx_static_config(domain, proj["name"], static_root)
    else:
        config_content = generate_nginx_proxy_config(domain, port, proj["name"])

    _ensure_nginx_rate_limit_zone()

    config_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", proj["name"])
    available_path = os.path.join(NGINX_SITES_AVAILABLE, config_name)
    enabled_path = os.path.join(NGINX_SITES_ENABLED, config_name)

    if os.path.isfile(available_path) and interactive:
        if not confirm(f"  {available_path} exists. Overwrite?"):
            return

    os.makedirs(NGINX_SITES_AVAILABLE, exist_ok=True)
    os.makedirs(NGINX_SITES_ENABLED, exist_ok=True)
    with open(available_path, "w") as f:
        f.write(config_content)
    if os.path.islink(enabled_path) or os.path.exists(enabled_path):
        os.remove(enabled_path)
    os.symlink(available_path, enabled_path)

    nginx_reload()

    if enable_ssl and _certbot_is_installed():
        if not interactive or confirm(f"  Run certbot for {domain}?", default=True):
            try:
                run_cmd(["certbot", "--nginx", "-d", domain, "--non-interactive",
                         "--agree-tos", "--redirect"], timeout=120)
            except DeployError as e:
                print(f"Certbot failed: {e}")
    elif enable_ssl:
        print(f"certbot not installed. Run: certbot --nginx -d {domain}")

def nginx_reload():
    result = run_cmd(["nginx", "-t"], check=False, capture=True)
    if result.returncode != 0:
        raise DeployError(f"nginx config test failed:\n{(result.stderr or '') + (result.stdout or '')}")
    run_cmd(["systemctl", "reload", "nginx"])

def remove_nginx_config(proj):
    config_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", proj["name"])
    removed = False
    for path in [os.path.join(NGINX_SITES_ENABLED, config_name), os.path.join(NGINX_SITES_AVAILABLE, config_name)]:
        if os.path.islink(path) or os.path.exists(path):
            os.remove(path)
            removed = True
    if removed:
        nginx_reload()

def _generate_secret(length=64):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*_+-="
    return "".join(secrets.choice(alphabet) for _ in range(length))

def _read_env_file(env_path):
    entries = []
    if not os.path.isfile(env_path):
        return entries
    with open(env_path) as f:
        for line in f:
            raw = line.rstrip("\n")
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                entries.append(("", "", raw))
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key, value = key.strip(), value.strip()
                if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                entries.append((key, value, raw))
            else:
                entries.append(("", "", raw))
    return entries

def _write_env_file(env_path, entries):
    with open(env_path, "w") as f:
        for key, value, raw in entries:
            if key:
                if any(c in value for c in " \t#;'\""):
                    f.write(f'{key}="{value}"\n')
                else:
                    f.write(f"{key}={value}\n")
            else:
                f.write(raw + "\n")

def rotate_secret(proj):
    dest_dir = get_dest_dir(proj)
    env_path = os.path.join(dest_dir, proj.get("env_file", ".env"))
    if not os.path.isfile(env_path):
        raise DeployError(f".env not found: {env_path}")
    entries = _read_env_file(env_path)
    secret_keys = [(i, k, v) for i, (k, v, _) in enumerate(entries) if k]
    if not secret_keys:
        raise DeployError("No keys found in .env")

    print(f"\n  Secret rotation for {proj['name']}\n")
    secret_patterns = ["SECRET", "KEY", "TOKEN", "PASSWORD", "PASS", "JWT", "API_KEY", "PRIVATE", "AUTH", "HASH", "SALT"]
    for idx, (i, key, value) in enumerate(secret_keys, start=1):
        marker = " *" if any(p in key.upper() for p in secret_patterns) else ""
        masked = value[:3] + "…" + value[-3:] if len(value) > 8 else "***"
        print(f"  {idx:3d}) {key:<40s} = {masked}{marker}")
    print(f"    0) Cancel")

    choice = input("\n  Select key to rotate: ").strip()
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(secret_keys):
        return
    entry_index, key, _ = secret_keys[int(choice) - 1]

    print(f"\n  Rotating: {key}")
    print(f"  1) Auto-generate  2) Manual")
    gen = input("  Choice [1]: ").strip() or "1"
    if gen == "1":
        length = int(input("  Length [64]: ").strip() or "64")
        new_value = _generate_secret(max(1, length))
        print(f"  Generated: {new_value[:8]}…{new_value[-8:]}")
    elif gen == "2":
        new_value = input("  New value: ").strip()
        if not new_value:
            return
    else:
        return

    if not confirm(f"  Update {key} and restart?", default=False):
        return

    backup_env = env_path + f".bak.{ts()}"
    shutil.copy2(env_path, backup_env)
    entries[entry_index] = (key, new_value, "")
    _write_env_file(env_path, entries)
    user = proj["user"]
    run_cmd(["chown", f"{user}:{user}", env_path])
    os.chmod(env_path, 0o600)

    try:
        if needs_service(proj):
            restart_service(proj)
    except DeployError:
        print("Service restart failed. Restoring .env backup...")
        shutil.copy2(backup_env, env_path)
        run_cmd(["chown", f"{user}:{user}", env_path])
        if needs_service(proj):
            restart_service(proj)
        raise

def full_deploy(proj, skip_backup=False, branch=None, commit=None, force_branch=False):
    ptype = proj["type"]
    print(f"\n  deploying {proj['name']} ({ptype})")

    steps = []
    steps.append(("Backup", lambda: create_backup(proj) if not skip_backup else None))

    if commit:
        steps.append(("Pin Commit", lambda: step_git_pin_commit(proj, commit)))
    elif branch:
        steps.append(("Checkout Branch", lambda: step_git_checkout_branch(proj, branch, force=force_branch)))
        steps.append(("Git Pull", lambda: step_git_pull(proj)))
    else:
        steps.append(("Git Pull", lambda: step_git_pull(proj)))

    steps.append(("Rsync", lambda: step_rsync(proj)))

    steps.append(("Fix Ownership", lambda: fix_ownership(proj)))

    steps.append(("Install Dependencies", lambda: step_install_deps(proj)))

    if ptype == "django":
        steps.append(("Django Migrate", lambda: step_django_migrate(proj)))
        steps.append(("Django Collectstatic", lambda: step_django_collectstatic(proj)))

    if needs_build(proj):
        steps.append(("Build", lambda: step_build(proj)))

    if needs_service(proj):
        steps.append(("Restart Service", lambda: restart_service(proj)))

    config_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", proj["name"])
    if os.path.exists(os.path.join(NGINX_SITES_ENABLED, config_name)):
        steps.append(("Nginx Reload", lambda: nginx_reload()))

    completed, backup_path = [], None
    for step_name, step_fn in steps:
        try:
            result = step_fn()
            if step_name == "Backup" and result:
                backup_path = result
            completed.append(step_name)
        except DeployError as e:
            print(f"  {step_name} FAILED: {e}")
            if backup_path and confirm("  Rollback to backup?", default=True):
                try:
                    rollback(proj, backup_path)
                except DeployError as e2:
                    print(f"  Rollback also failed: {e2}")
            return False

    print(f"  done: {proj['name']}")
    return True

def first_time_setup():
    print("\n  1) From config  2) Add new")
    choice = input("  Choice [1]: ").strip() or "1"
    proj = choose_project("Choose project:") if choice == "1" else interactive_add_project() if choice == "2" else None
    if not proj:
        return

    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        repo_url = input(f"  Git repo URL: ").strip()
        if not repo_url:
            return
        try:
            step_git_clone(proj, repo_url)
        except DeployError as e:
            print(f"Clone failed: {e}")
            return
    else:
        if confirm("  Run git pull?", default=True):
            try:
                step_git_pull(proj)
            except DeployError as e:
                print(str(e))
                return

    ensure_system_user(proj["user"])
    os.makedirs(get_dest_dir(proj), exist_ok=True)

    env_path = os.path.join(get_dest_dir(proj), ".env")
    if not os.path.isfile(env_path):
        print(f"No .env at {env_path} — create it before starting the service")
        input("  Press Enter to continue...")

    # Rsync first (as root), then chown, then deps/build as service user
    try:
        step_rsync(proj)
    except DeployError as e:
        print(f"Rsync failed: {e}")
        return

    fix_ownership(proj)

    try:
        step_install_deps(proj)
    except DeployError as e:
        print(f"Install deps failed: {e}")
        return

    if proj["type"] == "django":
        try:
            step_django_migrate(proj)
            step_django_collectstatic(proj)
        except DeployError as e:
            print(f"Django step failed: {e}")

    if needs_build(proj):
        try:
            step_build(proj)
        except DeployError as e:
            print(f"Build failed: {e}")
            return

    fix_ownership(proj)

    if needs_service(proj):
        svc_path = os.path.join(SYSTEMD_DIR, proj.get("service", ""))
        if proj.get("service") and not os.path.isfile(svc_path):
            if confirm("  Create systemd service?", default=True):
                create_service_file(proj, interactive=True)
        if confirm("  Start the service?", default=True):
            try:
                restart_service(proj)
            except DeployError as e:
                print(str(e))

    if confirm("  Set up nginx reverse proxy?", default=True):
        try:
            create_nginx_config(proj, interactive=True)
        except DeployError as e:
            print(str(e))

def interactive_add_project():
    print("\n  Define a new project:\n")
    name = input("  Project name (repo dir): ").strip()
    if not name:
        return None

    print(f"  Type: " + " | ".join(f"{i+1}) {t}" for i, t in enumerate(SUPPORTED_TYPES)))
    type_choice = input("  Choice: ").strip()
    try:
        ptype = SUPPORTED_TYPES[int(type_choice) - 1]
    except (ValueError, IndexError):
        print("  Invalid type.")
        return None

    user = input(f"  System user [{ptype}]: ").strip() or ptype
    port_str = input(f"  Port [{'0 (static)' if ptype == 'react' else '3000'}]: ").strip()
    port = int(port_str) if port_str.isdigit() else (0 if ptype == "react" else 3000)
    domain = input("  Domain (e.g. app.example.com): ").strip()

    if ptype == "react":
        service = ""
        entry_point = ""
        build_output = input("  Build output dir [dist]: ").strip() or "dist"
    elif ptype == "fastapi":
        service = input(f"  Service name [{name}.service]: ").strip() or f"{name}.service"
        entry_point = input("  Uvicorn ASGI app [app.main:app]: ").strip() or "app.main:app"
        build_output = ""
    elif ptype == "django":
        service = input(f"  Service name [{name}.service]: ").strip() or f"{name}.service"
        entry_point = input(f"  WSGI module [{DJANGO_DEFAULT_WSGI}]: ").strip() or DJANGO_DEFAULT_WSGI
        build_output = ""
    else:
        service = input(f"  Service name [{name}.service]: ").strip() or f"{name}.service"
        entry_point = input("  Entry point [src/index.js]: ").strip() or "src/index.js"
        build_output = ""

    extra_exc = input("  Extra rsync excludes (comma-sep): ").strip()
    extra_excludes = [e.strip() for e in extra_exc.split(",") if e.strip()] if extra_exc else []

    proj = {
        "name": name, "type": ptype, "user": user, "service": service,
        "entry_point": entry_point, "port": port, "domain": domain,
        "extra_excludes": extra_excludes,
        "build_required": ptype in ("nextapp", "react"),
    }
    if ptype == "django":
        proj["wsgi_module"] = entry_point
        proj["run_migrate"] = True
        proj["run_collectstatic"] = True
        settings = input("  DJANGO_SETTINGS_MODULE [leave empty]: ").strip()
        if settings:
            proj["django_settings"] = settings
    if ptype == "react":
        proj["build_output"] = build_output

    PROJECTS.append(proj)
    print("To persist, add to PROJECTS list in this script.")
    return proj

def show_status():
    print(f"\n{'Name':<40s} {'Type':<9s} {'Service':<38s} {'Status':<12s} {'Port':<6s} {'Bkps'}")
    print("─" * 115)
    for proj in PROJECTS:
        state = "n/a"
        if needs_service(proj) and proj.get("service"):
            try:
                r = run_cmd(["systemctl", "is-active", proj["service"]], check=False, capture=True)
                state = r.stdout.strip() if r.stdout else "unknown"
            except DeployError:
                state = "error"
        elif proj["type"] == "react":
            state = "static"
        color = "\033[32m" if state in ("active", "static") else "\033[31m" if state in ("failed", "inactive") else "\033[33m"
        backups = list_backups(proj)
        port = str(proj.get("port", "-")) if proj.get("port") else "-"
        svc = proj.get("service", "(nginx)") or "(nginx)"
        print(f"{proj['name']:<40s} {proj['type']:<9s} {svc:<38s} {color}{state}\033[0m{'':12s} {port:<6s} {len(backups)}")

def interactive_menu():
    require_root()
    while True:
        print("""

--- Deploy Manager v4.0 ---
fastapi | django | node | next | react

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

  0) Exit""")

        c = input("\nSelect: ").strip()
        try:
            if c == "1":
                p = choose_project(); p and full_deploy(p)
            elif c == "2":
                p = choose_project()
                if p:
                    b = input("  Branch: ").strip()
                    b and full_deploy(p, branch=b)
            elif c == "3":
                p = choose_project()
                if p:
                    h = input("  Commit hash: ").strip()
                    h and full_deploy(p, commit=h)
            elif c == "4":
                first_time_setup()
            elif c == "5":
                p = choose_project(); p and step_git_pull(p)
            elif c == "6":
                p = choose_project()
                if p:
                    b = input("  Branch: ").strip()
                    b and step_git_checkout_branch(p, b)
            elif c == "7":
                p = choose_project(); p and step_rsync(p)
            elif c == "8":
                p = choose_project(); p and step_install_deps(p)
            elif c == "9":
                p = choose_project(); p and step_build(p)
            elif c == "10":
                p = choose_project(); p and fix_ownership(p)
            elif c == "11":
                p = choose_project(); p and restart_service(p)
            elif c == "12":
                p = choose_project(); p and step_django_migrate(p)
            elif c == "13":
                p = choose_project(); p and step_django_collectstatic(p)
            elif c == "14":
                p = choose_project(); p and create_service_file(p, interactive=True)
            elif c == "15":
                p = choose_project()
                if p and p.get("service"):
                    n = input("  Lines [50]: ").strip() or "50"
                    run_cmd(["journalctl", "-u", p["service"], "-n", n, "--no-pager"], check=False)
            elif c == "16":
                p = choose_project(); p and create_nginx_config(p, interactive=True)
            elif c == "17":
                p = choose_project()
                if p and confirm(f"  Remove nginx config for {p['name']}?"):
                    remove_nginx_config(p)
            elif c == "18":
                p = choose_project(); p and create_backup(p)
            elif c == "19":
                p = choose_project()
                if p:
                    bk = list_backups(p)
                    if not bk:
                        print("No backups found")
                    else:
                        print("\n  Available backups:")
                        for i, bp in enumerate(bk, 1):
                            meta_path = os.path.join(bp, ".deploy-meta.json")
                            info = ""
                            if os.path.isfile(meta_path):
                                with open(meta_path) as f:
                                    m = json.load(f)
                                info = f"  {m.get('created_at','?')}  commit={m.get('git_commit','?')[:10]}"
                            print(f"    {i}) {os.path.basename(bp)}{info}")
                        idx = input("  Select (Enter=latest): ").strip()
                        bp = bk[int(idx)-1] if idx.isdigit() and 1 <= int(idx) <= len(bk) else bk[-1]
                        if confirm(f"  Rollback to {os.path.basename(bp)}?"):
                            rollback(p, bp)
            elif c == "20":
                p = choose_project()
                if p:
                    bk = list_backups(p)
                    if not bk:
                        print(f"  No backups for {p['name']}")
                    else:
                        for bp in bk:
                            meta_path = os.path.join(bp, ".deploy-meta.json")
                            info = ""
                            if os.path.isfile(meta_path):
                                with open(meta_path) as f:
                                    m = json.load(f)
                                info = f"  {m.get('created_at','?')}  commit={m.get('git_commit','?')[:10]}"
                            sz = "?"
                            try:
                                r = run_cmd(["du", "-sh", bp], capture=True, check=False)
                                if r.stdout: sz = r.stdout.split()[0]
                            except DeployError: pass
                            print(f"    {os.path.basename(bp)}  size={sz}{info}")
            elif c == "21":
                p = choose_project(); p and rotate_secret(p)
            elif c == "22":
                create_deploy_user()
            elif c == "23":
                list_deploy_users()
            elif c == "24":
                show_status()
            elif c in ("0", ""):
                print("Bye."); sys.exit(0)
            else:
                print("  Invalid choice.")
        except DeployError as e:
            print(f"Error: {e}")
        except KeyboardInterrupt:
            print("\n  Interrupted.")
        except Exception as e:
            print(f"Unexpected error: {e}")

def parse_args():
    p = argparse.ArgumentParser(description="Deploy Manager v4.0")
    p.add_argument("--deploy", metavar="PROJECT")
    p.add_argument("--branch", metavar="BRANCH")
    p.add_argument("--commit", metavar="HASH")
    p.add_argument("--force-branch", action="store_true")
    p.add_argument("--rollback", metavar="PROJECT")
    p.add_argument("--status", action="store_true")
    p.add_argument("--list", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    if args.status:
        show_status(); return
    if args.list:
        print(f"\n{'#':<4} {'Name':<40} {'Type':<9} {'Service':<38} {'Port':<6} {'Domain'}")
        print("─" * 125)
        for i, p in enumerate(PROJECTS, 1):
            svc = p.get("service", "(nginx)") or "(nginx)"
            print(f"{i:<4} {p['name']:<40} {p['type']:<9} {svc:<38} {str(p.get('port','-')):<6} {p.get('domain','-')}")
        return
    if args.deploy:
        require_root()
        proj = find_project_by_name(args.deploy)
        if not proj:
            print(f"Unknown: {args.deploy}")
            sys.exit(1)
        if args.branch and args.commit:
            print("Cannot use both --branch and --commit"); sys.exit(1)
        sys.exit(0 if full_deploy(proj, branch=args.branch, commit=args.commit, force_branch=args.force_branch) else 1)
    if args.rollback:
        require_root()
        proj = find_project_by_name(args.rollback)
        if not proj: print(f"Unknown: {args.rollback}"); sys.exit(1)
        try: rollback(proj)
        except DeployError as e: print(str(e)); sys.exit(1)
        return
    interactive_menu()

if __name__ == "__main__":
    main()