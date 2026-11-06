variable "aws_region" {
  type    = string
  default = "us-east-2"
}
variable "project" {
  type    = string
  default = "repoguide-demo"
}
variable "frontend_origin" {
  type    = string
  default = "https://repo-guide-five.vercel.app"
}
variable "validation_frontend_origin" {
  type        = string
  default     = ""
  description = "Temporary exact Vercel deployment origin for live browser verification; remove after cutover."
  validation {
    condition     = var.validation_frontend_origin == "" || can(regex("^https://[a-z0-9-]+\\.vercel\\.app$", var.validation_frontend_origin))
    error_message = "Validation origin must be a single HTTPS Vercel deployment hostname."
  }
}
variable "worker_image_uris" {
  type        = map(string)
  default     = {}
  description = "Only evaluated ECR image digests keyed by answer and index."
  validation {
    condition     = alltrue([for image in values(var.worker_image_uris) : can(regex("@sha256:[0-9a-f]{64}$", image))])
    error_message = "Workers must use immutable image digests."
  }
}
variable "worker_sizes" {
  type = map(object({ cpu = number, memory = number }))
  default = {
    answer = { cpu = 1024, memory = 4096 }
    index  = { cpu = 1024, memory = 4096 }
  }
}
variable "ssm_prefix" {
  type    = string
  default = "/repoguide/demo"
}
variable "alert_email" {
  type    = string
  default = "nikhilreddy.maligireddy2@gmail.com"
}
variable "release_id" {
  type    = string
  default = "unreleased"
}
variable "github_oidc_subject" {
  type    = string
  default = "repo:notnikhilreddy/RepoGuide:environment:production"
}
variable "enable_public_registration" {
  description = "Enable only after the new API's ownership and durable conversation smoke tests pass."
  type        = bool
  default     = false
}
