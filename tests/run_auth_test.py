#!/usr/bin/env python3
"""Simple runner for the API authentication test."""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Now run the test
if __name__ == "__main__":
    import unittest

    from taskflows.tests.test_api_auth import TestAPIAuthentication

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAPIAuthentication)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)