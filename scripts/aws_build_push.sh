#!/usr/bin/env bash
set -euo pipefail
# Usage: AWS_REGION=us-east-1 PROJECT=repoguide-demo ./scripts/aws_build_push.sh
# Precondition: ECR repositories created by terraform -target and aws sso login.
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${PROJECT:-repoguide-demo}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TAG="$(git rev-parse --short=12 HEAD)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
for kind in api worker; do
  if [ "$kind" = api ]; then dockerfile='docker/Dockerfile.lambda'; else dockerfile='docker/Dockerfile.worker'; fi
  URI="${REGISTRY}/${PROJECT}/${kind}:${TAG}"
  echo "Building ${kind} for linux/amd64 — image may be large due to PyTorch."
  docker buildx build --platform linux/amd64 --provenance=false -f "$dockerfile" -t "$URI" --push .
  echo "${kind}: ${URI}"
done
