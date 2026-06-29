#!/usr/bin/env bash
# Source this file (do NOT execute it):
#     source local_setup/setup_env.sh
#
# It activates .venv, prompts for the DashScope API key (never stored, never
# printed), exports the OpenAI-compatible + WSL proxy variables, and defines a
# small `test_qwen_api` helper.

# --- Guard: must be sourced, not executed ------------------------------------
# If run as `bash setup_env.sh`, exports would only live in a child shell and
# vanish on exit. Detect that case and bail out with a clear instruction.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: This script must be sourced, not executed."
    echo "Run:"
    echo "  source local_setup/setup_env.sh"
    exit 1
fi

# --- Locate the repo root (works whether sourced from bash or zsh) -----------
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
    echo "[setup_env] Activated venv: ${_SS_REPO_ROOT}/.venv"
    echo "[setup_env] python: $(command -v python)  ($(python --version 2>&1))"
else
    echo "[setup_env] WARNING: ${_SS_REPO_ROOT}/.venv/bin/activate not found." >&2
    echo "[setup_env]          Create it (python3.11 -m venv .venv) and retry." >&2
fi

# --- Prompt for the DashScope API key (never stored, never printed) ----------
# read -s every session: WSL env vars vanish after `wsl --shutdown`.
printf "[setup_env] Enter DashScope API key (input hidden): "
read -rs DASHSCOPE_API_KEY
printf "\n"

if [ -z "${DASHSCOPE_API_KEY}" ]; then
    echo "[setup_env] WARNING: empty API key entered; runs will fail to authenticate." >&2
else
    export DASHSCOPE_API_KEY
    export OPENAI_API_KEY="${DASHSCOPE_API_KEY}"
    export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    # Print length only — never the key itself.
    echo "[setup_env] OPENAI_API_KEY set (length=${#OPENAI_API_KEY})."
    echo "[setup_env] OPENAI_BASE_URL=${OPENAI_BASE_URL}"
fi

# --- WSL proxy exports (Windows proxy reachable via the default gateway) ------
WIN_HOST="$(ip route | awk '/default/ {print $3}')"
if [ -n "${WIN_HOST}" ]; then
    export ALL_PROXY="socks5h://${WIN_HOST}:10818"
    export all_proxy="socks5h://${WIN_HOST}:10818"
    # DashScope (Alibaba) is directly reachable in China and must NOT go through
    # the (overseas) SOCKS proxy, or LLM calls time out. HuggingFace still uses
    # the proxy for downloads. So exclude the DashScope host from the proxy.
    export NO_PROXY="127.0.0.1,localhost,dashscope.aliyuncs.com"
    export no_proxy="127.0.0.1,localhost,dashscope.aliyuncs.com"
    echo "[setup_env] Proxy set: ALL_PROXY=socks5h://${WIN_HOST}:10818 (NO_PROXY includes dashscope.aliyuncs.com)"
    echo "[setup_env] (The WSL localhost proxy warning is expected and can be ignored.)"
else
    echo "[setup_env] WARNING: could not determine Windows gateway; proxy not set." >&2
fi

# --- Helper: quick Qwen connectivity check -----------------------------------
# Usage: test_qwen_api
test_qwen_api() {
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "test_qwen_api: OPENAI_API_KEY is not set. Source setup_env.sh first." >&2
        return 1
    fi
    python - <<'PY'
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get(
        "OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ),
)
resp = client.chat.completions.create(
    model="qwen-plus",
    messages=[{"role": "user", "content": "Say OK only."}],
)
print("qwen-plus replied:", resp.choices[0].message.content)
PY
}

echo "[setup_env] Done. Helper available: test_qwen_api"
