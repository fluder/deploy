from deploy.tasks.stop import stop_dev, stop_prod
from deploy.tasks.deploy import deploy_dev, deploy_prod


def restart(mode, stack, service):
    print("\033[1;37;40mRemoving service %s @ %s\033[0m" % (service, mode))
    if mode == "dev":
        return restart_dev(stack, service)
    elif mode == "prod":
        return restart_prod(stack, service)


def restart_dev(stack, service):
    stop_dev(stack, service)
    deploy_dev(stack, service)


def restart_prod(stack, service):
    stop_prod(stack, service)
    deploy_prod(stack, service)

