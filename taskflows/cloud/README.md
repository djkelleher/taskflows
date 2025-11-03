# Taskflows Cloud Deployment Module

This module provides cloud deployment capabilities for taskflows, allowing you to deploy scheduled tasks to cloud platforms like AWS Lambda, GCP Cloud Functions, and Azure Functions.

## Features

- **Multi-Cloud Abstraction**: Common interface for deploying to different cloud providers
- **Schedule Translation**: Automatic conversion of taskflows schedules (Calendar/Periodic) to cloud-native scheduling (EventBridge, Cloud Scheduler, etc.)
- **Function Packaging**: Automatic bundling of functions and dependencies into deployment packages
- **Resource Management**: Full lifecycle management (create, update, delete, invoke)
- **Monitoring**: Log retrieval and function listing capabilities

## Currently Supported Providers

### AWS Lambda (Fully Implemented)

- Function deployment with automatic dependency packaging
- EventBridge scheduling for Calendar and Periodic schedules
- CloudWatch Logs integration
- VPC, IAM, and resource configuration support
- Automatic scaling and concurrency management

## Installation

```bash
# For AWS Lambda support
pip install boto3

# For GCP Cloud Functions (future)
# pip install google-cloud-functions

# For Azure Functions (future)
# pip install azure-functions
```

## Quick Start

### 1. AWS Lambda Deployment

```python
from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
from taskflows.schedule import Calendar, Periodic

# Define your task
def daily_backup():
    print("Running daily backup...")
    # Your backup logic here

# Configure AWS Lambda environment
lambda_env = AWSLambdaEnvironment(
    region="us-east-1",
    execution_role_arn="arn:aws:iam::123456789012:role/lambda-role"
)

# Configure the function deployment
config = CloudFunctionConfig(
    function_name="my-daily-backup",
    runtime="python3.11",
    memory_mb=512,
    timeout_seconds=300,
    schedules=[
        Calendar(schedule="Mon-Fri 02:00")  # Every weekday at 2 AM UTC
    ],
    environment_variables={
        "BACKUP_BUCKET": "my-backup-bucket",
        "ENVIRONMENT": "production"
    }
)

# Deploy to AWS Lambda
result = lambda_env.deploy_function(
    function=daily_backup,
    config=config,
    dependencies=["boto3", "requests"]
)

if result.success:
    print(f"Deployed! Function ARN: {result.resource_id}")
else:
    print(f"Deployment failed: {result.error}")
```

### 2. Invoke a Deployed Function

```python
# Manually trigger the function
response = lambda_env.invoke_function(
    function_name="my-daily-backup",
    payload={"manual_trigger": True}
)

print(response)
```

### 3. Retrieve Logs

```python
logs = lambda_env.get_function_logs(
    function_name="my-daily-backup",
    limit=50
)

for log_line in logs:
    print(log_line)
```

### 4. Update Function Code

```python
def daily_backup_v2():
    print("Running daily backup v2 with improvements!")
    # Updated logic

lambda_env.update_function_code(
    function_name="my-daily-backup",
    function=daily_backup_v2
)
```

### 5. Delete Function

```python
lambda_env.delete_function("my-daily-backup")
```

## Schedule Translation

The module automatically translates taskflows schedules to cloud-native expressions:

### Calendar Schedules → EventBridge Cron

```python
# Taskflows Calendar
Calendar(schedule="Mon-Fri 14:00")
# Becomes EventBridge cron expression:
# cron(0 14 ? * MON-FRI *)

# Multiple days
Calendar(schedule="Mon,Wed,Fri 09:30")
# cron(30 9 ? * MON,WED,FRI *)

# Daily
Calendar(schedule="Mon-Sun 00:00")
# cron(0 0 ? * * *)
```

### Periodic Schedules → EventBridge Rate

```python
# Every hour
Periodic(start_on="boot", period=3600, relative_to="finish")
# rate(1 hour)

# Every 30 minutes
Periodic(start_on="command", period=1800, relative_to="start")
# rate(30 minutes)

# Every day
Periodic(start_on="boot", period=86400, relative_to="finish")
# rate(1 day)
```

**Note**: EventBridge rate expressions don't support sub-minute intervals. Minimum is `rate(1 minute)`.

## Configuration Options

### CloudFunctionConfig

```python
CloudFunctionConfig(
    # Required
    function_name="my-function",        # Unique identifier

    # Runtime
    runtime="python3.11",                # Python version
    memory_mb=256,                       # 128-10240 MB
    timeout_seconds=60,                  # 1-900 seconds

    # Scheduling
    schedules=[                          # List of Schedule objects
        Calendar(schedule="Mon 09:00"),
        Periodic(period=3600, ...)
    ],

    # Environment
    environment_variables={              # Environment vars
        "KEY": "value"
    },

    # IAM (AWS)
    execution_role_arn="arn:...",       # Lambda execution role

    # Networking (AWS)
    vpc_config={                         # VPC configuration
        "SubnetIds": ["subnet-xxx"],
        "SecurityGroupIds": ["sg-xxx"]
    },

    # Monitoring
    log_retention_days=7,                # CloudWatch log retention
    enable_xray_tracing=True,           # X-Ray tracing

    # Concurrency (AWS)
    reserved_concurrent_executions=5,    # Max concurrent invocations

    # Metadata
    description="Function description",
    tags={"Project": "MyProject"}
)
```

### AWSLambdaConfig

```python
from taskflows.cloud.aws_lambda import AWSLambdaConfig

aws_config = AWSLambdaConfig(
    region="us-east-1",
    execution_role_arn="arn:aws:iam::123456789012:role/lambda-role",
    deployment_bucket="my-deployment-bucket",  # For large packages
    kms_key_arn="arn:aws:kms:...",            # Encryption
    vpc_config={...}                           # Default VPC config
)

lambda_env = AWSLambdaEnvironment(aws_config=aws_config)
```

## Resource Limits

### AWS Lambda

| Resource | Minimum | Maximum | Notes |
|----------|---------|---------|-------|
| Memory | 128 MB | 10,240 MB | In 1 MB increments |
| Timeout | 1 second | 900 seconds (15 min) | |
| Deployment Package | - | 50 MB (zipped) | Use S3 for larger packages |
| Concurrent Executions | - | 1000 (default) | Can request increase |
| Environment Variables | - | 4 KB | Total size |

## AWS IAM Requirements

Your Lambda execution role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

For VPC access, also attach: `arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole`

## Architecture

```
taskflows.cloud
├── base.py              # Abstract CloudEnvironment interface
├── aws_lambda.py        # AWS Lambda implementation
├── utils.py             # Schedule translation, packaging utilities
└── README.md           # This file

Future additions:
├── gcp_functions.py    # Google Cloud Functions
├── azure_functions.py  # Azure Functions
└── kubernetes.py       # Kubernetes CronJob deployment
```

## Integration with Existing Taskflows

The cloud module is designed to work alongside the existing systemd-based deployment:

```python
from taskflows.service import Service
from taskflows.schedule import Calendar
from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig

# Define service using existing API
service = Service(
    name="my-service",
    start_command=lambda: print("Running task"),
    start_schedule=Calendar(schedule="Mon-Fri 09:00")
)

# Option 1: Deploy to systemd (existing behavior)
service.create()

# Option 2: Deploy to AWS Lambda (new capability)
lambda_env = AWSLambdaEnvironment(...)
config = CloudFunctionConfig(
    function_name=service.name,
    schedules=[service.start_schedule]
)
lambda_env.deploy_function(service.start_command, config)
```

## Examples

See `examples/aws_lambda_deployment_example.py` for comprehensive examples including:

1. Simple periodic tasks
2. Calendar-based scheduling
3. Multiple schedules per function
4. Manual invocation
5. Log retrieval
6. Function updates
7. Configuration changes

## Troubleshooting

### "boto3 is required"

```bash
pip install boto3
```

### "execution_role_arn must be provided"

Create an IAM role for Lambda:

```bash
aws iam create-role \
  --role-name lambda-execution-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name lambda-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### "Deployment package is too large"

- Reduce dependencies
- Use Lambda Layers for shared dependencies
- Use S3 for deployment packages over 50MB

### EventBridge not triggering

- Check CloudWatch Logs for errors
- Verify EventBridge rule is ENABLED
- Check Lambda has permission for EventBridge to invoke it
- Verify schedule expression is valid

## Future Enhancements

- [ ] Google Cloud Functions support
- [ ] Azure Functions support
- [ ] Kubernetes CronJob deployment
- [ ] Automatic dependency detection and installation
- [ ] Lambda Layers support for shared dependencies
- [ ] S3 deployment for large packages
- [ ] CloudFormation/Terraform output
- [ ] Multi-region deployment
- [ ] Cost estimation
- [ ] Performance monitoring integration

## Contributing

To add support for a new cloud provider:

1. Create a new file (e.g., `gcp_functions.py`)
2. Implement the `CloudEnvironment` abstract class
3. Add schedule translation logic in `utils.py`
4. Update `__init__.py` exports
5. Add examples and documentation
6. Write tests

See `aws_lambda.py` as a reference implementation.
