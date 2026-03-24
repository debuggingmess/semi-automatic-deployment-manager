import argparse
import sys

from deploy_manager.cli.commands import full_deploy
from deploy_manager.cli.menu import interactive_menu, show_status
from deploy_manager.config.settings import PROJECTS
from deploy_manager.core.exceptions import DeployError
from deploy_manager.core.utils import require_root
from deploy_manager.operations.backup import rollback
from deploy_manager.projects.helpers import find_project_by_name


def parse_args():
    p = argparse.ArgumentParser(description="Deploy Manager v4.0")
    p.add_argument("--deploy", metavar="PROJECT")
    p.add_argument("--branch", metavar="BRANCH")
    p.add_argument("--commit", metavar="HASH")
    p.add_argument("--force-branch", action="store_true")
    p.add_argument("--rollback", metavar="PROJECT")
    p.add_argument("--status", action="store_true")
    p.add_argument("--list", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.status:
        show_status()
        return
    if args.list:
        print(f"\n{'#':<4} {'Name':<40} {'Type':<9} {'Service':<38} {'Port':<6} {'Domain'}")
        print("─" * 125)
        for i, p in enumerate(PROJECTS, 1):
            svc = p.get("service", "(nginx)") or "(nginx)"
            print(f"{i:<4} {p['name']:<40} {p['type']:<9} {svc:<38} {str(p.get('port','-')):<6} {p.get('domain','-')}")
        return
    if args.deploy:
        require_root()
        proj = find_project_by_name(args.deploy)
        if not proj:
            print(f"Unknown: {args.deploy}")
            sys.exit(1)
        if args.branch and args.commit:
            print("Cannot use both --branch and --commit")
            sys.exit(1)
        sys.exit(0 if full_deploy(proj, branch=args.branch, commit=args.commit, force_branch=args.force_branch) else 1)
    if args.rollback:
        require_root()
        proj = find_project_by_name(args.rollback)
        if not proj:
            print(f"Unknown: {args.rollback}")
            sys.exit(1)
        try:
            rollback(proj)
        except DeployError as e:
            print(str(e))
            sys.exit(1)
        return
    interactive_menu()
