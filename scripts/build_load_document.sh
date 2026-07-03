#!/usr/bin/env bash
# Build the load_document Lambda package with PyMuPDF dependency.
# Called by Terraform's null_resource before creating the archive.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build/load_document"
SOURCE_FILE="$PROJECT_ROOT/api/workflow/load_document.py"
# Exported from uv.lock at build time (not committed) — see pyproject.toml
# [dependency-groups] load_document. Written to .build/ (gitignored), outside
# the Lambda package target so it isn't bundled into the zip.
EXPORTED_REQS="$PROJECT_ROOT/.build/load_document.requirements.txt"

echo "Building load_document Lambda package..."

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Export the pinned deps from uv.lock (lock-faithful, so the built package
# matches the versions the dependency scan sees), then install them
# cross-compiled for the Lambda x86_64 runtime.
uv export --only-group load_document --no-emit-project --no-hashes --no-annotate \
  --project "$PROJECT_ROOT" -o "$EXPORTED_REQS"

# Target manylinux_2_28 (glibc 2.28): the PYTHON_3_13 Lambda runtime is Amazon
# Linux 2023 (glibc 2.34), which runs 2_28 wheels. The older manylinux2014
# (glibc 2.17) tag is no longer published by some native deps (e.g. PyMuPDF).
uv pip install \
  --python-platform x86_64-manylinux_2_28 \
  --target "$BUILD_DIR" \
  --python-version 3.13 \
  --only-binary=:all: \
  --upgrade \
  -r "$EXPORTED_REQS" \
  --quiet

# Copy Lambda handler
cp "$SOURCE_FILE" "$BUILD_DIR/"

echo "Build complete: $BUILD_DIR"
