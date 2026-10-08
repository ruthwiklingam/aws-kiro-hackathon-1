#!/usr/bin/env bash
# =============================================================================
# deploy.sh – Student Risk Dashboard CloudFormation deploy script
#
# Usage:
#   ./scripts/deploy.sh [--region us-east-1] [--stack-name student-risk-dashboard]
#
# Idempotent: safe to re-run.  Existing stack will be updated; existing S3
# objects will be overwritten.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults (override via env vars or flags)
# ---------------------------------------------------------------------------
REGION="${AWS_REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-student-risk-dashboard}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${REPO_ROOT}/infra/template.yaml"

LAMBDA_PACKAGE_DIR="/tmp/lambda-packages"
LAYER_DIR="/tmp/lambda-layers"
LAYER_ZIP="/tmp/lambda-layer.zip"

# Lambda source directories (relative to repo root)
# Adjust these paths if your handler code lives elsewhere.
declare -A LAMBDA_DIRS=(
  [ingest-students]="${REPO_ROOT}/lambdas/ingest-students"
  [score-risk]="${REPO_ROOT}/lambdas/score-risk"
  [generate-recommendations]="${REPO_ROOT}/lambdas/generate-recommendations"
)

# Requirements file shared by all Lambdas (or each can have its own)
SHARED_REQUIREMENTS="${REPO_ROOT}/lambdas/requirements.txt"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
header() { echo; echo "=============================================================="; echo "  $*"; echo "=============================================================="; }
info()   { echo "[INFO]  $*"; }
ok()     { echo "[OK]    $*"; }
warn()   { echo "[WARN]  $*"; }

# ---------------------------------------------------------------------------
# 1. Verify AWS CLI is configured
# ---------------------------------------------------------------------------
header "1. Verifying AWS credentials"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
  echo "[ERROR] 'aws sts get-caller-identity' failed."
  echo "        Make sure AWS CLI is configured (aws configure / env vars / IAM role)."
  exit 1
}
ok "Authenticated as account ${ACCOUNT_ID} in region ${REGION}"

DEPLOY_BUCKET="student-risk-deploy-${ACCOUNT_ID}"

# ---------------------------------------------------------------------------
# 2. Create deployment S3 bucket if it doesn't exist
# ---------------------------------------------------------------------------
header "2. Ensuring deployment bucket: ${DEPLOY_BUCKET}"

if aws s3api head-bucket --bucket "${DEPLOY_BUCKET}" --region "${REGION}" 2>/dev/null; then
  ok "Bucket already exists: ${DEPLOY_BUCKET}"
else
  info "Creating bucket ${DEPLOY_BUCKET} in ${REGION}..."
  if [[ "${REGION}" == "us-east-1" ]]; then
    # us-east-1 must NOT pass a LocationConstraint
    aws s3api create-bucket \
      --bucket "${DEPLOY_BUCKET}" \
      --region "${REGION}"
  else
    aws s3api create-bucket \
      --bucket "${DEPLOY_BUCKET}" \
      --region "${REGION}" \
      --create-bucket-configuration LocationConstraint="${REGION}"
  fi
  # Block all public access on the deploy bucket
  aws s3api put-public-access-block \
    --bucket "${DEPLOY_BUCKET}" \
    --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
  ok "Bucket created."
fi

# ---------------------------------------------------------------------------
# 3. Build Lambda packages
# ---------------------------------------------------------------------------
header "3. Building Lambda packages"

rm -rf "${LAMBDA_PACKAGE_DIR}"
mkdir -p "${LAMBDA_PACKAGE_DIR}"

for FUNC_NAME in "${!LAMBDA_DIRS[@]}"; do
  SRC_DIR="${LAMBDA_DIRS[$FUNC_NAME]}"
  ZIP_FILE="${LAMBDA_PACKAGE_DIR}/${FUNC_NAME}.zip"

  if [[ ! -d "${SRC_DIR}" ]]; then
    warn "Source directory not found: ${SRC_DIR} – creating placeholder."
    mkdir -p "${SRC_DIR}"
    cat > "${SRC_DIR}/handler.py" <<'PLACEHOLDER'
import json

def lambda_handler(event, context):
    """Placeholder handler – replace with real implementation."""
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "not implemented"})
    }
PLACEHOLDER
  fi

  info "Packaging ${FUNC_NAME} -> ${ZIP_FILE}"
  (
    cd "${SRC_DIR}"
    zip -r "${ZIP_FILE}" . -x "*.pyc" -x "__pycache__/*" -x "*.egg-info/*"
  )
  ok "${FUNC_NAME} packaged."
done

# ---------------------------------------------------------------------------
# 4. Build Lambda layer
# ---------------------------------------------------------------------------
header "4. Building Lambda dependency layer"

rm -rf "${LAYER_DIR}" "${LAYER_ZIP}"
mkdir -p "${LAYER_DIR}/python/lib/python3.12/site-packages"

if [[ -f "${SHARED_REQUIREMENTS}" ]]; then
  info "Installing dependencies from ${SHARED_REQUIREMENTS} ..."
  pip install \
    --quiet \
    --target "${LAYER_DIR}/python/lib/python3.12/site-packages" \
    -r "${SHARED_REQUIREMENTS}"
  ok "Dependencies installed."
else
  warn "No requirements.txt found at ${SHARED_REQUIREMENTS}. Layer will be empty."
  # Create a minimal placeholder so the layer ZIP is valid
  echo "# no dependencies" > "${LAYER_DIR}/python/lib/python3.12/site-packages/.placeholder"
fi

info "Zipping layer -> ${LAYER_ZIP}"
(
  cd "${LAYER_DIR}"
  zip -r "${LAYER_ZIP}" python/ -x "*.pyc" -x "__pycache__/*"
)
ok "Layer ZIP created."

# ---------------------------------------------------------------------------
# 5. Upload packages and layer to S3
# ---------------------------------------------------------------------------
header "5. Uploading artifacts to s3://${DEPLOY_BUCKET}"

aws s3 cp "${LAYER_ZIP}" \
  "s3://${DEPLOY_BUCKET}/layers/dependencies.zip" \
  --region "${REGION}"
ok "Layer uploaded."

for FUNC_NAME in "${!LAMBDA_DIRS[@]}"; do
  ZIP_FILE="${LAMBDA_PACKAGE_DIR}/${FUNC_NAME}.zip"
  aws s3 cp "${ZIP_FILE}" \
    "s3://${DEPLOY_BUCKET}/lambdas/${FUNC_NAME}.zip" \
    --region "${REGION}"
  ok "${FUNC_NAME} Lambda uploaded."
done

# ---------------------------------------------------------------------------
# 6. Deploy the CloudFormation stack
# ---------------------------------------------------------------------------
header "6. Deploying CloudFormation stack: ${STACK_NAME}"

aws cloudformation deploy \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --template-file "${TEMPLATE}" \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    LambdaLayerBucket="${DEPLOY_BUCKET}" \
    LambdaLayerKey="layers/dependencies.zip" \
    IngestLambdaS3Key="lambdas/ingest-students.zip" \
    ScoreLambdaS3Key="lambdas/score-risk.zip" \
    RecommendLambdaS3Key="lambdas/generate-recommendations.zip" \
  --no-fail-on-empty-changeset

ok "Stack deploy complete."

# ---------------------------------------------------------------------------
# 7. Print stack outputs
# ---------------------------------------------------------------------------
header "7. Stack outputs"

aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}" \
  --output table

# ---------------------------------------------------------------------------
# 8. Next steps
# ---------------------------------------------------------------------------
header "8. Next steps"

BUCKET_NAME=$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" \
  --output text 2>/dev/null || echo "<BucketName>")

USER_POOL_ID=$(aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
  --output text 2>/dev/null || echo "<UserPoolId>")

cat <<NEXTSTEPS

  a) Upload student data to trigger the ingest pipeline:
       aws s3 cp Team1Dataset.xlsx s3://${BUCKET_NAME}/Team1Dataset.xlsx

  b) Create the first Cognito advisor account:
       ./scripts/create-admin-user.sh ${USER_POOL_ID} advisor@example.com

  c) Add an SNS email subscription for alerts:
       aws sns subscribe \\
         --topic-arn \$(aws sns list-topics --query "Topics[?contains(TopicArn,'StudentRiskAlerts')].TopicArn" --output text) \\
         --protocol email \\
         --notification-endpoint your-email@example.com

  d) Deploy your Amplify frontend (configure the API URL and Cognito IDs
     from the outputs above in your Amplify environment variables).

NEXTSTEPS

ok "Deployment finished successfully."
