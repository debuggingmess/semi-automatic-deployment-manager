import os
import secrets
import shutil
import string

from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import confirm, run_cmd, ts
from deploy_manager.operations.deploy_steps import restart_service
from deploy_manager.projects.helpers import get_dest_dir, needs_service


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
    rotate_keys = proj.get("rotate_keys", [])
    for idx, (i, key, value) in enumerate(secret_keys, start=1):
        marker = " *" if key in rotate_keys else ""
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
