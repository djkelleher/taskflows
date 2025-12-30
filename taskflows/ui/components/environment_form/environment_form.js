// Environment form with dynamic fields for full Venv/DockerContainer objects

// Initialize form on page load
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('env-form');
    if (form) {
        form.addEventListener('submit', handleSubmit);
    }

    // Check if we're in edit mode (URL param)
    const urlParams = new URLSearchParams(window.location.search);
    const editEnvName = urlParams.get('name') || urlParams.get('edit');
    if (editEnvName) {
        loadEnvironment(editEnvName);
    }
});

// Toggle between venv and docker fields
function toggleTypeFields(type) {
    const venvFields = document.getElementById('venv-fields');
    const dockerFields = document.getElementById('docker-fields');

    if (type === 'venv') {
        venvFields.classList.remove('hidden');
        dockerFields.classList.add('hidden');
    } else {
        venvFields.classList.add('hidden');
        dockerFields.classList.remove('hidden');
    }
}

// Add volume field
function addVolumeField(hostPath = '', containerPath = '', readOnly = false) {
    const container = document.getElementById('docker-volumes');
    const div = document.createElement('div');
    div.className = 'flex gap-2 items-center volume-field';

    const hostInput = document.createElement('input');
    hostInput.type = 'text';
    hostInput.placeholder = 'Host path';
    hostInput.className = 'flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue';
    hostInput.value = hostPath;
    hostInput.dataset.volumeType = 'host';

    const containerInput = document.createElement('input');
    containerInput.type = 'text';
    containerInput.placeholder = 'Container path';
    containerInput.className = 'flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue';
    containerInput.value = containerPath;
    containerInput.dataset.volumeType = 'container';

    const roLabel = document.createElement('label');
    roLabel.className = 'flex items-center text-sm';
    const roCheckbox = document.createElement('input');
    roCheckbox.type = 'checkbox';
    roCheckbox.className = 'mr-1';
    roCheckbox.checked = readOnly;
    roCheckbox.dataset.volumeType = 'readonly';
    roLabel.appendChild(roCheckbox);
    roLabel.appendChild(document.createTextNode('RO'));

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = 'Remove';
    removeBtn.className = 'btn btn-danger text-sm';
    removeBtn.onclick = () => div.remove();

    div.appendChild(hostInput);
    div.appendChild(containerInput);
    div.appendChild(roLabel);
    div.appendChild(removeBtn);

    container.appendChild(div);
}

// Add port field
function addPortField(containerPort = '', hostPort = '') {
    const container = document.getElementById('docker-ports');
    const div = document.createElement('div');
    div.className = 'flex gap-2 items-center port-field';

    const containerInput = document.createElement('input');
    containerInput.type = 'text';
    containerInput.placeholder = 'Container port (e.g., 8080/tcp)';
    containerInput.className = 'flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue';
    containerInput.value = containerPort;
    containerInput.dataset.portType = 'container';

    const hostInput = document.createElement('input');
    hostInput.type = 'text';
    hostInput.placeholder = 'Host port';
    hostInput.className = 'flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue';
    hostInput.value = hostPort;
    hostInput.dataset.portType = 'host';

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = 'Remove';
    removeBtn.className = 'btn btn-danger text-sm';
    removeBtn.onclick = () => div.remove();

    div.appendChild(containerInput);
    div.appendChild(hostInput);
    div.appendChild(removeBtn);

    container.appendChild(div);
}

// Add environment variable field
function addEnvVarField(key = '', value = '') {
    const container = document.getElementById('docker-env-vars');
    const div = document.createElement('div');
    div.className = 'flex gap-2 items-center env-var-field';

    const keyInput = document.createElement('input');
    keyInput.type = 'text';
    keyInput.placeholder = 'Variable name';
    keyInput.className = 'flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue';
    keyInput.value = key;
    keyInput.dataset.varType = 'key';

    const valueInput = document.createElement('input');
    valueInput.type = 'text';
    valueInput.placeholder = 'Value';
    valueInput.className = 'flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-electric-blue';
    valueInput.value = value;
    valueInput.dataset.varType = 'value';

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = 'Remove';
    removeBtn.className = 'btn btn-danger text-sm';
    removeBtn.onclick = () => div.remove();

    div.appendChild(keyInput);
    div.appendChild(valueInput);
    div.appendChild(removeBtn);

    container.appendChild(div);
}

// Load environment for editing
async function loadEnvironment(name) {
    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch(`/api/environments/${encodeURIComponent(name)}`, {
            headers: {'Authorization': 'Bearer ' + token}
        });

        if (res.status === 401) {
            if (await refreshToken()) {
                return loadEnvironment(name);
            }
            window.location.href = '/login';
            return;
        }

        if (!res.ok) throw new Error('Failed to load environment');

        const namedEnv = await res.json();

        // Set form values
        document.getElementById('env-name').value = namedEnv.name;
        document.getElementById('env-original-name').value = namedEnv.name;
        document.getElementById('env-description').value = namedEnv.description || '';

        const env = namedEnv.environment;

        // Set type and populate fields
        if (namedEnv.type === 'venv') {
            document.getElementById('type-venv').checked = true;
            toggleTypeFields('venv');
            document.getElementById('venv-name').value = env.env_name || '';
        } else {
            document.getElementById('type-docker').checked = true;
            toggleTypeFields('docker');

            // Basic fields
            document.getElementById('docker-image').value = env.image || '';
            document.getElementById('docker-network-mode').value = env.network_mode || '';
            document.getElementById('docker-restart-policy').value = env.restart_policy || 'no';
            document.getElementById('docker-shm-size').value = env.shm_size || '';
            document.getElementById('docker-privileged').checked = env.privileged || false;

            // Volumes
            if (env.volumes && Array.isArray(env.volumes)) {
                for (const v of env.volumes) {
                    addVolumeField(v.host_path, v.container_path, v.read_only || false);
                }
            }

            // Ports
            if (env.ports) {
                for (const [containerPort, hostPort] of Object.entries(env.ports)) {
                    addPortField(containerPort, String(hostPort));
                }
            }

            // Environment variables
            if (env.environment) {
                for (const [key, value] of Object.entries(env.environment)) {
                    addEnvVarField(key, value);
                }
            }
        }

        // Change submit button text
        const submitBtn = document.querySelector('#env-form button[type="submit"]');
        submitBtn.textContent = 'Update Environment';
    } catch (err) {
        console.error('Error loading environment:', err);
        showError('Failed to load environment');
    }
}

// Handle form submission
async function handleSubmit(e) {
    e.preventDefault();

    const name = document.getElementById('env-name').value;
    const originalName = document.getElementById('env-original-name').value;
    const type = document.querySelector('input[name="type"]:checked').value;
    const description = document.getElementById('env-description').value;

    let environment;

    if (type === 'venv') {
        const envName = document.getElementById('venv-name').value;
        if (!envName) {
            showError('Venv name is required');
            return;
        }
        environment = { env_name: envName };
    } else {
        const image = document.getElementById('docker-image').value;
        if (!image) {
            showError('Docker image is required');
            return;
        }

        environment = { image };

        // Network mode
        const networkMode = document.getElementById('docker-network-mode').value;
        if (networkMode) {
            environment.network_mode = networkMode;
        }

        // Restart policy
        const restartPolicy = document.getElementById('docker-restart-policy').value;
        if (restartPolicy && restartPolicy !== 'no') {
            environment.restart_policy = restartPolicy;
        }

        // Shared memory size
        const shmSize = document.getElementById('docker-shm-size').value;
        if (shmSize) {
            environment.shm_size = shmSize;
        }

        // Privileged mode
        const privileged = document.getElementById('docker-privileged').checked;
        if (privileged) {
            environment.privileged = true;
        }

        // Volumes
        const volumes = collectVolumes();
        if (volumes.length > 0) {
            environment.volumes = volumes;
        }

        // Ports
        const ports = collectPorts();
        if (Object.keys(ports).length > 0) {
            environment.ports = ports;
        }

        // Environment variables
        const envVars = collectEnvVars();
        if (Object.keys(envVars).length > 0) {
            environment.environment = envVars;
        }
    }

    const data = {
        name,
        type,
        description: description || null,
        environment,
    };

    try {
        const token = localStorage.getItem('access_token');
        const isEdit = originalName !== '';
        const url = isEdit
            ? `/api/environments/${encodeURIComponent(originalName)}`
            : '/api/environments';
        const method = isEdit ? 'PUT' : 'POST';

        const res = await fetch(url, {
            method,
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        if (res.status === 401) {
            if (await refreshToken()) {
                return handleSubmit(e);
            }
            window.location.href = '/login';
            return;
        }

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to save environment');
        }

        showSuccess(isEdit ? 'Environment updated successfully' : 'Environment created successfully');
        setTimeout(() => {
            window.location.href = '/environments';
        }, 1000);
    } catch (err) {
        console.error('Error saving environment:', err);
        showError('Failed to save environment: ' + err.message);
    }
}

// Collect volumes from form
function collectVolumes() {
    const volumes = [];
    const fields = document.querySelectorAll('.volume-field');

    fields.forEach(field => {
        const hostPath = field.querySelector('[data-volume-type="host"]').value;
        const containerPath = field.querySelector('[data-volume-type="container"]').value;
        const readOnly = field.querySelector('[data-volume-type="readonly"]').checked;
        if (hostPath && containerPath) {
            volumes.push({
                host_path: hostPath,
                container_path: containerPath,
                read_only: readOnly
            });
        }
    });

    return volumes;
}

// Collect ports from form
function collectPorts() {
    const ports = {};
    const fields = document.querySelectorAll('.port-field');

    fields.forEach(field => {
        const containerPort = field.querySelector('[data-port-type="container"]').value;
        const hostPort = field.querySelector('[data-port-type="host"]').value;
        if (containerPort && hostPort) {
            ports[containerPort] = hostPort;
        }
    });

    return ports;
}

// Collect environment variables from form
function collectEnvVars() {
    const envVars = {};
    const fields = document.querySelectorAll('.env-var-field');

    fields.forEach(field => {
        const key = field.querySelector('[data-var-type="key"]').value;
        const value = field.querySelector('[data-var-type="value"]').value;
        if (key) {
            envVars[key] = value;
        }
    });

    return envVars;
}
