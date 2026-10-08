"""
ingest-students Lambda handler.

Triggered by an S3 PUT event on Team1Dataset.xlsx.
Reads the xlsx from S3, parses each student row, computes a risk score,
and batch-writes all records to DynamoDB.
"""

import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO

import boto3
import openpyxl
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration (injected via Lambda environment variables)
# ---------------------------------------------------------------------------
STUDENTS_TABLE = os.environ["STUDENTS_TABLE"]
STUDENTS_BUCKET = os.environ["STUDENTS_BUCKET"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(STUDENTS_TABLE)

# ---------------------------------------------------------------------------
# Expected column headers (order-independent; matched by name)
# Matches the actual Team1Dataset.xlsx columns:
#   student_id, current_gpa, previous_gpa, attendance_pct, missed_classes,
#   lms_activity_score, missing_assignments, advising_visit_count,
#   days_since_last_advising, retention_status
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = {
    "student_id",
    "current_gpa",
    "previous_gpa",
    "attendance_pct",
    "missed_classes",
    "lms_activity_score",
    "missing_assignments",
    "advising_visit_count",
    "days_since_last_advising",
    "retention_status",
}

# DynamoDB batch_writer flushes at 25 items; AWS limit is 25 per batch.
DYNAMO_BATCH_SIZE = 25


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def compute_risk(current_gpa: float, attendance_pct: float, advising_visit_count: int,
                 missing_assignments: int, missed_classes: int,
                 days_since_last_advising: int) -> tuple[int, str]:
    """
    Compute a risk score (0-100) and risk level ('HIGH'/'MEDIUM'/'LOW')
    from the given student metrics.

    Returns
    -------
    (risk_score, risk_level)
    """
    score = 0

    # GPA contribution
    if current_gpa < 1.5:
        score += 40
    elif current_gpa < 2.0:
        score += 30
    elif current_gpa < 2.5:
        score += 15
    elif current_gpa < 3.0:
        score += 5

    # Attendance contribution
    if attendance_pct < 60:
        score += 30
    elif attendance_pct < 75:
        score += 15
    elif attendance_pct < 85:
        score += 5

    # Advising visits contribution
    if advising_visit_count == 0:
        score += 15
    elif advising_visit_count == 1:
        score += 5

    # Missing assignments
    score += min(missing_assignments * 5, 20)

    # Missed classes
    score += min(missed_classes * 3, 15)

    # Days since last advising
    if days_since_last_advising > 60:
        score += 10
    elif days_since_last_advising > 30:
        score += 5

    score = min(score, 100)

    if score >= 60:
        risk_level = "HIGH"
    elif score >= 30:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return score, risk_level


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _safe_float(value, default: float = 0.0) -> float:
    """Convert a cell value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Convert a cell value to int, returning default on failure."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_bool(value) -> bool:
    """
    Interpret various Excel representations of a boolean.
    Treats 1, '1', 'true', 'yes', 'y' (case-insensitive) as True.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _safe_str(value, default: str = "") -> str:
    """Convert a cell value to str, stripping surrounding whitespace."""
    if value is None:
        return default
    return str(value).strip()


def _enrollment_date_str(value) -> str:
    """Return an ISO-8601 date string from a date/datetime/str cell value."""
    if isinstance(value, (datetime,)):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):          # datetime.date
        return value.isoformat()
    return _safe_str(value)


# ---------------------------------------------------------------------------
# xlsx reading
# ---------------------------------------------------------------------------

def read_xlsx_from_s3(bucket: str, key: str) -> list[dict]:
    """
    Download *key* from *bucket* and parse every data row.

    Returns a list of raw student dicts keyed by column header name.
    Raises ValueError if required columns are missing.
    """
    logger.info("Downloading s3://%s/%s", bucket, key)
    response = s3_client.get_object(Bucket=bucket, Key=key)
    xlsx_bytes = response["Body"].read()
    logger.info("Downloaded %d bytes", len(xlsx_bytes))

    workbook = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    sheet = workbook.active

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Workbook sheet is empty.")

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    missing = REQUIRED_COLUMNS - set(headers)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    col_index = {name: idx for idx, name in enumerate(headers)}

    def cell(row: tuple, col_name: str):
        return row[col_index[col_name]]

    students = []
    for row_num, row in enumerate(rows[1:], start=2):
        student_id = _safe_str(cell(row, "student_id"))
        if not student_id:
            logger.warning("Row %d: empty StudentID — skipped", row_num)
            continue

        students.append({
            "studentId":           student_id,
            "currentGpa":          _safe_float(cell(row, "current_gpa")),
            "previousGpa":         _safe_float(cell(row, "previous_gpa")),
            "attendancePct":       _safe_float(cell(row, "attendance_pct")),
            "missedClasses":       _safe_int(cell(row, "missed_classes")),
            "lmsActivityScore":    _safe_float(cell(row, "lms_activity_score")),
            "missingAssignments":  _safe_int(cell(row, "missing_assignments")),
            "advisingVisitCount":  _safe_int(cell(row, "advising_visit_count")),
            "daysSinceLastAdvising": _safe_int(cell(row, "days_since_last_advising")),
            "retentionStatus":     _safe_str(cell(row, "retention_status")),
        })

    logger.info("Parsed %d student rows", len(students))
    return students


# ---------------------------------------------------------------------------
# DynamoDB batch write
# ---------------------------------------------------------------------------

def _to_dynamo_item(student: dict, now_iso: str) -> dict:
    """
    Build a DynamoDB item from a parsed student dict.

    DynamoDB does not accept Python floats directly; Decimal is used instead.
    """
    risk_score, risk_level = compute_risk(
        current_gpa=student["currentGpa"],
        attendance_pct=student["attendancePct"],
        advising_visit_count=student["advisingVisitCount"],
        missing_assignments=student["missingAssignments"],
        missed_classes=student["missedClasses"],
        days_since_last_advising=student["daysSinceLastAdvising"],
    )

    return {
        "studentId":             student["studentId"],
        "currentGpa":            Decimal(str(round(student["currentGpa"], 4))),
        "previousGpa":           Decimal(str(round(student["previousGpa"], 4))),
        "attendancePct":         Decimal(str(round(student["attendancePct"], 4))),
        "missedClasses":         student["missedClasses"],
        "lmsActivityScore":      Decimal(str(round(student["lmsActivityScore"], 4))),
        "missingAssignments":    student["missingAssignments"],
        "advisingVisitCount":    student["advisingVisitCount"],
        "daysSinceLastAdvising": student["daysSinceLastAdvising"],
        "retentionStatus":       student["retentionStatus"],
        "riskScore":             risk_score,
        "riskLevel":             risk_level,
        "lastUpdated":           now_iso,
    }


def batch_write_students(students: list[dict], now_iso: str) -> dict:
    """
    Write all student items to DynamoDB using batch_writer.

    Returns a summary dict with counts of successes and failures.
    """
    succeeded = 0
    failed = 0

    with table.batch_writer() as batch:
        for student in students:
            try:
                item = _to_dynamo_item(student, now_iso)
                batch.put_item(Item=item)
                succeeded += 1
            except (ClientError, Exception) as exc:  # noqa: BLE001
                logger.error(
                    "Failed to prepare item for studentId=%s: %s",
                    student.get("studentId", "UNKNOWN"),
                    exc,
                )
                failed += 1

    logger.info("DynamoDB write complete — succeeded: %d, failed: %d", succeeded, failed)
    return {"succeeded": succeeded, "failed": failed}


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    Parameters
    ----------
    event : dict
        S3 event notification payload.
    context : LambdaContext
        Lambda runtime context (unused, but required by the signature).

    Returns
    -------
    dict
        Summary of the ingest run.
    """
    logger.info("Event: %s", json.dumps(event))

    records = event.get("Records", [])
    if not records:
        logger.warning("No S3 records in event; nothing to do.")
        return {"status": "no_records", "processed": 0}

    now_iso = datetime.now(timezone.utc).isoformat()
    total_succeeded = 0
    total_failed = 0

    for record in records:
        try:
            bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
            logger.info("Processing s3://%s/%s", bucket, key)

            students = read_xlsx_from_s3(bucket, key)
            if not students:
                logger.warning("No student rows found in %s", key)
                continue

            result = batch_write_students(students, now_iso)
            total_succeeded += result["succeeded"]
            total_failed += result["failed"]

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            logger.error("AWS error processing record: %s — %s", error_code, exc)
            raise
        except ValueError as exc:
            logger.error("Validation error: %s", exc)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error processing record: %s", exc)
            raise

    summary = {
        "status": "ok",
        "processed": total_succeeded,
        "failed": total_failed,
        "timestamp": now_iso,
    }
    logger.info("Ingest complete: %s", summary)
    return summary
