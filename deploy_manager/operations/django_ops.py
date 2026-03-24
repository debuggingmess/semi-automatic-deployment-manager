import os

from deploy_manager.core.utils import run_cmd
from deploy_manager.projects.helpers import get_dest_dir, get_venv_bin


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
