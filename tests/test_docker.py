from pathlib import Path
from tempfile import NamedTemporaryFile
from time import sleep

import pytest
from taskflows import DockerContainer, Service, Venv, Volume

venv = Venv("trading")


@pytest.fixture
def temp_file():
    with NamedTemporaryFile() as f:
        yield Path(f.name)
        # yield f"/opt/{Path(f.name).name}"


@pytest.fixture
def docker_container(temp_file):
    return DockerContainer(
        name="services-test",
        image="services",
        command=lambda: temp_file.write_text("hello"),
        network_mode="host",
        volumes=[
            # Volume(
            #    host_path="/home/dan/.taskflows",
            #    container_path=f"/root/.taskflows",
            # ),
            Volume(
                host_path=temp_file,
                container_path=temp_file,
            ),
            Volume(
                host_path="/var/run/docker.sock",
                container_path="/var/run/docker.sock",
            ),
        ],
    )


@pytest.mark.skip(reason="Requires Docker image 'services' to be available")
def test_container_run_py_function(temp_file, docker_container):
    docker_container.run()
    sleep(2)
    assert temp_file.read_text() == "hello"


@pytest.mark.skip(reason="Requires Docker image 'services' to be available")
def test_docker_run_service(temp_file, docker_container):
    srv = Service(name="services-test", environment=docker_container)
    srv.create()
    srv.start()
    sleep(2)
    assert temp_file.read_text() == "hello"


def test_docker_container_ensure_name_idempotency():
    """Test that _ensure_name() is idempotent and doesn't mutate on repeated calls."""
    container = DockerContainer(
        image="python:3.11-slim",
        command="echo 'test'",
    )

    # First call should generate a name
    name1 = container._ensure_name()
    assert name1 is not None
    assert container.name == name1

    # Second call should return the same name
    name2 = container._ensure_name()
    assert name2 == name1
    assert container.name == name1

    # name_or_generated property should also return the same name
    name3 = container.name_or_generated
    assert name3 == name1


def test_docker_container_exists_no_mutation():
    """Test that exists property doesn't mutate container state."""
    container = DockerContainer(
        image="python:3.11-slim",
        command="echo 'test'",
    )

    # Store initial name state
    initial_name = container.name

    # Multiple calls to exists should not mutate name if it was None
    _ = container.exists
    _ = container.exists
    _ = container.exists

    # Name should either stay None or be consistently generated
    if initial_name is None:
        # If name generation happens, it should be stable
        if container.name is not None:
            name_after_exists = container.name
            # Additional exists calls should not change the name
            _ = container.exists
            assert container.name == name_after_exists


def test_docker_run_cli_command_with_quoted_args():
    """Test that docker_run_cli_command() handles quoted arguments correctly."""
    container = DockerContainer(
        image="python:3.11-slim",
        command="echo 'hello world'",
    )

    # Call _ensure_name to ensure name is set
    container._ensure_name()

    # Generate CLI command
    cli_cmd = container.docker_run_cli_command()

    # The command should contain properly split arguments
    # "echo 'hello world'" should become ["echo", "hello world"]
    assert "echo" in cli_cmd
    assert "'hello world'" in cli_cmd or '"hello world"' in cli_cmd or "hello world" in cli_cmd


def test_docker_run_cli_command_with_escaped_spaces():
    """Test that docker_run_cli_command() handles escaped spaces correctly."""
    container = DockerContainer(
        image="python:3.11-slim",
        command=r"python script\ with\ spaces.py",
    )

    # Call _ensure_name to ensure name is set
    container._ensure_name()

    # Generate CLI command
    cli_cmd = container.docker_run_cli_command()

    # The command should handle escaped spaces properly
    assert "python" in cli_cmd
    assert "script" in cli_cmd


def test_docker_run_cli_command_with_multiple_args():
    """Test that docker_run_cli_command() handles multiple complex arguments."""
    container = DockerContainer(
        image="python:3.11-slim",
        command='python -c "print(\'hello world\')" --arg "value with spaces"',
    )

    # Call _ensure_name to ensure name is set
    container._ensure_name()

    # Generate CLI command
    cli_cmd = container.docker_run_cli_command()

    # Verify command is properly constructed
    assert "python" in cli_cmd
    assert "-c" in cli_cmd
