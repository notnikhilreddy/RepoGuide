# Optional: enable for automated image pushes after reviewing IAM boundaries.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_oidc_subject != "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "github_deploy" {
  count = var.github_oidc_subject != "" ? 1 : 0
  name  = "${local.name}-github-ecr-push"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity",
    Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn },
    Condition = { StringEquals = {
      "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub" = var.github_oidc_subject
    } }
  }] })
}
resource "aws_iam_role_policy" "github_ecr" {
  count = var.github_oidc_subject != "" ? 1 : 0
  role  = aws_iam_role.github_deploy[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload",
      "ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage"],
    Resource = [aws_ecr_repository.api.arn, aws_ecr_repository.worker.arn] }
  ] })
}
output "github_ecr_role_arn" { value = var.github_oidc_subject != "" ? aws_iam_role.github_deploy[0].arn : null }
