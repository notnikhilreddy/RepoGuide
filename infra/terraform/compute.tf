resource "aws_ecs_cluster" "main" { name = "${local.name}-cluster" }
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "4096"
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn
  container_definitions = jsonencode([{ name = "worker", image = var.worker_image_uri, essential = true,
    environment = [
      { name = "REPOGUIDE_CLOUD_MODE", value = "true" },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      { name = "REPOGUIDE_SSM_PARAMETER", value = var.ssm_parameter_name },
      { name = "REPOGUIDE_JOB_TABLE", value = aws_dynamodb_table.jobs.name },
      { name = "REPOGUIDE_QUEUE_URL", value = aws_sqs_queue.index.id },
      { name = "REPOGUIDE_ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.bucket },
      { name = "MLFLOW_ENABLED", value = "false" }
    ],
    logConfiguration = { logDriver = "awslogs", options = {
      "awslogs-group" = aws_cloudwatch_log_group.worker.name,
    "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "worker" } }
  }])
}
resource "aws_ecs_service" "worker" {
  name                   = "${local.name}-worker"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.worker.arn
  desired_count          = 0
  launch_type            = "FARGATE"
  enable_execute_command = false
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = true
  }
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 200
  lifecycle { ignore_changes = [desired_count] }
}
resource "aws_lambda_function" "api" {
  function_name                  = "${local.name}-api"
  role                           = aws_iam_role.api.arn
  package_type                   = "Image"
  image_uri                      = var.api_image_uri
  memory_size                    = 2048
  timeout                        = 29
  architectures                  = ["x86_64"]
  reserved_concurrent_executions = -1
  ephemeral_storage { size = 2048 }
  environment { variables = {
    REPOGUIDE_CLOUD_MODE               = "true"
    REPOGUIDE_SSM_PARAMETER            = var.ssm_parameter_name
    REPOGUIDE_JOB_TABLE                = aws_dynamodb_table.jobs.name
    REPOGUIDE_QUEUE_URL                = aws_sqs_queue.index.id
    REPOGUIDE_ECS_CLUSTER              = aws_ecs_cluster.main.name
    REPOGUIDE_ECS_SERVICE              = aws_ecs_service.worker.name
    REPOGUIDE_USER_REQUESTS_PER_MINUTE = "5"
    MLFLOW_ENABLED                     = "false"
    HF_HOME                            = "/opt/hf_cache"
    HF_HUB_OFFLINE                     = "1"
  } }
  depends_on = [aws_iam_role_policy_attachment.api_logs, aws_cloudwatch_log_group.api]
}
resource "aws_lambda_function" "scaler" {
  function_name                  = "${local.name}-scaler"
  role                           = aws_iam_role.scaler.arn
  package_type                   = "Zip"
  memory_size                    = 256
  timeout                        = 30
  architectures                  = ["x86_64"]
  reserved_concurrent_executions = -1
  environment { variables = {
    REPOGUIDE_JOB_TABLE   = aws_dynamodb_table.jobs.name
    REPOGUIDE_QUEUE_URL   = aws_sqs_queue.index.id
    REPOGUIDE_ECS_CLUSTER = aws_ecs_cluster.main.name
    REPOGUIDE_ECS_SERVICE = aws_ecs_service.worker.name
  } }
  depends_on = [aws_iam_role_policy_attachment.scaler_logs, aws_cloudwatch_log_group.scaler]
  # Tiny stdlib + runtime-provided boto3 ZIP; no PyTorch or model weights.
  filename         = data.archive_file.scaler.output_path
  source_code_hash = data.archive_file.scaler.output_base64sha256
  runtime          = "python3.12"
  handler          = "cloud_scaler.handler"
}
resource "aws_cloudwatch_event_rule" "scaler" {
  name                = "${local.name}-worker-scaler"
  schedule_expression = "rate(5 minutes)"
}
resource "aws_cloudwatch_event_target" "scaler" {
  rule = aws_cloudwatch_event_rule.scaler.name
  arn  = aws_lambda_function.scaler.arn
}
resource "aws_lambda_permission" "scaler" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scaler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scaler.arn
}

# Keep this generated ZIP under .terraform so it cannot be committed by mistake.
# Run terraform init before plan: the archive data source needs its output folder.
data "archive_file" "scaler" {
  type             = "zip"
  source_file      = "${path.module}/../../src/repoguide/cloud_scaler.py"
  output_path      = "${path.module}/.terraform/repoguide_scaler.zip"
  output_file_mode = "0644"
}
