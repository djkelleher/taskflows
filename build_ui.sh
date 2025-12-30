#!/bin/bash
# Build the Taskflows UI

set -e

# Create quant shim for build process
mkdir -p /tmp/quant_shim/quant/utils/infra

cat > /tmp/quant_shim/quant/__init__.py << 'EOF'
EOF

cat > /tmp/quant_shim/quant/utils/__init__.py << 'EOF'
EOF

cat > /tmp/quant_shim/quant/utils/infra/__init__.py << 'EOF'
EOF

cat > /tmp/quant_shim/quant/utils/infra/logger.py << 'EOF'
import logging

def get_logger(name):
    """Simple logger shim for build process."""
    return logging.getLogger(name)
EOF

# Build UI
cd taskflows/ui
export PYTHONPATH=/tmp/quant_shim:$(dirname $(dirname $PWD)):$PYTHONPATH
python build_ui_simple.py

echo ""
echo "Build complete! UI files are in: taskflows/ui/static/"
echo ""
echo "To start the API with UI:"
echo "  tf api setup-ui --username admin    # First time only"
echo "  tf api start --enable-ui"
