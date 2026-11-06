data "aws_caller_identity" "current" {}
resource "random_id" "suffix" { byte_length = 4 }
locals {
  name  = "${var.project}-${random_id.suffix.hex}"
  kinds = toset(["answer", "index"])
}
resource "aws_s3_bucket" "artifacts" { bucket = "${local.name}-artifacts" }
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}
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
    id     = "expire-job-results"
    status = "Enabled"
    filter { prefix = "jobs/" }
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }
  rule {
    id     = "retain-current-conversations"
    status = "Enabled"
    filter { prefix = "conversations/" }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_s3_bucket_policy" "artifacts_tls" {
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_dynamodb_table" "jobs" {
  name         = "${local.name}-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "dispatch_key"
    type = "S"
  }
  attribute {
    name = "dispatch_at"
    type = "N"
  }
  attribute {
    name = "catalog_pk"
    type = "S"
  }
  attribute {
    name = "catalog_sk"
    type = "S"
  }
  global_secondary_index {
    name            = "catalog"
    hash_key        = "catalog_pk"
    range_key       = "catalog_sk"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "dispatch"
    hash_key        = "dispatch_key"
    range_key       = "dispatch_at"
    projection_type = "KEYS_ONLY"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
resource "aws_sqs_queue" "dlq" {
  for_each                  = local.kinds
  name                      = "${local.name}-${each.key}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "work" {
  for_each                   = local.kinds
  name                       = "${local.name}-${each.key}"
  visibility_timeout_seconds = 120
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn, maxReceiveCount = 5 })
}
resource "aws_ecr_repository" "workers" {
  for_each = local.kinds
  name     = "${var.project}/${each.key}"
  image_scanning_configuration { scan_on_push = true }
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
}
resource "aws_ecr_lifecycle_policy" "workers" {
  for_each   = local.kinds
  repository = aws_ecr_repository.workers[each.key].name
  # Tagged production/rollback digests are protected; explicit retention script
  # removes older releases only after checking ECS and the release manifest.
  policy = jsonencode({ rules = [{ rulePriority = 1, description = "Expire only untagged images after seven days",
  selection = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }, action = { type = "expire" } }] })
}
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = 7
}
resource "aws_cloudwatch_log_group" "scaler" {
  name              = "/aws/lambda/${local.name}-controller"
  retention_in_days = 7
}
resource "aws_cloudwatch_log_group" "workers" {
  for_each          = local.kinds
  name              = "/ecs/${local.name}-${each.key}"
  retention_in_days = 7
}
