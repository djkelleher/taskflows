import atexit
import base64
import shlex
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Union
from weakref import WeakValueDictionary

import cloudpickle
import docker
from docker.errors import ImageNotFound
from docker.models.containers import Container
from docker.models.images import Image
from docker.types import LogConfig
from docker.types.containers import LogConfigTypesEnum
from dotenv import dotenv_values
from xxhash import xxh32

from .common import logger
from .constraints import CgroupConfig
from .exec import PickledFunction


# Global registry of Docker clients with weak references for cleanup
_docker_clients: Dict[str, docker.DockerClient] = {}


def get_docker_client(user_host: Optional[str] = None) -> docker.DockerClient:
    """Get or create a Docker client.

    FIXED: Removed @lru_cache to prevent connection leaks. Clients are now
    tracked in a global dict and properly closed on application exit.

    Args:
        user_host: Optional SSH host for remote Docker daemon

    Returns:
        Docker client instance
    """
    base_url = f"ssh://{user_host}" if user_host else "unix:///var/run/docker.sock"

    # Reuse existing client if available
    if base_url in _docker_clients:
        client = _docker_clients[base_url]
        try:
            # Verify client is still alive
            client.ping()
            return client
        except Exception:
            # Client is stale, remove it
            try:
                client.close()
            except Exception:
                pass
            del _docker_clients[base_url]

    # Create new client
    client = docker.DockerClient(base_url=base_url)
    _docker_clients[base_url] = client
    return client


@contextmanager
def docker_client_context(user_host: Optional[str] = None):
    """Context manager for Docker client with guaranteed cleanup.

    Use this for one-off operations where you want guaranteed cleanup.
    For long-running operations, use get_docker_client() directly.

    Example:
        with docker_client_context() as client:
            client.containers.run(...)
    """
    client = get_docker_client(user_host)
    try:
        yield client
    finally:
        # Don't close here as it's a shared client
        pass


def cleanup_docker_clients():
    """Close all Docker clients. Called on application exit."""
    for base_url, client in list(_docker_clients.items()):
        try:
            logger.debug(f"Closing Docker client for {base_url}")
            client.close()
        except Exception as e:
            logger.warning(f"Error closing Docker client for {base_url}: {e}")
    _docker_clients.clear()


# Register cleanup on exit
atexit.register(cleanup_docker_clients)


def apply_container_action(
    container_name: str, action: Literal["start", "restart", "stop"]
):
    logger.info(f"{action}ing {container_name} container.")
    client = get_docker_client()
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        logger.error(
            f"Container {container_name} not found. Can not {action} container"
        )
        return
    getattr(container, action)()


@dataclass
class ContainerLimits:
    # Set memory limit for build.
    memory: Optional[int] = None
    # Total memory (memory + swap), -1 to disable swap
    memswap: Optional[int] = None
    # CPU shares (relative weight)
    cpushares: Optional[int] = None
    # CPUs in which to allow execution, e.g., 0-3, 0,1
    cpusetcpus: Optional[str] = None

    def __hash__(self):
        return hash((self.memory, self.memswap, self.cpushares, self.cpusetcpus))


@dataclass
class DockerImage:
    """Docker image."""

    # Image name.
    tag: str
    # Directory that docker build command should be ran in.
    path: str
    # path to Dockerfile relative to `path`.
    dockerfile: str = "Dockerfile"
    # Whether to return the status
    quiet: bool = False
    # Do not use the cache when set to True.
    nocache: Optional[bool] = None
    # Remove intermediate containers.
    rm: bool = True
    # HTTP timeout
    timeout: Optional[int] = None
    # The encoding for a stream. Set to gzip for compressing.
    encoding: Optional[str] = None
    # Downloads any updates to the FROM image in Dockerfiles
    pull: Optional[bool] = None
    # Always remove intermediate containers, even after unsuccessful builds
    forcerm: Optional[bool] = None
    # A dictionary of build arguments
    buildargs: Optional[dict] = None
    # A dictionary of limits applied to each container created by the build process. Valid keys:
    container_limits: Optional[ContainerLimits] = None
    # Size of /dev/shm in bytes. The size must be greater than 0. If omitted the system uses 64MB.
    shmsize: Optional[int] = None
    # A dictionary of labels to set on the image
    labels: Optional[Dict[str, str]] = None
    # A list of images used for build cache resolution.
    cache_from: Optional[list] = None
    # Name of the build-stage to build in a multi-stage Dockerfile
    target: Optional[str] = None
    # networking mode for the run commands during build
    network_mode: Optional[str] = None
    # Squash the resulting images layers into a single layer.
    squash: Optional[bool] = None
    # Extra hosts to add to /etc/hosts in building
    # containers, as a mapping of hostname to IP address.
    extra_hosts: Optional[dict] = None
    # Platform in the format.
    platform: Optional[str] = None
    # Isolation technology used during build. Default: None.
    isolation: Optional[str] = None
    # If True, and if the docker client
    # configuration file (~/.docker/config.json by default)
    # contains a proxy configuration, the corresponding environment
    # variables will be set in the container being built.
    use_config_proxy: Optional[bool] = None

    def __post_init__(self):
        self.path = str(self.path)

    def build(self, force_recreate: bool = False) -> Image:
        client = get_docker_client()
        try:
            img = client.images.get(self.tag)
        except ImageNotFound:
            img = None
        if img is not None:
            if not force_recreate:
                logger.warning(f"Will not recreate image: {self.tag}")
                return img
            logger.warning(f"Removing existing image: {self.tag}")
            client.images.remove(self.tag, force=True)
        logger.info(f"Building image {self.tag}")
        built_img, log = client.images.build(**asdict(self))
        fmt_log = []
        for row in log:
            if "id" in row:
                row_fmt = f"[{row['id']}]"
                if s := row["status"]:
                    row_fmt += f"[{s}]"
                if pd := row.get("progress_detail"):
                    row_fmt += f"[{pd}]"
                if p := row.get("progress"):
                    row_fmt += f"[{p}]"
            elif "stream" in row:
                fmt_log.append(row["stream"])
        fmt_log = "".join(fmt_log)
        logger.info(fmt_log)
        return built_img


@dataclass
class Volume:
    """Docker volume."""

    host_path: Union[Path, str]
    container_path: Union[Path, str]
    read_only: bool = False

    def __post_init__(self):
        self.host_path = str(self.host_path)
        self.container_path = str(self.container_path)

    def __hash__(self):
        return hash((self.host_path, self.container_path, self.read_only))


@dataclass
class Ulimit:
    """System ulimit (system resource limit)."""

    name: str
    soft: Optional[int] = None
    hard: Optional[int] = None

    def __post_init__(self):
        if self.soft is None and self.hard is None:
            raise ValueError("Either `soft` limit or `hard` limit must be set.")

    def __hash__(self):
        return hash((self.name, self.soft, self.hard))


@dataclass
class DockerContainer:
    """Docker container.
    
    Note: Resource constraints must be specified using the `cgroup_config` parameter
    with a CgroupConfig instance. Individual resource parameters have been removed
    in favor of centralized resource management.
    """

    image: Union[str, DockerImage]
    command: Optional[Union[str, Callable[[], None]]] = None
    name: Optional[str] = None
    # do we intend to create the container and start it with 'docker start'?
    persisted: Optional[bool] = None
    # Unified cgroup configuration (preferred method for resource constraints)
    cgroup_config: Optional[CgroupConfig] = None
    network_mode: Optional[
        Literal["bridge", "host", "none", "overlay", "ipvlan", "macvlan"]
    ] = None
    # Restart the container when it exits?
    restart_policy: Literal["no", "always", "unless-stopped", "on-failure"] = "no"
    init: Optional[bool] = None
    detach: Optional[bool] = None
    shm_size: Optional[str] = None
    # Environment variables to set inside
    environment: Optional[Union[Dict[str, str]]] = None
    env_file: Optional[Union[str, Path]] = None
    # Local volumes.
    volumes: Optional[Union[Volume, Sequence[Volume]]] = None
    # List of container names or IDs to get volumes from.
    volumes_from: Optional[List[str]] = None
    # The name of a volume driver/plugin.
    volume_driver: Optional[str] = None
    ulimits: Optional[Union[Ulimit, Sequence[Ulimit]]] = None
    # enable auto-removal of the container on api
    # side when the containeras process exits.
    auto_remove: Optional[bool] = None
    # Block IO weight (relative device weight) in
    # the form of:. [{"Path": "device_path", "Weight": weight}].
    blkio_weight_device: Optional[Dict[str, str]] = None
    # Number of usable CPUs (Windows only).
    cpu_count: Optional[int] = None
    # Usable percentage of the available CPUs
    # (Windows only).
    cpu_percent: Optional[int] = None
    # Limit CPU real-time period in microseconds.
    cpu_rt_period: Optional[int] = None
    # Limit CPU real-time runtime in microseconds.
    cpu_rt_runtime: Optional[int] = None
    # Memory nodes (MEMs) in which to allow execution
    # (,). Only effective on NUMA systems.
    cpuset_mems: Optional[str] = None
    # Expose host resources such as
    # GPUs to the container, as a list ofinstances.
    device_requests: Optional[List[docker.types.DeviceRequest]] = None
    # Set custom DNS servers.
    dns: Optional[List[str]] = None
    # Additional options to be added to the containers resolv.conf file.
    dns_opt: Optional[List[str]] = None
    # DNS search domains.
    dns_search: Optional[List[str]] = None
    # Set custom DNS search domains.
    domainname: Optional[Union[str, List[str]]] = None
    # The entrypoint for the container.
    entrypoint: Optional[Union[str, List[str]]] = None
    # Additional hostnames to resolve inside the
    # container, as a mapping of hostname to IP address.
    extra_hosts: Optional[Dict[str, str]] = None
    # List of additional group names and/or
    # IDs that the container process will run as.
    group_add: Optional[List[str]] = None
    # Specify a test to perform to check that the
    # container is healthy. The dict takes the following keys:
    # TODO this should have it's own type?
    healthcheck: Optional[Dict[str, Any]] = None
    # Optional hostname for the container.
    hostname: Optional[str] = None
    # Run an init inside the container that forwards
    # signals and reaps processes
    init: Optional[bool] = None
    # Path to the docker-init binary
    init_path: Optional[str] = None
    # Set the IPC mode for the container.
    ipc_mode: Optional[str] = None
    # Isolation technology to use. Default:.
    isolation: Optional[str] = None
    # Kernel memory limit
    kernel_memory: Optional[Union[str, int]] = None
    # A dictionary of name-value labels (e.g.) or a list of
    # names of labels to set with empty values (e.g.)
    labels: Optional[Union[Dict[str, str], List[str]]] = None
    # Mapping of links using theformat. The alias is optional.
    # Containers declared in this dict will be linked to the new
    # container using the provided alias. Default:.
    links: Optional[Dict[str, str]] = None
    # LXC config.
    lxc_conf: Optional[dict] = None
    # MAC address to assign to the container.
    mac_address: Optional[str] = None
    # Specification for mounts to be added to
    # the container. More powerful alternative to. Each
    # item in the list is expected to be aobject.
    mounts: Optional[List[docker.types.Mount]] = None
    # The name for this container.
    name: Optional[str] = None
    # CPU quota in units of 1e-9 CPUs.
    nano_cpus: Optional[int] = None
    # Name of the network this container will be connected
    # to at creation time. You can connect to additional networks
    # using. Incompatible with.
    network: Optional[str] = None
    # Disable networking.
    network_disabled: Optional[bool] = None
    # Whether to disable OOM killer.
    oom_kill_disable: Optional[bool] = None
    # If set to, use the host PID
    # inside the container.
    pid_mode: Optional[str] = None
    # Platform in the format.
    # Only used if the method needs to pull the requested image.
    platform: Optional[str] = None
    # Ports to bind inside the container.The keys of the dictionary are the ports to bind inside the
    # container, either as an integer or a string in the form, where the protocol is either,, or.The values of the dictionary are the corresponding ports to
    # open on the host, which can be either:Incompatible withnetwork mode.
    ports: Optional[dict] = None
    # Give extended privileges to this container.
    privileged: Optional[bool] = None
    # Publish all ports to the host.
    publish_all_ports: Optional[bool] = None
    # Runtime to use with this container.
    runtime: Optional[str] = None
    # A list of string values to
    # customize labels for MLS systems, such as SELinux.
    security_opt: Optional[List[str]] = None
    # Size of /dev/shm (e.g.).
    shm_size: Optional[Union[str, int]] = None
    # The stop signal to use to stop the container
    # (e.g.).
    stop_signal: Optional[str] = None
    # Storage driver options per container as a
    # key-value mapping.
    storage_opt: Optional[dict] = None
    # If true andis false, return a log
    # generator instead of a string. Ignored ifis true.
    # Default:.
    stream: Optional[bool] = None
    # Kernel parameters to set in the container.
    sysctls: Optional[dict] = None
    # Temporary filesystems to mount, as a dictionary
    # mapping a path inside the container to options for that path.For example:
    tmpfs: Optional[dict] = None
    # Allocate a pseudo-TTY.
    tty: Optional[bool] = None
    # If, and if the docker client
    # configuration file (by default)
    # contains a proxy configuration, the corresponding environment
    # variables will be set in the container being built.
    use_config_proxy: Optional[bool] = None
    # Sets the user namespace mode for the container
    # when user namespace remapping option is enabled. Supported
    # values are:
    userns_mode: Optional[str] = None
    # Sets the UTS namespace mode for the container.
    # Supported values are:
    uts_mode: Optional[str] = None
    # The version of the API to use. Set toto
    # automatically detect the serveras version. Default:
    version: Optional[str] = None

    def __post_init__(self):
        """Validate security-sensitive fields."""
        # Validate env_file path to prevent directory traversal
        if self.env_file:
            from taskflows.security_validation import validate_env_file_path

            try:
                self.env_file = str(validate_env_file_path(self.env_file, allow_nonexistent=True))
            except Exception as e:
                from taskflows.common import logger

                logger.error(f"Invalid env_file path: {e}")
                raise

    def _ensure_name(self) -> str:
        """Ensure container has a name, generating one if needed."""
        if self.name is None:
            if isinstance(self.image, DockerImage):
                img_name = self.image.tag
            else:
                img_name = self.image.split("/")[-1].split(":")[0]
            command_id = xxh32(str(self.command)).hexdigest()
            self.name = f"{img_name}-{command_id}"
        return self.name

    @property
    def name_or_generated(self) -> str:
        """Get container name, generating if needed."""
        return self._ensure_name()
    

    @property
    def exists(self):
        """Check if container exists.

        WARNING: This check is subject to time-of-check-time-of-use (TOCTOU) race conditions.
        Between checking exists and performing an operation, another process could create or
        delete the container. For robust code, wrap operations in try-except blocks to handle
        docker.errors.NotFound rather than checking exists first.

        Returns:
            bool: True if container exists, False otherwise
        """
        try:
            # Use self.name if already set, otherwise generate it
            name = self.name if self.name else self._ensure_name()
            get_docker_client().containers.get(name)
            return True
        except docker.errors.NotFound:
            return False
        except Exception as e:
            # Other errors (connection issues, etc) should be logged
            logger.warning(f"Error checking if container {self.name} exists: {e}")
            return False

    def create(self, **kwargs) -> Container:
        """Create a Docker container for running a script.

        FIXED: Handles race conditions more gracefully by attempting deletion
        and handling conflicts atomically.

        Args:
            task_name (str): Name of the task the container is for.
            container (Container): container for the task.

        Returns:
            Container: The created Docker container.

        Raises:
            docker.errors.APIError: If container creation fails after cleanup
        """
        # create default container name if one wasn't assigned.
        self._ensure_name()

        # remove any existing container with this name.
        # This is idempotent - delete() handles NotFound gracefully
        self.delete()

        # if image is not build, it must be built.
        if isinstance(self.image, DockerImage):
            self.image.build()
        if self.command and not isinstance(self.command, str):
            self.command = PickledFunction(self.command, self.name, "command")

        # Apply cgroup configuration if present
        cfg = self._apply_cgroup_config(self._params())

        cfg.update(kwargs)
        logger.info(f"Creating Docker container {self.name}: {cfg}")
        client = get_docker_client()

        # Try to create container with automatic retry on common errors
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                return client.containers.create(**cfg)
            except docker.errors.ImageNotFound:
                if isinstance(self.image, DockerImage):
                    raise
                # Pull image and retry
                logger.info(f"Pulling Docker image {self.image}")
                image_and_tag = self.image.split(":")
                if len(image_and_tag) == 1:
                    client.images.pull(self.image)
                else:
                    image, tag = image_and_tag
                    client.images.pull(image, tag=tag)
                # Retry creation after pulling image
                continue
            except docker.errors.APIError as e:
                # Handle conflict error (container already exists despite deletion)
                if "Conflict" in str(e) and attempt < max_attempts - 1:
                    logger.warning(
                        f"Container {self.name} conflict detected (race condition), "
                        f"retrying deletion and creation (attempt {attempt + 1}/{max_attempts})"
                    )
                    # Force delete and retry
                    delete_docker_container(self.name, force=True)
                    continue
                else:
                    # Other API errors or final attempt - propagate
                    raise

        # Shouldn't reach here, but just in case
        raise RuntimeError(f"Failed to create container {self.name} after {max_attempts} attempts")

    def docker_run_cli_command(self) -> str:
        """Build the docker run CLI command string for this container.

        SECURITY: All user-controlled values are escaped using shlex.quote()
        to prevent command injection when the command string is executed.
        """
        import shlex

        # Build docker run command
        cmd = ["docker", "run"]

        # Handle command
        if self.command and not isinstance(self.command, str):
            self.command = f"_run_function {base64.b64encode(cloudpickle.dumps(self.command)).decode('utf-8')}"

        # Container name (user-controlled, must be escaped)
        container_name = self._ensure_name()
        cmd.extend(["--name", shlex.quote(container_name)])

        # Auto-remove container
        cmd.append("--rm")

        # Detach mode (default to True for consistency with previous behavior)
        if self.detach is None or self.detach:
            cmd.append("-d")

        # Network mode (user-controlled, must be escaped)
        if self.network_mode:
            cmd.extend(["--network", shlex.quote(self.network_mode)])

        # Restart policy (user-controlled, must be escaped)
        if self.restart_policy != "no":
            cmd.extend(["--restart", shlex.quote(self.restart_policy)])

        # Init
        if self.init:
            cmd.append("--init")

        # Shared memory size (user-controlled, must be escaped)
        if self.shm_size:
            cmd.extend(["--shm-size", shlex.quote(str(self.shm_size))])

        # Environment variables (CRITICAL: user-controlled, must be escaped)
        env = {}
        if self.environment:
            env.update(self.environment)
        if self.env_file:
            env.update(dotenv_values(self.env_file))
        for key, value in env.items():
            # Escape both key and value to prevent injection
            cmd.extend(["--env", shlex.quote(f"{key}={value}")])
            
        # Volumes (user-controlled paths, must be escaped)
        volumes = [self.volumes] if isinstance(self.volumes, Volume) else self.volumes
        if volumes:
            for v in volumes:
                mode = "ro" if v.read_only else "rw"
                cmd.extend(["-v", shlex.quote(f"{v.host_path}:{v.container_path}:{mode}")])

        # Volumes from (user-controlled, must be escaped)
        if self.volumes_from:
            for vf in self.volumes_from:
                cmd.extend(["--volumes-from", shlex.quote(vf)])

        # Volume driver (user-controlled, must be escaped)
        if self.volume_driver:
            cmd.extend(["--volume-driver", shlex.quote(self.volume_driver)])

        # Ulimits (user-controlled values, must be escaped)
        ulimits = [self.ulimits] if isinstance(self.ulimits, Ulimit) else self.ulimits
        if ulimits:
            for l in ulimits:
                ulimit_str = f"{l.name}="
                if l.soft is not None:
                    ulimit_str += str(l.soft)
                if l.hard is not None:
                    ulimit_str += f":{l.hard}"
                cmd.extend(["--ulimit", shlex.quote(ulimit_str)])

        # Apply cgroup configuration if present
        if self.cgroup_config:
            cgroup_args = self.cgroup_config.to_docker_cli_args()
            # Cgroup args should already be safe, but escape them anyway
            cmd.extend([shlex.quote(arg) if not arg.startswith("--") else arg for arg in cgroup_args])

        # Other container settings (all user-controlled, must be escaped)
        if self.hostname:
            cmd.extend(["--hostname", shlex.quote(self.hostname)])
        if self.domainname:
            cmd.extend(["--domainname", shlex.quote(str(self.domainname))])
        if self.dns:
            for dns_server in self.dns:
                cmd.extend(["--dns", shlex.quote(dns_server)])
        if self.dns_search:
            for domain in self.dns_search:
                cmd.extend(["--dns-search", shlex.quote(domain)])
        if self.dns_opt:
            for opt in self.dns_opt:
                cmd.extend(["--dns-opt", shlex.quote(opt)])
        if self.mac_address:
            cmd.extend(["--mac-address", shlex.quote(self.mac_address)])
        if self.pid_mode:
            cmd.extend(["--pid", shlex.quote(self.pid_mode)])
        if self.ipc_mode:
            cmd.extend(["--ipc", shlex.quote(self.ipc_mode)])
        if self.uts_mode:
            cmd.extend(["--uts", shlex.quote(self.uts_mode)])
        if self.userns_mode:
            cmd.extend(["--userns", shlex.quote(self.userns_mode)])
        if self.privileged:
            cmd.append("--privileged")
        if self.publish_all_ports:
            cmd.append("-P")
        if self.tty:
            cmd.append("-t")
        if self.entrypoint:
            if isinstance(self.entrypoint, list):
                # Escape each element and join
                cmd.extend(["--entrypoint", shlex.quote(" ".join(shlex.quote(e) for e in self.entrypoint))])
            else:
                cmd.extend(["--entrypoint", shlex.quote(str(self.entrypoint))])
            
        # Ports (user-controlled, must be escaped)
        if self.ports:
            for container_port, host_config in self.ports.items():
                if host_config:
                    if isinstance(host_config, dict):
                        host_port = host_config.get('HostPort')
                        host_ip = host_config.get('HostIp', '')
                        if host_ip:
                            cmd.extend(["-p", shlex.quote(f"{host_ip}:{host_port}:{container_port}")])
                        else:
                            cmd.extend(["-p", shlex.quote(f"{host_port}:{container_port}")])
                    else:
                        cmd.extend(["-p", shlex.quote(f"{host_config}:{container_port}")])

        # Log configuration
        cmd.extend(["--log-driver", "journald"])
        cmd.extend(["--log-opt", "tag=docker.{{.Name}}"])

        # Image (user-controlled, must be escaped)
        if isinstance(self.image, DockerImage):
            image_name = self.image.tag
            # Ensure image is built
            self.image.build()
        else:
            image_name = self.image

        cmd.append(shlex.quote(image_name))
        
        # Command
        if self.command:
            # Use shlex.split() for proper shell parsing
            try:
                cmd.extend(shlex.split(self.command))
            except ValueError as e:
                # SECURITY: Do not fall back to unsafe split - fail hard
                raise ValueError(
                    f"Invalid command syntax: {e}. "
                    "Commands must use proper shell quoting. "
                    f"Got: {self.command!r}"
                ) from e
        
        # Return the command string
        return " ".join(cmd)

    def run(self):
        """Run container using the Python Docker API."""
        # Handle command serialization
        if self.command and not isinstance(self.command, str):
            self.command = PickledFunction(self.command, self.name, "command")
        
        cfg = self._params()
        
        # Apply cgroup configuration if present
        self._apply_cgroup_config(cfg)
        
        # Enable auto-removal of the container when it exits
        cfg["auto_remove"] = True
        # Run detached by default (can be overridden by self.detach)
        cfg["detach"] = self.detach if self.detach is not None else True
        
        logger.info(f"Running Docker container {self.name}: {cfg}")
        client = get_docker_client()
        
        # Pull image if not present
        try:
            client.images.get(self.image)
        except docker.errors.ImageNotFound:
            logger.info(f"Pulling Docker image {self.image}")
            image_and_tag = self.image.split(":")
            if len(image_and_tag) == 1:
                client.images.pull(self.image)
            else:
                image, tag = image_and_tag
                client.images.pull(image, tag=tag)
        
        return client.containers.run(**cfg)

    def delete(self):
        """Remove container."""
        delete_docker_container(self.name)

    def _params(self) -> Dict[str, Any]:
        cfg = {k: v for k, v in asdict(self).items() if v is not None}
        # Fields that are internal to our service system and should not be passed to Docker API
        cfg.pop("persisted", None)
        cfg.pop("cgroup_config", None)
        cfg["log_config"] = LogConfig(
            type=LogConfigTypesEnum.JOURNALD,
            config={
                "tag": "docker.{{.Name}}",
                # "labels": "environment,service_type,version",
            },
        )
        restart_policy = cfg.get("restart_policy")
        if isinstance(restart_policy, str):
            cfg["restart_policy"] = {"Name": restart_policy}
        env = cfg.get("environment", {})
        if env_file := cfg.pop("env_file", None):
            env.update(dotenv_values(env_file))
        if env:
            cfg["environment"] = env
        cfg["name"] = self.name
        if self.command and " " in self.command:
            cfg["command"] = self.command.split()
        ulimits = [self.ulimits] if isinstance(self.ulimits, Ulimit) else self.ulimits
        if ulimits:
            cfg["ulimits"] = [
                docker.types.Ulimit(name=l.name, soft=l.soft, hard=l.hard)
                for l in ulimits
            ]
        volumes = [self.volumes] if isinstance(self.volumes, Volume) else self.volumes
        if volumes:
            cfg["volumes"] = {
                v.host_path: {
                    "bind": v.container_path,
                    "mode": "ro" if v.read_only else "rw",
                }
                for v in volumes
            }
        if isinstance(self.image, DockerImage):
            cfg["image"] = self.image.tag
        return cfg

    def _apply_cgroup_config(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Apply cgroup configuration to the container config dictionary using intelligent mapping."""
        if not self.cgroup_config:
            return cfg
        
        # Use the centralized intelligent mapping logic from CgroupConfig
        # This leverages all the smart parameter conversion and precedence rules
        
        # CPU configuration - use intelligent mapping
        if self.cgroup_config.cpu_quota:
            cfg['cpu_quota'] = self.cgroup_config.cpu_quota
        if self.cgroup_config.cpu_period:
            cfg['cpu_period'] = self.cgroup_config.cpu_period
            
        # CPU weight: prefer cpu_shares, fallback to converted cpu_weight
        if self.cgroup_config.cpu_shares:
            cfg['cpu_shares'] = self.cgroup_config.cpu_shares
        elif self.cgroup_config.cpu_weight:
            # Convert systemd weight (1-10000) to Docker shares (~1024 default)
            docker_shares = int((self.cgroup_config.cpu_weight / 100) * 1024)
            cfg['cpu_shares'] = docker_shares
            
        if self.cgroup_config.cpuset_cpus:
            cfg['cpuset_cpus'] = self.cgroup_config.cpuset_cpus

        # Memory configuration - use intelligent mapping
        effective_memory = self.cgroup_config._calculate_effective_memory_limit()
        if effective_memory:
            cfg['mem_limit'] = effective_memory
            
        effective_swap = self.cgroup_config._calculate_effective_swap_limit()
        if effective_swap:
            cfg['memswap_limit'] = effective_swap
            
        effective_reservation = self.cgroup_config._calculate_effective_memory_reservation()
        if effective_reservation:
            cfg['mem_reservation'] = effective_reservation
            
        if self.cgroup_config.memory_swappiness is not None:
            cfg['mem_swappiness'] = self.cgroup_config.memory_swappiness

        # I/O configuration - intelligent mapping
        # I/O weight: prefer blkio_weight, fallback to converted io_weight
        if self.cgroup_config.blkio_weight:
            cfg['blkio_weight'] = self.cgroup_config.blkio_weight
        elif self.cgroup_config.io_weight:
            # Convert systemd IOWeight (1-10000) to Docker blkio-weight (10-1000)
            docker_blkio = max(10, min(1000, int(self.cgroup_config.io_weight / 10)))
            cfg['blkio_weight'] = docker_blkio
            
        # Device bandwidth and IOPS limits (direct mapping)
        if self.cgroup_config.device_read_bps:
            cfg['device_read_bps'] = [f"{dev}:{bps}" for dev, bps in self.cgroup_config.device_read_bps.items()]
        if self.cgroup_config.device_write_bps:
            cfg['device_write_bps'] = [f"{dev}:{bps}" for dev, bps in self.cgroup_config.device_write_bps.items()]
        if self.cgroup_config.device_read_iops:
            cfg['device_read_iops'] = [f"{dev}:{iops}" for dev, iops in self.cgroup_config.device_read_iops.items()]
        if self.cgroup_config.device_write_iops:
            cfg['device_write_iops'] = [f"{dev}:{iops}" for dev, iops in self.cgroup_config.device_write_iops.items()]
            
        # Process limits
        if self.cgroup_config.pids_limit:
            cfg['pids_limit'] = self.cgroup_config.pids_limit
            
        # Security and isolation
        if self.cgroup_config.oom_score_adj is not None:
            cfg['oom_score_adj'] = self.cgroup_config.oom_score_adj
        if self.cgroup_config.read_only_rootfs:
            cfg['read_only'] = self.cgroup_config.read_only_rootfs
        if self.cgroup_config.cap_add:
            cfg['cap_add'] = self.cgroup_config.cap_add
        if self.cgroup_config.cap_drop:
            cfg['cap_drop'] = self.cgroup_config.cap_drop
        if self.cgroup_config.devices:
            cfg['devices'] = self.cgroup_config.devices
            
        # Environment and execution settings
        if self.cgroup_config.environment:
            env = cfg.get('environment', {})
            env.update(self.cgroup_config.environment)
            cfg['environment'] = env
        if self.cgroup_config.user:
            cfg['user'] = self.cgroup_config.user
        if self.cgroup_config.group:
            cfg['group'] = self.cgroup_config.group
        if self.cgroup_config.working_dir:
            cfg['working_dir'] = self.cgroup_config.working_dir
            
        # Apply timeouts
        if self.cgroup_config.timeout_stop:
            cfg['stop_timeout'] = self.cgroup_config.timeout_stop
            
        return cfg


def delete_docker_container(container_name: str, force: bool = True) -> bool:
    """Remove container.

    Args:
        container_name (str): Name of container to remove.
    """
    try:
        container = get_docker_client().containers.get(container_name)
    except docker.errors.NotFound:
        return False
    container.remove(force=force)
    logger.info(f"Removed Docker container: {container_name}")
    return True
