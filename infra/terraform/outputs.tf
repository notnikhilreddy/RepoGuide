output "api_url" { value = aws_apigatewayv2_api.http.api_endpoint }
output "user_pool_id" { value = aws_cognito_user_pool.demo.id }
output "cognito_client_id" { value = aws_cognito_user_pool_client.spa.id }
output "cognito_issuer" { value = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.demo.id}" }
output "cognito_domain" { value = "https://${aws_cognito_user_pool_domain.demo.domain}.auth.${var.aws_region}.amazoncognito.com" }
output "ecr_workers" { value = { for k, r in aws_ecr_repository.workers : k => r.repository_url } }
output "job_table" { value = aws_dynamodb_table.jobs.name }
output "queues" { value = { for k, q in aws_sqs_queue.work : k => q.url } }
output "deadletter_queues" { value = { for k, q in aws_sqs_queue.dlq : k => q.url } }
output "ecs_cluster" { value = aws_ecs_cluster.main.name }
output "ecs_services" { value = { for k, s in aws_ecs_service.workers : k => s.name } }
output "artifact_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "api_function" { value = aws_lambda_function.api.function_name }
output "controller_function" { value = aws_lambda_function.scaler.function_name }
