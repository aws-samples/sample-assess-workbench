"""Backfill existing review findings into shared SEMANTIC memory.

Reads findings from DynamoDB for a given project and stores them
in the shared memory using batch_create_memory_records.
"""
import boto3
import json
from datetime import datetime

REGION = "us-west-2"
MEMORY_ID = "risk_assessor_shared_memory_dev-mKxLYB9aQX"
TABLE_NAME = "risk-assessor-projects-dev"
PROJECT_ID = "7e5abd63"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
agentcore = boto3.client("bedrock-agentcore", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def get_project_info():
    response = table.get_item(Key={"PK": f"PROJECT#{PROJECT_ID}", "SK": "METADATA"})
    return response.get("Item", {})


def get_review_findings():
    """Get the latest review findings from DynamoDB."""
    # Query for review items
    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": f"PROJECT#{PROJECT_ID}",
            ":sk": "REVIEW#",
        },
    )
    items = response.get("Items", [])
    print(f"Found {len(items)} review items")

    # Find the completed review with findings
    for item in items:
        findings = item.get("findings")
        if findings:
            if isinstance(findings, str):
                findings = json.loads(findings)
            return findings
    return None


def store_findings(findings):
    """Store findings in memory using batch_create_memory_records."""
    reviews = findings.get("reviews", {})
    if not reviews:
        print("No reviews found in findings")
        return

    project_info = get_project_info()
    project_name = project_info.get("name", "Unknown")

    records = []
    for agent_type, review_data in reviews.items():
        agent_findings = review_data.get("findings", [])
        print(f"  {agent_type}: {len(agent_findings)} findings")

        for finding in agent_findings:
            content = f"""Finding: {finding['title']}

Severity: {finding['severity']}
Agent: {agent_type}

Description:
{finding['description']}

Recommendation:
{finding['recommendation']}

References: {', '.join(finding.get('references', []))}

Project: {project_name}
Project ID: {PROJECT_ID}"""

            records.append({
                "content": {"text": content},
                "namespaces": [f"/findings/{PROJECT_ID}/{agent_type}"],
                "requestIdentifier": f"{PROJECT_ID}-{finding['id']}",
                "timestamp": datetime.utcnow(),
            })

    # Batch create in chunks of 100
    total_stored = 0
    for i in range(0, len(records), 100):
        batch = records[i : i + 100]
        print(f"Storing batch {i // 100 + 1} ({len(batch)} records)...")

        response = agentcore.batch_create_memory_records(
            memoryId=MEMORY_ID,
            records=batch,
        )

        success = len(response.get("successfulRecords", []))
        failed = len(response.get("failedRecords", []))
        total_stored += success
        print(f"  Success: {success}, Failed: {failed}")

        if failed > 0:
            for f in response["failedRecords"]:
                print(f"  Error: {f.get('requestIdentifier')}: {f.get('errorMessage')}")

    print(f"\nTotal stored: {total_stored}/{len(records)}")


if __name__ == "__main__":
    print(f"Backfilling findings for project {PROJECT_ID}")
    print(f"Memory: {MEMORY_ID}")
    print(f"Table: {TABLE_NAME}")
    print()

    findings = get_review_findings()
    if findings:
        print("Found review findings, storing in memory...")
        store_findings(findings)
    else:
        print("No review findings found in DynamoDB")
