variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "project" {
  type    = string
  default = "repoguide-demo"
}
variable "frontend_origin" {
  type    = string
  default = "http://localhost:5173"
}
variable "api_image_uri" {
  type        = string
  description = "An ECR image URL (tag or digest). Build/push before final apply."
}
variable "worker_image_uri" {
  type        = string
  description = "An ECR image URL (tag or digest). Build/push before final apply."
}
variable "ssm_parameter_name" {
  type    = string
  default = "/repoguide/demo/runtime"
}
variable "alert_email" {
  type        = string
  description = "Email for cost/error alerts"
}
variable "github_oidc_subject" {
  type        = string
  default     = ""
  description = "Optional GitHub OIDC: exact token sub claim for main branch (newer repos may use org/repo IDs)"
}
