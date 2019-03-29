from deploy.environment import EnvironmentFactory, LocalEnvironment
from deploy.kube_manager import KubeManager
from deploy.docker_manager import DockerManager


def log(mode, stack, service, tail=None):
    print("\033[1;37;40mGetting logs of service %s @ %s\033[0m" % (service, mode))
    tail = tail or 100
    if mode == "dev":
        return log_dev(stack, service, tail)
    elif mode == "prod":
        return log_prod(stack, service, tail)


def log_dev(stack, service, tail):
    local_env = LocalEnvironment()
    docker_manager = DockerManager(stack, local_env)
    docker_manager.logs(service, tail)


def log_prod(stack, service, tail):
    env = EnvironmentFactory.get_remote(stack[service].instance.public_ip)
    kube_manager = KubeManager(stack, env)
    kube_manager.logs(service, tail=tail)
