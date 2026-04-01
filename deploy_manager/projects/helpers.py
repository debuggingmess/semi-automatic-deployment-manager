import os

from deploy_manager.config.settings import (
    DEPLOY_BASES,
    GLOBAL_RSYNC_EXCLUDES,
    PROJECTS,
    SRC_BASE,
    SUPPORTED_TYPES,
    TYPE_META,
    TYPE_RSYNC_EXCLUDES,
)
from deploy_manager.core.exceptions import DeployError


def get_dest_base(proj_type):
    if proj_type not in DEPLOY_BASES:
        raise DeployError(f"Unknown project type: {proj_type}. Supported: {', '.join(SUPPORTED_TYPES)}")
    return DEPLOY_BASES[proj_type]


def get_dest_dir(proj):
    return os.path.join(get_dest_base(proj["type"]), proj["name"])


def get_src_dir(proj):
    return os.path.join(SRC_BASE, proj["name"])


def get_rsync_excludes(proj):
    excludes = list(GLOBAL_RSYNC_EXCLUDES)
    excludes.extend(TYPE_RSYNC_EXCLUDES.get(proj["type"], []))
    excludes.extend(proj.get("extra_excludes", []))
    return excludes


def get_type_meta(proj):
    return TYPE_META.get(proj["type"], {})


def find_project_by_name(name):
    for proj in PROJECTS:
        if proj["name"].lower() == name.lower():
            return proj
    return None


def is_python_type(proj):
    return get_type_meta(proj).get("runtime") == "python"


def is_node_type(proj):
    return get_type_meta(proj).get("runtime") == "node"


def is_compose_type(proj):
    return get_type_meta(proj).get("runtime") == "compose"


def needs_service(proj):
    return get_type_meta(proj).get("needs_service", True)


def needs_build(proj):
    meta = get_type_meta(proj)
    return meta.get("needs_build", False) or proj.get("build_required", False)


def get_venv_dir(proj):
    return os.path.join(get_dest_dir(proj), "venv")


def get_venv_bin(proj, binary):
    return os.path.join(get_venv_dir(proj), "bin", binary)
