#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=5252

# Check if server is already running on port 5252
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
  echo "ChatGPT Switcher server is already running on port $PORT."
else
  echo "Starting ChatGPT Switcher server on port $PORT..."
  python3 "$DIR/web/server.py" > /tmp/chatgpt-switcher-server.log 2>&1 &
  sleep 1
fi

echo "Opening dashboard in browser..."
open "http://localhost:$PORT"
echo "Done! You can manage your ChatGPT accounts at http://localhost:$PORT"
