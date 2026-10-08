# ingest-students Lambda

## Overview

Triggered by an S3 `ObjectCreated` (PUT) event on `Team1Dataset.xlsx`.
Reads the uploaded Excel file, parses every student row, computes a risk score
for each student, and batch-writes all records to DynamoDB.

## Trigger

- **Type:** S3 event notification
- **Bucket:** value of `STUDENTS_BUCKET` env var
- **Object key filter:** `Team1Dataset.xlsx`

## Risk Scoring Algorithm

| Condition | Points |
|-----------|--------|
| GPA < 1.5 | +40 |
| GPA 1.5–1.99 | +30 |
| GPA 2.0–2.49 | +15 |
| GPA 2.5–2.99 | +5 |
| Attendance < 60% | +30 |
| Attendance 60–74% | +15 |
| Attendance 75–84% | +5 |
| No advising visits | +15 |
| 1 advising visit | +5 |
| Failed courses | +10 per course |
| Financial aid issues | +10 |
| Last login > 14 days ago | +5 |

Score is capped at 100.  
`score >= 60` → **HIGH**, `score >= 30` → **MEDIUM**, otherwise **LOW**.

## DynamoDB Record Shape

All source columns are stored verbatim plus:

| Field | Type | Description |
|-------|------|-------------|
| `riskScore` | Number | 0–100 |
| `riskLevel` | String | HIGH / MEDIUM / LOW |
| `lastUpdated` | String | ISO-8601 UTC timestamp |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STUDENTS_TABLE` | Yes | DynamoDB table name |
| `STUDENTS_BUCKET` | Yes | S3 bucket name (for reference; bucket is taken from the event) |
| `AWS_REGION` | No | Defaults to `us-east-1` |

## Dependencies

- `boto3` — AWS SDK (DynamoDB, S3)
- `openpyxl` — xlsx parsing

## IAM Permissions Required

- `s3:GetObject` on the dataset bucket/key
- `dynamodb:BatchWriteItem` on the students table
