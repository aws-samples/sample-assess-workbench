"""Test namespace scoping for memory retrieval.

Compares results from root namespace vs scoped namespaces to verify
that chat agents will only receive findings relevant to their domain.
"""

import boto3

MEMORY_ID = "risk_assessor_shared_memory_dev-mKxLYB9aQX"
PROJECT_ID = "7e5abd63"
REGION = "us-west-2"
QUERY = "security vulnerabilities and authentication"

client = boto3.client("bedrock-agentcore", region_name=REGION)


def retrieve(namespace, query=QUERY):
    """Retrieve records from a given namespace."""
    response = client.retrieve_memory_records(
        memoryId=MEMORY_ID,
        namespace=namespace,
        searchCriteria={"searchQuery": query, "topK": 10},
    )
    return response.get("memoryRecordSummaries", [])


def extract_agent(text):
    """Extract agent type from finding text."""
    for line in text.split("\n"):
        if line.startswith("Agent:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def print_results(label, records):
    """Print summary of retrieved records."""
    print(f"\n{'='*60}")
    print(f"{label}: {len(records)} results")
    print(f"{'='*60}")
    for i, record in enumerate(records):
        text = record.get("content", {}).get("text", "")
        agent = extract_agent(text)
        score = record.get("score", 0)
        # Extract finding title (first line after "Finding: ")
        title = "unknown"
        for line in text.split("\n"):
            if line.startswith("Finding:"):
                title = line.split(":", 1)[1].strip()
                break
        print(f"  {i+1}. [{agent}] {title} (score: {score:.2f})")


# Test all namespaces
print(f"Memory ID: {MEMORY_ID}")
print(f"Project ID: {PROJECT_ID}")
print(f"Query: {QUERY}")

namespaces = {
    "Root /": "/",
    f"Project /findings/{PROJECT_ID}": f"/findings/{PROJECT_ID}",
    f"Security /findings/{PROJECT_ID}/security": f"/findings/{PROJECT_ID}/security",
    f"Architecture /findings/{PROJECT_ID}/architecture": f"/findings/{PROJECT_ID}/architecture",
    f"Risk /findings/{PROJECT_ID}/risk": f"/findings/{PROJECT_ID}/risk",
}

for label, namespace in namespaces.items():
    try:
        records = retrieve(namespace)
        print_results(label, records)
    except Exception as e:
        print(f"\n{label}: ERROR - {e}")

# Summary
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
print("If scoped namespaces return only their agent type's findings,")
print("namespace scoping is working correctly.")
print("If scoped namespaces return 0 results, the namespace hierarchy")
print("may not match how records were stored.")
