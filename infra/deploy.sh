#!/usr/bin/env bash
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO="pg-autopilot"
CLUSTER="pg-autopilot"
SERVICE="pg-voter"
TASK_FAMILY="pg-voter"
WORKERS=10
TASKS_PER_REGION=10
REGIONS="${PG_REGIONS:-ap-southeast-1 ap-northeast-1 ap-south-1 us-east-1 eu-west-1 us-west-2}"
BUILD_REGION="${PG_BUILD_REGION:-ap-southeast-1}"
NTFY_TOPIC="pg-autopilot-sh3rd1l"

echo "╔══════════════════════════════════════════════╗"
echo "║     PG Autopilot — Full AWS Deployment       ║"
echo "╠══════════════════════════════════════════════╣"
echo "  Account:  $ACCOUNT"
echo "  Regions:  $REGIONS"
echo "  Workers:  $WORKERS per region"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Build Docker image ────────────────────────────────────────────
echo "=== Building Docker image ==="
cd "$(dirname "$0")/.."
DOCKER_BUILDKIT=0 docker build -t $REPO:latest .
echo "Build complete"

# ── 2. IAM Role (if not exists) ──────────────────────────────────────
ROLE_NAME="pg-autopilot-ecs-role"
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

if ! aws iam get-role --role-name $ROLE_NAME >/dev/null 2>&1; then
  echo "=== Creating ECS execution role ==="
  aws iam create-role \
    --role-name $ROLE_NAME \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": ["ecs-tasks.amazonaws.com"]},
        "Action": "sts:AssumeRole"
      }]
    }' >/dev/null

  aws iam attach-role-policy --role-name $ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
  aws iam attach-role-policy --role-name $ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/CloudWatchFullAccess

  echo "Waiting for role propagation..."
  sleep 10
fi

EXEC_ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text)
echo "Execution role: $EXEC_ROLE_ARN"

# Task role for CloudWatch metrics
TASK_ROLE_NAME="pg-autopilot-task-role"
if ! aws iam get-role --role-name $TASK_ROLE_NAME >/dev/null 2>&1; then
  echo "=== Creating task role ==="
  aws iam create-role \
    --role-name $TASK_ROLE_NAME \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": ["ecs-tasks.amazonaws.com"]},
        "Action": "sts:AssumeRole"
      }]
    }' >/dev/null
  aws iam attach-role-policy --role-name $TASK_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/CloudWatchFullAccess
  sleep 10
fi
TASK_ROLE_ARN=$(aws iam get-role --role-name $TASK_ROLE_NAME --query 'Role.Arn' --output text)

# ── 3. Deploy to each region ─────────────────────────────────────────
for region in $REGIONS; do
  echo ""
  echo "═══ Deploying to $region ═══"

  # ECR repo
  REPO_URI="${ACCOUNT}.dkr.ecr.${region}.amazonaws.com/${REPO}"
  aws ecr create-repository --repository-name $REPO --region $region 2>/dev/null || true

  # Login + push
  aws ecr get-login-password --region $region | \
    docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${region}.amazonaws.com" 2>&1 | tail -1
  docker tag ${REPO}:latest ${REPO_URI}:latest
  docker push ${REPO_URI}:latest 2>&1 | tail -2

  # ECS cluster
  aws ecs create-cluster --cluster-name $CLUSTER --region $region 2>/dev/null || true

  # Get default VPC subnets
  DEFAULT_VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' --output text --region $region 2>/dev/null)
  SUBNETS=$(aws ec2 describe-subnets --filters Name=vpc-id,Values=$DEFAULT_VPC \
    --query 'Subnets[*].SubnetId' --output text --region $region 2>/dev/null | tr '\t' ',')
  # Get default security group
  SG=$(aws ec2 describe-security-groups \
    --filters Name=vpc-id,Values=$DEFAULT_VPC Name=group-name,Values=default \
    --query 'SecurityGroups[0].GroupId' --output text --region $region 2>/dev/null)

  # CloudWatch log group
  aws logs create-log-group --log-group-name "/ecs/pg-autopilot" --region $region 2>/dev/null || true

  # Task definition
  TASK_DEF=$(cat <<TASKEOF
{
  "family": "${TASK_FAMILY}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "containerDefinitions": [{
    "name": "voter",
    "image": "${REPO_URI}:latest",
    "essential": true,
    "environment": [
      {"name": "PG_WORKERS", "value": "${WORKERS}"},
      {"name": "PG_NONCE", "value": "3e04eea04c"},
      {"name": "PG_POST_ID", "value": "24454"},
      {"name": "PG_NTFY_TOPIC", "value": "${NTFY_TOPIC}"},
      {"name": "PG_ENABLE_CLOUDWATCH", "value": "1"},
      {"name": "PG_ENABLE_SOLVER", "value": "0"},
      {"name": "AWS_REGION", "value": "${region}"},
      {"name": "PG_INSTANCE_ID", "value": "fargate-${region}"}
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/pg-autopilot",
        "awslogs-region": "${region}",
        "awslogs-stream-prefix": "voter"
      }
    }
  }]
}
TASKEOF
  )
  echo "$TASK_DEF" > /tmp/pg-task-def.json
  TASK_ARN=$(aws ecs register-task-definition --cli-input-json file:///tmp/pg-task-def.json \
    --region $region --query 'taskDefinition.taskDefinitionArn' --output text)
  echo "  Task: $TASK_ARN"

  # Create or update service
  EXISTING=$(aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
    --region $region --query 'services[?status==`ACTIVE`].serviceName' --output text 2>/dev/null)

  if [ -n "$EXISTING" ] && [ "$EXISTING" != "None" ]; then
    echo "  Updating existing service..."
    aws ecs update-service --cluster $CLUSTER --service $SERVICE \
      --task-definition $TASK_ARN --desired-count ${TASKS_PER_REGION} --force-new-deployment \
      --region $region >/dev/null
  else
    echo "  Creating service..."
    aws ecs create-service \
      --cluster $CLUSTER \
      --service-name $SERVICE \
      --task-definition $TASK_ARN \
      --desired-count ${TASKS_PER_REGION} \
      --launch-type FARGATE \
      --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=ENABLED}" \
      --region $region >/dev/null
  fi

  echo "  ✓ $region deployed"
done

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  DEPLOYMENT COMPLETE                         ║"
echo "║  ${#REGIONS[@]} regions, $WORKERS workers each          ║"
echo "║  Monitor: ntfy.sh/${NTFY_TOPIC}  ║"
echo "╚══════════════════════════════════════════════╝"
