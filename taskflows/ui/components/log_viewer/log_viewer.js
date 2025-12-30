// Log viewer with search and auto-scroll functionality

let autoScroll = true;
let logLines = 1000;
let allLogs = '';
let pollingInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadLogs();
    startPolling();

    // Add debounced search functionality
    const debouncedSearch = debounce((query) => searchLogs(query), 300);
    const searchInput = document.getElementById('log-search');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            debouncedSearch(e.target.value);
        });
    }
});

// Load logs from API
async function loadLogs() {
    const serviceName = document.getElementById('service-name').value;
    const logContent = document.getElementById('log-content');

    try {
        const token = localStorage.getItem('access_token');
        const res = await fetch(
            `/api/logs?service_name=${encodeURIComponent(serviceName)}&n_lines=${logLines}&as_json=true`,
            {
                headers: {'Authorization': 'Bearer ' + token}
            }
        );

        if (res.status === 401) {
            // Token expired, try to refresh
            if (await refreshToken()) {
                return loadLogs(); // Retry after refresh
            }
            window.location.href = '/login';
            return;
        }

        if (!res.ok) {
            throw new Error('Failed to load logs');
        }

        const data = await res.json();
        allLogs = data.logs || '';

        // Apply current search filter if any
        const searchQuery = document.getElementById('log-search').value;
        if (searchQuery) {
            searchLogs(searchQuery);
        } else {
            logContent.textContent = allLogs;
        }

        if (autoScroll) {
            scrollToBottom();
        }
    } catch (err) {
        console.error('Error loading logs:', err);
        showError(`Failed to load logs: ${err.message}`);
        logContent.textContent = `Error loading logs: ${err.message}`;
    }
}

// Update log lines
function updateLogLines(lines) {
    logLines = parseInt(lines);
    loadLogs();
}

// Toggle auto-scroll
function toggleAutoScroll(enabled) {
    autoScroll = enabled;
    if (autoScroll) {
        scrollToBottom();
    }
}

// Search logs
function searchLogs(query) {
    const logContent = document.getElementById('log-content');

    if (!query) {
        logContent.textContent = allLogs;
        return;
    }

    const lines = allLogs.split('\n');
    const filtered = lines.filter(line =>
        line.toLowerCase().includes(query.toLowerCase())
    );

    logContent.textContent = filtered.join('\n');

    if (autoScroll) {
        scrollToBottom();
    }
}

// Scroll to bottom of log container
function scrollToBottom() {
    const container = document.getElementById('log-container');
    container.scrollTop = container.scrollHeight;
}

// Download logs
function downloadLogs() {
    const serviceName = document.getElementById('service-name').value;
    const blob = new Blob([allLogs], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${serviceName}_logs.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// Start polling for log updates
function startPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(loadLogs, 3000); // Poll every 3 seconds
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
