#!/usr/bin/env bash
# Run a "lived-in" scene with HSSD retrieval only (NO text-to-3D generation).
#
# Goes beyond bare furniture: also runs wall-mounted objects (pictures, shelves)
# and manipulands (tabletop/counter small objects: bowls, books, cups, decor),
# so the result actually looks like a home. All assets are STATIC retrieved
# HSSD meshes -- visible but not separable/openable (that needs generation,
# which 8GB VRAM cannot run).
#
# Prerequisite (same shell):
#     source local_setup/setup_env.sh
#
# Usage:
#     bash local_setup/run_house_hssd.sh                       # default: 3-room house, all stages
#     bash local_setup/run_house_hssd.sh "custom prompt ..."   # custom scene
#
# Configurable via env vars (RECOMMENDED: validate small first):
#     SS_MODE=room  SS_STOP=manipuland  bash local_setup/run_house_hssd.sh "One cozy living room ..."
#       -> single rich room, all stages: fast sanity check of richness + memory/time
#     SS_MODE=house SS_STOP=furniture   bash local_setup/run_house_hssd.sh
#       -> multi-room but big-furniture only (lighter)
#   SS_MODE  : room | house         (default: house)
#   SS_STOP  : furniture | wall_mounted | manipuland   (default: manipuland)

set -euo pipefail

_SS_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"
_SS_REPO_ROOT="$(cd "${_SS_SETUP_DIR}/.." >/dev/null 2>&1 && pwd)"
cd "${_SS_REPO_ROOT}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[run] ERROR: OPENAI_API_KEY empty/unset.  Run: source local_setup/setup_env.sh" >&2
    exit 1
fi
if [ -z "${OPENAI_BASE_URL:-}" ]; then
    echo "[run] ERROR: OPENAI_BASE_URL unset.  Run: source local_setup/setup_env.sh" >&2
    exit 1
fi
echo "[run] OPENAI_API_KEY present (length=${#OPENAI_API_KEY}). BASE_URL=${OPENAI_BASE_URL}"

if [ -f "${_SS_REPO_ROOT}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${_SS_REPO_ROOT}/.venv/bin/activate"
fi
echo "[run] python: $(command -v python)  ($(python --version 2>&1))"

SS_MODE="${SS_MODE:-house}"
SS_STOP="${SS_STOP:-manipuland}"

HOUSE_PROMPT="${1:-A small single-story home with three rooms connected by a hallway. A bedroom with a bed, two nightstands, a wardrobe, and a small bookshelf. A living room with a two-seater sofa, a coffee table, a TV stand with a television, a rug, and a couple of potted plants. A kitchen with lower cabinets, a fridge, a stove, and a dining table with two chairs. Make every room look fully furnished and lived-in.}"

echo "[run] MODE=${SS_MODE}  STOP_STAGE=${SS_STOP}"
echo "[run] Prompt: ${HOUSE_PROMPT}"

echo "[run] Freeing port 7006 if held..."
kill -9 $(lsof -t -i :7006) 2>/dev/null || true

# Build asset overrides: force HSSD-only on EVERY furnishing agent so no stage
# falls back to generation / articulated / materials servers (which we do not run).
# Model used for all agents. Default qwen-plus (DashScope). Override with
# SS_MODEL, e.g. SS_MODEL=qwen2.5vl:3b for a local Ollama model.
SS_MODEL="${SS_MODEL:-qwen-plus}"
echo "[run] MODEL=${SS_MODEL}"

ARGS=(
    +name=house_hssd_lived_in_qwen
    floor_plan_agent.mode="${SS_MODE}"
    experiment.pipeline.stop_stage="${SS_STOP}"
    experiment.prompts="[\"${HOUSE_PROMPT}\"]"
    experiment.projection.enabled=false
    experiment.sceneeval_export.enabled=false
    "floor_plan_agent.openai.model=${SS_MODEL}"
    "floor_plan_agent.session_memory.summarization_model=${SS_MODEL}"
)
for AGENT in furniture_agent wall_agent ceiling_agent manipuland_agent; do
    ARGS+=(
        "${AGENT}.openai.model=${SS_MODEL}"
        "${AGENT}.session_memory.summarization_model=${SS_MODEL}"
        "${AGENT}.asset_manager.general_asset_source=hssd"
        "${AGENT}.asset_manager.router.enabled=false"
        "${AGENT}.asset_manager.router.strategies.generated.enabled=false"
        "${AGENT}.asset_manager.router.strategies.articulated.enabled=false"
        "${AGENT}.asset_manager.router.strategies.thin_covering.enabled=false"
    )
done

echo "[run] Launching pipeline (Ctrl-C to stop)..."
python main.py "${ARGS[@]}"
