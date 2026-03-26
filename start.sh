#!/bin/bash
# Backend Mastery — Start the learning server
# Usage: ./start.sh [port]

PORT=${1:-3000}

echo "Starting Backend Mastery server..."
echo ""

cd "$(dirname "$0")/server"

# Check Go is installed
if ! command -v go &> /dev/null; then
    echo "Error: Go is not installed."
    echo "Install it from https://go.dev/dl/"
    exit 1
fi

PORT=$PORT go run main.go
