#!/usr/bin/env bash
# Source this (do NOT execute) to run SceneSmith against the real OpenAI
# (ChatGPT) API instead of DashScope/Qwen or local Ollama:
#     source local_setup/setup_env_openai.sh
#
# It activates .venv, prompts for the OpenAI API key (never stored, never
# printed), points the OpenAI-compatible client at api.openai.com, and defines
# a small `test_openai_api` helper. No GPU is required for the HSSD-only path.

# --- Guard: must be sourced, not executed ------------------------------------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: This script must be sourced, not executed."
    echo "Run:  source local_setup/setup_env_openai.sh"
    exit 1
fi

# --- Locate repo root --------------------------------------------------------
if [ -n "${BASH_SOURCE:-}" ]; then
    _SS_SCRIPT="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    _SS_SCRIPT="${(%):-%N}"
else
    _SS_SCRIPT="$0"
fi
_SS_SETUP_DIR="$(cd "$(dirname "${_SS_SCRIPT}")" >/dev/null 2>&1 && pwd)"
_SS_REPO_ROOT="$(cd "${_SS_SETUP_DIR}/.." >/dev/null 2>&1 && pwd)"

# --- Activate the virtualenv -------------------------------------------------
if [ -f "${_SS_REPO_ROOT}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${_SS_REPO_ROOT}/.venv/bin/activate"
    echo "[setup_env_openai] Activated venv: ${_SS_REPO_ROOT}/.venv"
    echo "[setup_env_openai] python: $(command -v python)  ($(python --version 2>&1))"
else
    echo "[setup_env_openai] WARNING: ${_SS_REPO_ROOT}/.venv not found." >&2
    echo "[setup_env_openai]          Create it (python3.11 -m venv .venv) and retry." >&2
fi

# --- Prompt for the OpenAI API key (never stored, never printed) -------------
printf "[setup_env_openai] Enter OpenAI API key (input hidden): "
read -rs OPENAI_API_KEY
printf "\n"

if [ -z "${OPENAI_API_KEY}" ]; then
    echo "[setup_env_openai] WARNING: empty API key; runs will fail to authenticate." >&2
else
    export OPENAI_API_KEY
    # Real OpenAI endpoint. (Unset any leftover DashScope/Ollama base url.)
    export OPENAI_BASE_URL="https://api.openai.com/v1"
    echo "[setup_env_openai] OPENAI_API_KEY set (length=${#OPENAI_API_KEY})."
    echo "[setup_env_openai] OPENAI_BASE_URL=${OPENAI_BASE_URL}"
fi

# --- Proxy note --------------------------------------------------------------
# On many HPC compute nodes outbound internet is blocked or needs an http proxy.
# If api.openai.com is unreachable, export your cluster's proxy BEFORE running:
#     export HTTPS_PROXY=http://<proxy-host>:<port>
#     export https_proxy="$HTTPS_PROXY"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

# --- Helper: quick OpenAI connectivity check ---------------------------------
# Usage: test_openai_api   (defaults to gpt-4o-mini; override: SS_MODEL=gpt-4o test_openai_api)
test_openai_api() {
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "test_openai_api: OPENAI_API_KEY is not set. Source setup_env_openai.sh first." >&2
        return 1
    fi
    SS_MODEL="${SS_MODEL:-gpt-4o-mini}" python - <<'PY'
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
model = os.environ.get("SS_MODEL", "gpt-4o-mini")
resp = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Say OK only."}],
)
print(f"{model} replied:", resp.choices[0].message.content)
PY
}

echo "[setup_env_openai] Done. Helper available: test_openai_api"
echo "[setup_env_openai] Run a master room with:"
echo "    SS_MODEL=gpt-4o-mini SS_MODE=room SS_STOP=manipuland bash local_setup/run_house_hssd.sh \"<your master-bedroom prompt>\""
