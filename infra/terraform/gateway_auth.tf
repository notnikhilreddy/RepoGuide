resource "aws_cognito_user_pool" "demo" {
  name = "${local.name}-users"
  admin_create_user_config { allow_admin_create_user_only = true }
  auto_verified_attributes = ["email"]
  username_attributes = ["email"]
  password_policy {
    minimum_length = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers = true
    require_symbols = true
    temporary_password_validity_days = 7
  }
}
resource "aws_cognito_user_group" "admins" {
  user_pool_id = aws_cognito_user_pool.demo.id
  name = "repoguide-admins"
  description = "May enqueue costly indexing jobs"
}
resource "aws_cognito_user_pool_domain" "demo" {
  domain = "${var.project}-${random_id.suffix.hex}"
  user_pool_id = aws_cognito_user_pool.demo.id
}
resource "aws_cognito_user_pool_client" "spa" {
  name = "${local.name}-spa"
  user_pool_id = aws_cognito_user_pool.demo.id
  generate_secret = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows = ["code"]
  allowed_oauth_scopes = ["openid", "email", "profile"]
  supported_identity_providers = ["COGNITO"]
  callback_urls = ["${var.frontend_origin}/", "http://localhost:5173/"]
  logout_urls = ["${var.frontend_origin}/", "http://localhost:5173/"]
  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH"]
}
resource "aws_apigatewayv2_api" "http" {
  name = "${local.name}-http"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = distinct([var.frontend_origin, "http://localhost:5173"])
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Authorization", "Content-Type"]
    max_age = 600
  }
}
resource "aws_apigatewayv2_integration" "lambda" {
  api_id = aws_apigatewayv2_api.http.id
  integration_type = "AWS_PROXY"
  integration_uri = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id = aws_apigatewayv2_api.http.id
  name = "cognito"
  authorizer_type = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.spa.id]
    issuer = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.demo.id}"
  }
}
resource "aws_apigatewayv2_route" "default" {
  api_id = aws_apigatewayv2_api.http.id
  route_key = "$default"
  target = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id = aws_apigatewayv2_authorizer.jwt.id
}
resource "aws_apigatewayv2_route" "health" {
  api_id = aws_apigatewayv2_api.http.id
  route_key = "GET /health"
  target = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "NONE"
}
resource "aws_apigatewayv2_stage" "default" {
  api_id = aws_apigatewayv2_api.http.id
  name = "$default"
  auto_deploy = true
  default_route_settings { throttling_rate_limit = 20, throttling_burst_limit = 40 }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.gateway.arn
    format = jsonencode({ requestId="$context.requestId", sourceIp="$context.identity.sourceIp",
      httpMethod="$context.httpMethod", path="$context.path", status="$context.status",
      responseLatency="$context.responseLatency", integrationError="$context.integrationErrorMessage" })
  }
}
resource "aws_cloudwatch_log_group" "gateway" {
  name = "/apigateway/${local.name}-http"
  retention_in_days = 7
}
resource "aws_lambda_permission" "apigateway" {
  action = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal = "apigateway.amazonaws.com"
  source_arn = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
