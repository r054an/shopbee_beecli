#!/usr/bin/env bash
# ShopBee — "You said you needed it. Bee remembers."
# Run ShopBee from the command line with automatic dependency checks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Dependency Checks ───────────────────────────────────────────────

check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "Error: '$1' is not installed. Please install it first." >&2
        return 1
    fi
}

# Check Python
if check_command python3; then
    PYTHON=python3
else
    PYTHON=python
fi

# Activate virtual environment if available
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
elif [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
fi

# Check Bee CLI
if ! check_command npx; then
    echo "Error: 'npx' is required. Install Node.js first." >&2
    exit 1
fi

echo "ShopBee — 'You said you needed it. Bee remembers.'"
echo ""

# ── Commands ────────────────────────────────────────────────────────

run_pending() {
    echo "🔍 Finding pending shopping items..."
    python3 -m shopbee pending
}

run_add() {
    local product="${1:?Usage: ./run.sh add <product_name>}"
    echo "🛒 Adding '$product' to cart..."
    python3 -m shopbee add "$product"
}

run_search() {
    local query="${1:?Usage: ./run.sh search <query>}"
    echo "🔎 Searching and adding '$query'..."
    python3 -m shopbee search "$query"
}

run_cart() {
    echo "🛒 Building shopping cart from all sources..."
    python3 -m shopbee cart
}

# ── Main ────────────────────────────────────────────────────────────

case "${1:-pending}" in
    pending) run_pending ;;
    add)     run_add "$2" ;;
    search)  run_search "$2" ;;
    cart)    run_cart ;;
    help|--help|-h)
        echo "Usage: ./run.sh [command] [args]"
        echo ""
        echo "Commands:"
        echo "  pending          Find items you mentioned needing"
        echo "  add <product>    Add product to cart"
        echo "  search <query>   Search and add in one step"
        echo "  cart             Build complete shopping cart"
        echo "  help             Show this help message"
        ;;
    *)
        echo "Unknown command: $1" >&2
        exit 1
        ;;
esac
