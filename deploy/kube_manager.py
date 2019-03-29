import json
import shlex

from time import sleep


class KubeManager:
    def __init__(self, stack, env):
        self.stack = stack
        self.env = env

    def get_containers(self):
        result = json.loads(self.env.run("kubectl get pods -o json", hide=True)["stdout"])

        return {
            item["metadata"]["name"]: item["spec"]["containers"][0]
            for item in result["items"]
        }

    def add_container(self, image, name, instance, privileged=False, network=None, expose=None, restart="always", volumes=None,
                      envs=None, nonce=None, host_network=False, mem_limit=None, oneshot=False, cmd=None):
        #env.run("kubectl label nodes %s node=%s" % (instance, instance))
        desc = {
            "kind": "Pod",
            "apiVersion": "v1",
            "metadata": {
                "name": name.rsplit(".", 1)[0],
                "namespace": name.rsplit(".", 1)[1],
                "labels": {
                    "subdomain": "true",
                    "name": name.rsplit(".", 1)[0]
                }
            },
            "spec": {
                "hostNetwork": host_network,
                "dnsPolicy": "ClusterFirst",
                "hostname": name.split(".")[0],
                "subdomain": name.split(".")[1],
                "containers": [
                    {
                        "name": name.rsplit(".", 1)[0].replace(".", "-"),
                        "image": image,
                        "resources": {
                            "limits": {
                                "memory": mem_limit
                            }
                        } if mem_limit is not None else {},
                        "terminationMessagePath": "/dev/termination-log",
                        "terminationMessagePolicy": "File",
                        "imagePullPolicy": "IfNotPresent",
                        "securityContext": {
                            "privileged": privileged
                        },
                        "env": [
                            {
                                "name": key,
                                "value": str(value)
                            }
                            for key, value in (envs or {}).items()
                        ]
                    }
                ],
                "restartPolicy": "Always",
                "terminationGracePeriodSeconds": 30,
                "nodeSelector": {
                    "node": instance
                },
                "schedulerName": "default-scheduler"
            },
            "status": {}
        }
        if oneshot:
            desc["spec"]["restartPolicy"] = "Never"
        if cmd:
            desc["spec"]["containers"][0]["command"] = shlex.split(cmd)

        if volumes:
            desc["spec"]["volumes"] = [
                {
                    "name": volume_on_instance.replace(".", "-").replace("_", "-").replace("/", ""),
                    "hostPath": {
                        "path": ("/srv/volumes/" + volume_on_instance.replace(".", "-").replace("_", "-")) if "/" not in volume_on_instance else volume_on_instance,
                        "type": "Directory"
                    }
                }
                for volume_in_container, volume_on_instance in volumes.items()
            ]
            desc["spec"]["containers"][0]["volumeMounts"] = [
                {
                    "mountPath": volume_in_container,
                    "name": volume_on_instance.replace(".", "-").replace("_", "-").replace("/", "")
                }
                for volume_in_container, volume_on_instance in volumes.items()
            ]

        self.env.run("cat /dev/null > /tmp/pod.json", hide=True)
        self.env.put(json.dumps(desc), "/tmp/pod.json")
        cmd = "kubectl create -f /tmp/pod.json"
        self.env.run(cmd, ignore_errors=True)
        if expose and not host_network:
            for target_port, port in expose.items():
                self.env.run(
                    "kubectl delete service %s-%s --namespace=%s" % (
                        name.rsplit(".", 1)[0].replace(".", "-"),
                        target_port,
                        name.rsplit(".", 1)[1]
                    ),
                    hide=True,
                    ignore_errors=True
                )
                self.env.run(
                    "kubectl expose pod %s --port=%s --target-port=%s --namespace=%s --name=%s-%s --external-ip=%s" % (
                        name.rsplit(".", 1)[0],
                        port,
                        target_port,
                        name.rsplit(".", 1)[1],
                        name.rsplit(".", 1)[0].replace(".", "-"),
                        target_port,
                        self.stack[instance].public_ip
                    ),
                    hide=True,
                    ignore_errors=True
                )


    def remove_container(self, name):
        # stop_container(name)
        # env.run("docker rm %s" % name, show=True)
        pass


    def logs(self, service, tail=100):
        while True:
            try:
                self.env.run(
                    "kubectl logs %s -f --tail=%s --namespace=%s --timestamps=true" % (
                        service.rsplit(".", 1)[0],
                        tail,
                        service.rsplit(".", 1)[1]
                    )
                )
                break
            except Exception:
                sleep(1)



    def stop(self, service):
        self.env.run(
            "kubectl delete pod %s --namespace=%s" % (
                service.rsplit(".", 1)[0],
                service.rsplit(".", 1)[1]
            ),
            ignore_errors=True
        )