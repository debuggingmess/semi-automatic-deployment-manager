import os

from deploy_manager.config.settings import DEFAULT_PYTHON_BIN
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import run_cmd
from deploy_manager.projects.helpers import (
    get_dest_dir,
    get_rsync_excludes,
    get_src_dir,
    get_venv_bin,
    get_venv_dir,
    is_node_type,
    is_python_type,
    needs_build,
    needs_service,
)


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
