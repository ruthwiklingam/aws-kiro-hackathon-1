# generate-recommendations Lambda

## Overview

HTTP Lambda (API Gateway proxy integration) that generates AI-powered
intervention recommendations for an at-risk student by calling Amazon Bedrock
(Claude 3 Haiku), then persists the results back to DynamoDB.

## Route

### `POST /students/{id}/recommend`

1. Fetches the student record from DynamoDB.
2. Builds a structured prompt with the student's risk profile.
3. Calls Bedrock (`anthropic.claude-3-haiku-20240307-v1:0`) with exponential
   backoff on throttling (max 3 retries, base delay 2 s).
4. Parses the model's JSON response into 3 recommendations.
5. Stores the recommendations and a `lastRecommended` timestamp on the
   student's DynamoDB record.
6. Returns the full recommendations payload.

**Response:**

```json
{
  "studentId": "S001",
  "studentName": "Jane Doe",
  "riskLevel": "HIGH",
  "generatedAt": "2026-10-08T15:22:10.241Z",
  "recommendations": [
    {
      "title": "Academic tutoring referral",
      "description": "Refer to the math tutoring center given GPA of 1.8 ...",
      "urgency": "high",
      "category": "academic"
    }
  ]
}
```

**Recommendation object fields:**

| Field | Values |
|-------|--------|
| `title` | Short label |
| `description` | Specific, tailored action |
| `urgency` | `high` / `medium` / `low` |
| `category` | `academic` / `financial` / `social` / `engagement` |

**Error codes:**

| Code | Meaning |
|------|---------|
| 400 | Missing student ID |
| 404 | Student not found |
| 502 | Bedrock error or unparseable AI response |
| 500 | Unexpected server error |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STUDENTS_TABLE` | Yes | DynamoDB table name |
| `AWS_REGION` | No | Defaults to `us-east-1` |

## Bedrock Model

`anthropic.claude-3-haiku-20240307-v1:0` — must be enabled in the AWS account
in the target region.

## Dependencies

- `boto3` — AWS SDK (DynamoDB, Bedrock Runtime)

## IAM Permissions Required

- `dynamodb:GetItem` on the students table
- `dynamodb:UpdateItem` on the students table
- `bedrock:InvokeModel` for `anthropic.claude-3-haiku-20240307-v1:0`
