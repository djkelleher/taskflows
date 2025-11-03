#!/bin/bash
# Fluent Bit startup script with environment defaults
# This script sources the env file and starts Fluent Bit

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the environment file
ENV_FILE="${SCRIPT_DIR}/fluent-bit.env"
if [ -f "$ENV_FILE" ]; then
    echo "Loading environment from: $ENV_FILE"
    source "$ENV_FILE"
else
    echo "Warning: Environment file not found at $ENV_FILE"
    exit 1
fi

# Configuration file path
CONFIG_FILE="${SCRIPT_DIR}/fluent-bit.conf"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found at $CONFIG_FILE"
    exit 1
fi

# Display configuration
echo "Starting Fluent Bit with:"
echo "  LOKI_HOST: ${LOKI_HOST}"
echo "  LOKI_PORT: ${LOKI_PORT}"
echo "  HOSTNAME: ${HOSTNAME}"
echo "  Config: ${CONFIG_FILE}"
echo ""

# Start Fluent Bit
# Pass any additional arguments to fluent-bit
exec fluent-bit -c "$CONFIG_FILE" "$@"
