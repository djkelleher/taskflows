"""Environment form component for creating/editing named environments."""
from pathlib import Path

from dominate import tags as e
from dominate.util import raw

from ui.components.component import component

here = Path(__file__).parent


class environment_form(component):
    """Form for creating and editing named environments."""

    js_files = {here / "environment_form.js"}

    def __init__(self, **kwargs):
        super().__init__("div", _class="w-full max-w-2xl mx-auto", **kwargs)

        with self:
            # Form
            with e.form(id="env-form", _class="space-y-6 bg-white p-6 rounded-lg shadow-md"):
                # Name field
                with e.div():
                    e.label(
                        "Environment Name",
                        _for="env-name",
                        _class="block text-sm font-medium mb-2 text-gray-700",
                    )
                    e.input_(
                        type="text",
                        id="env-name",
                        name="name",
                        required=True,
                        _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                        placeholder="my-environment",
                    )

                # Type selector
                with e.div():
                    e.label(
                        "Environment Type",
                        _class="block text-sm font-medium mb-2 text-gray-700",
                    )
                    with e.div(_class="flex gap-4"):
                        with e.label(_class="flex items-center"):
                            e.input_(
                                type="radio",
                                name="type",
                                value="venv",
                                id="type-venv",
                                _class="mr-2",
                                checked=True,
                                onchange="toggleTypeFields('venv')",
                            )
                            e.span("Virtual Environment (venv)")

                        with e.label(_class="flex items-center"):
                            e.input_(
                                type="radio",
                                name="type",
                                value="docker",
                                id="type-docker",
                                _class="mr-2",
                                onchange="toggleTypeFields('docker')",
                            )
                            e.span("Docker Container")

                # Venv fields (shown by default)
                with e.div(id="venv-fields", _class="space-y-4"):
                    with e.div():
                        e.label(
                            "Venv Name",
                            _for="venv-name",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.input_(
                            type="text",
                            id="venv-name",
                            name="env_name",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                            placeholder="my-venv",
                        )

                # Docker fields (hidden by default)
                with e.div(id="docker-fields", _class="hidden space-y-4"):
                    # Docker Image
                    with e.div():
                        e.label(
                            "Docker Image",
                            _for="docker-image",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.input_(
                            type="text",
                            id="docker-image",
                            name="image",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                            placeholder="python:3.11",
                        )

                    # Network Mode
                    with e.div():
                        e.label(
                            "Network Mode",
                            _for="docker-network-mode",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        with e.select(
                            id="docker-network-mode",
                            name="network_mode",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                        ):
                            e.option("Default (bridge)", value="")
                            e.option("bridge", value="bridge")
                            e.option("host", value="host")
                            e.option("none", value="none")
                            e.option("overlay", value="overlay")
                            e.option("ipvlan", value="ipvlan")
                            e.option("macvlan", value="macvlan")

                    # Restart Policy
                    with e.div():
                        e.label(
                            "Restart Policy",
                            _for="docker-restart-policy",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        with e.select(
                            id="docker-restart-policy",
                            name="restart_policy",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                        ):
                            e.option("no", value="no")
                            e.option("always", value="always")
                            e.option("unless-stopped", value="unless-stopped")
                            e.option("on-failure", value="on-failure")

                    # Shared Memory Size
                    with e.div():
                        e.label(
                            "Shared Memory Size",
                            _for="docker-shm-size",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.input_(
                            type="text",
                            id="docker-shm-size",
                            name="shm_size",
                            _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                            placeholder="e.g., 2g, 512m",
                        )

                    # Privileged Mode
                    with e.div(_class="flex items-center"):
                        e.input_(
                            type="checkbox",
                            id="docker-privileged",
                            name="privileged",
                            _class="mr-2 h-4 w-4",
                        )
                        e.label(
                            "Privileged Mode",
                            _for="docker-privileged",
                            _class="text-sm font-medium text-gray-700",
                        )

                    # Volumes
                    with e.div():
                        e.label(
                            "Volumes",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.div(id="docker-volumes", _class="space-y-2")
                        e.button(
                            "+ Add Volume",
                            type="button",
                            _class="btn btn-secondary text-sm",
                            onclick="addVolumeField()",
                        )

                    # Ports
                    with e.div():
                        e.label(
                            "Port Mappings",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.div(id="docker-ports", _class="space-y-2")
                        e.button(
                            "+ Add Port",
                            type="button",
                            _class="btn btn-secondary text-sm",
                            onclick="addPortField()",
                        )

                    # Environment variables
                    with e.div():
                        e.label(
                            "Environment Variables",
                            _class="block text-sm font-medium mb-2 text-gray-700",
                        )
                        e.div(id="docker-env-vars", _class="space-y-2")
                        e.button(
                            "+ Add Variable",
                            type="button",
                            _class="btn btn-secondary text-sm",
                            onclick="addEnvVarField()",
                        )

                # Description
                with e.div():
                    e.label(
                        "Description (optional)",
                        _for="env-description",
                        _class="block text-sm font-medium mb-2 text-gray-700",
                    )
                    e.textarea(
                        id="env-description",
                        name="description",
                        rows="3",
                        _class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue",
                        placeholder="Describe this environment...",
                    )

                # Hidden field for edit mode
                e.input_(type="hidden", id="env-original-name", value="")

                # Submit buttons
                with e.div(_class="flex gap-4 justify-end pt-4"):
                    e.button(
                        "Cancel",
                        type="button",
                        _class="btn btn-secondary",
                        onclick="window.location.href='/environments'",
                    )
                    e.button(
                        "Save Environment",
                        type="submit",
                        _class="btn btn-primary",
                    )
