"""Example: Deploying taskflows functions to AWS Lambda.

This example demonstrates how to use the AWS Lambda cloud deployment module
to deploy scheduled tasks to AWS Lambda with EventBridge triggers.

Prerequisites:
    1. Install boto3: pip install boto3
    2. Configure AWS credentials (aws configure or environment variables)
    3. Create an IAM role for Lambda execution with trust policy:
       {
         "Version": "2012-10-17",
         "Statement": [{
           "Effect": "Allow",
           "Principal": {"Service": "lambda.amazonaws.com"},
           "Action": "sts:AssumeRole"
         }]
       }
    4. Attach policy: arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
"""

from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
from taskflows.schedule import Calendar, Periodic


# Example 1: Simple periodic task
def send_daily_report():
    """Send a daily report (mock implementation)."""
    import json
    from datetime import datetime

    report = {
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",
        "tasks_completed": 42,
    }

    print(f"Daily Report: {json.dumps(report, indent=2)}")
    return report


# Example 2: Data processing task
def process_data():
    """Process data from S3 (mock implementation)."""
    print("Processing data from S3...")
    # In real implementation:
    # import boto3
    # s3 = boto3.client('s3')
    # data = s3.get_object(Bucket='my-bucket', Key='data.csv')
    print("Data processing complete!")


# Example 3: Cleanup task
def cleanup_old_files():
    """Clean up old files from storage."""
    print("Running cleanup task...")
    # Mock cleanup logic
    deleted_count = 15
    print(f"Deleted {deleted_count} old files")
    return {"deleted": deleted_count}


def main():
    """Main example demonstrating AWS Lambda deployment."""

    # Initialize AWS Lambda environment
    # Replace with your actual IAM role ARN
    LAMBDA_EXECUTION_ROLE = "arn:aws:iam::123456789012:role/lambda-execution-role"

    lambda_env = AWSLambdaEnvironment(
        region="us-east-1",
        execution_role_arn=LAMBDA_EXECUTION_ROLE,
    )

    print("=" * 60)
    print("AWS Lambda Deployment Examples")
    print("=" * 60)

    # =========================================================================
    # Example 1: Deploy function with Calendar schedule (daily at 9 AM)
    # =========================================================================
    print("\n1. Deploying daily report function...")

    daily_report_config = CloudFunctionConfig(
        function_name="taskflows-daily-report",
        description="Sends daily report every morning",
        runtime="python3.11",
        memory_mb=256,
        timeout_seconds=60,
        schedules=[
            Calendar(schedule="Mon-Fri 09:00")  # Weekdays at 9 AM UTC
        ],
        environment_variables={
            "REPORT_EMAIL": "admin@example.com",
            "ENVIRONMENT": "production",
        },
        tags={
            "Project": "TaskFlows",
            "Purpose": "DailyReporting",
        },
    )

    result = lambda_env.deploy_function(
        function=send_daily_report,
        config=daily_report_config,
        dependencies=["boto3"],  # Additional dependencies if needed
    )

    if result.success:
        print(f"✓ Deployed successfully!")
        print(f"  Function ARN: {result.resource_id}")
        print(f"  Package size: {result.metadata['package_size_mb']} MB")
        print(f"  Schedules: {len(result.metadata['schedule_rules'])} rule(s)")
    else:
        print(f"✗ Deployment failed: {result.error}")

    # =========================================================================
    # Example 2: Deploy function with Periodic schedule (every hour)
    # =========================================================================
    print("\n2. Deploying hourly data processing function...")

    data_processing_config = CloudFunctionConfig(
        function_name="taskflows-data-processor",
        description="Processes data every hour",
        runtime="python3.11",
        memory_mb=512,  # More memory for data processing
        timeout_seconds=300,  # 5 minutes
        schedules=[
            Periodic(
                start_on="command",  # Don't start on boot
                period=3600,  # Every hour (3600 seconds)
                relative_to="finish",
            )
        ],
        environment_variables={
            "S3_BUCKET": "my-data-bucket",
            "PROCESSING_MODE": "batch",
        },
    )

    result = lambda_env.deploy_function(
        function=process_data,
        config=data_processing_config,
    )

    if result.success:
        print(f"✓ Deployed successfully!")
        print(f"  Function ARN: {result.resource_id}")
    else:
        print(f"✗ Deployment failed: {result.error}")

    # =========================================================================
    # Example 3: Deploy function with multiple schedules
    # =========================================================================
    print("\n3. Deploying cleanup function with multiple schedules...")

    cleanup_config = CloudFunctionConfig(
        function_name="taskflows-cleanup",
        description="Cleanup task running on multiple schedules",
        runtime="python3.11",
        memory_mb=256,
        timeout_seconds=120,
        schedules=[
            # Run every Sunday at midnight
            Calendar(schedule="Sun 00:00"),
            # Also run every 6 hours
            Periodic(start_on="boot", period=21600, relative_to="finish"),
        ],
        log_retention_days=14,  # Keep logs for 2 weeks
    )

    result = lambda_env.deploy_function(
        function=cleanup_old_files,
        config=cleanup_config,
    )

    if result.success:
        print(f"✓ Deployed successfully!")
        print(f"  Function ARN: {result.resource_id}")
        print(f"  Schedules: {len(result.metadata['schedule_rules'])} rule(s)")
    else:
        print(f"✗ Deployment failed: {result.error}")

    # =========================================================================
    # Example 4: Manually invoke a function
    # =========================================================================
    print("\n4. Manually invoking the daily report function...")

    invoke_result = lambda_env.invoke_function(
        function_name="taskflows-daily-report",
        payload={"manual_trigger": True},
        invocation_type="RequestResponse",  # Synchronous
    )

    print(f"  Status Code: {invoke_result.get('StatusCode')}")
    if "Payload" in invoke_result:
        print(f"  Response: {invoke_result['Payload']}")

    # =========================================================================
    # Example 5: Retrieve function logs
    # =========================================================================
    print("\n5. Retrieving logs from daily report function...")

    logs = lambda_env.get_function_logs(
        function_name="taskflows-daily-report",
        limit=10,
    )

    print(f"  Retrieved {len(logs)} log lines:")
    for log_line in logs[:5]:  # Show first 5
        print(f"    {log_line}")

    # =========================================================================
    # Example 6: List all deployed functions
    # =========================================================================
    print("\n6. Listing all Lambda functions...")

    functions = lambda_env.list_functions()
    taskflows_functions = [f for f in functions if f["name"].startswith("taskflows-")]

    print(f"  Found {len(taskflows_functions)} taskflows functions:")
    for func in taskflows_functions:
        print(f"    - {func['name']} ({func['runtime']}, {func['memory']}MB)")

    # =========================================================================
    # Example 7: Update function code
    # =========================================================================
    print("\n7. Updating daily report function code...")

    def send_daily_report_v2():
        """Updated version of daily report."""
        print("Daily Report v2.0 - Now with more features!")
        return {"version": "2.0", "status": "awesome"}

    update_result = lambda_env.update_function_code(
        function_name="taskflows-daily-report",
        function=send_daily_report_v2,
    )

    if update_result.success:
        print(f"✓ Code updated successfully!")
    else:
        print(f"✗ Update failed: {update_result.error}")

    # =========================================================================
    # Example 8: Update function configuration
    # =========================================================================
    print("\n8. Updating cleanup function configuration...")

    updated_cleanup_config = CloudFunctionConfig(
        function_name="taskflows-cleanup",
        memory_mb=512,  # Increase memory
        timeout_seconds=180,  # Increase timeout
        environment_variables={
            "CLEANUP_AGGRESSIVE": "true",
            "MAX_AGE_DAYS": "30",
        },
    )

    config_update_result = lambda_env.update_function_configuration(
        function_name="taskflows-cleanup",
        config=updated_cleanup_config,
    )

    if config_update_result.success:
        print(f"✓ Configuration updated successfully!")
    else:
        print(f"✗ Update failed: {config_update_result.error}")

    # =========================================================================
    # Cleanup (optional - uncomment to delete functions)
    # =========================================================================
    # print("\n9. Cleaning up deployed functions...")
    #
    # for function_name in ["taskflows-daily-report", "taskflows-data-processor", "taskflows-cleanup"]:
    #     if lambda_env.delete_function(function_name):
    #         print(f"✓ Deleted {function_name}")
    #     else:
    #         print(f"✗ Failed to delete {function_name}")

    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)


def advanced_example_with_service_integration():
    """Advanced example showing integration with existing taskflows Service class.

    This demonstrates how you could extend the Service class to support
    cloud deployment alongside the existing systemd deployment.
    """
    from taskflows.service import Service
    from taskflows.schedule import Calendar

    # Define a service using existing taskflows API
    service = Service(
        name="data-sync",
        start_command=lambda: print("Syncing data..."),
        start_schedule=Calendar(schedule="Mon-Fri 14:00"),
    )

    # In a future integration, you could do something like:
    # if deploy_to_cloud:
    #     lambda_env = AWSLambdaEnvironment(...)
    #     config = CloudFunctionConfig(
    #         function_name=service.name,
    #         schedules=[service.start_schedule],
    #         ...
    #     )
    #     result = lambda_env.deploy_function(service.start_command, config)
    # else:
    #     service.create()  # Deploy to systemd as usual

    print("Advanced integration example (conceptual)")


if __name__ == "__main__":
    # Check for boto3 before running examples
    try:
        import boto3

        main()

        # Optionally run advanced example
        # advanced_example_with_service_integration()

    except ImportError:
        print("Error: boto3 is not installed.")
        print("Install it with: pip install boto3")
        print("\nAlso ensure you have AWS credentials configured:")
        print("  - Run 'aws configure' to set up credentials")
        print("  - Or set environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY")
    except Exception as e:
        print(f"Error running examples: {e}")
        import traceback

        traceback.print_exc()
