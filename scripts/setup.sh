#!/usr/bin/env bash
set -euo pipefail

echo "=== Vibe Marketing Setup ==="

# System dependencies
echo "Installing ffmpeg..."
if ! command -v ffmpeg &>/dev/null; then
    sudo apt-get update && sudo apt-get install -y ffmpeg
else
    echo "  ffmpeg already installed"
fi

echo "Installing yt-dlp..."
if ! command -v yt-dlp &>/dev/null; then
    sudo apt-get install -y yt-dlp 2>/dev/null || pip install yt-dlp
else
    echo "  yt-dlp already installed"
fi

# Python venv
echo "Setting up Python venv..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python dependencies..."
pip install -e ".[dev]"

# Create directories
mkdir -p plans tmp

echo ""
echo "=== Setup complete ==="
echo "Activate venv: source .venv/bin/activate"
echo "Run server:    uvicorn src.main:app --reload"
echo "Run CLI:       python scripts/process_reel.py <url>"
