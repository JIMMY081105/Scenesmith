#!/usr/bin/env bash
# Run the minimal Qwen + HSSD-only furniture pipeline.
#
# Prerequisite (same shell):
#     source local_setup/setup_env.sh
#
# Then:
#     bash local_setup/run_hssd_furniture.sh
#
# Note: run with `bash` (not `source`). It validates env, frees port 7006,
# and stops the pipeline at the furniture stage.

set -euo pipefail

_SS_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"
_SS_REPO_ROOT="$(cd "${_SS_SETUP_DIR}/.." >/dev/null 2>&1 && pwd)"
cd "${_SS_REPO_ROOT}"

# --- Sanity checks: credentials must be present in this shell ----------------
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[run] ERROR: OPENAI_API_KEY is empty/unset." >&2
    echo "[run]        Run:  source local_setup/setup_env.sh" >&2
    exit 1
fi
if [ -z "${OPENAI_BASE_URL:-}" ]; then
    echo "[run] ERROR: OPENAI_BASE_URL is unset." >&2
    echo "[run]        Run:  source local_setup/setup_env.sh" >&2
    exit 1
fi
echo "[run] OPENAI_API_KEY present (length=${#OPENAI_API_KEY})."
echo "[run] OPENAI_BASE_URL=${OPENAI_BASE_URL}"

# Make sure we use the venv interpreter even when invoked via `bash`.
if [ -f "${_SS_REPO_ROOT}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${_SS_REPO_ROOT}/.venv/bin/activate"
fi
echo "[run] python: $(command -v python)  ($(python --version 2>&1))"

# --- Free a leftover HSSD retrieval server on port 7006 ----------------------
echo "[run] Freeing port 7006 if held..."
kill -9 $(lsof -t -i :7006) 2>/dev/null || true

# --- Minimal HSSD-only furniture run -----------------------------------------
# Key overrides:
#   stop_stage=furniture            -> stop after furniture (no manipulands/export)
#   general_asset_source=hssd       -> HSSD retrieval as the asset source
#   router.enabled=false            -> non-router path => straight to HSSD retrieval,
#                                      never tries generated/articulated/thin_covering
#   strategies.*.enabled=false      -> belt-and-suspenders: don't even construct the
#                                      generated/articulated/materials clients
#   projection/sceneeval_export off -> skip extra stages
echo "[run] Launching pipeline (Ctrl-C to stop)..."
python main.py \
    +name=hssd_furniture_test_qwen_hssdonly \
    experiment.pipeline.stop_stage=furniture \
    experiment.prompts='["A small office room with one desk and one office chair."]' \
    experiment.projection.enabled=false \
    experiment.sceneeval_export.enabled=false \
    floor_plan_agent.openai.model=qwen-plus \
    furniture_agent.openai.model=qwen-plus \
    floor_plan_agent.session_memory.summarization_model=qwen-plus \
    furniture_agent.session_memory.summarization_model=qwen-plus \
    furniture_agent.asset_manager.general_asset_source=hssd \
    furniture_agent.asset_manager.router.enabled=false \
    furniture_agent.asset_manager.router.strategies.generated.enabled=false \
    furniture_agent.asset_manager.router.strategies.articulated.enabled=false \
    furniture_agent.asset_manager.router.strategies.thin_covering.enabled=false
