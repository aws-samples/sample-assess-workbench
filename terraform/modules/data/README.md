# Data Module

DynamoDB table for storing projects, reviews, and chat history using single-table design.

## Table Design

### Single-Table Design Pattern

Uses a single DynamoDB table with PK/SK (partition key/sort key) pattern for cost optimization and flexibility.

### Access Patterns

| Pattern | PK | SK | GSI1PK | GSI1SK |
|---------|----|----|--------|--------|
| Get project | `PROJECT#<id>` | `METADATA` | - | - |
| Get review | `PROJECT#<id>` | `REVIEW#<timestamp>` | - | - |
| Get chat messages | `PROJECT#<id>` | `CHAT#<agent>#<timestamp>` | - | - |
| List all projects | - | - | `PROJECT` | `<created_at>` |
| List projects by status | - | - | `STATUS#<status>` | `<created_at>` |
| Get agent chat history | `PROJECT#<id>` | begins_with(`CHAT#<agent>#`) | - | - |

### Item Structure

#### Project Metadata
```json
{
  "PK": "PROJECT#abc123",
  "SK": "METADATA",
  "GSI1PK": "PROJECT",
  "GSI1SK": "2024-03-05T10:00:00Z",
  "project_id": "abc123",
  "name": "Payment System Design",
  "status": "completed",
  "s3_bucket": "risk-assessor-design-docs-dev-...",
  "s3_key": "projects/abc123/files/payment-system-design.pdf",
  "created_at": "2024-03-05T10:00:00Z",
  "updated_at": "2024-03-05T10:30:00Z"
}
```

#### Review Results
```json
{
  "PK": "PROJECT#abc123",
  "SK": "REVIEW#2024-03-05T10:15:00Z",
  "review_id": "rev_xyz789",
  "status": "completed",
  "findings": {
    "architecture": [...],
    "security": [...],
    "risk": [...]
  },
  "created_at": "2024-03-05T10:15:00Z"
}
```

#### Chat Messages
```json
{
  "PK": "PROJECT#abc123",
  "SK": "CHAT#security#2024-03-05T10:20:00Z",
  "message_id": "msg_123",
  "agent": "security",
  "role": "user",
  "content": "Can you explain finding SEC-001?",
  "created_at": "2024-03-05T10:20:00Z"
}
```

## Features

- **Pay-per-request billing**: Cost-effective for variable workload
- **Point-in-time recovery**: Data protection and backup
- **Server-side encryption**: Data encrypted at rest
- **TTL support**: Automatic cleanup of old data (optional)
- **Global secondary index**: Efficient queries by status and time
- **CloudWatch alarms**: Monitoring for throttling events

## Usage

```hcl
module "data" {
  source = "./modules/data"

  project_name                  = "risk-assessor"
  environment                   = "dev"
  enable_point_in_time_recovery = true
  kms_key_arn                   = "" # Optional: use AWS managed key
}
```

## Outputs

- `table_name`: DynamoDB table name
- `table_arn`: DynamoDB table ARN
- `table_stream_arn`: Stream ARN (if enabled)
- `gsi1_name`: Global secondary index name
