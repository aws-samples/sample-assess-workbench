#!/usr/bin/env bash
# Build the core Lambda layer: shared application code from api/core/.
# Rebuilt on every deploy (~30KB).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build/core_layer"
LAYER_DIR="$BUILD_DIR/python"

echo "Building core layer..."

rm -rf "$BUILD_DIR"
mkdir -p "$LAYER_DIR"

cp -r "$PROJECT_ROOT/api/core" "$LAYER_DIR/core"

# Clean up __pycache__ from the copy
find "$LAYER_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo "Core layer built: $(du -sh "$BUILD_DIR" | cut -f1)"
