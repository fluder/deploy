import os

from deploy.environment import EnvironmentFactory
from deploy.kube_manager import KubeManager


def migrate(mode, stack, service, is_rollback=False, revision=None):
    if mode == "dev":
        pass
    elif mode == "prod":
        migrate_prod(stack, service, is_rollback, revision)


def migrate_prod(stack, service, is_rollback, revision):
    container = stack[service]
    root_instance = stack.get_root_instance(stack[service].instance.domain)
    env = EnvironmentFactory.get_remote(root_instance.public_ip)
    instance_env = EnvironmentFactory.get_remote(container.instance.public_ip)
    kube_manager = KubeManager(stack, env)

    print(" - Syncing project files")
    instance_env.run("mkdir -p /home/ubuntu/serv_files")
    instance_env.sync(
        local_dir=".",
        exclude=[".git", "launcher_iso"],
        remote_dir="/home/ubuntu/serv_files",
        delete=True
    )

    print(" - Running migration task")
    host = stack[service].env[stack.vars["migrate_host_field"]]
    port = stack[service].env.get(stack.vars["migrate_port_field"], 5432)
    db = stack[service].env[stack.vars["migrate_db_field"]]
    user = stack[service].env[stack.vars["migrate_user_field"]]
    password = stack[service].env[stack.vars["migrate_password_field"]]

    if not is_rollback:
        cmd = "yoyo apply -b -v --database postgresql://%s:%s@%s:%s/%s" % (
            user, password, host, port, db
        )
    else:
        cmd = "yoyo rollback -b -v --database postgresql://%s:%s@%s:%s/%s" % (
            user, password, host, port, db
        )
    if revision:
        migration_files = os.listdir(os.path.join(stack.vars["project_dir"], container.build, "migrations"))
        for migration_file in migration_files:
            if migration_file.startswith(revision):
                revision = migration_file.rsplit(".py", 1)[0]
                break
        else:
            raise Exception("Unknown revision: %s" % revision)
        cmd += " -r %s" % revision
    cmd += " /mnt"
    print(cmd)

    add_container_parms = {
        "instance": str(container.instance),
        "image": str(container),
        "name": "migrate.%s" % str(container),
        "oneshot": True,
        "volumes": {
            "/mnt": "/home/ubuntu/serv_files/%s/migrations" % container.build
        },
        "cmd": cmd
    }
    kube_manager.stop("migrate.%s" % str(container))
    kube_manager.add_container(**add_container_parms)
    kube_manager.logs("migrate.%s" % service, tail=1000)
    kube_manager.stop("migrate.%s" % str(container))
