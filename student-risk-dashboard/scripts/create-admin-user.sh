#!/usr/bin/env bash
# =============================================================================
# create-admin-user.sh – Create the first Cognito advisor user
#
# Usage:
#   ./scripts/create-admin-user.sh <UserPoolId> <email>
#
# Example:
#   ./scripts/create-admin-user.sh us-east-1_AbCdEf123 advisor@university.edu
#
# What it does:
#   1. Creates a Cognito user with the given email as the username.
#   2. Sets a temporary password and marks the account as confirmed.
#   3. Flags the account so the user must change their password on first login.
#   4. Prints login instructions.
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------
if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <UserPoolId> <email>"
  echo "Example: $0 us-east-1_AbCdEf123 advisor@university.edu"
  exit 1
fi

USER_POOL_ID="$1"
EMAIL="$2"

# Basic email format check
if [[ ! "${EMAIL}" =~ ^[^@]+@[^@]+\.[^@]+$ ]]; then
  echo "[ERROR] '${EMAIL}' does not look like a valid email address."
  exit 1
fi

# ---------------------------------------------------------------------------
# Generate a temporary password that meets the pool's policy:
#   - 8+ chars, uppercase, lowercase, number
# The user will be forced to change it on first login.
# ---------------------------------------------------------------------------
TEMP_PASSWORD="Tmp$(date +%s)@1A"

echo
echo "=============================================================="
echo "  Creating Cognito advisor user"
echo "=============================================================="
echo "  User Pool : ${USER_POOL_ID}"
echo "  Email     : ${EMAIL}"
echo "  Region    : ${REGION}"
echo "=============================================================="
echo

# ---------------------------------------------------------------------------
# Create the user
# (--message-action SUPPRESS skips the welcome email so we can set a
#  known temp password without confusing the user with two emails)
# ---------------------------------------------------------------------------
echo "[INFO] Creating user '${EMAIL}' in pool ${USER_POOL_ID}..."

aws cognito-idp admin-create-user \
  --region "${REGION}" \
  --user-pool-id "${USER_POOL_ID}" \
  --username "${EMAIL}" \
  --temporary-password "${TEMP_PASSWORD}" \
  --user-attributes \
    Name=email,Value="${EMAIL}" \
    Name=email_verified,Value=true \
  --message-action SUPPRESS \
  --output table

echo "[OK]   User created."

# ---------------------------------------------------------------------------
# Force the user to change their password on first sign-in.
# Cognito sets this automatically when a temp password is used, but we
# explicitly confirm here with a set-user-password call so the account
# is in FORCE_CHANGE_PASSWORD state (not CONFIRMED) — the user MUST reset.
# ---------------------------------------------------------------------------
echo "[INFO] Setting temporary password (user will be prompted to change it)..."

aws cognito-idp admin-set-user-password \
  --region "${REGION}" \
  --user-pool-id "${USER_POOL_ID}" \
  --username "${EMAIL}" \
  --password "${TEMP_PASSWORD}" \
  --no-permanent

echo "[OK]   Temporary password set. Account is in FORCE_CHANGE_PASSWORD state."

# ---------------------------------------------------------------------------
# Print login instructions
# ---------------------------------------------------------------------------
COGNITO_DOMAIN="student-risk-advisors-$(
  aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "<AccountId>"
)"

echo
echo "=============================================================="
echo "  Login instructions for ${EMAIL}"
echo "=============================================================="
echo
echo "  1. Open the application and sign in with:"
echo "       Username : ${EMAIL}"
echo "       Password : ${TEMP_PASSWORD}"
echo
echo "  2. You will be immediately prompted to set a new permanent password."
echo "     The new password must be at least 8 characters and contain:"
echo "       * An uppercase letter"
echo "       * A lowercase letter"
echo "       * A number"
echo
echo "  3. After resetting the password you will be signed in normally."
echo
echo "  Cognito Hosted UI (if configured):"
echo "    https://${COGNITO_DOMAIN}.auth.${REGION}.amazoncognito.com"
echo
echo "  To add more users, re-run this script with a different email address."
echo "=============================================================="
echo
echo "[OK]  Done."
