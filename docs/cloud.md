# AWS Lambda deployment (beta)

`taskflows.cloud` packages a no-argument Python callable as an AWS Lambda
function and can reconcile EventBridge schedules around it. This feature is a
**beta**: use it first in a non-production AWS account and review every IAM and
Pulumi change before applying it.

Only AWS Lambda is implemented. The GCP, Azure, Kubernetes, and Terraform enum
values reserve names for possible future work; selecting them raises an error.

## Install

Use the direct AWS SDK backend:

```console
pip install "taskflows[aws]"
```

For the experimental Pulumi backend, install the Pulumi CLI and:

```console
pip install "taskflows[pulumi]"
```

Both backends use the normal AWS credential chain. Do not put credentials in a
`CloudFunctionConfig` or in source code.

## Deploy with boto3

```python
from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
from taskflows.schedule import Calendar


def cleanup() -> dict[str, int]:
    # Imports used only by the function can be declared in dependencies below.
    return {"deleted": 3}


environment = AWSLambdaEnvironment(
    region="us-east-1",
    # Supplying an existing least-privilege role is recommended. When omitted,
    # auto_create_role=True creates and attaches the basic execution policy.
    execution_role_arn="arn:aws:iam::123456789012:role/taskflows-cleanup",
    # Required only when the compressed package is larger than 50 MB.
    deployment_bucket="my-versioned-deployment-bucket",
)

config = CloudFunctionConfig(
    function_name="cleanup",
    schedules=[Calendar("Mon-Fri 09:00")],  # UTC
    timeout_seconds=120,
    memory_mb=512,
    environment_variables={"BUCKET": "archive"},
    enable_versioning=True,
    create_alias="live",
    auto_create_role=False,
    tags={"Application": "maintenance"},
)

result = environment.deploy_function(cleanup, config, dependencies=["boto3"])
if not result.success:
    raise RuntimeError(result.error)
print(result.resource_id, result.version)
```

When dependencies are supplied, Taskflows builds them in the matching AWS
Lambda Linux image with Docker by default. This matters for packages containing
native extensions. Set `build_dependencies_in_docker=False` only when the
packages are known to be pure Python and the local interpreter matches the
configured Lambda runtime.

Encryption settings are intentionally separate: use
`AWSLambdaConfig(lambda_kms_key_arn=...)` for Lambda environment-variable
encryption and `deployment_kms_key_arn=...` for S3 deployment archives. The
older `kms_key_arn` field remains a compatibility alias for the Lambda setting.

## Deploy with Pulumi

```python
from taskflows.cloud import CloudFunctionConfig, PulumiAWSEnvironment

environment = PulumiAWSEnvironment(
    project_name="maintenance",
    stack_name="production",
    region="us-east-1",
)
config = CloudFunctionConfig(function_name="cleanup")
print(environment.preview_function(cleanup, config))
result = environment.deploy_function(cleanup, config)
```

Pulumi state and generated archives default to
`~/.taskflows/pulumi/<project>/`. Each function gets a separate deterministic
stack; this prevents one function deployment from deleting another function.
The Pulumi backend is still experimental. Inspect `preview_function` output and
complete a real AWS smoke deployment before production use.

## Callable contract

- The callable must take no arguments. EventBridge/Lambda event data is not
  passed to it.
- The callable and its closure are serialized with `cloudpickle`. Treat a
  deployment package as executable code and control who can replace it.
- `Service.start_command` must be a Python callable. Local shell commands,
  conda environments, Docker containers, working directories, and systemd-only
  service settings cannot be translated to Lambda.
- The generated handler is `index.handler` and only Python Lambda runtimes are
  accepted.
- Secret values are never copied into environment variables. Pass a secret ARN
  or name and retrieve it from AWS Secrets Manager at runtime using an IAM role.

## Schedule translation

Supported calendar forms are deliberately narrow:

```text
Mon-Fri 09:00
Mon,Wed,Fri 16:30
Sun 17:00 UTC
```

They become legacy EventBridge scheduled rules and therefore run in UTC.
Non-UTC timezone suffixes and non-zero seconds are rejected rather than silently
changing when a function runs. Broader systemd calendar syntax is not supported.

`Periodic` intervals must be whole minutes. EventBridge rate expressions run at
fixed intervals from rule creation; they cannot exactly reproduce systemd's
`relative_to="finish"`, boot/login activation, persistence, accuracy, or
randomized delay behavior.

## Lifecycle behavior

A full `deploy_function` call reconciles:

- function code and mutable configuration;
- published versions and an optional alias;
- Taskflows-owned EventBridge rules (including stale-rule removal);
- asynchronous retry/event-age settings;
- reserved and provisioned concurrency;
- CloudWatch log retention and optional alarms;
- optional Lambda layers, DLQ, VPC, X-Ray, and code-signing settings.

For an encrypted DLQ, set `DeadLetterConfig.kms_key_arn`. Auto-created roles
then receive the required KMS permissions; an externally supplied role must be
granted the equivalent permissions by its owner.

Provisioned concurrency requires an alias. This gives updates a stable target
and prevents capacity from being left attached to immutable old versions. Alias
and user-tag changes are reconciled only for resources recorded as Taskflows
managed; unmarked customer aliases and tags are not deleted. Auto-created IAM
roles are tagged and stale policies previously attached by Taskflows are
removed, while an existing unmarked role is rejected rather than modified.

The boto3 backend can invoke, list, update, delete, inspect logs/metrics, list
versions, move aliases, and roll an alias back to an earlier published version.
Rollback changes an alias; it does not mutate an immutable published version.
Pass the alias as `rollback_id` when a function has more than one alias.

Deletion removes the Lambda function and Taskflows-prefixed EventBridge rules.
It intentionally preserves logs, IAM roles, deployment objects, DLQs, and alarms
because those resources may contain audit data or be shared. Clean them up
explicitly after checking ownership.

## Important limitations

- No end-to-end deployment has yet been certified against a real AWS account.
- There is no API Gateway/function-URL integration.
- There are no GCP, Azure, Kubernetes, or Terraform implementations.
- Dependency auto-detection is best-effort; pass an explicit, pinned list.
- Lambda's 50 MB direct-upload and 250 MB extracted package limits apply. Large
  archives require an S3 bucket in the same region.
- EventBridge Scheduler timezone support is not implemented; scheduled rules
  are UTC only.
- Pulumi runtime operations such as listing are limited to functions deployed in
  the current process; persisted stacks can still be reconciled or destroyed by
  deterministic function name.

## Verification before production

1. Run unit tests and an AWS emulator-backed test suite.
2. Run and inspect `PulumiAWSEnvironment.preview_function`.
3. Deploy to a sandbox account and invoke both manually and on schedule.
4. Verify IAM least privilege, DLQ delivery, alarms, log retention, rollback,
   package architecture, and cleanup behavior.
5. Add an automated sandbox deployment/destroy workflow before removing the
   beta label.
