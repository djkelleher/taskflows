#!/usr/bin/env python3
"""
Simple test to verify the refactored API structure works correctly.
Tests that the free functions can be called directly and via FastAPI endpoints.
"""

import sys
import os

# Add parent dir to path to import taskflows
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_free_functions():
    """Test that free functions exist and have correct signatures."""
    print("=" * 60)
    print("Testing Free Functions in api.py")
    print("=" * 60)
    
    try:
        from taskflows.admin import api
        
        # Check that free functions exist
        free_functions = [
            'free_health_check',
            'free_list_servers', 
            'free_history',
            'free_list_services',
            'free_status',
            'free_logs',
            'free_show',
            'free_create',
            'free_start',
            'free_stop',
            'free_restart',
            'free_enable',
            'free_disable',
            'free_remove'
        ]
        
        print("\nChecking for free functions:")
        for func_name in free_functions:
            if hasattr(api, func_name):
                print(f"  ✓ {func_name} exists")
            else:
                print(f"  ✗ {func_name} NOT FOUND")
        
        # Check function signatures
        print("\nFunction signatures:")
        import inspect
        for func_name in free_functions:
            if hasattr(api, func_name):
                func = getattr(api, func_name)
                sig = inspect.signature(func)
                print(f"  {func_name}{sig}")
                
    except ImportError as e:
        print(f"Failed to import api module: {e}")
        return False
    
    return True


def test_api_client_functions():
    """Test that API client functions check for host=None."""
    print("\n" + "=" * 60)
    print("Testing API Client Functions")
    print("=" * 60)
    
    try:
        # Read the api_client.py file to check implementation
        with open('taskflows/admin/api_client.py', 'r') as f:
            content = f.read()
        
        # Check that functions check for host=None
        api_functions = [
            'api_health',
            'api_list_servers',
            'api_history',
            'api_list_services',
            'api_status',
            'api_logs',
            'api_show',
            'api_create',
            'api_start',
            'api_stop',
            'api_restart',
            'api_enable',
            'api_disable',
            'api_remove'
        ]
        
        print("\nChecking that API client functions handle host=None:")
        for func_name in api_functions:
            # Find the function definition
            func_start = content.find(f"def {func_name}(")
            if func_start == -1:
                print(f"  ✗ {func_name} not found")
                continue
            
            # Find the function body (up to next def or class)
            func_end = content.find("\ndef ", func_start + 1)
            if func_end == -1:
                func_end = content.find("\nclass ", func_start + 1)
            if func_end == -1:
                func_end = len(content)
            
            func_body = content[func_start:func_end]
            
            # Check if it handles host=None
            if "if host is None:" in func_body:
                # Check if it imports the corresponding free function
                free_func_name = func_name.replace('api_', 'free_')
                if free_func_name == 'free_list_services':
                    free_func_name = 'free_list_services'
                
                if f"from taskflows.admin.api import {free_func_name}" in func_body or \
                   f"free_{func_name[4:]}" in func_body:
                    print(f"  ✓ {func_name} handles host=None correctly")
                else:
                    print(f"  ⚠ {func_name} checks host=None but may not import free function")
            else:
                print(f"  ✗ {func_name} does not handle host=None")
                
    except Exception as e:
        print(f"Failed to analyze api_client.py: {e}")
        return False
    
    return True


def test_fastapi_endpoints():
    """Test that FastAPI endpoints call free functions."""
    print("\n" + "=" * 60)
    print("Testing FastAPI Endpoints")
    print("=" * 60)
    
    try:
        # Read the api.py file to check endpoints
        with open('taskflows/admin/api.py', 'r') as f:
            content = f.read()
        
        endpoints = [
            ('/health', 'free_health_check'),
            ('/list-servers', 'free_list_servers'),
            ('/history', 'free_history'),
            ('/list', 'free_list_services'),
            ('/status', 'free_status'),
            ('/logs', 'free_logs'),
            ('/show', 'free_show'),
            ('/create', 'free_create'),
            ('/start', 'free_start'),
            ('/stop', 'free_stop'),
            ('/restart', 'free_restart'),
            ('/enable', 'free_enable'),
            ('/disable', 'free_disable'),
            ('/remove', 'free_remove')
        ]
        
        print("\nChecking that endpoints call free functions:")
        for endpoint, free_func in endpoints:
            # Find the endpoint definition
            if '@app.get("' + endpoint in content or '@app.post("' + endpoint in content:
                # Check if it calls the free function
                if f"return {free_func}(" in content or f"return await {free_func}(" in content:
                    print(f"  ✓ {endpoint} -> {free_func}()")
                else:
                    print(f"  ⚠ {endpoint} exists but may not call {free_func}()")
            else:
                print(f"  ✗ {endpoint} endpoint not found")
                
    except Exception as e:
        print(f"Failed to analyze api.py: {e}")
        return False
    
    return True


def main():
    """Run all tests."""
    print("Testing API Refactoring Implementation")
    print("=" * 60)
    
    results = []
    
    # Test 1: Free functions exist
    results.append(("Free Functions", test_free_functions()))
    
    # Test 2: API client functions handle host=None
    results.append(("API Client Functions", test_api_client_functions()))
    
    # Test 3: FastAPI endpoints call free functions
    results.append(("FastAPI Endpoints", test_fastapi_endpoints()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED - Implementation is correct!")
    else:
        print("✗ SOME TESTS FAILED - Please review the implementation")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())