# Student Risk Dashboard

AI-powered dashboard that ingests first-year student data (GPA, attendance, advising visits) and flags at-risk students with personalized Bedrock-powered intervention recommendations.

## Architecture

```
Team1Dataset.xlsx
       |
       v
   S3 Bucket  ──(trigger)──>  ingest-students Lambda
                                    |
                                    v
                              DynamoDB (students)
                                    |
                         ┌──────────┴──────────┐
                         v                     v
                   score-risk Lambda    generate-recommendations
                   (GET /students)       Lambda (POST /recommend)
                   (GET /students/{id})        |
                         |                Bedrock Claude Haiku
                         v
                    API Gateway (REST) + Cognito Authorizer
                         |
                    React Frontend (Amplify)
```
## Dataset Selection & Rationale

### Why We Selected `Team1Dataset.xlsx`

The objective of the Student Risk Dashboard is to identify first-year students who may benefit from early academic intervention. We selected `Team1Dataset.xlsx` to demonstrate how multiple indicators of academic performance, engagement, and student support needs can be integrated into a single risk-assessment workflow.

Our selection was guided by four considerations:

1. **Academic Performance:** GPA and failed-course indicators provide information about students experiencing academic challenges.
2. **Student Engagement:** Attendance and learning-platform activity help identify reduced participation or potential disengagement.
3. **Student Support:** Advising visits and financial aid indicators provide additional context for understanding students' support needs.
4. **Actionable Intervention:** Combining these factors enables the dashboard to prioritize students for advisor review and generate context-specific intervention recommendations.

### How the Dataset Powers the AWS Architecture

The dataset serves as the starting point for an automated, event-driven data pipeline:

**Excel Dataset → Amazon S3 → AWS Lambda → Amazon DynamoDB → Risk Scoring → Amazon Bedrock → API Gateway → React Dashboard**

- **Data Ingestion:** Uploading the Excel file to Amazon S3 triggers an AWS Lambda function to parse and process student records.
- **Structured Storage:** Student records are stored in Amazon DynamoDB for efficient retrieval.
- **Risk Assessment:** A rule-based scoring algorithm evaluates academic and engagement indicators and assigns HIGH, MEDIUM, or LOW risk categories.
- **AI-Assisted Recommendations:** Amazon Bedrock generates intervention suggestions based on relevant student information.
- **Advisor Dashboard:** A React application presents student records, risk classifications, and recommended actions to support timely intervention.

### Project Value

This dataset allows us to demonstrate how structured educational data can be transformed into actionable information using AWS serverless services and generative AI.

The approach supports early identification, prioritization of advising resources, and personalized student support. The architecture can also be extended to accommodate additional indicators and future datasets.

### Limitations and Responsible Use

The current risk-scoring weights are heuristic and have not been validated against historical student outcomes. Risk classifications should therefore be treated as preliminary decision-support indicators rather than definitive predictions.

Before using real student data, appropriate privacy protections, access controls, and institutional data-governance requirements must be established. AI-generated recommendations should remain subject to human advisor review.

## Stack

| Layer | Service |
|---|---|
| Storage | S3 + DynamoDB |
| Compute | Lambda (Python 3.12) × 3 |
| AI | Bedrock (claude-3-haiku) |
| API | API Gateway REST + Cognito |
| Auth | Cognito User Pool |
| Frontend | React 18 → Amplify Hosting |
| Observability | CloudWatch Alarms + SNS |
| IaC | CloudFormation |

## Project Structure

```
student-risk-dashboard/
├── infra/
│   └── template.yaml          # CloudFormation (687 lines)
├── lambdas/
│   ├── ingest-students/       # S3-triggered xlsx parser + DynamoDB writer
│   ├── score-risk/            # GET /students, GET /students/{id}
│   └── generate-recommendations/  # POST /students/{id}/recommend → Bedrock
├── frontend/                  # React 18 app
│   └── src/
│       ├── pages/             # Dashboard, StudentDetail, LoginPage
│       ├── components/        # RiskBadge, LoadingSpinner
│       └── hooks/             # useStudents, useStudent
├── scripts/
│   ├── deploy.sh              # Full CloudFormation deploy script
│   └── create-admin-user.sh   # Create first Cognito advisor account
└── data/                      # Place Team1Dataset.xlsx here
```

## Deploy

### Prerequisites
- AWS CLI configured (`aws configure` or `aws sso login`)
- Python 3.12, pip, zip on PATH
- Bedrock model access: `anthropic.claude-3-haiku-20240307-v1:0` enabled in us-east-1

### Step 1 — Deploy Infrastructure + Lambdas

```bash
cd student-risk-dashboard
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

This will print all stack outputs at the end including `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `BucketName`.

### Step 2 — Upload Dataset

```bash
aws s3 cp data/Team1Dataset.xlsx s3://<BucketName>/Team1Dataset.xlsx
```

The S3 trigger fires `ingest-students` automatically. Check CloudWatch Logs for `/aws/lambda/student-risk-ingest-students` to confirm ingestion.

### Step 3 — Create First Advisor Account

```bash
chmod +x scripts/create-admin-user.sh
./scripts/create-admin-user.sh <UserPoolId> advisor@university.edu
```

### Step 4 — Deploy Frontend

```bash
cd frontend
cp .env.example .env
# Edit .env with values from Step 1 stack outputs
npm install
npm run build
```

Then in the AWS Amplify console: connect to your git repo or manually deploy the `build/` folder.

### Step 5 — Subscribe to Alerts (Optional)

In the SNS console, subscribe your email to the `StudentRiskAlerts` topic to receive Lambda error notifications.

## Risk Scoring Algorithm

| Factor | Points |
|---|---|
| GPA < 1.5 | +40 |
| GPA 1.5–1.99 | +30 |
| GPA 2.0–2.49 | +15 |
| GPA 2.5–2.99 | +5 |
| Attendance < 60% | +30 |
| Attendance 60–74% | +15 |
| Attendance 75–84% | +5 |
| No advising visits | +15 |
| 1 advising visit | +5 |
| Each failed course | +10 |
| Financial aid issues | +10 |
| Last login > 14 days | +5 |

**Score ≥ 60 → HIGH · Score 30–59 → MEDIUM · Score < 30 → LOW**
