# Student Risk Dashboard — Frontend

React 18 SPA for the Student Risk Dashboard. Authenticates via Cognito (AWS Amplify v6), calls the API Gateway backend, and renders risk analytics using Recharts.

---

## Prerequisites

- Node.js 18+
- npm 9+

---

## Setup

### 1. Copy the environment file

```bash
cp .env.example .env
```

### 2. Fill in values from CloudFormation outputs

Open `.env` and set:

| Variable | CloudFormation Output Key |
|---|---|
| `REACT_APP_API_URL` | `ApiGatewayUrl` |
| `REACT_APP_USER_POOL_ID` | `UserPoolId` |
| `REACT_APP_USER_POOL_CLIENT_ID` | `UserPoolClientId` |

Example `.env`:
```
REACT_APP_API_URL=https://abc123xyz.execute-api.us-east-1.amazonaws.com/prod
REACT_APP_USER_POOL_ID=us-east-1_AbcDeFgHi
REACT_APP_USER_POOL_CLIENT_ID=1a2b3c4d5e6f7g8h9i0j
```

### 3. Install dependencies

```bash
npm install
```

---

## Development

```bash
npm start
```

Opens on [http://localhost:3000](http://localhost:3000). Hot-reloads on file changes.

---

## Production Build

```bash
npm run build
```

Outputs to `build/`. Deploy that directory to S3 (via CloudFormation) or any static host.

---

## Run Tests

```bash
npm test
```

---

## Architecture

```
src/
├── index.js              # Amplify config, app bootstrap
├── App.js                # Routes + auth-guard (ProtectedRoute)
├── pages/
│   ├── LoginPage.js/.module.css   # Cognito sign-in, FORCE_CHANGE_PASSWORD
│   ├── Dashboard.js/.module.css   # Stats, charts, student grid, pagination
│   └── StudentDetail.js/.module.css  # Detail view, radar chart, Bedrock recs
├── components/
│   ├── RiskBadge.js              # HIGH/MEDIUM/LOW colored pill
│   └── LoadingSpinner.js/.module.css
└── hooks/
    ├── useStudents.js    # GET /students (all students)
    └── useStudent.js     # GET /students/:id (single student)
```

## Auth Flow

1. User signs in via LoginPage → `signIn()` (Amplify v6)
2. If `CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED`, shows new-password form → `confirmSignIn()`
3. All API calls include `Authorization: Bearer <Cognito ID token>` from `fetchAuthSession()`
4. Unauthenticated routes redirect to `/login`

## Color Palette

| Token | Value |
|---|---|
| `--risk-high` | `#dc2626` (red) |
| `--risk-medium` | `#d97706` (amber) |
| `--risk-low` | `#16a34a` (green) |
| `--primary` | `#1d4ed8` (blue) |
| `--bg` | `#f8fafc` (off-white) |
