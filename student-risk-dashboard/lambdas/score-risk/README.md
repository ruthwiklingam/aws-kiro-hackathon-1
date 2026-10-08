# score-risk Lambda

## Overview

HTTP Lambda (API Gateway proxy integration) that exposes a REST API for
querying student risk data stored in DynamoDB.

## Routes

### `GET /students`

Returns all students. Supports optional query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `riskLevel` | string | Filter by `HIGH`, `MEDIUM`, or `LOW` |
| `sortBy` | string | Sort field: `gpa`, `attendance`, or `riskScore` |
| `order` | string | `asc` (default) or `desc` |
| `limit` | integer | Maximum number of records to return |

**Response:**

```json
{
  "students": [ { ... } ],
  "count": 42
}
```

### `GET /students/{id}`

Returns a single student by `studentId`.

- **200** — student record
- **404** — student not found
- **500** — database error

## Response Headers

All responses include:

```
Access-Control-Allow-Origin: *
Content-Type: application/json
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STUDENTS_TABLE` | Yes | DynamoDB table name |
| `AWS_REGION` | No | Defaults to `us-east-1` |

## Dependencies

- `boto3` — AWS SDK (DynamoDB)

## IAM Permissions Required

- `dynamodb:Scan` on the students table
- `dynamodb:GetItem` on the students table
