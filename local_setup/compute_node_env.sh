#!/usr/bin/env bash
# Source this ONLY after you are on the GPU compute node (hostname = m4gn1601...).
#     source local_setup/compute_node_env.sh
#
# It activates the venv and sets: VPN proxy (mihomo on ln08:7890), HuggingFace
# mirror, and the uv download timeout. Works for BOTH ChatGPT (via VPN) and
# Qwen (direct — dashscope is excluded from the proxy via NO_PROXY).
#
# It does NOT set any API key — set that separately (see RECONNECT_RUNBOOK.md).

# Safety: refuse to run on the login node (ln08 kills >4-core processes).
if [[ "$(hostname)" == ln* ]]; then
    echo "[env] REFUSING: you are on a login node ($(hostname))." >&2
    echo "[env] Get onto the GPU node first:  srun --jobid=\$JOB --overlap --pty bash" >&2
    return 1 2>/dev/null || exit 1
fi

cd ~/projects/scenesmith || return 1
# shellcheck disable=SC1091
source .venv/bin/activate

# --- VPN proxy → mihomo running on ln08 (port 7890 confirmed reachable) -------
export HTTPS_PROXY=http://ln08:7890
export HTTP_PROXY=http://ln08:7890
# Keep local servers + domestic services OFF the proxy (direct = faster/works).
export NO_PROXY=127.0.0.1,localhost,dashscope.aliyuncs.com,hf-mirror.com
export no_proxy="$NO_PROXY"

# --- HuggingFace mirror (HSSD/asset downloads) + uv download timeout ----------
export HF_ENDPOINT=https://hf-mirror.com
export UV_HTTP_TIMEOUT=600

# --- Keep big stuff off the tiny 1.1G home quota → use the work disk ----------
# uv cache + venv + outputs must live on /data/run01 (1.8T), not /data/home (1.1G).
export UV_CACHE_DIR=/data/run01/scvj260/uv-cache
# JuiceFS hardlink/rename is flaky (os error 5) → make uv copy instead.
export UV_LINK_MODE=copy

echo "[env] node   : $(hostname)"
echo "[env] python : $(command -v python)"
echo "[env] proxy  : $HTTPS_PROXY   (NO_PROXY=$NO_PROXY)"
echo "[env] HF     : $HF_ENDPOINT"
echo "[env] Reminder: set your API key next —"
echo "      ChatGPT:  export OPENAI_API_KEY=sk-...   (uses VPN)"
echo "      Qwen   :  export OPENAI_API_KEY=<dashscope>  OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1"
