"""Deployment tool.

Usage:
  d [dev] deploy <service>
  d [dev] stop <service>
  d [dev] (log|logs) <service> [--tail=<lines>]
  d [dev] migrate [rollback] <service> [--rev=<rev>]{extend}

Options:
  -h --help     Show this screen.
  --version     Show version.
"""
from docopt import docopt

from deploy.stack import Stack
from deploy.tasks.deploy import deploy
from deploy.tasks.log import log
from deploy.tasks.stop import stop
from deploy.tasks.migrate import migrate


def main():
    arguments = docopt(__doc__.format(extend=""), version="1.0")
    mode = "dev" if arguments["dev"] else "prod"

    stack = Stack(
        mode,
        vault_file="vault.yml",
        stack_vars_file="stack_vars.yml",
        stack_file="stack.yml",
        instance_common_file="templates/instance_common.yml"
    )

    if arguments["deploy"]:
        deploy(mode, stack, arguments["<service>"])
    elif arguments["stop"]:
        stop(mode, stack, arguments["<service>"])
    elif arguments["log"] or arguments["logs"]:
        log(mode, stack, arguments["<service>"], arguments["--tail"])
    elif arguments["migrate"]:
        migrate(mode, stack, arguments["<service>"], arguments["rollback"], arguments["--rev"])
