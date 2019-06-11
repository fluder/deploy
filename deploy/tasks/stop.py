from deploy.environment import EnvironmentFactory, LocalEnvironment
from deploy.kube_manager import KubeManager
from deploy.docker_manager import DockerManager


def stop(mode, stack, service):
    print("\033[1;37;40mRemoving service %s @ %s\033[0m" % (service, mode))
    if mode == "dev":
        return stop_dev(stack, service)
    elif mode == "prod":
        return stop_prod(stack, service)


def stop_dev(stack, service):
    local_env = LocalEnvironment()
    docker_manager = DockerManager(stack, local_env)
    docker_manager.remove_container(service)


def stop_prod(stack, service):
    root_instance = stack.get_root_instance(stack[service].instance.domain)
    env = EnvironmentFactory.get_remote(root_instance.public_ip)
    kube_manager = KubeManager(stack, env)
    kube_manager.stop(service)

