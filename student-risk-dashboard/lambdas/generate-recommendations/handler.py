"""
generate-recommendations Lambda handler.

HTTP Lambda behind API Gateway (proxy integration).

Route
-----
POST /students/{id}/recommend
    Fetches the student from DynamoDB, calls Amazon Bedrock
    (anthropic.claude-3-haiku-20240307-v1:0) with a structured prompt, parses
    the JSON recommendations from the model response, stores them back to
    DynamoDB, and returns the full recommendations payload.

Bedrock throttling is handled with exponential backoff (max 3 retries).

Environment Variables
---------------------
STUDENTS_TABLE : str
    DynamoDB table name.
AWS_REGION : str
    AWS region (default: us-east-1).
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
STUDENTS_TABLE = os.environ["STUDENTS_TABLE"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

# Retry / backoff settings for Bedrock throttling
MAX_RETRIES = 3
BACKOFF_BASE_SECS = 2  # seconds; doubled on each retry

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(STUDENTS_TABLE)
bedrock_client = boto3.client("bedrock-runtime", region_name=REGION)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}


class DecimalEncoder(json.JSONEncoder):
    """Encode Decimal values stored in DynamoDB as float."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _json_response(status_code: int, body: object) -> dict:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _error(status_code: int, message: str) -> dict:
    return _json_response(status_code, {"error": message})


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def fetch_student(student_id: str) -> dict | None:
    """
    Retrieve a student record by primary key.

    Returns the item dict, or None if not found.
    Raises ClientError on AWS errors.
    """
    response = table.get_item(Key={"studentId": student_id})
    return response.get("Item")


def store_recommendations(student_id: str, recommendations: list[dict], now_iso: str) -> None:
    """
    Update the student's DynamoDB record with generated recommendations.

    Parameters
    ----------
    student_id : str
        The student's partition key.
    recommendations : list[dict]
        The list of recommendation objects to store.
    now_iso : str
        ISO-8601 timestamp string for lastRecommended.
    """
    table.update_item(
        Key={"studentId": student_id},
        UpdateExpression="SET recommendations = :r, lastRecommended = :t",
        ExpressionAttributeValues={
            ":r": recommendations,
            ":t": now_iso,
        },
    )
    logger.info("Stored %d recommendations for studentId=%s", len(recommendations), student_id)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_prompt(student: dict) -> str:
    """
    Build a structured Bedrock prompt for the given student record.

    The prompt asks the model to return a strict JSON object with the
    recommendations schema expected by the API.
    """
    student_id = student.get("studentId", "Unknown")
    current_gpa = float(student.get("currentGpa", 0))
    previous_gpa = float(student.get("previousGpa", 0))
    attendance_pct = float(student.get("attendancePct", 0))
    missed_classes = student.get("missedClasses", 0)
    lms_score = float(student.get("lmsActivityScore", 0))
    missing_assignments = student.get("missingAssignments", 0)
    advising_visits = student.get("advisingVisitCount", 0)
    days_since_advising = student.get("daysSinceLastAdvising", 0)
    retention_status = student.get("retentionStatus", "Unknown")
    risk_score = student.get("riskScore", 0)
    risk_level = student.get("riskLevel", "UNKNOWN")

    prompt = f"""You are an academic advisor assistant helping to identify at-risk students and suggest interventions.

Student Profile:
- Student ID: {student_id}
- Current GPA: {current_gpa:.2f}
- Previous GPA: {previous_gpa:.2f}
- Attendance: {attendance_pct:.0f}%
- Missed Classes: {missed_classes}
- Missing Assignments: {missing_assignments}
- LMS Activity Score: {lms_score:.0f}/100
- Advising Visits This Term: {advising_visits}
- Days Since Last Advising: {days_since_advising}
- Retention Status: {retention_status}
- Risk Score: {risk_score}/100
- Risk Level: {risk_level}

Based on this student's specific risk factors, provide exactly 3 targeted, actionable intervention recommendations.

Return ONLY a valid JSON object — no explanation, no markdown, no code fences — matching this exact schema:
{{
  "recommendations": [
    {{
      "title": "<short title>",
      "description": "<specific, actionable description tailored to this student>",
      "urgency": "<high|medium|low>",
      "category": "<academic|financial|social|engagement>"
    }}
  ]
}}

Rules:
- Each recommendation must directly address one of this student's documented risk factors.
- Urgency must reflect the risk level and the severity of the factor being addressed.
- Do not include generic advice not supported by the student's data.
- Return exactly 3 recommendations.
"""
    return prompt


# ---------------------------------------------------------------------------
# Bedrock invocation with retry / backoff
# ---------------------------------------------------------------------------

def invoke_bedrock_with_retry(prompt: str) -> str:
    """
    Call Bedrock's Converse API with exponential backoff on throttling.

    Parameters
    ----------
    prompt : str
        The user prompt to send to the model.

    Returns
    -------
    str
        The raw text content from the model's response.

    Raises
    ------
    ClientError
        Re-raised after MAX_RETRIES exhausted, or immediately for non-throttle errors.
    """
    messages = [{"role": "user", "content": [{"text": prompt}]}]

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = bedrock_client.converse(
                modelId=BEDROCK_MODEL_ID,
                messages=messages,
                inferenceConfig={
                    "maxTokens": 1024,
                    "temperature": 0.2,  # low temp for consistent JSON output
                    "topP": 0.9,
                },
            )
            content_blocks = response.get("output", {}).get("message", {}).get("content", [])
            text_parts = [block["text"] for block in content_blocks if "text" in block]
            return "\n".join(text_parts)

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            is_throttle = error_code in {
                "ThrottlingException",
                "ServiceUnavailableException",
                "ModelTimeoutException",
            }

            if is_throttle and attempt < MAX_RETRIES:
                wait_secs = BACKOFF_BASE_SECS * (2 ** attempt)
                logger.warning(
                    "Bedrock throttled (attempt %d/%d). Retrying in %ds...",
                    attempt + 1, MAX_RETRIES, wait_secs,
                )
                time.sleep(wait_secs)
                continue

            logger.error("Bedrock invocation failed (error=%s): %s", error_code, exc)
            raise

    # Should not reach here, but satisfies linters
    raise RuntimeError("Bedrock retry loop exited without result or exception.")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_recommendations(raw_text: str) -> list[dict]:
    """
    Parse the model's raw text response into a list of recommendation dicts.

    The model is prompted to return strict JSON, but we defensively strip any
    accidental markdown fences before parsing.

    Parameters
    ----------
    raw_text : str
        Raw text returned by the model.

    Returns
    -------
    list[dict]
        Validated list of recommendation objects.

    Raises
    ------
    ValueError
        If the text cannot be parsed as JSON or fails schema validation.
    """
    # Strip markdown fences if the model included them despite instructions
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the first and last fence lines
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned non-JSON output: {exc}\nRaw: {raw_text[:500]}") from exc

    recs = parsed.get("recommendations")
    if not isinstance(recs, list):
        raise ValueError(f"'recommendations' key missing or not a list. Got: {type(recs)}")

    valid_urgencies = {"high", "medium", "low"}
    valid_categories = {"academic", "financial", "social", "engagement"}

    cleaned = []
    for i, rec in enumerate(recs):
        if not isinstance(rec, dict):
            raise ValueError(f"Recommendation {i} is not an object.")
        title = str(rec.get("title", "")).strip()
        description = str(rec.get("description", "")).strip()
        urgency = str(rec.get("urgency", "")).lower().strip()
        category = str(rec.get("category", "")).lower().strip()

        if not title:
            raise ValueError(f"Recommendation {i} missing 'title'.")
        if urgency not in valid_urgencies:
            raise ValueError(f"Recommendation {i} has invalid urgency '{urgency}'.")
        if category not in valid_categories:
            raise ValueError(f"Recommendation {i} has invalid category '{category}'.")

        cleaned.append({
            "title": title,
            "description": description,
            "urgency": urgency,
            "category": category,
        })

    return cleaned


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    Handles POST /students/{id}/recommend.  Fetches the student, calls Bedrock
    to produce 3 tailored recommendations, stores them on the DynamoDB record,
    and returns the full payload.

    Parameters
    ----------
    event : dict
        API Gateway proxy integration event.
    context : LambdaContext
        Lambda runtime context (unused).

    Returns
    -------
    dict
        API Gateway proxy response containing the recommendations payload.
    """
    http_method = event.get("httpMethod", "").upper()
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}

    logger.info("Incoming request: %s %s", http_method, resource)

    # Handle CORS preflight
    if http_method == "OPTIONS":
        return _json_response(200, {})

    if http_method != "POST" or resource != "/students/{id}/recommend":
        return _error(404, f"Route not found: {http_method} {resource}")

    student_id = (path_params.get("id") or "").strip()
    if not student_id:
        return _error(400, "Missing student ID in path.")

    now_iso = datetime.now(timezone.utc).isoformat()

    # --- Fetch student ---
    try:
        student = fetch_student(student_id)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("DynamoDB error fetching studentId=%s: %s", student_id, error_code)
        return _error(500, "Failed to retrieve student from the database.")

    if not student:
        return _error(404, f"Student '{student_id}' not found.")

    # --- Call Bedrock ---
    try:
        prompt = build_prompt(student)
        raw_response = invoke_bedrock_with_retry(prompt)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("Bedrock error for studentId=%s: %s", student_id, error_code)
        return _error(502, f"AI service error: {error_code}. Please retry.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected Bedrock error for studentId=%s: %s", student_id, exc)
        return _error(500, "An unexpected error occurred calling the AI service.")

    # --- Parse response ---
    try:
        recommendations = parse_recommendations(raw_response)
    except ValueError as exc:
        logger.error("Failed to parse Bedrock response for studentId=%s: %s", student_id, exc)
        return _error(502, "AI service returned an unparseable response.")

    # --- Store back to DynamoDB ---
    try:
        store_recommendations(student_id, recommendations, now_iso)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("DynamoDB error storing recommendations for studentId=%s: %s",
                     student_id, error_code)
        # Return the recommendations even if storage failed — they were generated successfully.
        logger.warning("Returning recommendations despite storage failure.")

    # --- Build response payload ---
    payload = {
        "studentId": student_id,
        "riskLevel": student.get("riskLevel", "UNKNOWN"),
        "recommendations": recommendations,
        "generatedAt": now_iso,
    }

    logger.info(
        "Generated %d recommendations for studentId=%s (riskLevel=%s)",
        len(recommendations), student_id, payload["riskLevel"],
    )
    return _json_response(200, payload)
