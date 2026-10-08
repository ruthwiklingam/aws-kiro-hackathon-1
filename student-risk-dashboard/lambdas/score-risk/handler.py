"""
score-risk Lambda handler.

HTTP Lambda behind API Gateway (proxy integration).

Routes
------
GET /students
    Scan all students from DynamoDB.
    Optional query parameters:
      - riskLevel   : filter to HIGH | MEDIUM | LOW
      - sortBy      : field to sort by (gpa | attendance | riskScore)
      - order       : asc | desc  (default: asc)
      - limit       : maximum number of records to return (positive integer)

GET /students/{id}
    Fetch a single student by studentId.
    Returns HTTP 404 if the student does not exist.

All responses include CORS headers (Access-Control-Allow-Origin: *).
"""

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
STUDENTS_TABLE = os.environ["STUDENTS_TABLE"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(STUDENTS_TABLE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type": "application/json",
}

SORT_FIELD_MAP = {
    "gpa": "gpa",
    "attendance": "attendanceRate",
    "riskscore": "riskScore",
}


class DecimalEncoder(json.JSONEncoder):
    """Encode Decimal values stored in DynamoDB as float for JSON output."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _json_response(status_code: int, body: object) -> dict:
    """Build a properly structured API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _error(status_code: int, message: str) -> dict:
    return _json_response(status_code, {"error": message})


def _parse_int(value: str, default: int | None = None) -> int | None:
    """Parse an integer from a query-string string; return default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def get_students(query_params: dict) -> dict:
    """
    Scan all students and apply optional filtering, sorting, and limiting.

    Parameters
    ----------
    query_params : dict
        Parsed query string parameters from the API Gateway event.

    Returns
    -------
    dict
        API Gateway proxy response with the list of students.
    """
    risk_level_filter = (query_params.get("riskLevel") or "").upper() or None
    sort_by_raw = (query_params.get("sortBy") or "").lower()
    sort_field = SORT_FIELD_MAP.get(sort_by_raw)
    order = (query_params.get("order") or "asc").lower()
    limit_param = _parse_int(query_params.get("limit"))

    if risk_level_filter and risk_level_filter not in {"HIGH", "MEDIUM", "LOW"}:
        return _error(400, f"Invalid riskLevel '{risk_level_filter}'. Must be HIGH, MEDIUM, or LOW.")

    if order not in {"asc", "desc"}:
        return _error(400, "Invalid order value. Must be 'asc' or 'desc'.")

    if limit_param is not None and limit_param < 1:
        return _error(400, "limit must be a positive integer.")

    # Scan with optional FilterExpression
    scan_kwargs: dict = {}
    if risk_level_filter:
        scan_kwargs["FilterExpression"] = Attr("riskLevel").eq(risk_level_filter)

    items: list[dict] = []
    try:
        while True:
            response = table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))
            last_evaluated = response.get("LastEvaluatedKey")
            if not last_evaluated:
                break
            scan_kwargs["ExclusiveStartKey"] = last_evaluated
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("DynamoDB scan failed: %s — %s", error_code, exc)
        return _error(500, "Failed to retrieve students from the database.")

    # Sort
    if sort_field:
        reverse = order == "desc"
        items.sort(key=lambda s: (s.get(sort_field) or 0), reverse=reverse)

    # Limit
    if limit_param is not None:
        items = items[:limit_param]

    logger.info(
        "get_students: returned %d records (filter=%s, sort=%s %s, limit=%s)",
        len(items), risk_level_filter, sort_field, order, limit_param,
    )
    return _json_response(200, {"students": items, "count": len(items)})


def get_student_by_id(student_id: str) -> dict:
    """
    Fetch a single student record by its primary key.

    Parameters
    ----------
    student_id : str
        The studentId partition key value.

    Returns
    -------
    dict
        API Gateway proxy response (200 with the item, or 404 if not found).
    """
    try:
        response = table.get_item(Key={"studentId": student_id})
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("DynamoDB get_item failed for studentId=%s: %s — %s",
                     student_id, error_code, exc)
        return _error(500, "Failed to retrieve student from the database.")

    item = response.get("Item")
    if not item:
        logger.info("Student not found: studentId=%s", student_id)
        return _error(404, f"Student '{student_id}' not found.")

    logger.info("get_student_by_id: found studentId=%s", student_id)
    return _json_response(200, item)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    Routes incoming API Gateway proxy requests to the appropriate handler
    based on the HTTP method and resource path.

    Parameters
    ----------
    event : dict
        API Gateway proxy integration event.
    context : LambdaContext
        Lambda runtime context (unused).

    Returns
    -------
    dict
        API Gateway proxy response.
    """
    http_method = event.get("httpMethod", "").upper()
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}

    logger.info("Incoming request: %s %s", http_method, resource)

    # Handle CORS preflight
    if http_method == "OPTIONS":
        return _json_response(200, {})

    try:
        if http_method == "GET" and resource == "/students":
            return get_students(query_params)

        if http_method == "GET" and resource == "/students/{id}":
            student_id = path_params.get("id", "").strip()
            if not student_id:
                return _error(400, "Missing student ID in path.")
            return get_student_by_id(student_id)

        return _error(404, f"Route not found: {http_method} {resource}")

    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled exception in score-risk handler: %s", exc)
        return _error(500, "An unexpected error occurred.")
