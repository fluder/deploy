import pkg_resources
import tempfile
from jinja2 import Template

from deploy.docker_manager import DockerManager
from deploy.environment import LocalEnvironment, EnvironmentFactory
from deploy.kube_manager import KubeManager
from deploy.utils import get_nonce, wait_for_cloud_init
from deploy.tasks.log import log


def deploy(mode, stack, service):
    print("\033[1;37;40mDeploying service %s @ %s\033[0m" % (service, mode))
    if mode == "dev":
        deploy_dev(stack, service)
    elif mode == "prod":
        deploy_prod(stack, service)

    # openvpn_j2_template = Template(pkg_resources.resource_string("deploy", "templates/gateway.ovpn.j2"))
    # rendered_data = None
    # if mode == "prod":
    #     rendered_data = openvpn_j2_template.render(mode=mode, instances=[x.public_ip for x in stack.get_instances().values()])
    # elif mode == "dev":
    #     rendered_data = openvpn_j2_template.render(mode=mode, instances=["127.0.0.1"])
    #
    # if rendered_data:
    #     open("ovpn_%s.ovpn" % mode, "w").write(rendered_data)

    log(mode, stack, service)


def deploy_dev(stack, service):
    local_env = LocalEnvironment()
    docker_manager = DockerManager(stack, local_env)

    for domain in stack.get_domains():
        if str(domain) not in docker_manager.get_networks():
            docker_manager.add_network(str(domain))

    for volume in stack[service].instance.volumes:
        if volume not in docker_manager.get_volumes():
            docker_manager.add_volume(volume)

    container = stack[service]
    volumes = container.volumes
    image_name = None
    if container.build:
        image_name = str(container)
        tmp_dir = tempfile.mktemp()
        local_env.run("cp -R %s %s" % (container.build, tmp_dir))
        modules = local_env.run("ls _common/", hide=True)["stdout"].split("\n")
        for module in modules:
            local_env.run("cp -R _common/%s/%s %s" % (module, module, tmp_dir))
        docker_manager.build_image(tmp_dir, str(container), docker_file=container.docker_file)
        local_env.run("rm -Rf %s" % tmp_dir)
    elif container.run:
        image_name = container.run
        docker_manager.pull_image(container.run)
    image = docker_manager.get_images(get_all=True)[image_name]
    add_container_parms = {
        "image": image_name,
        "name": str(container),
        "privileged": container.is_privileged,
        "network": str(container.instance.domain),
        "volumes": volumes,
        "expose": container.expose,
        "envs": container.env,
    }
    nonce = get_nonce(add_container_parms)

    if (
        str(container) in docker_manager.get_containers() and (
            docker_manager.get_containers()[str(container)]["Config"]["Labels"].get("NONCE") != nonce or
            not docker_manager.get_containers()[str(container)]["Image"].startswith("sha256:%s" % image["Id"])
        )
    ):
        docker_manager.remove_container(str(container))

    if str(container) not in docker_manager.get_containers():
        add_container_parms["nonce"] = nonce
        docker_manager.add_container(**add_container_parms)


def deploy_prod(stack, service):
    if len(service.split(".")) == 2:
        # Deploying service
        root_instance = stack.get_root_instance(stack[service].domain)
        root_env = EnvironmentFactory.get_remote(root_instance.public_ip)
        kube_manager = KubeManager(stack, root_env)
        kube_manager.add_service(service, ports=stack[service].ports, expose=stack[service].expose)
        for container in stack[service].containers:
            kube_manager.label_container(container, "service-%s" % service.rsplit(".", 1)[0], "true")
    elif len(service.split(".")) == 3:
        for instance in stack.get_instances():
            print("\033[1;37;40mBootstraping %s (%s)\033[0m" % (str(instance), instance.public_ip))
            env = EnvironmentFactory.get_remote(instance.public_ip)
            deploy_prod_bootstrap(stack, env, instance)
        # Deploying container
        root_instance = stack.get_root_instance(stack[service].instance.domain)

        print("\033[1;37;40mBuilding docker image\033[0m")
        env = EnvironmentFactory.get_remote(stack[service].instance.public_ip)
        root_env = EnvironmentFactory.get_remote(root_instance.public_ip)
        image = deploy_prod_build_docker_images(stack, env, stack[service])

        print("\033[1;37;40mDeploying service\033[0m")
        env = EnvironmentFactory.get_remote(root_instance.public_ip)
        deploy_prod_initialize_kube_namespaces(stack, env, root_instance.domain)
        deploy_prod_service(stack, env, stack[service], image)


def deploy_prod_bootstrap(stack, env, instance):
    wait_for_cloud_init(env)
    env.run("apt-get install -y software-properties-common", hide=True)
    print(" - Checking for curl")
    if "command not found" in env.run("curl", hide=True, ignore_errors=True)["stderr"]:
        env.run("apt-get install -y curl")

    print(" - Checking for hostname")
    if env.run("hostname", hide=True)["stdout"].strip() != str(instance):
        print(" - Setting up host")
        env.run("echo \"\" >> /etc/hosts")
        env.run("echo \"%s %s\" >> /etc/hosts" % (instance.public_ip, instance))
        env.run("echo %s > /etc/hostname" % str(instance))
        env.run("hostname %s" % str(instance))
        env.reboot()

    #print(" - Checking swap")
    # if not env.run("mount | grep swap", hide=True, ignore_errors=True)["stdout"].strip():
    #     print(" - Setting up swap")
    #     env.run("fallocate -l 2G /swapfile")
    #     env.run("chmod 600 /swapfile")
    #     env.run("mkswap /swapfile")
    #     env.run("swapon /swapfile")

    print(" - Checking for docker")
    if "command not found" in env.run("docker --version", hide=True, ignore_errors=True)["stderr"]:
        print(" - Setting up docker")
        env.run("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -")
        env.run("apt-key fingerprint 0EBFCD88")
        env.run("add-apt-repository \"deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\"")
        env.run("apt-get update -y")
        env.run("apt-get install -y docker-ce")
        env.run("systemctl enable docker")
        env.run("systemctl restart docker")


    print(" - Checking for kubernetes")
    if "command not found" in env.run("kubeadm", hide=True, ignore_errors=True)["stderr"]:
        print(" - Setting up kubernetes")
        env.run("curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add")
        env.run("echo \"deb http://apt.kubernetes.io/ kubernetes-xenial main\" > /etc/apt/sources.list.d/kubernetes.list")
        env.run("apt-get update")
        env.run("apt-get install -y kubelet=1.11.0-00 kubeadm=1.11.0-00 kubectl=1.11.0-00 kubernetes-cni=0.6.0-00")

    if instance.is_root:
        # Master
        if "No such file" in env.run("stat ~/.kube", hide=True, ignore_errors=True)["stderr"]:
            env.run("kubeadm init --token 40iy4i.mg57avb3c9ih1fob --token-ttl 0 --pod-network-cidr=10.244.0.0/16 --ignore-preflight-errors=NumCPU,swap,SystemVerification")
            env.run("mkdir -p $HOME/.kube")
            env.run("cp -i /etc/kubernetes/admin.conf $HOME/.kube/config")
            env.run("kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml")
            env.run("kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/k8s-manifests/kube-flannel-rbac.yml")
            env.run("kubectl taint nodes %s node-role.kubernetes.io/master:NoSchedule-" % str(instance),)
    else:
        # Slave
        if "No such file" in env.run("stat ~/.kube_slave", hide=True, ignore_errors=True)["stderr"]:
            env.run("kubeadm join %s:6443 --token 40iy4i.mg57avb3c9ih1fob --discovery-token-unsafe-skip-ca-verification --ignore-preflight-errors=NumCPU,SystemVerification,swap" % (stack.get_root_instance(instance.domain).public_ip,))
            env.run("touch ~/.kube_slave")


def deploy_prod_initialize_kube_namespaces(stack, env, domain):
    print(" - Creating kubernetes namespaces/labels")
    service = """
    apiVersion: v1
    kind: Service
    metadata:
      namespace: %s
      name: %s
    spec:
      selector:
        subdomain: "true"
      clusterIP: None
      ports:
        - name: foo
          port: 1234
          targetPort: 1234"""
    env.run("kubectl create namespace %s" % str(domain), hide=True, ignore_errors=True)
    for instance in domain.instances.values():
        env.put(service % (str(instance.domain), str(instance).split(".")[0]), "/tmp/svc.yml")
        env.run("kubectl create -f /tmp/svc.yml && sleep 10", hide=True, ignore_errors=True)
        env.run("kubectl taint nodes %s node-role.kubernetes.io/master:NoSchedule-" % str(instance), hide=True, ignore_errors=True)
        env.run("kubectl label node %s node=\"%s\"" % (str(instance), str(instance)), hide=True, ignore_errors=True)


def deploy_prod_build_docker_images(stack, env, container):
    docker_manager = DockerManager(stack, env)

    print(" - Syncing project files")
    env.run("mkdir -p /home/ubuntu/serv_files_orig")
    env.sync(
        local_dir=".",
        exclude=[".git"] + stack.vars.get("rsync_exclude", "").split(";"),
        remote_dir="/home/ubuntu/serv_files_orig",
        delete=True
    )
    env.run("rm -R /home/ubuntu/serv_files", ignore_errors=True)
    env.run("cp -R /home/ubuntu/serv_files_orig /home/ubuntu/serv_files")
    if container.build:
        modules = env.run("ls /home/ubuntu/serv_files_orig/_common/", hide=True, ignore_errors=True)["stdout"].split("\n")
        for module in modules:
            env.run("cp -R /home/ubuntu/serv_files_orig/_common/%s/%s /home/ubuntu/serv_files/%s/%s" % (module, module, container.build, module))
    env.cd("/home/ubuntu/serv_files")

    print(" - Creating volume directories")
    for volume in container.instance.volumes:
        env.run("mkdir -p /srv/volumes/" + volume.replace(".", "-").replace("_", "-"))

    print(" - Building docker image")
    if container.build:
        return docker_manager.build_image(container.build, str(container), docker_file=container.docker_file)
    elif container.run:
        return docker_manager.pull_image(container.run)


def deploy_prod_service(stack, env, container, image):
    print(" - Creating kubernetes pod")
    kube_manager = KubeManager(stack, env)

    env.cd("/home/ubuntu/serv_files")
    volumes = container.volumes
    image_name = container.run or str(container)
    add_container_parms = {
        "instance": str(container.instance),
        "image": image_name,
        "name": str(container),
        "volumes": volumes,
        "expose": container.expose,
        "envs": container.env,
        "privileged": container.is_privileged,
        "host_network": container.network == "host",
        "mem_limit": container.mem_limit
    }
    nonce = get_nonce(add_container_parms)
    containers = kube_manager.get_containers()
    if (
        str(container) in containers and (
            containers[str(container)]["metadata"]["labels"].get("nonce") != nonce or
            not containers[str(container)]["status"] or
            not containers[str(container)]["status"]["imageID"].startswith("docker://sha256:%s" % image["Id"])
        )
    ):
        kube_manager.stop(str(container))

    containers = kube_manager.get_containers()
    if str(container) not in containers:
        add_container_parms["nonce"] = nonce
        kube_manager.add_container(**add_container_parms)
        for service in container.instance.domain.services.values():
            for _container in service.containers:
                if _container == str(container):
                    kube_manager.label_container(str(container), "service-%s" % str(service).rsplit(".", 1)[0], "true")

