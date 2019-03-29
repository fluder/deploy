import os
import shlex
from copy import copy
from os import getcwd
from subprocess import Popen, PIPE
from threading import Thread

from time import sleep

from paramiko import SSHClient, AutoAddPolicy, RSAKey


class Environment:
    def run(self, cmd, hide=False):
        raise NotImplementedError()

    def reboot(self):
        raise NotImplementedError()

    def cd(self, path):
        raise NotImplementedError()


class LocalEnvironment(Environment):
    def __init__(self):
        self.cwd = getcwd()
        self._env = {}

    def process_stream(self, stream, lines, hide=False):
        for line in line_buffered(stream):
            if not hide:
                print("\033[36m        - [Local] %s\033[0m" % line)
            lines.append(line)

    def run(self, cmd, hide=False):
        if not hide:
            print("\033[36m    - [Local] Executing %s\033[0m" % cmd)
        _env = copy(os.environ)
        for key, value in self._env.items():
            _env[key] = str(value)
        p = Popen(shlex.split(cmd), stdout=PIPE, stderr=PIPE, cwd=self.cwd, env=_env)
        stdout_lines = []
        stderr_lines = []
        stdout_thread = Thread(target=self.process_stream, args=(p.stdout, stdout_lines, hide), daemon=True)
        stderr_thread = Thread(target=self.process_stream, args=(p.stderr, stderr_lines, hide), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        stdout_thread.join()
        stderr_thread.join()
        return {
            "stdout": "\n".join(stdout_lines),
            "stderr": "\n".join(stderr_lines)
        }

    def cd(self, path):
        if not path.startswith("/"):
            self.cwd = os.path.join(self.cwd, path)
        else:
            self.cwd = path

    def add_env(self, key, value):
        self._env[key] = value


def line_buffered(f):
    line_buf = b""
    while True:
        chunk = f.read(1)
        if not chunk:
            break
        line_buf += chunk
        if line_buf.endswith(b"\n"):
            yield line_buf.decode("utf8").strip()
            line_buf = b""


class SSHEnvironment(Environment):
    def __init__(self, hostname, port=22):
        self.hostname = hostname
        self.port = port
        self._client = None
        self.cwd = "/"

    def process_stream(self, stream, lines, hide=False):
        for line in line_buffered(stream):
            if not hide:
                print("\033[32m        - [%s:%s] %s\033[0m" % (self.hostname, self.port, line))
            lines.append(line)

    def run(self, cmd, hide=False, ignore_errors=False):
        if not hide:
            print("\033[32m    - [%s:%s] Executing %s\033[0m" % (self.hostname, self.port, cmd))
        while True:
            try:
                if not self._client:
                    self._client = SSHClient()
                    self._client.set_missing_host_key_policy(AutoAddPolicy())
                    key = RSAKey.from_private_key_file("root.pem")
                    self._client.connect(self.hostname, port=self.port, username="root", pkey=key)
                stdin, stdout, stderr = self._client.exec_command("cd %s; %s; echo $?" % (self.cwd, cmd))
                stdout_lines = []
                stderr_lines = []
                stdout_thread = Thread(target=self.process_stream, args=(stdout, stdout_lines, hide), daemon=True)
                stderr_thread = Thread(target=self.process_stream, args=(stderr, stderr_lines, hide), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
                stdout_thread.join()
                stderr_thread.join()
                try:
                    return_code = int(stdout_lines[-1])
                except Exception:
                    return_code = -1
                if not ignore_errors and return_code:
                    raise RuntimeError("Return code is %s" % return_code)
                return {
                    "stdout": "\n".join(stdout_lines[:-1]),
                    "stderr": "\n".join(stderr_lines)
                }
            except RuntimeError:
                raise
            except Exception as e:
                print("\033[31m%s\033[0m" % e)
                self._client.close()
                self._client = None
                sleep(1)

    def reboot(self):
        up_since = self.run("uptime -s", hide=True)["stdout"]
        self.run("reboot", ignore_errors=True)
        while True:
            if self.run("uptime -s", hide=True)["stdout"] != up_since:
                return

    def cd(self, path):
        if not path.startswith("/"):
            self.cwd = os.path.join(self.cwd, path)
        else:
            self.cwd = path

    def sync(self, local_dir, remote_dir, exclude, delete):
        local_env = LocalEnvironment()
        local_env.run(
            "rsync -v -a -r -e \"ssh -iroot.pem -oStrictHostKeyChecking=no -p%s\" %s%s%s root@%s:%s" % (
                self.port,
                "--delete " if delete else "",
                " ".join(["--exclude=%s" % x for x in exclude]) + " ",
                local_dir,
                self.hostname,
                remote_dir
            )
        )

    def put(self, data, path):
        sftp = self._client.open_sftp()
        fd = sftp.file(path, "wb")
        fd.write(data)
        fd.close()


class EnvironmentFactory:
    _remotes = {}

    @classmethod
    def get_remote(cls, hostname, port=22):
        if (hostname, port) not in cls._remotes.keys():
            cls._remotes[hostname, port] = SSHEnvironment(hostname, port)
        return cls._remotes[hostname, port]

    @staticmethod
    def get_local():
        return LocalEnvironment()
