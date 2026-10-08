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
    "Access-Control-Allow-Methods": "POST,PATCH,OPTIONS",
    "Content-Type": "application/json",
}

VALID_STATUSES = [
    "Pending",
    "Assigned to Advisor",
    "Outreach Sent",
    "Meeting Completed",
    "Resolved / Improved",
]


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


def normalize_recommendation(rec: dict, index: int, now_iso: str) -> dict:
    """Ensure a recommendation object contains all lifecycle tracking fields."""
    rec_id = rec.get("id") or f"intv-{int(time.time() * 1000)}-{index + 1}"
    status = rec.get("status") if rec.get("status") in VALID_STATUSES else "Pending"
    created_at = rec.get("createdAt") or now_iso
    updated_at = rec.get("updatedAt") or now_iso
    notes = rec.get("notes") if isinstance(rec.get("notes"), list) else []
    history = rec.get("history") if isinstance(rec.get("history"), list) else [
        {
            "status": status,
            "timestamp": created_at,
            "by": "AI / System",
            "note": "Recommendation generated",
        }
    ]

    return {
        "id": rec_id,
        "title": str(rec.get("title", "")).strip(),
        "description": str(rec.get("description", "")).strip(),
        "urgency": str(rec.get("urgency", "medium")).lower().strip(),
        "category": str(rec.get("category", "academic")).lower().strip(),
        "status": status,
        "assignedTo": rec.get("assignedTo"),
        "notes": notes,
        "history": history,
        "createdAt": created_at,
        "updatedAt": updated_at,
    }


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

def generate_heuristic_recommendations(student: dict) -> list[dict]:
    """Generate high-quality rule-based recommendations tailored to student risk factors."""
    now_iso = datetime.now(timezone.utc).isoformat()
    current_gpa = float(student.get("currentGpa", 0))
    attendance_pct = float(student.get("attendancePct", 100))
    missing_assignments = int(student.get("missingAssignments", 0))
    lms_score = float(student.get("lmsActivityScore", 100))
    days_since_advising = int(student.get("daysSinceLastAdvising", 0))
    risk_level = student.get("riskLevel", "MEDIUM").upper()

    recs = []

    # Academic intervention
    if current_gpa < 2.5 or missing_assignments > 2:
        recs.append({
            "title": "Academic Tutoring & Assignment Recovery Plan",
            "description": f"Current GPA is {current_gpa:.2f} with {missing_assignments} missing assignments. Schedule weekly tutoring sessions at the Academic Success Center and establish a makeup plan.",
            "urgency": "high" if risk_level == "HIGH" else "medium",
            "category": "academic",
        })
    else:
        recs.append({
            "title": "Peer Mentoring & Study Group Enrollment",
            "description": "Connect student with high-performing upperclassmen study circles to reinforce course mastery and maintain academic momentum.",
            "urgency": "medium",
            "category": "academic",
        })

    # Attendance & LMS engagement
    if attendance_pct < 80 or lms_score < 60:
        recs.append({
            "title": "Attendance Accountability & Digital LMS Check-in",
            "description": f"Attendance is at {attendance_pct:.0f}% with an LMS activity score of {lms_score:.0f}/100. Implement mandatory bi-weekly digital check-ins and verify course portal notifications.",
            "urgency": "high" if attendance_pct < 75 else "medium",
            "category": "engagement",
        })
    else:
        recs.append({
            "title": "Extracurricular & Campus Life Engagement",
            "description": "Encourage participation in departmental student organizations and career workshop series to bolster campus community integration.",
            "urgency": "low",
            "category": "social",
        })

    # Advising intervention
    if days_since_advising > 30 or risk_level == "HIGH":
        recs.append({
            "title": "Immediate 1-on-1 Academic Advisor Consultation",
            "description": f"Last advising appointment was {days_since_advising} days ago. Schedule an in-person advising session to review degree progress and evaluate course load adjustments.",
            "urgency": "high" if risk_level == "HIGH" else "medium",
            "category": "academic",
        })
    else:
        recs.append({
            "title": "Midterm Progress Review & Financial Aid Check",
            "description": "Conduct a holistic check on degree audit milestones, prerequisite completion, and institutional scholarship retention criteria.",
            "urgency": "low",
            "category": "financial",
        })

    return [normalize_recommendation(r, i, now_iso) for i, r in enumerate(recs[:3])]


def invoke_bedrock_with_retry(prompt: str) -> str:
    """
    Call Bedrock's Converse API with model fallbacks and retry on throttling.
    """
    candidate_models = [
        BEDROCK_MODEL_ID,
        "anthropic.claude-3-haiku-20240307-v1:0",
        "us.anthropic.claude-3-haiku-20240307-v1:0",
        "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "us.anthropic.claude-3-5-sonnet-20240620-v1:0",
    ]
    seen = set()
    models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

    messages = [{"role": "user", "content": [{"text": prompt}]}]
    last_error = None

    for model_id in models_to_try:
        logger.info("Attempting Bedrock Converse with modelId=%s", model_id)
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = bedrock_client.converse(
                    modelId=model_id,
                    messages=messages,
                    inferenceConfig={
                        "maxTokens": 1024,
                        "temperature": 0.2,
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

                last_error = exc
                logger.warning("Bedrock model %s failed (error=%s): %s", model_id, error_code, exc)
                break

    if last_error:
        raise last_error
    raise RuntimeError("Bedrock invocation failed on all candidate models.")


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_recommendations(raw_text: str) -> list[dict]:
    """
    Parse the model's raw text response into a list of recommendation dicts.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
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
            urgency = "medium"
        if category not in valid_categories:
            category = "academic"

        rec_obj = {
            "title": title,
            "description": description,
            "urgency": urgency,
            "category": category,
        }
        cleaned.append(normalize_recommendation(rec_obj, i, now_iso))

    return cleaned


# ---------------------------------------------------------------------------
# Intervention status update handler (PATCH)
# ---------------------------------------------------------------------------

def handle_patch_intervention(student_id: str, body_str: str) -> dict:
    """
    Update the status, assignment, and notes of an intervention.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        body = json.loads(body_str or "{}")
    except json.JSONDecodeError:
        return _error(400, "Invalid JSON body.")

    intervention_id = body.get("interventionId") or body.get("id")
    new_status = body.get("status")
    assigned_to = body.get("assignedTo")
    note_text = body.get("note")
    author = body.get("author") or assigned_to or "Advisor"

    if new_status and new_status not in VALID_STATUSES:
        return _error(400, f"Invalid status '{new_status}'. Allowed: {VALID_STATUSES}")

    student = fetch_student(student_id)
    if not student:
        return _error(404, f"Student '{student_id}' not found.")

    raw_recs = student.get("recommendations") or []
    if not isinstance(raw_recs, list) or len(raw_recs) == 0:
        return _error(404, "No recommendations found on student record to update.")

    updated_recs = [normalize_recommendation(r, idx, now_iso) for idx, r in enumerate(raw_recs)]

    # Match by ID or fallback to first matching or index
    target_idx = -1
    if intervention_id:
        for idx, r in enumerate(updated_recs):
            if str(r.get("id")) == str(intervention_id):
                target_idx = idx
                break

    if target_idx == -1:
        target_idx = 0  # fallback to first if not specified

    target = updated_recs[target_idx]

    if new_status:
        target["status"] = new_status
    if assigned_to is not None:
        target["assignedTo"] = assigned_to

    if note_text:
        target.setdefault("notes", []).append({
            "id": f"note-{int(time.time() * 1000)}",
            "author": author,
            "text": str(note_text).strip(),
            "timestamp": now_iso,
        })

    target.setdefault("history", []).append({
        "status": target["status"],
        "timestamp": now_iso,
        "by": author,
        "note": note_text or f"Status changed to {target['status']}",
    })

    target["updatedAt"] = now_iso
    updated_recs[target_idx] = target

    # Store back to DynamoDB
    store_recommendations(student_id, updated_recs, now_iso)

    return _json_response(200, {
        "studentId": student_id,
        "recommendations": updated_recs,
        "updatedAt": now_iso,
    })


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    Handles:
      POST  /students/{id}/recommend       -> Generate recommendations with initial Pending status
      PATCH /students/{id}/recommend       -> Update intervention status, advisor assignment, or notes
    """
    http_method = event.get("httpMethod", "").upper()
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}

    logger.info("Incoming request: %s %s", http_method, resource)

    # Handle CORS preflight
    if http_method == "OPTIONS":
        return _json_response(200, {})

    student_id = (path_params.get("id") or "").strip()
    if not student_id:
        return _error(400, "Missing student ID in path.")

    # --- Handle PATCH intervention status ---
    if http_method == "PATCH":
        return handle_patch_intervention(student_id, event.get("body", ""))

    if http_method != "POST":
        return _error(404, f"Route not found: {http_method} {resource}")

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

    # --- Call Bedrock with Graceful Heuristic Fallback ---
    recommendations = None
    try:
        prompt = build_prompt(student)
        raw_response = invoke_bedrock_with_retry(prompt)
        recommendations = parse_recommendations(raw_response)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Bedrock generation failed for studentId=%s (%s). Using tailored heuristic recommendations.",
            student_id, exc,
        )
        recommendations = generate_heuristic_recommendations(student)

    # --- Store back to DynamoDB ---
    try:
        store_recommendations(student_id, recommendations, now_iso)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("DynamoDB error storing recommendations for studentId=%s: %s",
                     student_id, error_code)
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
