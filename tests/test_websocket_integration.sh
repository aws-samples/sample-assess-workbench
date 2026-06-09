#!/bin/bash
# Quick WebSocket integration test script

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
WEBSOCKET_URL="${WEBSOCKET_URL:-}"
TEST_PROJECT_ID="${TEST_PROJECT_ID:-7e5abd63}"

if [ -z "$WEBSOCKET_URL" ]; then
    echo -e "${RED}Error: WEBSOCKET_URL environment variable not set${NC}"
    echo "Usage: export WEBSOCKET_URL=wss://abc123.execute-api.us-west-2.amazonaws.com/dev"
    exit 1
fi

echo -e "${GREEN}WebSocket Integration Tests${NC}"
echo "WebSocket URL: $WEBSOCKET_URL"
echo "Test Project: $TEST_PROJECT_ID"
echo ""

# Check if websockets is installed
if ! uv run python -c "import websockets" 2>/dev/null; then
    echo -e "${YELLOW}Installing websockets library with uv...${NC}"
    uv pip install websockets pytest-asyncio
fi

# Run tests based on argument
case "${1:-all}" in
    quick)
        echo -e "${GREEN}Running quick test (security agent only)...${NC}"
        uv run pytest tests/live/test_websocket_chat.py::test_websocket_connects_and_disconnects -v -s
        uv run pytest tests/live/test_websocket_chat.py::test_security_agent_responds -v -s
        ;;
    
    agents)
        echo -e "${GREEN}Testing all agents...${NC}"
        uv run pytest tests/live/test_websocket_chat.py::test_security_agent_responds -v -s
        uv run pytest tests/live/test_websocket_chat.py::test_architecture_agent_responds -v -s
        uv run pytest tests/live/test_websocket_chat.py::test_risk_agent_responds -v -s
        ;;
    
    validation)
        echo -e "${GREEN}Testing validation and error handling...${NC}"
        uv run pytest tests/live/test_websocket_chat.py::test_invalid_agent_returns_error -v -s
        uv run pytest tests/live/test_websocket_chat.py::test_missing_fields_returns_error -v -s
        uv run pytest tests/live/test_websocket_chat.py::test_nonexistent_project_returns_error -v -s
        ;;
    
    conversation)
        echo -e "${GREEN}Testing multi-turn conversation...${NC}"
        uv run pytest tests/live/test_websocket_chat.py::test_multi_turn_conversation -v -s
        ;;
    
    all)
        echo -e "${GREEN}Running all WebSocket live tests...${NC}"
        uv run pytest tests/live/test_websocket_chat.py -v -s
        ;;
    
    *)
        echo "Usage: $0 {quick|agents|validation|conversation|all}"
        echo ""
        echo "  quick        - Quick smoke test (connection + security agent)"
        echo "  agents       - Test all three agents"
        echo "  validation   - Test error handling and validation"
        echo "  conversation - Test multi-turn conversation"
        echo "  all          - Run all tests"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✓ Tests complete${NC}"
