#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG="config.yaml"
DRY_RUN=""
MAX_POSTS=""
POST_NOW=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config|-c)
            CONFIG="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --post-now)
            POST_NOW="--post-now"
            shift
            ;;
        --max-posts)
            MAX_POSTS="--max-posts $2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.12+ and try again."
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing/updating dependencies..."
pip install -q -r requirements.txt

echo "Starting bot..."
# shellcheck disable=SC2086
python -m src.main --config "$CONFIG" $DRY_RUN $POST_NOW $MAX_POSTS
