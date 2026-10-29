data "aws_caller_identity" "current" {}
resource "random_id" "suffix" { byte_length = 4 }
locals { name = "${var.project}-${random_id.suffix.hex}" }
resource "aws_s3_bucket" "artifacts" { bucket = "${local.name}-artifacts" }
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-short-lived-job-artifacts"
    status = "Enabled"
    filter { prefix = "jobs/" }
    expiration { days = 30 }
  }
}
resource "aws_dynamodb_table" "jobs" {
  name         = "${local.name}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery { enabled = false }
}
resource "aws_sqs_queue" "deadletter" {
  name                      = "${local.name}-index-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "index" {
  name                       = "${local.name}-index"
  visibility_timeout_seconds = 900
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.deadletter.arn, maxReceiveCount = 3 })
}
resource "aws_ecr_repository" "api" {
  name = "${var.project}/api"
  image_scanning_configuration { scan_on_push = true }
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
}
resource "aws_ecr_repository" "worker" {
  name = "${var.project}/worker"
  image_scanning_configuration { scan_on_push = true }
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
}
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = 7
}
resource "aws_cloudwatch_log_group" "scaler" {
  name              = "/aws/lambda/${local.name}-scaler"
  retention_in_days = 7
}
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name}-worker"
  retention_in_days = 7
}
