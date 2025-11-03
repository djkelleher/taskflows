"""Production AWS Lambda Deployment Examples.

This example demonstrates production-ready deployment of taskflows services
to AWS Lambda using both Pulumi (recommended) and boto3 backends.

Prerequisites:
    pip install boto3 pulumi pulumi-aws
    aws configure
    # Create IAM role (see QUICK_START.md)
"""

from taskflows.cloud import (
    CloudFunctionConfig,
    DeadLetterConfig,
    DeploymentBackend,
    LayerConfig,
    MonitoringConfig,
    RetryConfig,
)
from taskflows.cloud.manager import DeploymentManager, deploy_service_to_cloud
from taskflows.schedule import Calendar, Periodic
from taskflows.service import Service


# ============================================================================
# Example 1: Production Deployment with Full Monitoring
# ============================================================================

def example_production_deployment():
    """Deploy a function with full production features."""
    print("\n" + "=" * 70)
    print("Example 1: Production Deployment with Monitoring")
    print("=" * 70)

    # Initialize deployment manager with Pulumi
    manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
        project_name="my-app",
        environment="production",
    )

    # Define production task
    def daily_report_generator():
        """Generate and send daily reports."""
        import json
        from datetime import datetime

        report = {
            "timestamp": datetime.now().isoformat(),
            "metrics": {"tasks": 150, "success_rate": 0.98},
        }
        print(f"Generated report: {json.dumps(report)}")
        return report

    # Production configuration with monitoring and error handling
    config = CloudFunctionConfig(
        function_name="daily-report-prod",
        description="Production daily report generator",
        runtime="python3.11",
        memory_mb=512,
        timeout_seconds=300,
        schedules=[
            Calendar(schedule="Mon-Fri 09:00")  # Weekdays at 9 AM
        ],
        environment_variables={
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "INFO",
        },
        # Monitoring and alerting
        monitoring=MonitoringConfig(
            enable_cloudwatch_alarms=True,
            error_rate_threshold=0.05,  # Alert if >5% errors
            duration_threshold_ms=250000,  # Alert if >250s duration
            # alarm_sns_topic_arn="arn:aws:sns:us-east-1:123456789012:alerts"
        ),
        # Error handling
        dead_letter_config=DeadLetterConfig(
            auto_create=True,  # Auto-create DLQ
        ),
        retry_config=RetryConfig(
            max_retry_attempts=2,
            max_event_age_seconds=3600,
        ),
        # Auto-create IAM role with permissions
        auto_create_role=True,
        # Versioning and aliases
        enable_versioning=True,
        create_alias="live",
        # Tags for cost tracking
        tags={
            "Project": "MyApp",
            "Environment": "Production",
            "CostCenter": "Engineering",
            "Owner": "data-team",
        },
    )

    result = manager.deploy_function(
        name="daily-report-prod",
        function=daily_report_generator,
        config=config,
        dependencies=["boto3"],  # Additional dependencies
    )

    if result.success:
        print(f"✓ Deployed successfully!")
        print(f"  ARN: {result.resource_id}")
        print(f"  Version: {result.version}")
        print(f"  Metadata: {result.metadata}")
    else:
        print(f"✗ Deployment failed: {result.error}")


# ============================================================================
# Example 2: Using Lambda Layers for Shared Dependencies
# ============================================================================

def example_with_layers():
    """Deploy function using Lambda Layers for dependencies."""
    print("\n" + "=" * 70)
    print("Example 2: Deployment with Lambda Layers")
    print("=" * 70)

    manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
    )

    def data_processor():
        """Process data using pandas and requests."""
        import pandas as pd
        import requests

        # Your processing logic
        print("Processing data with pandas...")
        df = pd.DataFrame({"col1": [1, 2, 3]})
        print(df.describe())

    # Create a reusable layer with heavy dependencies
    layer_config = LayerConfig(
        layer_name="data-processing-deps",
        dependencies=["pandas", "requests", "numpy"],
        compatible_runtimes=["python3.11"],
    )

    config = CloudFunctionConfig(
        function_name="data-processor",
        memory_mb=1024,  # More memory for pandas
        timeout_seconds=600,
        layers=[layer_config],  # Use the layer
        schedules=[Periodic(start_on="boot", period=3600, relative_to="finish")],
    )

    result = manager.deploy_function(
        name="data-processor",
        function=data_processor,
        config=config,
        # No need to include pandas/requests in function package - they're in the layer
        dependencies=[],
    )

    print(f"Result: {result.success}")


# ============================================================================
# Example 3: Deploying Existing taskflows Service
# ============================================================================

def example_deploy_existing_service():
    """Deploy an existing taskflows Service to the cloud."""
    print("\n" + "=" * 70)
    print("Example 3: Deploy Existing taskflows Service")
    print("=" * 70)

    # Define service using standard taskflows API
    def cleanup_task():
        """Cleanup old data."""
        print("Running cleanup...")
        # Cleanup logic here
        deleted = 25
        print(f"Deleted {deleted} old files")
        return {"deleted": deleted}

    service = Service(
        name="cleanup-service",
        start_command=cleanup_task,
        start_schedule=Calendar(schedule="Sun 00:00"),  # Weekly on Sunday
        timeout=120,
        env={
            "MAX_AGE_DAYS": "30",
            "DRY_RUN": "false",
        },
    )

    # Deploy to cloud with one function call
    result = deploy_service_to_cloud(
        service,
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
        environment="production",
        # Override or add cloud-specific config
        memory_mb=256,
        enable_monitoring=True,
    )

    if result.success:
        print(f"✓ Service deployed: {result.resource_id}")
    else:
        print(f"✗ Failed: {result.error}")


# ============================================================================
# Example 4: Multi-Function Deployment
# ============================================================================

def example_multi_function_deployment():
    """Deploy multiple related functions together."""
    print("\n" + "=" * 70)
    print("Example 4: Multi-Function Deployment")
    print("=" * 70)

    manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
        project_name="data-pipeline",
    )

    # Define multiple functions
    def ingest_data():
        print("Ingesting data...")

    def transform_data():
        print("Transforming data...")

    def export_data():
        print("Exporting data...")

    # Deploy as a pipeline
    functions = [
        {
            "name": "ingest",
            "function": ingest_data,
            "schedule": "0 * * * *",  # Every hour
            "memory_mb": 512,
        },
        {
            "name": "transform",
            "function": transform_data,
            "schedule": "30 * * * *",  # 30 minutes past every hour
            "memory_mb": 1024,
        },
        {
            "name": "export",
            "function": export_data,
            "schedule": "45 * * * *",  # 45 minutes past every hour
            "memory_mb": 256,
        },
    ]

    results = manager.deploy_multiple(functions)

    for result in results:
        status = "✓" if result.success else "✗"
        print(f"{status} {result.metadata.get('function_name', 'unknown')}: {result.resource_id}")


# ============================================================================
# Example 5: Development vs Production Environments
# ============================================================================

def example_multi_environment_deployment():
    """Deploy to multiple environments (dev, staging, prod)."""
    print("\n" + "=" * 70)
    print("Example 5: Multi-Environment Deployment")
    print("=" * 70)

    def my_task():
        import os
        env = os.environ.get("ENVIRONMENT", "unknown")
        print(f"Running in {env} environment")

    # Deploy to development
    dev_manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
        environment="dev",
    )

    dev_result = dev_manager.deploy_function(
        name="my-task",
        function=my_task,
        schedule="Mon-Fri 09:00",
        memory_mb=256,
        environment_variables={"ENVIRONMENT": "development"},
        tags={"Environment": "Dev", "CostCenter": "R&D"},
    )

    # Deploy to production with more resources
    prod_manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
        environment="production",
    )

    prod_result = prod_manager.deploy_function(
        name="my-task",
        function=my_task,
        schedule="Mon-Fri 09:00",
        memory_mb=512,  # More memory in prod
        environment_variables={"ENVIRONMENT": "production"},
        enable_monitoring=True,  # Monitoring only in prod
        tags={"Environment": "Production", "CostCenter": "Operations"},
    )

    print(f"Dev: {dev_result.success}, Prod: {prod_result.success}")


# ============================================================================
# Example 6: Runtime Operations (Invoke, Logs, Metrics)
# ============================================================================

def example_runtime_operations():
    """Perform runtime operations on deployed functions."""
    print("\n" + "=" * 70)
    print("Example 6: Runtime Operations")
    print("=" * 70)

    manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
    )

    function_name = "daily-report-prod"

    # 1. Manually invoke function
    print("\n1. Invoking function...")
    response = manager.invoke(
        function_name,
        payload={"test": True},
        async_invoke=False,  # Synchronous
    )
    print(f"Response: {response}")

    # 2. Get logs
    print("\n2. Retrieving logs...")
    logs = manager.get_logs(function_name, limit=20)
    for log in logs[:5]:  # Show first 5 lines
        print(f"  {log}")

    # 3. Get metrics
    print("\n3. Getting metrics...")
    try:
        metrics = manager.get_metrics(function_name)
        print(f"Metrics: {metrics}")
    except NotImplementedError:
        print("  Metrics retrieval not yet implemented for this backend")

    # 4. List all functions
    print("\n4. Listing deployed functions...")
    functions = manager.list_functions()
    for func in functions:
        print(f"  - {func['name']}: {func.get('arn', 'N/A')}")


# ============================================================================
# Example 7: Rollback and Version Management
# ============================================================================

def example_rollback():
    """Demonstrate rollback capabilities."""
    print("\n" + "=" * 70)
    print("Example 7: Rollback and Version Management")
    print("=" * 70)

    manager = DeploymentManager(
        provider="aws",
        backend=DeploymentBackend.PULUMI,
        region="us-east-1",
    )

    function_name = "daily-report-prod"

    # Get function versions
    try:
        versions = manager._environment.list_versions(function_name)
        print(f"Available versions: {versions}")

        # Rollback to previous version
        if len(versions) > 1:
            prev_version = versions[-2]["version"]
            print(f"\nRolling back to version {prev_version}...")
            result = manager.rollback(function_name, version=prev_version)
            print(f"Rollback: {'Success' if result.success else 'Failed'}")
    except NotImplementedError:
        print("Rollback not yet implemented for this backend")


# ============================================================================
# Main Example Runner
# ============================================================================

def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("PRODUCTION AWS LAMBDA DEPLOYMENT EXAMPLES")
    print("=" * 70)

    examples = [
        ("Production Deployment", example_production_deployment),
        ("Lambda Layers", example_with_layers),
        ("Deploy Service", example_deploy_existing_service),
        ("Multi-Function", example_multi_function_deployment),
        ("Multi-Environment", example_multi_environment_deployment),
        ("Runtime Operations", example_runtime_operations),
        ("Rollback", example_rollback),
    ]

    for name, example_func in examples:
        try:
            print(f"\n\nRunning: {name}")
            print("-" * 70)
            example_func()
        except Exception as e:
            print(f"✗ Error in {name}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("Examples Complete!")
    print("=" * 70)


if __name__ == "__main__":
    # Check dependencies
    try:
        import boto3
        import pulumi

        main()

    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("\nInstall required packages:")
        print("  pip install boto3 pulumi pulumi-aws")
