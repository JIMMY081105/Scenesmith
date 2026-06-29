#!/usr/bin/env bash
# Source this to run SceneSmith against a LOCAL Ollama model (free, no API cost)
# instead of DashScope/qwen-plus:
#     source local_setup/setup_env_local.sh
#
# It activates .venv, points the OpenAI-compatible client at the local Ollama
# server, and keeps the SOCKS proxy for HuggingFace downloads while bypassing it
# for localhost. No API key is needed (Ollama ignores it).

# --- Guard: must be sourced, not executed ------------------------------------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: This script must be sourced, not executed."
    echo "Run:"
    echo "  source local_setup/setup_env_local.sh"
    exit 1
fi

_SS_SCRIPT="${BASH_SOURCE[0]}"
_SS_SETUP_DIR="$(cd "$(dirname "${_SS_SCRIPT}")" >/dev/null 2>&1 && pwd)"
_SS_REPO_ROOT="$(cd "${_SS_SETUP_DIR}/.." >/dev/null 2>&1 && pwd)"

# --- Activate the virtualenv -------------------------------------------------
if [ -f "${_SS_REPO_ROOT}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${_SS_REPO_ROOT}/.venv/bin/activate"
    echo "[setup_env_local] Activated venv ($(python --version 2>&1))"
else
    echo "[setup_env_local] WARNING: .venv not found." >&2
fi

# --- Point the OpenAI-compatible client at local Ollama ----------------------
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="ollama"   # dummy; Ollama does not check it
echo "[setup_env_local] OPENAI_BASE_URL=${OPENAI_BASE_URL} (local Ollama)"

# HuggingFace China mirror so HSSD mesh downloads work WITHOUT the proxy.
export HF_ENDPOINT="https://hf-mirror.com"
echo "[setup_env_local] HF_ENDPOINT=${HF_ENDPOINT}"

# --- Proxy-free: everything we need is reachable China-direct -----------------
# LLM = local Ollama (no internet at runtime); HSSD = hf-mirror; DashScope = direct.
# We deliberately do NOT set ALL_PROXY: the Windows proxy is unreliable, and a
# dead proxy in ALL_PROXY would make even hf-mirror requests hang.
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
echo "[setup_env_local] Proxy DISABLED (using China-direct + hf-mirror)."

# --- Sanity: is the Ollama server up? ----------------------------------------
if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "[setup_env_local] Ollama is reachable. Installed models:"
    (curl -s http://localhost:11434/api/tags | python -c 'import sys,json;[print("   -",m["name"]) for m in json.load(sys.stdin).get("models",[])]') 2>/dev/null || true
else
    echo "[setup_env_local] NOTE: Ollama not reachable at :11434 yet."
    echo "[setup_env_local]   Install:  curl -fsSL https://ollama.com/install.sh | sh"
    echo "[setup_env_local]   Serve:    ollama serve   (or it autostarts)"
    echo "[setup_env_local]   Pull:     ollama pull qwen2.5vl:3b"
fi

echo "[setup_env_local] Done. Run with:  SS_MODEL=qwen2.5vl:3b SS_MODE=room SS_STOP=wall_mounted bash local_setup/run_measured.sh \"<prompt>\""
