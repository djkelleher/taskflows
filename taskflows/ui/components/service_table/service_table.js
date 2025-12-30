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
