resource "aws_ecs_cluster" "main" { name = "${local.name}-cluster" }
resource "aws_ecs_task_definition" "workers" {
  for_each                 = local.kinds
  family                   = "${local.name}-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  skip_destroy             = true
  cpu                      = tostring(var.worker_sizes[each.key].cpu)
  memory                   = tostring(var.worker_sizes[each.key].memory)
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.workers[each.key].arn
  container_definitions = jsonencode([{
    name        = each.key, image = lookup(var.worker_image_uris, each.key, "UNPUBLISHED"), essential = true,
    stopTimeout = 120, readonlyRootFilesystem = true,
    user        = "10001:10001", linuxParameters = { capabilities = { add = [], drop = ["ALL"] } },
    environment = concat([
      { name = "REPOGUIDE_WORKER_KIND", value = each.key },
      { name = "REPOGUIDE_CLOUD_MODE", value = "true" },
      { name = "REPOGUIDE_SSM_PARAMETER", value = "${var.ssm_prefix}/${each.key}" },
      { name = "REPOGUIDE_RELEASE", value = var.release_id },
      { name = "REPOGUIDE_JOB_TABLE", value = aws_dynamodb_table.jobs.name },
      { name = "REPOGUIDE_ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.bucket },
      { name = "REPOGUIDE_CACHE_NAMESPACE", value = "production" },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      { name = "MLFLOW_ENABLED", value = "false" }
      ], [for kind in local.kinds : { name = "REPOGUIDE_${upper(kind)}_SERVICE", value = "${local.name}-${kind}" }],
      [for kind in local.kinds : { name = "REPOGUIDE_${upper(kind)}_QUEUE_URL", value = aws_sqs_queue.work[kind].url }],
    [for kind in local.kinds : { name = "REPOGUIDE_${upper(kind)}_DLQ_URL", value = aws_sqs_queue.dlq[kind].url }]),
    mountPoints = [{ sourceVolume = "scratch", containerPath = "/tmp", readOnly = false }],
    logConfiguration = { logDriver = "awslogs", options = {
      "awslogs-group"  = aws_cloudwatch_log_group.workers[each.key].name,
      "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = each.key
    } }
  }])
  volume { name = "scratch" }
  lifecycle {
    precondition {
      condition     = contains(keys(var.worker_image_uris), each.key) && local.approved_release
      error_message = "Build and evaluate both workers before deploying their task definitions."
    }
  }
}
resource "aws_ecs_service" "workers" {
  for_each         = local.kinds
  name             = "${local.name}-${each.key}"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.workers[each.key].arn
  desired_count    = 0
  launch_type      = "FARGATE"
  platform_version = "1.4.0"
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = true
  }
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  lifecycle { ignore_changes = [desired_count] }
}
locals {
  release_approval = try(jsondecode(file("${path.module}/../../.artifacts/release-approval.json")), {})
  release_manifest = try(jsondecode(file("${path.module}/../../.artifacts/release-manifest.json")), {})
  approved_release = try(local.release_approval.technical_checks_passed == true && contains(["passed", "skipped_by_owner"], local.release_approval.quality_status) && local.release_approval.source_sha256 == jsondecode(file("${path.module}/../../deployment/release-config.json")).source_sha256 && local.release_approval.source_sha256 == local.release_manifest.source_sha256 && local.release_approval.release_fingerprint == local.release_manifest.release_fingerprint && tomap(local.release_manifest.images) == var.worker_image_uris && local.release_manifest.release_id == var.release_id, false)
  control_environment = merge({
    REPOGUIDE_JOB_TABLE       = aws_dynamodb_table.jobs.name
    REPOGUIDE_ECS_CLUSTER     = aws_ecs_cluster.main.name
    REPOGUIDE_ARTIFACT_BUCKET = aws_s3_bucket.artifacts.bucket
    }, { for kind in local.kinds : "REPOGUIDE_${upper(kind)}_SERVICE" => "${local.name}-${kind}" },
    { for kind in local.kinds : "REPOGUIDE_${upper(kind)}_QUEUE_URL" => aws_sqs_queue.work[kind].url },
  { for kind in local.kinds : "REPOGUIDE_${upper(kind)}_DLQ_URL" => aws_sqs_queue.dlq[kind].url })
}
resource "aws_lambda_function" "api" {
  function_name    = "${local.name}-api"
  role             = aws_iam_role.api.arn
  package_type     = "Zip"
  filename         = "${path.module}/../../deployment/api.zip"
  source_code_hash = fileexists("${path.module}/../../deployment/api.zip") ? filebase64sha256("${path.module}/../../deployment/api.zip") : null
  runtime          = "python3.12"
  handler          = "repoguide.cloud_api.handler"
  memory_size      = 512
  timeout          = 15
  architectures    = ["x86_64"]
  environment { variables = merge(local.control_environment, {
    REPOGUIDE_API_SSM_PARAMETER = "${var.ssm_prefix}/api"
    REPOGUIDE_RELEASE           = var.release_id
    REPOGUIDE_COGNITO_ISSUER    = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.demo.id}"
    REPOGUIDE_COGNITO_CLIENT_ID = aws_cognito_user_pool_client.spa.id
    REPOGUIDE_FRONTEND_ORIGIN   = var.frontend_origin
  }) }
  lifecycle {
    precondition {
      condition     = local.approved_release
      error_message = "Production requires technical checks, evaluated or explicitly owner-authorized quality status, and the exact published manifest."
    }
  }
  depends_on = [aws_iam_role_policy.api_logs, aws_cloudwatch_log_group.api]
}
resource "aws_lambda_function" "scaler" {
  function_name    = "${local.name}-controller"
  role             = aws_iam_role.scaler.arn
  package_type     = "Zip"
  filename         = "${path.module}/../../deployment/controller.zip"
  source_code_hash = fileexists("${path.module}/../../deployment/controller.zip") ? filebase64sha256("${path.module}/../../deployment/controller.zip") : null
  runtime          = "python3.12"
  handler          = "repoguide.cloud_scaler.handler"
  memory_size      = 256
  timeout          = 30
  architectures    = ["x86_64"]
  environment { variables = local.control_environment }
  lifecycle {
    precondition {
      condition     = local.approved_release
      error_message = "Production requires the approved release manifest."
    }
  }
  depends_on = [aws_iam_role_policy.scaler_logs, aws_cloudwatch_log_group.scaler]
}
resource "aws_cloudwatch_event_rule" "scaler" {
  name                = "${local.name}-idle-controller"
  schedule_expression = "rate(1 minute)"
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
