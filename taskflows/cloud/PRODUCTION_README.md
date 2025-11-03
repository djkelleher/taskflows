```markdown
# TaskFlows Production Cloud Deployment

Full production-ready implementation for deploying taskflows services to AWS Lambda and other cloud platforms.

## Overview

This is the **production implementation** of cloud deployment for taskflows, featuring:

- **Multiple Backends**: Pulumi (recommended) and boto3
- **Production Features**: Monitoring, dead letter queues, auto-scaling, versioning
- **Lambda Layers**: Shared dependency management
- **Infrastructure as Code**: Pulumi integration for state management
- **Multi-Environment**: Dev, staging, production deployment support
- **Service Integration**: Deploy existing taskflows Services directly
- **Docker Builds**: Consistent dependency packaging

## Installation

```bash
# Full cloud deployment support
pip install -r requirements-cloud.txt

# Or install individually
pip install boto3 pulumi pulumi-aws cloudpickle
```

## Quick Start

### 1. Using Deployment Manager (Recommended)

```python
from taskflows.cloud.manager import DeploymentManager
from taskflows.cloud import MonitoringConfig

# Initialize manager
manager = DeploymentManager(
    provider="aws",
    backend="pulumi",  # or "boto3"
    region="us-east-1",
    environment="production"
)

# Deploy a function
def my_task():
    print("Hello from Lambda!")

result = manager.deploy_function(
    name="my-task",
    function=my_task,
    schedule="Mon-Fri 09:00",
    memory_mb=512,
    timeout_seconds=120,
    enable_monitoring=True
)

print(f"Deployed: {result.resource_id}")
```

### 2. Deploy Existing taskflows Service

```python
from taskflows.service import Service
from taskflows.cloud.manager import deploy_service_to_cloud

# Create service using standard taskflows API
service = Service(
    name="data-processor",
    start_command=lambda: process_data(),
    start_schedule=Calendar(schedule="Mon-Fri 14:00")
)

# Deploy to cloud
result = deploy_service_to_cloud(
    service,
    provider="aws",
    backend="pulumi",
    environment="production"
)
```

## Backends

### Pulumi (Recommended for Production)

**Advantages:**
- Infrastructure as Code with state management
- Preview changes before deployment
- Automatic rollback on failures
- Multi-cloud support (AWS, GCP, Azure, Kubernetes)
- GitOps-friendly

```python
from taskflows.cloud.manager import DeploymentManager
from taskflows.cloud import DeploymentBackend

manager = DeploymentManager(
    provider="aws",
    backend=DeploymentBackend.PULUMI,
    region="us-east-1",
    project_name="my-app",
    environment="production"
)
```

### Boto3 (Direct AWS SDK)

**Advantages:**
- No additional dependencies beyond boto3
- Direct control over AWS resources
- Faster for simple deployments

```python
from taskflows.cloud import AWSLambdaEnvironment

env = AWSLambdaEnvironment(
    region="us-east-1",
    execution_role_arn="arn:aws:iam::123456789012:role/lambda-role"
)
```

## Production Features

### 1. Monitoring and Alerting

```python
from taskflows.cloud import MonitoringConfig

config = CloudFunctionConfig(
    function_name="critical-task",
    monitoring=MonitoringConfig(
        enable_cloudwatch_alarms=True,
        error_rate_threshold=0.05,  # Alert if >5% errors
        duration_threshold_ms=10000,  # Alert if >10s duration
        alarm_sns_topic_arn="arn:aws:sns:us-east-1:123456789012:alerts"
    )
)
```

### 2. Dead Letter Queues

```python
from taskflows.cloud import DeadLetterConfig

config = CloudFunctionConfig(
    function_name="important-task",
    dead_letter_config=DeadLetterConfig(
        auto_create=True,  # Auto-create SQS queue for failed invocations
    )
)
```

### 3. Lambda Layers

```python
from taskflows.cloud import LayerConfig

# Create reusable layer with dependencies
layer = LayerConfig(
    layer_name="data-deps",
    dependencies=["pandas", "numpy", "requests"],
    compatible_runtimes=["python3.11"]
)

config = CloudFunctionConfig(
    function_name="data-processor",
    layers=[layer],  # Use the layer
)
```

### 4. Versioning and Aliases

```python
config = CloudFunctionConfig(
    function_name="api-handler",
    enable_versioning=True,
    create_alias="live",  # Create "live" alias pointing to latest version
)

# Later, rollback if needed
manager.rollback("api-handler", version="previous")
```

### 5. Retry Configuration

```python
from taskflows.cloud import RetryConfig

config = CloudFunctionConfig(
    function_name="flaky-task",
    retry_config=RetryConfig(
        max_retry_attempts=2,
        max_event_age_seconds=3600  # Retry for up to 1 hour
    )
)
```

## Multi-Environment Deployment

Deploy the same function to dev, staging, and production with environment-specific configuration:

```python
def deploy_to_all_environments(function, name):
    environments = {
        "dev": {
            "memory_mb": 256,
            "enable_monitoring": False,
        },
        "staging": {
            "memory_mb": 512,
            "enable_monitoring": True,
        },
        "production": {
            "memory_mb": 1024,
            "enable_monitoring": True,
            "provisioned_concurrency": 2,  # Keep warm
        }
    }

    results = {}
    for env, config_overrides in environments.items():
        manager = DeploymentManager(
            provider="aws",
            backend="pulumi",
            environment=env
        )

        result = manager.deploy_function(
            name=name,
            function=function,
            **config_overrides
        )

        results[env] = result

    return results
```

## Dependency Management

### Automatic Detection

```python
from taskflows.cloud.dependencies import DependencyManager

dep_mgr = DependencyManager()

# Auto-detect imports from source code
source = """
import requests
import pandas as pd

def process():
    df = pd.DataFrame(...)
    response = requests.get(...)
"""

imports = dep_mgr.detect_imports(source)
print(imports)  # {'requests', 'pandas'}
```

### Docker-Based Builds

For consistent builds matching Lambda environment:

```python
dep_mgr = DependencyManager()

# Build using Docker (matches Lambda runtime exactly)
package = dep_mgr.build_deployment_package(
    requirements=["pandas", "numpy"],
    use_docker=True  # Uses public.ecr.aws/lambda/python:3.11
)
```

### Layer Packaging

```python
# Create properly structured Lambda Layer
layer_package = dep_mgr.create_layer_package(
    requirements=["requests", "boto3"],
    runtime="python3.11"
)

# Structure: python/lib/python3.11/site-packages/...
```

## Runtime Operations

### Invoke Functions

```python
# Synchronous invocation
response = manager.invoke(
    "my-function",
    payload={"key": "value"},
    async_invoke=False
)

# Asynchronous invocation (fire and forget)
manager.invoke(
    "batch-processor",
    payload={"batch_id": 123},
    async_invoke=True
)
```

### Get Logs

```python
# Get recent logs
logs = manager.get_logs("my-function", limit=100)
for log in logs:
    print(log)

# Get logs in time range
import time
start = int(time.time() * 1000) - 3600000  # 1 hour ago
logs = manager.get_logs("my-function", start_time=start)
```

### Get Metrics

```python
metrics = manager.get_metrics("my-function")
print(f"Invocations: {metrics.get('invocations')}")
print(f"Errors: {metrics.get('errors')}")
print(f"Avg Duration: {metrics.get('avg_duration_ms')}ms")
```

## Best Practices

### 1. Use Pulumi for Production

```python
# Recommended for production
manager = DeploymentManager(
    provider="aws",
    backend=DeploymentBackend.PULUMI,  # Not boto3
    environment="production"
)
```

### 2. Enable Monitoring

```python
# Always enable monitoring in production
config = CloudFunctionConfig(
    function_name="prod-task",
    monitoring=MonitoringConfig(enable_cloudwatch_alarms=True),
    dead_letter_config=DeadLetterConfig(auto_create=True),
    enable_versioning=True
)
```

### 3. Use Layers for Large Dependencies

```python
# Don't include pandas in every function
# Use a shared layer instead
layer = LayerConfig(
    layer_name="data-processing",
    dependencies=["pandas", "numpy", "scipy"]
)

# All functions can use this layer
config = CloudFunctionConfig(layers=[layer])
```

### 4. Tag Everything

```python
config = CloudFunctionConfig(
    function_name="my-function",
    tags={
        "Project": "DataPipeline",
        "Environment": "Production",
        "CostCenter": "Engineering",
        "Owner": "data-team@company.com",
        "ManagedBy": "TaskFlows"
    }
)
```

### 5. Use Docker for Dependency Builds

```python
dep_mgr = DependencyManager()

# Ensures binary compatibility with Lambda
package = dep_mgr.build_deployment_package(
    requirements=["psycopg2-binary", "numpy"],
    use_docker=True
)
```

## Resource Limits

### AWS Lambda

| Resource | Min | Max | Notes |
|----------|-----|-----|-------|
| Memory | 128 MB | 10,240 MB | In 1 MB increments |
| Timeout | 1 sec | 900 sec (15 min) | |
| Ephemeral Storage | 512 MB | 10,240 MB | /tmp directory |
| Deployment Package | - | 50 MB (zipped) | Use S3 for larger |
| Concurrent Executions | - | 1000 (default) | Can request increase |
| Payload Size | - | 6 MB (sync) / 256 KB (async) | |

## Cost Optimization

### 1. Right-Size Memory

```python
# Start with 256 MB, monitor, and adjust
config = CloudFunctionConfig(
    memory_mb=256,  # Adjust based on actual usage
)
```

### 2. Use Provisioned Concurrency Sparingly

```python
# Only for latency-sensitive production workloads
config = CloudFunctionConfig(
    provisioned_concurrency=2,  # Costs $$$ even when idle
)
```

### 3. Share Dependencies via Layers

```python
# One layer, many functions = less storage cost
layer = LayerConfig(
    layer_name="common-deps",
    dependencies=["requests", "boto3"]
)

# All functions use same layer (stored once)
```

### 4. Set Appropriate Timeouts

```python
# Don't use default 60s if function runs in 5s
config = CloudFunctionConfig(
    timeout_seconds=10,  # Only what you need
)
```

## Troubleshooting

### Import Error: Pulumi

```bash
pip install pulumi pulumi-aws
```

### Docker Not Available

```bash
# Install Docker
# Or disable Docker builds:
dep_mgr.build_deployment_package(
    requirements=["pandas"],
    use_docker=False  # Use local pip instead
)
```

### IAM Permission Errors

Ensure your AWS credentials have:
- `lambda:*` permissions
- `iam:CreateRole`, `iam:AttachRolePolicy`
- `events:PutRule`, `events:PutTargets`
- `logs:CreateLogGroup`, `logs:PutRetentionPolicy`

### Package Too Large

```python
# Option 1: Use Layers
config = CloudFunctionConfig(
    layers=[LayerConfig(layer_name="deps", dependencies=["pandas"])]
)

# Option 2: Enable S3 deployment
config = CloudFunctionConfig(
    use_s3_for_large_packages=True  # Auto-uploads to S3 if >50MB
)
```

## Migration from POC

If you were using the POC implementation, here's how to upgrade:

```python
# OLD (POC)
from taskflows.cloud import AWSLambdaEnvironment

env = AWSLambdaEnvironment(...)
result = env.deploy_function(my_func, config)

# NEW (Production) - Option 1: Use Manager
from taskflows.cloud.manager import DeploymentManager

manager = DeploymentManager(provider="aws", backend="pulumi")
result = manager.deploy_function("my-func", my_func, schedule="Mon-Fri 09:00")

# NEW (Production) - Option 2: Deploy Service
from taskflows.cloud.manager import deploy_service_to_cloud

result = deploy_service_to_cloud(my_service, provider="aws")
```

## Examples

See `examples/production_aws_deployment.py` for comprehensive examples including:

1. Production deployment with full monitoring
2. Lambda Layers usage
3. Deploying existing taskflows Services
4. Multi-function deployments
5. Multi-environment deployments
6. Runtime operations (invoke, logs, metrics)
7. Rollback and version management

## API Reference

### DeploymentManager

Main entry point for cloud deployments.

```python
manager = DeploymentManager(
    provider: Union[CloudProvider, str],
    backend: Union[DeploymentBackend, str],
    region: str,
    project_name: str,
    environment: str
)

# Methods
manager.deploy_function(name, function, schedule, ...)
manager.deploy_service(service, dependencies, ...)
manager.invoke(function_name, payload, async_invoke)
manager.get_logs(function_name, limit)
manager.get_metrics(function_name)
manager.delete(function_name)
manager.rollback(function_name, version)
```

### CloudFunctionConfig

Complete configuration for function deployment.

```python
config = CloudFunctionConfig(
    # Required
    function_name: str,

    # Runtime
    runtime: str = "python3.11",
    memory_mb: int = 256,
    timeout_seconds: int = 60,
    ephemeral_storage_mb: int = 512,

    # Scheduling
    schedules: List[Schedule] = None,

    # Monitoring
    monitoring: MonitoringConfig = None,

    # Error Handling
    dead_letter_config: DeadLetterConfig = None,
    retry_config: RetryConfig = None,

    # Layers
    layers: List[LayerConfig] = None,

    # Deployment
    enable_versioning: bool = True,
    create_alias: str = None,

    # Tags
    tags: Dict[str, str] = None,
)
```

## Support

- **Documentation**: `taskflows/cloud/README.md`
- **Examples**: `examples/production_aws_deployment.py`
- **Quick Start**: `examples/QUICK_START.md`

## Future Enhancements

- [ ] Google Cloud Functions support
- [ ] Azure Functions support
- [ ] Kubernetes CronJob deployment
- [ ] Cost estimation and tracking
- [ ] Advanced canary deployments
- [ ] Multi-region deployment
- [ ] CloudFormation/Terraform export from Pulumi
```
