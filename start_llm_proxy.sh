#!/bin/bash

# This script sets up a Python virtual environment, exports API keys,
# and starts both the LiteLLM proxy server and FastAPI proxy

# --- Configuration ---
KEYS_CONFIG_FILE="api_keys.config"
VENV_DIR="venv-lm-proxy"
FASTAPI_SCRIPT="lm_proxy.py"
LITELLM_CONFIG_FILE="litellm-config.yaml"
LITELLM_PORT=8000
FASTAPI_PORT=8001

# --- Script Logic ---

# Check for Python3.12
if command -v python3.12 &>/dev/null; then
 PYTHON_CMD="python3.12"
elif python3 -c "import sys; exit(0 if sys.version_info >= (3,12) else1)" &>/dev/null; then
 PYTHON_CMD="python3"
else
 echo "Error: Python3.12 is required but not found."
 echo "Please install Python3.12 and try again."
 exit 1
fi

echo "Using Python: $($PYTHON_CMD --version)"

# Load API keys from config file
if [ -f "$KEYS_CONFIG_FILE" ]; then
 echo "Loading API keys from $KEYS_CONFIG_FILE..."
 while IFS= read -r LINE; do
 if [[ $LINE =~ ^[^#] ]]; then
 KEY=${LINE%%=*}
 VALUE=${LINE#*=}
 export "$KEY"="$VALUE"
 echo "Exported $KEY=$VALUE"
 fi
 done < "$KEYS_CONFIG_FILE"
else
 echo "Error: $KEYS_CONFIG_FILE not found."
 exit 1
fi

# Set up virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
 echo "Creating virtual environment..."
 if ! ("$PYTHON_CMD" -m venv "$VENV_DIR"); then
 echo "Failed to create virtual environment. Please install the 'venv' package and try again."
 exit 1
 fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Verify we're in the correct environment
if [ "$(which python)" != "$(pwd)/$VENV_DIR/bin/python" ]; then
 echo "Failed to activate virtual environment. Exiting."
 exit 1
fi

# Install required packages
echo "Installing required packages..."
pip install --upgrade pip
pip install 'litellm[proxy]' fastapi uvicorn httpx

# Function to handle cleanup when script exits
cleanup() {
  echo "Stopping services..."
  if kill -0 "$LITELLM_PID" 2>/dev/null; then
    kill "$LITELLM_PID" 2>/dev/null
    echo "LiteLLM proxy (PID: $LITELLM_PID) stopped."
  else
    echo "LiteLLM proxy (PID: $LITELLM_PID) already stopped."
  fi
  if kill -0 "$FASTAPI_PID" 2>/dev/null; then
    kill "$FASTAPI_PID" 2>/dev/null
    echo "FastAPI proxy (PID: $FASTAPI_PID) stopped."
  else
    echo "FastAPI proxy (PID: $FASTAPI_PID) already stopped."
  fi
  wait "$LITELLM_PID" 2>/dev/null
  wait "$FASTAPI_PID" 2>/dev/null
  echo "Deactivating virtual environment..."
  deactivate >/dev/null 2>&1
  exit
}

# Set trap for SIGINT (Ctrl+C) and SIGTERM
trap cleanup SIGINT SIGTERM

# Launch the LiteLLM proxy server in the background
echo "Launching LiteLLM proxy on port $LITELLM_PORT with config file: $LITELLM_CONFIG_FILE"
litellm --config "$LITELLM_CONFIG_FILE" --port "$LITELLM_PORT" &
LITELLM_PID=$!

# Wait a moment for LiteLLM to start up
sleep3

# Check if LiteLLM started successfully
if ps -p "$LITELLM_PID" > /dev/null; then
 echo "LiteLLM proxy started successfully with PID: $LITELLM_PID"
else
 echo "Failed to start LiteLLM proxy. Exiting."
 cleanup
fi

# Launch the FastAPI proxy server in the background
echo "Launching FastAPI proxy on port $FASTAPI_PORT"
export LITELLM_PROXY_URL="http://localhost:$LITELLM_PORT"
export FASTAPI_PROXY_PORT="$FASTAPI_PORT"
python "$FASTAPI_SCRIPT" &
FASTAPI_PID=$!

# Wait a moment for FastAPI to start up
sleep3

# Check if FastAPI started successfully
if ps -p "$FASTAPI_PID" > /dev/null; then
 echo "FastAPI proxy started successfully with PID: $FASTAPI_PID"
else
 echo "Failed to start FastAPI proxy. Stopping LiteLLM."
 cleanup
fi

echo "Both services are running!"
echo "- LiteLLM proxy: http://localhost:$LITELLM_PORT"
echo "- FastAPI proxy: http://localhost:$FASTAPI_PORT"
echo "Press Ctrl+C to stop both services."

# Wait for both processes to complete (or until Ctrl+C)
wait