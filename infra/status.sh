#!/usr/bin/env bash
set -euo pipefail

CLUSTER="pg-autopilot"
SERVICE="pg-voter"
REGIONS="${PG_REGIONS:-ap-southeast-1 ap-northeast-1 ap-south-1 us-east-1 eu-west-1 us-west-2}"

echo "╔══════════════════════════════════════════════╗"
echo "║        PG Autopilot — Status Dashboard       ║"
echo "╠══════════════════════════════════════════════╣"
echo ""

for region in $REGIONS; do
  echo "═══ $region ═══"

  # ECS status
  STATUS=$(aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
    --region $region --query 'services[0].{status:status,desired:desiredCount,running:runningCount}' \
    --output json 2>/dev/null || echo '{"status":"NOT_FOUND"}')
  echo "  ECS: $STATUS"

  # Lambda invocation count (last hour)
  INVOCATIONS=$(aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda --metric-name Invocations \
    --dimensions Name=FunctionName,Value=pg-vote \
    --start-time "$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 3600 --statistics Sum \
    --region $region --query 'Datapoints[0].Sum' --output text 2>/dev/null || echo "N/A")
  echo "  Lambda (1h): $INVOCATIONS invocations"

  # EventBridge rules count
  RULES=$(aws events list-rules --name-prefix pg-vote --region $region \
    --query 'length(Rules[?State==`ENABLED`])' --output text 2>/dev/null || echo "0")
  echo "  EventBridge: $RULES active rules"
  echo ""
done

# CloudWatch custom metrics
echo "═══ Custom Metrics (last 10 min) ═══"
for region in $REGIONS; do
  VPH=$(aws cloudwatch get-metric-statistics \
    --namespace PGAutopilot --metric-name VotesPerHour \
    --dimensions Name=Region,Value=$region \
    --start-time "$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 600 --statistics Average \
    --region $region --query 'Datapoints[0].Average' --output text 2>/dev/null || echo "N/A")
  echo "  $region: $VPH V/HR"
done
