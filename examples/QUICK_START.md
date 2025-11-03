# Quick Start: AWS Lambda Deployment

## Setup (One-Time)

### 1. Install Dependencies
```bash
pip install boto3
```

### 2. Configure AWS Credentials
```bash
aws configure
# Enter: Access Key, Secret Key, Region (e.g., us-east-1)
```

### 3. Create IAM Role
```bash
# Create the role
aws iam create-role \
  --role-name taskflows-lambda \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach execution policy
aws iam attach-role-policy \
  --role-name taskflows-lambda \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Get the ARN (you'll need this)
aws iam get-role --role-name taskflows-lambda --query 'Role.Arn' --output text
```

Copy the ARN - it looks like: `arn:aws:iam::123456789012:role/taskflows-lambda`

## Common Use Cases

### 1. Deploy a Daily Task

```python
from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
from taskflows.schedule import Calendar

# Your task
def daily_backup():
    print("Running daily backup...")
    # Your backup logic here

# Deploy
lambda_env = AWSLambdaEnvironment(
    region="us-east-1",
    execution_role_arn="arn:aws:iam::123456789012:role/taskflows-lambda"  # Your ARN
)

config = CloudFunctionConfig(
    function_name="daily-backup",
    schedules=[Calendar(schedule="Mon-Sun 02:00")],  # 2 AM UTC daily
)

result = lambda_env.deploy_function(daily_backup, config)
print("Deployed!" if result.success else f"Failed: {result.error}")
```

### 2. Deploy a Weekday Task

```python
from taskflows.schedule import Calendar

def send_report():
    print("Sending weekly report...")

config = CloudFunctionConfig(
    function_name="weekday-report",
    schedules=[Calendar(schedule="Mon-Fri 09:00")],  # Weekdays at 9 AM
)

lambda_env.deploy_function(send_report, config)
```

### 3. Deploy an Hourly Task

```python
from taskflows.schedule import Periodic

def check_status():
    print("Checking system status...")

config = CloudFunctionConfig(
    function_name="hourly-check",
    schedules=[Periodic(start_on="boot", period=3600, relative_to="finish")],  # Every hour
)

lambda_env.deploy_function(check_status, config)
```

### 4. Deploy with Environment Variables

```python
def process_data():
    import os
    bucket = os.environ.get("S3_BUCKET")
    print(f"Processing data from {bucket}...")

config = CloudFunctionConfig(
    function_name="data-processor",
    schedules=[Calendar(schedule="Mon-Fri 14:00")],
    environment_variables={
        "S3_BUCKET": "my-data-bucket",
        "ENVIRONMENT": "production"
    },
)

lambda_env.deploy_function(process_data, config)
```

### 5. Deploy with More Resources

```python
def heavy_processing():
    print("Running CPU-intensive task...")

config = CloudFunctionConfig(
    function_name="heavy-task",
    memory_mb=2048,       # 2 GB RAM
    timeout_seconds=600,  # 10 minutes
    schedules=[Periodic(start_on="boot", period=21600, relative_to="finish")],  # Every 6 hours
)

lambda_env.deploy_function(heavy_processing, config)
```

### 6. Deploy with Dependencies

```python
def fetch_and_process():
    import requests
    import pandas as pd
    # Your logic using requests and pandas

config = CloudFunctionConfig(
    function_name="fetch-process",
    schedules=[Calendar(schedule="Mon-Sun 00:00")],
)

lambda_env.deploy_function(
    fetch_and_process,
    config,
    dependencies=["requests", "pandas"]  # Will be packaged
)
```

## Management Operations

### Manually Trigger a Function
```python
response = lambda_env.invoke_function("daily-backup")
print(response)
```

### View Logs
```python
logs = lambda_env.get_function_logs("daily-backup", limit=20)
for log in logs:
    print(log)
```

### List All Functions
```python
functions = lambda_env.list_functions()
for func in functions:
    print(f"{func['name']}: {func['runtime']}, {func['memory']}MB")
```

### Update Function Code
```python
def daily_backup_v2():
    print("Running improved daily backup...")

lambda_env.update_function_code("daily-backup", daily_backup_v2)
```

### Update Configuration
```python
updated_config = CloudFunctionConfig(
    function_name="daily-backup",
    memory_mb=512,      # Increase memory
    timeout_seconds=300  # Increase timeout
)

lambda_env.update_function_configuration("daily-backup", updated_config)
```

### Delete a Function
```python
lambda_env.delete_function("daily-backup")
```

## Schedule Examples

| Description | Code |
|-------------|------|
| **Daily at 2 AM** | `Calendar(schedule="Mon-Sun 02:00")` |
| **Weekdays at 9 AM** | `Calendar(schedule="Mon-Fri 09:00")` |
| **Weekends at 10 AM** | `Calendar(schedule="Sat,Sun 10:00")` |
| **Every hour** | `Periodic(start_on="boot", period=3600, relative_to="finish")` |
| **Every 30 minutes** | `Periodic(start_on="boot", period=1800, relative_to="finish")` |
| **Every 6 hours** | `Periodic(start_on="boot", period=21600, relative_to="finish")` |
| **Every day** | `Periodic(start_on="boot", period=86400, relative_to="finish")` |

## Complete Example

```python
#!/usr/bin/env python3
from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
from taskflows.schedule import Calendar

# Initialize environment (do this once)
lambda_env = AWSLambdaEnvironment(
    region="us-east-1",
    execution_role_arn="arn:aws:iam::123456789012:role/taskflows-lambda"
)

# Define your task
def my_scheduled_task():
    """This runs every weekday at 9 AM UTC."""
    print("Task is running!")
    # Your business logic here
    return {"status": "success"}

# Configure deployment
config = CloudFunctionConfig(
    function_name="my-task",
    runtime="python3.11",
    memory_mb=256,
    timeout_seconds=60,
    schedules=[Calendar(schedule="Mon-Fri 09:00")],
    environment_variables={"ENV": "production"},
    tags={"Project": "MyProject"}
)

# Deploy
result = lambda_env.deploy_function(my_scheduled_task, config)

if result.success:
    print(f"✓ Deployed successfully!")
    print(f"  Function: {result.resource_id}")
    print(f"  Size: {result.metadata['package_size_mb']} MB")
else:
    print(f"✗ Failed: {result.error}")
```

## Troubleshooting

### "boto3 is required"
```bash
pip install boto3
```

### "execution_role_arn must be provided"
Create an IAM role (see Setup section above)

### "Could not assume role"
Check that:
1. The IAM role exists
2. The ARN is correct
3. Your AWS credentials have permission to use the role

### "Package too large" (>50MB)
- Reduce dependencies
- Use Lambda Layers (see advanced docs)

### Function not triggering on schedule
- Check CloudWatch Logs for errors
- Verify EventBridge rule is ENABLED:
  ```bash
  aws events list-rules --name-prefix "my-task-schedule"
  ```

## Next Steps

- See `aws_lambda_deployment_example.py` for more examples
- Read `taskflows/cloud/README.md` for detailed documentation
- Check `CLOUD_DEPLOYMENT_POC.md` for architecture details

## Support

Run tests to verify your setup:
```bash
TASKFLOWS_DATA_DIR=/tmp/taskflows-test-data \
  python -m pytest tests/test_cloud_schedule_translation.py -v
```

Expected: 21 tests passing
