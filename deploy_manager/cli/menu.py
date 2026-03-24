import json
import os
import sys

from deploy_manager.config.settings import (
    DJANGO_DEFAULT_WSGI,
    PROJECTS,
    SUPPORTED_TYPES,
    SYSTEMD_DIR,
)
from deploy_manager.cli.commands import full_deploy
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import confirm, require_root, run_cmd
from deploy_manager.operations.backup import create_backup, list_backups, rollback
from deploy_manager.operations.deploy_steps import (
    fix_ownership,
    restart_service,
    step_build,
    step_install_deps,
    step_rsync,
)
from deploy_manager.operations.django_ops import step_django_collectstatic, step_django_migrate
from deploy_manager.operations.git import (
    step_git_checkout_branch,
    step_git_clone,
    step_git_pull,
)
from deploy_manager.operations.nginx import create_nginx_config, nginx_reload, remove_nginx_config
from deploy_manager.operations.secrets import rotate_secret
from deploy_manager.operations.service import create_service_file
from deploy_manager.operations.users import create_deploy_user, ensure_system_user, list_deploy_users
from deploy_manager.projects.helpers import get_dest_dir, get_src_dir, needs_build, needs_service


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
    print("To persist, add to PROJECTS list in deploy_manager/config/settings.py")
    return proj


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
