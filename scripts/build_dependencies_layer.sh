#!/usr/bin/env bash
# Build the dependencies Lambda layer: boto3, python-jose.
# Rebuilt only when dependency versions change (~50MB).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build/dependencies_layer"
LAYER_DIR="$BUILD_DIR/python"

echo "Building dependencies layer..."

rm -rf "$BUILD_DIR"
mkdir -p "$LAYER_DIR"

uv pip install \
  --python-platform x86_64-manylinux2014 \
  --target "$LAYER_DIR" \
  --python-version 3.13 \
  --only-binary=:all: \
  --upgrade \
  "boto3>=1.42.0" \
  "python-jose[cryptography]>=3.3.0" \
  --quiet

echo "Dependencies layer built: $(du -sh "$BUILD_DIR" | cut -f1)"
