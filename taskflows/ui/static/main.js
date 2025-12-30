// Shared utilities for Taskflows UI
// This file contains common functions used across all components

// ===== Authentication Utilities =====

/**
 * Refresh the JWT access token using the refresh token
 * @returns {Promise<boolean>} True if refresh was successful
 */
async function refreshToken() {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) return false;

    try {
        const res = await fetch('/auth/refresh', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({refresh_token: refreshToken})
        });

        if (res.ok) {
            const data = await res.json();
            localStorage.setItem('access_token', data.access_token);
            return true;
        }
    } catch (err) {
        console.error('Token refresh failed:', err);
    }

    return false;
}

/**
 * Get authorization headers for API requests
 * @returns {Object} Headers object with Authorization bearer token
 */
function getAuthHeaders() {
    const token = localStorage.getItem('access_token');
    return {
        'Authorization': 'Bearer ' + token
    };
}

/**
 * Handle authentication errors and redirect to login if needed
 * @param {Response} response - Fetch response object
 * @param {Function} retryFn - Function to retry after token refresh
 * @returns {Promise<boolean>} True if handled and should retry
 */
async function handleAuthError(response, retryFn) {
    if (response.status === 401) {
        if (await refreshToken()) {
            return true; // Caller should retry
        }
        window.location.href = '/login';
        return false;
    }
    return false;
}

// ===== Toast Notification System =====

let toastContainer = null;

/**
 * Initialize toast container (called automatically on first toast)
 */
function initToastContainer() {
    if (toastContainer) return;

    toastContainer = document.createElement('div');
    toastContainer.id = 'toast-container';
    toastContainer.className = 'fixed top-4 right-4 z-50 space-y-2';
    document.body.appendChild(toastContainer);
}

/**
 * Show a toast notification
 * @param {string} message - Message to display
 * @param {string} type - Toast type: 'success', 'error', 'warning', 'info'
 * @param {number} duration - Duration in ms (default 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    initToastContainer();

    const toast = document.createElement('div');
    toast.className = 'min-w-64 px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-slide-in';

    // Set colors based on type
    const colors = {
        success: 'bg-neon-green text-gray-900',
        error: 'bg-neon-red text-white',
        warning: 'bg-yellow-500 text-gray-900',
        info: 'bg-electric-blue text-white'
    };
    toast.className += ' ' + (colors[type] || colors.info);

    // Add icon
    const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
    };
    const icon = document.createElement('span');
    icon.className = 'text-xl font-bold';
    icon.textContent = icons[type] || icons.info;

    // Add message
    const messageEl = document.createElement('span');
    messageEl.className = 'flex-1';
    messageEl.textContent = message;

    // Add close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'text-xl font-bold hover:opacity-70';
    closeBtn.textContent = '×';
    closeBtn.onclick = () => removeToast(toast);

    toast.appendChild(icon);
    toast.appendChild(messageEl);
    toast.appendChild(closeBtn);

    toastContainer.appendChild(toast);

    // Auto-remove after duration
    if (duration > 0) {
        setTimeout(() => removeToast(toast), duration);
    }
}

/**
 * Remove a toast with fade-out animation
 * @param {HTMLElement} toast - Toast element to remove
 */
function removeToast(toast) {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease-out';
    setTimeout(() => toast.remove(), 300);
}

/**
 * Show success toast
 * @param {string} message - Success message
 */
function showSuccess(message) {
    showToast(message, 'success');
}

/**
 * Show error toast
 * @param {string} message - Error message
 */
function showError(message) {
    showToast(message, 'error', 5000); // Errors stay longer
}

/**
 * Show warning toast
 * @param {string} message - Warning message
 */
function showWarning(message) {
    showToast(message, 'warning', 4000);
}

/**
 * Show info toast
 * @param {string} message - Info message
 */
function showInfo(message) {
    showToast(message, 'info');
}

// ===== Utility Functions =====

/**
 * Debounce a function call
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Show a confirmation dialog
 * @param {string} message - Confirmation message
 * @param {string} confirmText - Text for confirm button (default: 'Confirm')
 * @param {string} cancelText - Text for cancel button (default: 'Cancel')
 * @returns {Promise<boolean>} True if confirmed
 */
async function confirm(message, confirmText = 'Confirm', cancelText = 'Cancel') {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center';

        const dialog = document.createElement('div');
        dialog.className = 'bg-white rounded-lg shadow-xl p-6 max-w-md mx-4';

        const messageEl = document.createElement('p');
        messageEl.className = 'text-gray-800 mb-6 text-lg';
        messageEl.textContent = message;

        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'flex gap-3 justify-end';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.textContent = cancelText;
        cancelBtn.onclick = () => {
            overlay.remove();
            resolve(false);
        };

        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn btn-danger';
        confirmBtn.textContent = confirmText;
        confirmBtn.onclick = () => {
            overlay.remove();
            resolve(true);
        };

        buttonContainer.appendChild(cancelBtn);
        buttonContainer.appendChild(confirmBtn);

        dialog.appendChild(messageEl);
        dialog.appendChild(buttonContainer);
        overlay.appendChild(dialog);

        document.body.appendChild(overlay);

        // Focus confirm button
        confirmBtn.focus();

        // Close on ESC
        const handleEsc = (e) => {
            if (e.key === 'Escape') {
                overlay.remove();
                resolve(false);
                document.removeEventListener('keydown', handleEsc);
            }
        };
        document.addEventListener('keydown', handleEsc);
    });
}

/**
 * Sleep for a specified duration
 * @param {number} ms - Milliseconds to sleep
 * @returns {Promise<void>}
 */
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Fetch with automatic retry logic
 * @param {string} url - URL to fetch
 * @param {Object} options - Fetch options
 * @param {number} maxRetries - Maximum number of retries (default 3)
 * @returns {Promise<Response>}
 */
async function fetchWithRetry(url, options = {}, maxRetries = 3) {
    for (let i = 0; i < maxRetries; i++) {
        try {
            const res = await fetch(url, options);

            // Don't retry client errors (4xx)
            if (res.status >= 400 && res.status < 500) {
                return res;
            }

            // Return successful responses
            if (res.ok) {
                return res;
            }

            // Retry server errors (5xx)
            if (i < maxRetries - 1) {
                await sleep(Math.pow(2, i) * 1000); // Exponential backoff
                continue;
            }

            return res;
        } catch (err) {
            if (i === maxRetries - 1) {
                throw err;
            }
            await sleep(Math.pow(2, i) * 1000); // Exponential backoff
        }
    }
}

// Add CSS for toast animations
const style = document.createElement('style');
style.textContent = `
@keyframes slide-in {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.animate-slide-in {
    animation: slide-in 0.3s ease-out;
}
`;
document.head.appendChild(style);


// Environment form with dynamic fields

// Initialize form on page load
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('env-form');
    if (form) {
        form.addEventListener('submit', handleSubmit);
    }

    // Check if we're in edit mode (URL param or data attribute)
    const urlParams = new URLSearchParams(window.location.search);
    const editEnvName = urlParams.get('edit');
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

        // Clear docker fields
        document.getElementById('docker-image').value = '';
        document.getElementById('docker-volumes').innerHTML = '';
    } else {
        venvFields.classList.add('hidden');
        dockerFields.classList.remove('hidden');

        // Clear venv fields
        document.getElementById('venv-name').value = '';
    }
}

// Add volume field
function addVolumeField(hostPath = '', containerPath = '') {
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

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.textContent = 'Remove';
    removeBtn.className = 'btn btn-danger text-sm';
    removeBtn.onclick = () => div.remove();

    div.appendChild(hostInput);
    div.appendChild(containerInput);
    div.appendChild(removeBtn);

    container.appendChild(div);
}

// Add environment variable field
function addEnvVarField(key = '', value = '') {
    const container = document.getElementById('env-vars');
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
            // Token expired, try to refresh
            if (await refreshToken()) {
                return loadEnvironment(name); // Retry after refresh
            }
            window.location.href = '/login';
            return;
        }

        if (!res.ok) throw new Error('Failed to load environment');

        const env = await res.json();

        // Set form values
        document.getElementById('env-name').value = env.name;
        document.getElementById('env-original-name').value = env.name;
        document.getElementById('env-description').value = env.description || '';

        // Set type
        if (env.type === 'venv') {
            document.getElementById('type-venv').checked = true;
            toggleTypeFields('venv');
            document.getElementById('venv-name').value = env.venv_name || '';
        } else {
            document.getElementById('type-docker').checked = true;
            toggleTypeFields('docker');
            document.getElementById('docker-image').value = env.docker_image || '';

            // Load volumes
            if (env.docker_volumes) {
                for (const [host, container] of Object.entries(env.docker_volumes)) {
                    addVolumeField(host, container);
                }
            }
        }

        // Load environment variables
        if (env.env_vars) {
            for (const [key, value] of Object.entries(env.env_vars)) {
                addEnvVarField(key, value);
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

    const data = {
        name,
        type,
        description: description || null,
        env_vars: collectEnvVars(),
    };

    // Add type-specific fields
    if (type === 'venv') {
        data.venv_name = document.getElementById('venv-name').value;
        if (!data.venv_name) {
            showError('Venv name is required');
            return;
        }
    } else {
        data.docker_image = document.getElementById('docker-image').value;
        data.docker_volumes = collectDockerVolumes();
        if (!data.docker_image) {
            showError('Docker image is required');
            return;
        }
    }

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
            // Token expired, try to refresh
            if (await refreshToken()) {
                return handleSubmit(e); // Retry after refresh
            }
            window.location.href = '/login';
            return;
        }

        if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || 'Failed to save environment');
        }

        showSuccess(isEdit ? 'Environment updated successfully' : 'Environment created successfully');
        // Delay redirect to show toast
        setTimeout(() => {
            window.location.href = '/environments';
        }, 1000);
    } catch (err) {
        console.error('Error saving environment:', err);
        showError('Failed to save environment: ' + err.message);
    }
}

// Collect environment variables from form
function collectEnvVars() {
    const envVars = {};
    const fields = document.querySelectorAll('.env-var-field');

    fields.forEach(field => {
        const key = field.querySelector('[data-var-type="key"]').value;
        const value = field.querySelector('[data-var-type="value"]').value;
        if (key && value) {
            envVars[key] = value;
        }
    });

    return Object.keys(envVars).length > 0 ? envVars : null;
}

// Collect docker volumes from form
function collectDockerVolumes() {
    const volumes = {};
    const fields = document.querySelectorAll('.volume-field');

    fields.forEach(field => {
        const host = field.querySelector('[data-volume-type="host"]').value;
        const container = field.querySelector('[data-volume-type="container"]').value;
        if (host && container) {
            volumes[host] = container;
        }
    });

    return Object.keys(volumes).length > 0 ? volumes : null;
}


// Service table with multi-select and real-time updates

let selectedServices = new Set();
let allServices = [];
let pollingInterval = null;

// Initialize table on page load
document.addEventListener('DOMContentLoaded', () => {
    loadServices();
    startPolling();

    // Search functionality with debouncing
    const debouncedSearch = debounce((query) => filterServices(query), 300);
    document.getElementById('service-search').addEventListener('input', (e) => {
        debouncedSearch(e.target.value);
    });
});

// Load services from API
async function loadServices() {
    const loadingIndicator = document.getElementById('loading-indicator');
    loadingIndicator.classList.remove('hidden');

    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch('/api/services?as_json=true', {
            headers: {'Authorization': 'Bearer ' + token}
        });

        if (res.status === 401) {
            // Token expired, try to refresh
            if (await refreshToken()) {
                return loadServices(); // Retry after refresh
            }
            window.location.href = '/login';
            return;
        }

        if (!res.ok) {
            throw new Error('Failed to load services');
        }

        const data = await res.json();
        allServices = data.services || [];
        renderServices(allServices);
    } catch (err) {
        console.error('Error loading services:', err);
        showError('Failed to load services');
    } finally {
        loadingIndicator.classList.add('hidden');
    }
}

// Render services table
function renderServices(services) {
    const tbody = document.getElementById('services-tbody');
    tbody.innerHTML = '';

    if (services.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 6;
        td.className = 'px-4 py-8 text-center text-gray-500';
        td.textContent = 'No services found';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    services.forEach(service => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-50';
        tr.dataset.serviceName = service.name;

        // Checkbox
        const tdCheckbox = document.createElement('td');
        tdCheckbox.className = 'px-4 py-3';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'rounded service-checkbox';
        checkbox.dataset.serviceName = service.name;
        checkbox.checked = selectedServices.has(service.name);
        checkbox.onchange = () => toggleServiceSelection(service.name);
        tdCheckbox.appendChild(checkbox);
        tr.appendChild(tdCheckbox);

        // Service name
        const tdName = document.createElement('td');
        tdName.className = 'px-4 py-3 text-sm font-medium text-gray-900';
        tdName.textContent = service.name;
        tr.appendChild(tdName);

        // Status
        const tdStatus = document.createElement('td');
        tdStatus.className = 'px-4 py-3 text-sm';
        const statusBadge = createStatusBadge(service.status);
        tdStatus.appendChild(statusBadge);
        tr.appendChild(tdStatus);

        // Schedule
        const tdSchedule = document.createElement('td');
        tdSchedule.className = 'px-4 py-3 text-sm text-gray-700';
        tdSchedule.textContent = service.schedule || '-';
        tr.appendChild(tdSchedule);

        // Last run
        const tdLastRun = document.createElement('td');
        tdLastRun.className = 'px-4 py-3 text-sm text-gray-700';
        tdLastRun.textContent = service.last_run || '-';
        tr.appendChild(tdLastRun);

        // Actions
        const tdActions = document.createElement('td');
        tdActions.className = 'px-4 py-3 text-sm space-x-2';
        tdActions.appendChild(createActionButtons(service));
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
    });

    updateBatchButtonsState();
}

// Create status badge
function createStatusBadge(status) {
    const badge = document.createElement('span');
    badge.className = 'px-2 py-1 rounded-full text-xs font-semibold';

    if (status === 'running' || status === 'active') {
        badge.classList.add('bg-neon-green', 'text-gray-900');
        badge.textContent = 'Running';
    } else if (status === 'stopped' || status === 'inactive') {
        badge.classList.add('bg-gray-300', 'text-gray-700');
        badge.textContent = 'Stopped';
    } else if (status === 'failed') {
        badge.classList.add('bg-neon-red', 'text-white');
        badge.textContent = 'Failed';
    } else {
        badge.classList.add('bg-gray-200', 'text-gray-600');
        badge.textContent = status || 'Unknown';
    }

    return badge;
}

// Create action buttons for a service
function createActionButtons(service) {
    const container = document.createElement('div');
    container.className = 'flex gap-2';

    const isRunning = service.status === 'running' || service.status === 'active';

    if (isRunning) {
        const stopBtn = document.createElement('button');
        stopBtn.textContent = 'Stop';
        stopBtn.className = 'px-3 py-1 btn btn-danger text-xs';
        stopBtn.dataset.serviceName = service.name;
        stopBtn.onclick = async (e) => {
            const btn = e.target;
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Stopping...';
            await serviceAction(service.name, 'stop');
            // Button will be updated on next render
        };
        container.appendChild(stopBtn);

        const restartBtn = document.createElement('button');
        restartBtn.textContent = 'Restart';
        restartBtn.className = 'px-3 py-1 btn btn-primary text-xs';
        restartBtn.dataset.serviceName = service.name;
        restartBtn.onclick = async (e) => {
            const btn = e.target;
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Restarting...';
            await serviceAction(service.name, 'restart');
            // Button will be updated on next render
        };
        container.appendChild(restartBtn);
    } else {
        const startBtn = document.createElement('button');
        startBtn.textContent = 'Start';
        startBtn.className = 'px-3 py-1 btn btn-success text-xs';
        startBtn.dataset.serviceName = service.name;
        startBtn.onclick = async (e) => {
            const btn = e.target;
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Starting...';
            await serviceAction(service.name, 'start');
            // Button will be updated on next render
        };
        container.appendChild(startBtn);
    }

    const logsBtn = document.createElement('button');
    logsBtn.textContent = 'Logs';
    logsBtn.className = 'px-3 py-1 btn btn-secondary text-xs';
    logsBtn.onclick = () => window.location.href = `/logs/${service.name}`;
    container.appendChild(logsBtn);

    return container;
}

// Toggle service selection
function toggleServiceSelection(serviceName) {
    if (selectedServices.has(serviceName)) {
        selectedServices.delete(serviceName);
    } else {
        selectedServices.add(serviceName);
    }
    updateBatchButtonsState();
    updateSelectAllCheckbox();
}

// Toggle select all
function toggleSelectAll(checkbox) {
    const checkboxes = document.querySelectorAll('.service-checkbox');
    checkboxes.forEach(cb => {
        const serviceName = cb.dataset.serviceName;
        if (checkbox.checked) {
            selectedServices.add(serviceName);
            cb.checked = true;
        } else {
            selectedServices.delete(serviceName);
            cb.checked = false;
        }
    });
    updateBatchButtonsState();
}

// Update select all checkbox state
function updateSelectAllCheckbox() {
    const selectAllCheckbox = document.getElementById('select-all');
    const checkboxes = document.querySelectorAll('.service-checkbox');
    const totalVisible = checkboxes.length;
    const totalSelected = Array.from(checkboxes).filter(cb => cb.checked).length;

    selectAllCheckbox.checked = totalVisible > 0 && totalSelected === totalVisible;
    selectAllCheckbox.indeterminate = totalSelected > 0 && totalSelected < totalVisible;
}

// Update batch buttons enabled/disabled state
function updateBatchButtonsState() {
    const hasSelection = selectedServices.size > 0;
    document.getElementById('batch-start').disabled = !hasSelection;
    document.getElementById('batch-stop').disabled = !hasSelection;
    document.getElementById('batch-restart').disabled = !hasSelection;
}

// Filter services based on search query
function filterServices(query) {
    const filtered = allServices.filter(service =>
        service.name.toLowerCase().includes(query.toLowerCase())
    );
    renderServices(filtered);
}

// Perform action on a single service
async function serviceAction(serviceName, action) {
    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch(`/api/${action}?match=${encodeURIComponent(serviceName)}&as_json=true`, {
            method: 'POST',
            headers: {'Authorization': 'Bearer ' + token}
        });

        if (res.ok) {
            showSuccess(`Service ${serviceName} ${action} initiated`);
            setTimeout(loadServices, 1000); // Reload after 1 second
        } else {
            throw new Error(`Failed to ${action} service`);
        }
    } catch (err) {
        console.error(`Error performing ${action}:`, err);
        showError(`Failed to ${action} service ${serviceName}`);
    }
}

// Perform batch action
async function batchAction(action) {
    if (selectedServices.size === 0) return;

    const serviceNames = Array.from(selectedServices);

    // Confirmation for destructive actions
    if (action === 'stop' || action === 'restart') {
        const actionVerb = action === 'stop' ? 'stop' : 'restart';
        const confirmed = await confirm(
            `Are you sure you want to ${actionVerb} ${serviceNames.length} service(s)?`,
            actionVerb.charAt(0).toUpperCase() + actionVerb.slice(1),
            'Cancel'
        );
        if (!confirmed) return;
    }

    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch('/api/batch', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                service_names: serviceNames,
                operation: action
            })
        });

        if (res.ok) {
            showSuccess(`Batch ${action} initiated for ${serviceNames.length} service(s)`);
            selectedServices.clear();
            setTimeout(loadServices, 1000);
        } else {
            throw new Error(`Failed to ${action} services`);
        }
    } catch (err) {
        console.error(`Error performing batch ${action}:`, err);
        showError(`Failed to ${action} selected services`);
    }
}

// Start polling for updates
function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(loadServices, 5000); // Poll every 5 seconds
}

// Stop polling
function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    stopPolling();
});
