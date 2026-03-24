import os
import re

from deploy_manager.config.settings import NGINX_SITES_ENABLED
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import confirm
from deploy_manager.operations.backup import create_backup, rollback
from deploy_manager.operations.deploy_steps import (
    fix_ownership,
    restart_service,
    step_build,
    step_install_deps,
    step_rsync,
)
from deploy_manager.operations.django_ops import step_django_collectstatic, step_django_migrate
from deploy_manager.operations.git import step_git_checkout_branch, step_git_pin_commit, step_git_pull
from deploy_manager.operations.nginx import nginx_reload
from deploy_manager.projects.helpers import needs_build, needs_service


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
