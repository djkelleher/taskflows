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
