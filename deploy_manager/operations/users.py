import grp
import os
import pwd
import re

from deploy_manager.config.settings import DEFAULT_SHELL_HUMAN, DEFAULT_SHELL_SERVICE, PROJECTS
from deploy_manager.core.utils import confirm, run_cmd


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
