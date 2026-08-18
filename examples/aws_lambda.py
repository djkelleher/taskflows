"""Minimal AWS Lambda deployment example (creates billable AWS resources)."""

from taskflows.cloud import AWSLambdaEnvironment, CloudFunctionConfig
from taskflows.schedule import Calendar


def daily_report() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    environment = AWSLambdaEnvironment(
        region="us-east-1",
        execution_role_arn="arn:aws:iam::123456789012:role/taskflows-example",
    )
    result = environment.deploy_function(
        daily_report,
        CloudFunctionConfig(
            function_name="taskflows-daily-report",
            schedules=[Calendar("Mon-Fri 09:00")],
            create_alias="live",
            auto_create_role=False,
            tags={"ManagedBy": "Taskflows"},
        ),
    )
    if not result.success:
        raise RuntimeError(result.error)
    print(f"deployed {result.resource_id} version {result.version}")


if __name__ == "__main__":
    main()
