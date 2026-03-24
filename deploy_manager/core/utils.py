import datetime
import getpass
import os
import subprocess
import sys

from deploy_manager.core.exceptions import DeployError


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


def ts():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def ts_iso():
    return datetime.datetime.now().isoformat()


def get_current_user():
    return os.environ.get("SUDO_USER", getpass.getuser())
