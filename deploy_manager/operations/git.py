import os
import re

from deploy_manager.config.settings import ALLOWED_PROD_BRANCHES
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import confirm, run_cmd
from deploy_manager.projects.helpers import get_src_dir


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
