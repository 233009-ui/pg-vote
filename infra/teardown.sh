#!/usr/bin/env bash
set -euo pipefail

CLUSTER="pg-autopilot"
SERVICE="pg-voter"
REPO="pg-autopilot"
REGIONS="${PG_REGIONS:-ap-southeast-1 ap-northeast-1 ap-south-1 us-east-1 eu-west-1 us-west-2}"

echo "=== PG Autopilot Teardown ==="
echo "This will stop all ECS services and clean up EventBridge/Lambda."
echo ""

for region in $REGIONS; do
  echo "--- $region ---"

  # Stop ECS service
  aws ecs update-service --cluster $CLUSTER --service $SERVICE \
    --desired-count 0 --region $region 2>/dev/null && echo "  ECS service scaled to 0" || true
  aws ecs delete-service --cluster $CLUSTER --service $SERVICE \
    --force --region $region 2>/dev/null && echo "  ECS service deleted" || true
  aws ecs delete-cluster --cluster $CLUSTER --region $region 2>/dev/null && echo "  ECS cluster deleted" || true

  # Remove EventBridge rules
  for i in $(seq 1 30); do
    RULE="pg-vote-trigger-$i"
    aws events remove-targets --rule "$RULE" --ids "pg-vote-$i" --region $region 2>/dev/null || true
    aws events delete-rule --name "$RULE" --region $region 2>/dev/null || true
  done
  echo "  EventBridge rules removed"

  # Delete Lambda
  aws lambda delete-function --function-name pg-vote --region $region 2>/dev/null && echo "  Lambda deleted" || true

  # Delete ECR repos
  for repo in pg-vote pg-autopilot; do
    aws ecr delete-repository --repository-name $repo --force --region $region 2>/dev/null || true
  done
  echo "  ECR repos deleted"

  # Delete log groups
  aws logs delete-log-group --log-group-name "/ecs/pg-autopilot" --region $region 2>/dev/null || true
done

echo ""
echo "=== Teardown complete ==="
echo "IAM roles pg-autopilot-ecs-role and pg-autopilot-task-role left in place (global)."
echo "Delete manually if no longer needed."
