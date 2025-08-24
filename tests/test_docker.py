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


def test_container_run_py_function(temp_file, docker_container):
    docker_container.run()
    sleep(2)
    assert temp_file.read_text() == "hello"


def test_docker_run_service(temp_file, docker_container):
    srv = Service(name="services-test", environment=docker_container)
    srv.create()
    srv.start()
    sleep(2)
    assert temp_file.read_text() == "hello"
