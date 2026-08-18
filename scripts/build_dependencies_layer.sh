#!/usr/bin/env bash
# Build the dependencies Lambda layer: boto3, PyJWT.
# Rebuilt only when dependency versions change (~50MB).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build/dependencies_layer"
LAYER_DIR="$BUILD_DIR/python"
# Exported from uv.lock at build time (not committed) — see pyproject.toml
# [dependency-groups] lambda_layer. Written to .build/ (gitignored).
EXPORTED_REQS="$PROJECT_ROOT/.build/dependencies_layer.requirements.txt"

echo "Building dependencies layer..."

rm -rf "$BUILD_DIR"
mkdir -p "$LAYER_DIR"

# Export the pinned deps from uv.lock (lock-faithful, so the deployed layer
# matches the versions the dependency scan sees — notably PyJWT, which
# verifies Cognito JWTs), then install them cross-compiled for the Lambda.
uv export --only-group lambda_layer --no-emit-project --no-hashes --no-annotate \
  --project "$PROJECT_ROOT" -o "$EXPORTED_REQS"

# Target manylinux_2_28 (glibc 2.28): the PYTHON_3_13 Lambda runtime is Amazon
# Linux 2023 (glibc 2.34), which runs 2_28 wheels. The older manylinux2014
# (glibc 2.17) tag is increasingly dropped by native deps (e.g. cryptography).
uv pip install \
  --python-platform x86_64-manylinux_2_28 \
  --target "$LAYER_DIR" \
  --python-version 3.13 \
  --only-binary=:all: \
  --upgrade \
  -r "$EXPORTED_REQS" \
  --quiet

echo "Dependencies layer built: $(du -sh "$BUILD_DIR" | cut -f1)"
