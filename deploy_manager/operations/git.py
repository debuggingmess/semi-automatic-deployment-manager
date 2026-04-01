import glob
import os
import re

from deploy_manager.config.settings import ALLOWED_PROD_BRANCHES
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import confirm, get_current_user, run_cmd
from deploy_manager.projects.helpers import get_src_dir

_SSH_ERRORS = ("permission denied", "could not read from remote", "host key verification failed")
_SSH_SKIP = {"known_hosts", "known_hosts.old", "authorized_keys", "config", "environment"}


def _find_ssh_keys():
    """Return private key paths from the invoking user's ~/.ssh — no root fallback."""
    user = get_current_user()
    ssh_dir = os.path.join(f"/home/{user}", ".ssh")
    if not os.path.isdir(ssh_dir):
        raise DeployError(f"No .ssh directory found for user '{user}' at {ssh_dir}")
    keys = sorted(
        os.path.join(ssh_dir, f)
        for f in os.listdir(ssh_dir)
        if not f.endswith(".pub")
        and f not in _SSH_SKIP
        and os.path.isfile(os.path.join(ssh_dir, f))
    )
    if not keys:
        raise DeployError(f"No private keys found in {ssh_dir}")
    return keys


def _pick_ssh_key():
    keys = _find_ssh_keys()
    if len(keys) == 1:
        return keys[0]
    print("\n  Available SSH keys:")
    for i, k in enumerate(keys, 1):
        print(f"  {i}) {os.path.basename(k)}")
    choice = input("  Select key [1]: ").strip() or "1"
    if not choice.isdigit() or not (1 <= int(choice) <= len(keys)):
        raise DeployError("Invalid key selection.")
    return keys[int(choice) - 1]


def _ensure_ssh_agent():
    """Eval ssh-agent, add chosen key, return env dict with SSH_AUTH_SOCK/SSH_AGENT_PID."""
    key = _pick_ssh_key()

    # Try existing forwarded/running agent sockets first
    for sock in sorted(glob.glob("/tmp/ssh-*/agent.*"), reverse=True):
        env = {**os.environ, "SSH_AUTH_SOCK": sock}
        run_cmd(["ssh-add", key], env=env, check=False, capture=True)
        test = run_cmd(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-T", "git@github.com"],
            capture=True, check=False, env=env,
        )
        if test.returncode in (0, 1):  # 1 = authed but no shell (GitHub)
            print(f"  ssh-agent: using existing socket {sock} with {os.path.basename(key)}")
            return env

    # Start a fresh agent (equivalent of eval $(ssh-agent -s))
    result = run_cmd(["ssh-agent", "-s"], capture=True, check=False)
    if result.returncode != 0:
        raise DeployError("Failed to start ssh-agent.")
    agent_env = {**os.environ}
    for line in result.stdout.splitlines():
        m = re.match(r"(SSH_AUTH_SOCK|SSH_AGENT_PID)=([^;]+);", line)
        if m:
            agent_env[m.group(1)] = m.group(2)
    if "SSH_AUTH_SOCK" not in agent_env:
        raise DeployError("ssh-agent started but SSH_AUTH_SOCK not found in output.")
    run_cmd(["ssh-add", key], env=agent_env)
    print(f"  ssh-agent: started fresh agent, added {os.path.basename(key)}")
    return agent_env


def _git_cmd(cmd, cwd, env=None):
    """Run a git network command; on SSH failure fix the agent and retry once."""
    result = run_cmd(cmd, cwd=cwd, env=env, capture=True, check=False)
    if result.returncode == 0:
        if result.stdout:
            print(result.stdout.rstrip())
        return
    stderr = (result.stderr or "").lower()
    if any(e in stderr for e in _SSH_ERRORS):
        print("  SSH auth failed — fixing ssh-agent and retrying...")
        agent_env = _ensure_ssh_agent()
        run_cmd(cmd, cwd=cwd, env=agent_env)
    else:
        raise DeployError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}"
            + (f"\n  stderr: {result.stderr.strip()}" if result.stderr else "")
        )


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


def step_git_checkout_branch(proj, branch, force=False):
    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source directory does not exist: {src_dir}")
    _git_cmd(["git", "-c", "core.hooksPath=/dev/null", "fetch", "--all", "--prune"], cwd=src_dir)
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
    _git_cmd(["git", "-c", "core.hooksPath=/dev/null", "pull", "--ff-only"], cwd=src_dir)


def step_git_pin_commit(proj, commit_hash):
    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source directory does not exist: {src_dir}")
    if not re.match(r"^[0-9a-fA-F]{7,40}$", commit_hash):
        raise DeployError(f"Invalid commit hash format: {commit_hash}")
    _git_cmd(["git", "-c", "core.hooksPath=/dev/null", "fetch", "--all"], cwd=src_dir)
    result = run_cmd(["git", "cat-file", "-t", commit_hash], cwd=src_dir, capture=True, check=False)
    if result.returncode != 0 or result.stdout.strip() != "commit":
        raise DeployError(f"Commit '{commit_hash}' not found in {proj['name']}")
    run_cmd(["git", "stash", "--include-untracked"], cwd=src_dir, check=False)
    run_cmd(["git", "-c", "core.hooksPath=/dev/null", "checkout", commit_hash], cwd=src_dir)
    print("  WARNING: detached HEAD, checkout a branch later")


def step_git_pull(proj):
    src_dir = get_src_dir(proj)
    if not os.path.isdir(src_dir):
        raise DeployError(f"Source directory does not exist: {src_dir}")
    _git_cmd(["git", "-c", "core.hooksPath=/dev/null", "pull", "--ff-only"], cwd=src_dir)


def step_git_clone(proj, repo_url):
    src_dir = get_src_dir(proj)
    if os.path.isdir(src_dir):
        return
    _git_cmd(["git", "clone", "-c", "core.hooksPath=/dev/null", repo_url, src_dir], cwd=None)
