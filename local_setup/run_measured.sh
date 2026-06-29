#!/usr/bin/env bash
# Run a SceneSmith scene while recording elapsed time, peak RAM/swap, and peak
# VRAM. Delegates the actual run to run_house_hssd.sh, so all the HSSD-only
# overrides apply. Use this to measure what one room costs before scaling up.
#
# Prerequisite (same shell):
#     source local_setup/setup_env.sh
#
# Usage (defaults to a single room, furniture + wall-mounted stages):
#     bash local_setup/run_measured.sh "A bedroom prompt ..."
#
# Honors the same env vars as run_house_hssd.sh:
#     SS_MODE  : room | house              (default here: room)
#     SS_STOP  : furniture|wall_mounted|manipuland  (default here: wall_mounted)

set -uo pipefail   # NOT -e: we want the resource report even if the run fails.

_SS_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"
_SS_REPO_ROOT="$(cd "${_SS_SETUP_DIR}/.." >/dev/null 2>&1 && pwd)"
cd "${_SS_REPO_ROOT}"

# Single-room / furniture+wall by default (overridable via env).
export SS_MODE="${SS_MODE:-room}"
export SS_STOP="${SS_STOP:-wall_mounted}"

mkdir -p outputs
STAMP="$(date +%Y%m%d_%H%M%S)"
MONLOG="outputs/_resource_monitor_${STAMP}.log"

# --- Background resource sampler (every 5s) ----------------------------------
(
    echo "# epoch  mem_used_mb  swap_used_mb  gpu_used_mb"
    while true; do
        ts="$(date +%s)"
        read -r mem swap < <(free -m | awk '/Mem:/{m=$3} /Swap:/{s=$3} END{print m, s}')
        gpu="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1)"
        echo "${ts}  ${mem}  ${swap}  ${gpu:-NA}"
        sleep 5
    done
) >> "${MONLOG}" 2>/dev/null &
SAMPLER_PID=$!
# Make sure the sampler dies with us no matter how we exit.
trap 'kill "${SAMPLER_PID}" 2>/dev/null || true' EXIT INT TERM

echo "[measure] Resource log: ${MONLOG} (sampling every 5s)"
echo "[measure] MODE=${SS_MODE} STOP_STAGE=${SS_STOP}"
START="$(date +%s)"

# --- Run the actual pipeline -------------------------------------------------
bash local_setup/run_house_hssd.sh "$@"
RC=$?

END="$(date +%s)"
kill "${SAMPLER_PID}" 2>/dev/null || true

# --- Report ------------------------------------------------------------------
ELAPSED=$((END - START))
echo ""
echo "=================== MEASUREMENT REPORT ==================="
printf "exit code        : %s\n" "${RC}"
printf "elapsed          : %dm %ds (%ds)\n" $((ELAPSED/60)) $((ELAPSED%60)) "${ELAPSED}"
awk '
    NR>1 && $2!="" { if ($2+0>mm) mm=$2+0 }
    NR>1 && $3!="" { if ($3+0>ms) ms=$3+0 }
    NR>1 && $4!="NA" && $4!="" { if ($4+0>mg) mg=$4+0 }
    END {
        printf "peak RAM used    : %d MB (of ~11000)\n", mm
        printf "peak swap used   : %d MB (of ~24000)\n", ms
        printf "peak VRAM used   : %s MB (of 8188)\n", (mg=="" ? "NA" : mg)
    }
' "${MONLOG}"
echo "resource log     : ${MONLOG}"
echo "scene output     : outputs/latest-run/"
echo "========================================================="
echo "Share these numbers and I'll extrapolate to a 4-5 room house."
