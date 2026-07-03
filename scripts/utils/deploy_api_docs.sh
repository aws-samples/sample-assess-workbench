#!/bin/bash
# Generate and deploy API documentation to S3

set -e

# Parse arguments
LOCAL_ONLY=false
if [[ "$1" == "--local" ]]; then
    LOCAL_ONLY=true
    shift
fi

# Load common functions and environment (only if deploying)
if [[ "$LOCAL_ONLY" == false ]]; then
    source "$(dirname "$0")/common.sh"
    load_env
    require_env
fi

echo "=================================="
if [[ "$LOCAL_ONLY" == true ]]; then
    echo "Generate API Documentation"
else
    echo "Generate & Deploy API Documentation"
fi
echo "=================================="
echo ""

# Step 1: Generate documentation
echo "� Generating API documentation with Redoc..."

# Create docs output directory
mkdir -p api/docs

# Copy OpenAPI spec
echo "📄 Copying OpenAPI specification..."
cp api/openapi.yaml api/docs/

# Generate Redoc HTML (self-contained, no external dependencies)
echo "📝 Generating Redoc documentation..."
cat > api/docs/index.html <<'EOF'
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>AgentCore Risk Assessor API Documentation</title>
    <style>
        body {
            margin: 0;
            padding: 0;
        }
    </style>
</head>
<body>
    <redoc spec-url='openapi.yaml'></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
EOF

echo ""
echo "✅ Documentation generated in api/docs/"
echo ""
echo "Files created:"
echo "  - api/docs/index.html (Redoc documentation)"
echo "  - api/docs/openapi.yaml (OpenAPI specification)"

# If local only, stop here
if [[ "$LOCAL_ONLY" == true ]]; then
    echo ""
    echo "To view locally:"
    echo "  cd api/docs && python3 -m http.server 8000"
    echo "  Open http://localhost:8000"
    echo ""
    echo "To deploy to S3:"
    echo "  ./scripts/deploy_api_docs.sh"
    exit 0
fi

# Step 2: Deploy to S3
echo ""
echo "=================================="
echo "Deploying to S3"
echo "=================================="
echo ""

# Allow override via command line
BUCKET_NAME="${1:-${PROJECT_NAME}-api-docs-${ENVIRONMENT}}"

echo "Configuration:"
echo "  Bucket: ${BUCKET_NAME}"
echo "  Region: ${AWS_REGION}"
echo ""

# Check if bucket exists
if ! aws s3 ls "s3://${BUCKET_NAME}" --region "${AWS_REGION}" > /dev/null 2>&1; then
    echo "📦 Creating S3 bucket..."
    aws s3 mb "s3://${BUCKET_NAME}" --region "${AWS_REGION}"

    # Enable static website hosting
    aws s3 website "s3://${BUCKET_NAME}" \
        --index-document index.html \
        --error-document index.html

    # Set bucket policy for public read
    cat > /tmp/bucket-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${BUCKET_NAME}/*"
    }
  ]
}
EOF

    aws s3api put-bucket-policy \
        --bucket "${BUCKET_NAME}" \
        --policy file:///tmp/bucket-policy.json

    rm /tmp/bucket-policy.json

    echo "✓ Bucket created and configured"
else
    echo "✓ Bucket already exists"
fi

# Sync to S3
echo ""
echo "📤 Uploading documentation..."
aws s3 sync api/docs/ "s3://${BUCKET_NAME}/" \
    --delete \
    --cache-control "max-age=300" \
    --region "${AWS_REGION}"

# Get website URL
WEBSITE_URL="http://${BUCKET_NAME}.s3-website-${AWS_REGION}.amazonaws.com"

echo ""
echo "✅ Documentation deployed!"
echo ""
echo "Website URL: ${WEBSITE_URL}"
echo ""
echo "To use a custom domain:"
echo "  1. Create CloudFront distribution"
echo "  2. Point to S3 website endpoint"
echo "  3. Add custom domain in Route53"
