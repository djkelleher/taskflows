#!/usr/bin/env python3
"""
Test script to verify that API client functions work both locally (host=None) 
and via API calls.
"""

import asyncio
from taskflows.admin.api_client import (
    api_health,
    api_list_servers,
    api_history,
    api_list_services,
    api_status,
    api_logs,
    api_show,
    api_create,
    api_start,
    api_stop,
    api_restart,
    api_enable,
    api_disable,
    api_remove,
    execute_command_on_servers
)


def test_local_mode():
    """Test API client functions in local mode (host=None)."""
    print("=" * 60)
    print("Testing LOCAL MODE (host=None)")
    print("=" * 60)
    
    # Test health check
    print("\n1. Testing health check...")
    result = api_health(host=None)
    print(f"   Result: {result}")
    
    # Test list servers
    print("\n2. Testing list servers...")
    result = api_list_servers(host=None)
    print(f"   Result: {result}")
    
    # Test history
    print("\n3. Testing history...")
    result = api_history(host=None, limit=2)
    print(f"   Result: {result}")
    
    # Test list services
    print("\n4. Testing list services...")
    result = api_list_services(host=None)
    print(f"   Result: {result}")
    
    # Test status
    print("\n5. Testing status...")
    result = api_status(host=None)
    print(f"   Result: {result}")
    
    # Test logs (will need a valid service name)
    print("\n6. Testing logs...")
    result = api_logs(host=None, service_name="srv-api", n_lines=10)
    print(f"   Result: {result}")
    
    # Test show
    print("\n7. Testing show...")
    result = api_show(host=None, match="srv-api")
    print(f"   Result: {result}")
    
    print("\n" + "=" * 60)
    print("LOCAL MODE tests completed!")
    print("=" * 60)


def test_api_mode():
    """Test API client functions in API mode (host specified)."""
    print("\n" + "=" * 60)
    print("Testing API MODE (host='localhost:7777')")
    print("=" * 60)
    
    host = "localhost:7777"
    
    # Test health check
    print("\n1. Testing health check...")
    result = api_health(host=host)
    print(f"   Result: {result}")
    
    # Test list servers
    print("\n2. Testing list servers...")
    result = api_list_servers(host=host)
    print(f"   Result: {result}")
    
    # Test history
    print("\n3. Testing history...")
    result = api_history(host=host, limit=2)
    print(f"   Result: {result}")
    
    # Test list services
    print("\n4. Testing list services...")
    result = api_list_services(host=host)
    print(f"   Result: {result}")
    
    # Test status
    print("\n5. Testing status...")
    result = api_status(host=host)
    print(f"   Result: {result}")
    
    print("\n" + "=" * 60)
    print("API MODE tests completed!")
    print("=" * 60)


async def test_execute_command():
    """Test execute_command_on_servers with local and remote execution."""
    print("\n" + "=" * 60)
    print("Testing execute_command_on_servers")
    print("=" * 60)
    
    # Test with no servers (should use local)
    print("\n1. Testing with no servers (local execution)...")
    result = await execute_command_on_servers("health")
    print(f"   Result: {result}")
    
    # Test with explicit server
    print("\n2. Testing with explicit server...")
    result = await execute_command_on_servers("health", servers="localhost:7777")
    print(f"   Result: {result}")
    
    # Test list command
    print("\n3. Testing list command (local)...")
    result = await execute_command_on_servers("list")
    print(f"   Result: {result}")
    
    print("\n" + "=" * 60)
    print("execute_command_on_servers tests completed!")
    print("=" * 60)


def main():
    """Main test function."""
    print("Starting API client local/remote mode tests...")
    
    # Test local mode
    test_local_mode()
    
    # Test API mode (requires API server running)
    print("\n" + "=" * 60)
    print("Note: API mode tests require the API server to be running on localhost:7777")
    print("If the server is not running, these tests will fail.")
    print("=" * 60)
    
    try:
        test_api_mode()
    except Exception as e:
        print(f"\nAPI mode tests failed: {e}")
        print("Make sure the API server is running on localhost:7777")
    
    # Test async execute_command
    asyncio.run(test_execute_command())
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()