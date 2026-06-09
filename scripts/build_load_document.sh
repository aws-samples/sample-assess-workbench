#!/usr/bin/env bash
# Build the load_document Lambda package with PyMuPDF dependency.
# Called by Terraform's null_resource before creating the archive.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build/load_document"
SOURCE_FILE="$PROJECT_ROOT/api/workflow/load_document.py"
REQUIREMENTS="$PROJECT_ROOT/api/workflow/load_document_requirements.txt"

echo "Building load_document Lambda package..."

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Install dependencies for Lambda (Linux x86_64)
uv pip install \
  --python-platform x86_64-manylinux2014 \
  --target "$BUILD_DIR" \
  --python-version 3.13 \
  --only-binary=:all: \
  --upgrade \
  -r "$REQUIREMENTS" \
  --quiet

# Copy Lambda handler
cp "$SOURCE_FILE" "$BUILD_DIR/"

echo "Build complete: $BUILD_DIR"
