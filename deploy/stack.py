import json
import os

from io import StringIO

import yaml
from jinja2 import FileSystemLoader, Environment, PackageLoader


class Domain:
    def __init__(self, value):
        self.value = value
        self.instances = {}
        self.services = {}

    def set_instances(self, instances):
        self.instances = instances
        for instance in instances.values():
            instance.domain = self

    def set_services(self, services):
        self.services = services
        for service in services.values():
            service.domain = self

    def __str__(self):
        return self.value


class Instance:
    def __init__(self, value, public_ip=None, is_root=False, volumes=None):
        self.value = value
        self.domain = None
        self.public_ip = public_ip
        self.is_root = is_root
        self.volumes = volumes or []
        self.containers = {}

    def set_containers(self, containers):
        self.containers = containers
        for container in self.containers.values():
            container.instance = self

    def __str__(self):
        return self.value


class Container:
    def __init__(self, value, build=None, docker_file=None, run=None, volumes=None, env=None, expose=None,
                 is_privileged=False, network=None, mem_limit=None):
        self.value = value
        self.instance = None
        self.build = build
        self.docker_file = docker_file or "Dockerfile"
        self.run = run
        self.volumes = volumes or {}
        self.env = env or {}
        self.expose = expose or {}
        self.is_privileged = is_privileged
        self.network = network or "overlay"
        self.mem_limit = mem_limit or "512M"

    def __str__(self):
        return self.value


class Service:
    def __init__(self, value, containers=None, ports=None, expose=None):
        self.value = value
        self.domain = None
        self.containers = containers or []
        self.ports = ports or {}
        self.expose = expose or {}

    def __str__(self):
        return self.value


def posprocess_dict(d):
    if "<" in d:
        new_d = {}
        if type(d["<"]) is list:
            for x in d["<"]:
                new_d.update(x)
        else:
            new_d.update(d["<"])
        del(d["<"])
        new_d.update(d)
        d = new_d

    for k in list(d.keys()):
        if type(k) is str and k != "<" and k.startswith("<"):
            new_d = {}
            if type(d[k]) is list:
                for x in d[k]:
                    new_d.update(x)
            else:
                new_d.update(d[k])
            del (d[k])
            new_d.update(d[k[1:]])
            d[k[1:]] = new_d

    for k in d:
        if type(d[k]) == dict:
            d[k] = posprocess_dict(d[k])

    return d


class Stack:
    def __init__(self, mode, vault_file, stack_vars_file, stack_file, instance_common_file):
        project_dir = os.getcwd()
        with open(vault_file) as fd:
            self.vault = yaml.load(fd)

        loader = FileSystemLoader('.')
        package_loader = PackageLoader("deploy", ".")
        j2_env = Environment(loader=loader)
        j2_package_env = Environment(loader=package_loader)
        def jsonify(x):
            return json.dumps(x).replace("\n", " ")
        j2_env.filters["jsonify"] = jsonify
        j2_package_env.filters["jsonify"] = jsonify

        stack_vars_j2_template = j2_env.get_template(stack_vars_file)
        buf = StringIO(stack_vars_j2_template.render(**{
            "vault": self.vault,
            "mode": mode,
            "project_dir": project_dir
        }))
        vars = self.vars = yaml.load(buf)
        self.vars["vault"] = self.vault
        self.vars["mode"] = mode
        self.vars["project_dir"] = project_dir

        stack_j2_template = j2_env.get_template(stack_file)
        buf = StringIO(stack_j2_template.render(**self.vars))
        buf.name = stack_file
        class Loader(yaml.SafeLoader):
            def __init__(self, stream):
                super(Loader, self).__init__(stream)

            def include(self, node):
                filename = os.path.join("_stack/", self.construct_scalar(node))
                stack_j2_template = j2_env.get_template(filename)
                buf = StringIO(stack_j2_template.render(**vars))
                buf.name = filename
                return yaml.load(buf, Loader)

            def json(self, node):
                return json.dumps(self.construct_sequence(node, True))

        Loader.add_constructor('!include', Loader.include)
        Loader.add_constructor('!json', Loader.json)
        stack = yaml.load(buf, Loader)
        stack = posprocess_dict(stack)
        instance_common_j2_template = j2_package_env.get_template(instance_common_file)
        buf = StringIO(instance_common_j2_template.render(**self.vars))
        instance_common = yaml.load(buf)

        self.domains = {}
        for domain in stack:
            _instances = stack[domain]["instances"]
            _services = stack[domain]["services"]
            instances = {}
            services = {}
            for service, service_opts in _services.items():
                service = "%s.%s" % (service, domain)
                services[service] = Service(
                    value=service,
                    containers=service_opts.get("containers", []),
                    ports=service_opts.get("ports", {}),
                    expose=service_opts.get("expose", {})
                )

            for instance, instance_opts in _instances.items():
                instance = "%s.%s" % (instance, domain)
                _containers = instance_opts.pop("containers", {}) or {}
                _containers.update(instance_common.get("containers", {}))
                instance_opts["volumes"] = [
                    "%s.%s" % (volume, instance)
                    for volume in instance_common.get("volumes", []) + instance_opts.pop("volumes", [])
                ]
                containers = {}
                for container, container_opts in _containers.items():
                    container = "%s.%s" % (container, instance)
                    container_opts["volumes"] = {
                        volume_in_container: (
                            "%s.%s" % (volume_on_instance, instance) if not volume_on_instance.startswith("/")
                            else volume_on_instance
                        )
                        for volume_in_container, volume_on_instance in container_opts.get("volumes", {}).items()
                    }
                    containers[container] = Container(
                        value=container,
                        build=container_opts.get("build"),
                        docker_file=container_opts.get("docker_file"),
                        run=container_opts.get("run"),
                        volumes=container_opts.get("volumes"),
                        env=container_opts.get("env"),
                        expose=container_opts.get("expose"),
                        is_privileged=container_opts.get("is_privileged") is True,
                        network=container_opts.get("network"),
                        mem_limit=container_opts.get("mem_limit")
                    )

                instances[instance] = Instance(
                    value=instance,
                    public_ip=instance_opts.get("public_ip"),
                    is_root=instance_opts.get("root") is True,
                    volumes=instance_opts.get("volumes")
                )
                instances[instance].set_containers(containers)
            self.domains[domain] = Domain(value=domain)
            self.domains[domain].set_instances(instances)
            self.domains[domain].set_services(services)

    def get_domains(self):
        return self.domains.values()

    def get_instances(self, domain=None):
        domains = [domain] if domain else self.get_domains()
        result = []
        for domain in domains:
            result += list(self.domains[str(domain)].instances.values())
        return result

    def get_root_instance(self, domain):
        for instance in domain.instances.values():
            if instance.is_root:
                return instance

    def __getitem__(self, item):
        if item.count(".") == 0:
            return self.domains[item]
        elif item.count(".") == 1:
            try:
                return self.domains[item.split(".")[-1]].instances[item]
            except Exception:
                pass
            try:
                return self.domains[item.split(".")[-1]].services[item]
            except Exception:
                pass
            raise ValueError("No services or instances found by name %s" % item)
        elif item.count(".") == 2:
            return self.domains[item.split(".")[-1]].instances[item.split(".", 1)[-1]].containers[item]
