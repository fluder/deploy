import json


def _parse_docker_list(data, fields=None, key=None):
    result = [
        line.strip() if not fields
        else {
            field: value
            for field, value in zip(fields, line.strip().split(","))
        }
        for line in data.split("\n")
        if line.strip()
    ]

    if key:
        result = {
            x[key]: x
            for x in result
        }

    return result


class DockerManager:
    def __init__(self, stack, env):
        self.env = env
        self.stack = stack

    def get_networks(self):
        return _parse_docker_list(
            self.env.run(
                "docker network ls --format \"{{.Name}}\" --filter Label=\"STACK_ID=%s\"" % self.stack.vars["stack_id"],
                hide=True
            )["stdout"]
        )

    def add_network(self, name, subnet=None, gateway=None, driver=None):
        cmd = "docker network create %s --label \"STACK_ID=%s\" " % (name, self.stack.vars["stack_id"])
        if driver:
            cmd += "--driver %s " % driver
        if subnet:
            cmd += "--subnet %s " % subnet
        if gateway:
            cmd += "--gateway %s " % gateway

        self.env.run(cmd)

    def remove_network(self, name):
        self.env.run("docker network rm %s" % name)

    def get_volumes(self):
        return _parse_docker_list(
            self.env.run(
                "docker volume ls --format \"{{.Name}}\" --filter Label=\"STACK_ID=%s\"" % self.stack.vars["stack_id"],
                hide=True
            )["stdout"]
        )

    def add_volume(self, name):
        self.env.run("docker volume create %s --label \"STACK_ID=%s\"" % (name, self.stack.vars["stack_id"]))

    def remove_volume(self, name):
        self.env.run("docker volume rm %s" % name)

    def get_images(self, get_all=False):
        return {
            image: x
            for image, x in _parse_docker_list(
                self.env.run(
                    "docker images --format \"{{ .Repository }},{{ .ID }},{{ .Digest }}\" %s" % (
                        ("--filter Label=\"STACK_ID=%s\"" % self.stack.vars["stack_id"]) if not get_all else ""
                    ),
                    hide=True
                )["stdout"],
                fields=("Name", "Id", "Digest"),
                key="Name"
            ).items()
            if image != "<none>"
        }

    def pull_image(self, name):
        self.env.run("docker pull %s" % name)
        return self.get_images(True)[name.split(':')[0]]

    def build_image(self, path, name, docker_file="Dockerfile"):
        self.env.run(
            "docker build --label \"STACK_ID=%s\" -t %s -f %s/%s %s" % (self.stack.vars["stack_id"], name, path, docker_file, path)
        )
        return self.get_images(True)[name]

    def remove_image(self, name):
        self.env.run("docker rmi %s" % name)


    def get_containers(self):
        container_list = _parse_docker_list(
            self.env.run(
                "docker ps -a --format \"{{ .Names }}\" --filter Label=\"STACK_ID=%s\"" % self.stack.vars["stack_id"],
                hide=True
            )["stdout"]
        )

        return {
            container: json.loads(self.env.run("docker inspect %s" % container, hide=True)["stdout"])[0]
            for container in container_list
        }

    def add_container(self, image, name, privileged=False, network=None, expose=None, restart="always", volumes=None,
                      envs=None, nonce=None, cmd=None, oneshot=False):
        env_string = ""
        for env_name, env_value in (envs or {}).items():
            env_string += "-e %s " % env_name
            self.env.add_env(env_name, env_value)
        volume_string = ""
        for volume_in_container, volume_on_instance in (volumes or {}).items():
            volume_string += "--volume \"%s:%s\" " % (volume_on_instance, volume_in_container)
        expose_string = ""
        for port_in_container, port_on_instance in (expose or {}).items():
            expose_string += "-p %s:%s " % (port_on_instance, port_in_container)

        _cmd = "docker run -d --label \"STACK_ID=%s\" --log-driver=journald " % self.stack.vars["stack_id"]
        if nonce:
            _cmd += "--label \"NONCE=%s\" " % nonce
        _cmd += "--name %s " % name
        if network:
            _cmd += "--network %s " % network
        if restart and not oneshot:
            _cmd += "--restart %s " % restart
        if privileged:
            _cmd += "--privileged "
        if oneshot:
            _cmd += "--rm "
        _cmd += volume_string
        _cmd += env_string
        _cmd += expose_string
        _cmd += image
        if cmd:
            _cmd += " " + cmd

        self.env.run(_cmd)

    def remove_container(self, name):
        self.stop_container(name)
        self.env.run("docker rm %s" % name)

    def stop_container(self, name):
        self.env.run("docker stop %s" % name)

    def start_container(self, name):
        self.env.run("docker start %s" % name)

    def restart_container(self, name):
        self.stop_container(name)
        self.start_container(name)

    def logs(self, name, tail=None):
        while True:
            try:
                self.env.run("docker logs --tail %d -t %s -f" % (int(tail) if tail else 100, name))
                break
            except Exception:
                sleep(1)

    def inspect(self, name):
        self.env.run("docker inspect %s" % name)

    def wipe(self):
        for container in self.get_containers():
            self.remove_container(container)
        for image in self.get_images():
            self.remove_image(image)
        for volume in self.get_volumes():
            self.remove_volume(volume)
        for network in self.get_networks():
            self.remove_network(network)
