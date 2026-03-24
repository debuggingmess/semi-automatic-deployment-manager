import json
import os
import shutil

from deploy_manager.config.settings import BACKUP_BASE, BACKUP_RETENTION
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import get_current_user, run_cmd, ts, ts_iso
from deploy_manager.operations.deploy_steps import fix_ownership, restart_service
from deploy_manager.operations.git import get_git_branch, get_git_commit_full
from deploy_manager.projects.helpers import get_dest_dir, get_src_dir, needs_service


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
