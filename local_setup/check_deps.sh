#!/usr/bin/env bash
# Import-test the packages this minimal HSSD-only pipeline needs.
# Prints OK/FAIL per package. Installs NOTHING.
#
#     bash local_setup/check_deps.sh

set -u

_SS_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"
_SS_REPO_ROOT="$(cd "${_SS_SETUP_DIR}/.." >/dev/null 2>&1 && pwd)"

# Activate venv (so we test the right interpreter).
if [ -f "${_SS_REPO_ROOT}/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${_SS_REPO_ROOT}/.venv/bin/activate"
    echo "[check_deps] Using python: $(command -v python)  ($(python --version 2>&1))"
else
    echo "[check_deps] WARNING: ${_SS_REPO_ROOT}/.venv not found; using system python." >&2
fi

python - <<'PY'
import importlib
import sys

# (import_name, friendly_name) — import name differs from pip name for some.
modules = [
    "manifold3d",
    "trimesh",
    "rtree",
    "mapbox_earcut",
    "vhacdx",
    "coacd",
    "imageio",
    "skimage",
    "matplotlib",
    "pandas",
    "tqdm",
    "psutil",
    "rich",
    "open_clip",
    "torch",
    "bpy",
    "flask",
    "openai",
    "agents",
]

width = max(len(m) for m in modules)
n_ok = 0
n_fail = 0
for name in modules:
    try:
        importlib.import_module(name)
        print(f"  {name.ljust(width)}  OK")
        n_ok += 1
    except Exception as exc:  # noqa: BLE001 - we want to report any failure
        print(f"  {name.ljust(width)}  FAIL  ({exc.__class__.__name__}: {exc})")
        n_fail += 1

print()
print(f"[check_deps] {n_ok} OK, {n_fail} FAIL out of {len(modules)}.")
if n_fail:
    print("[check_deps] To install missing geometry packages (only if YOU choose to):")
    print('  uv pip install manifold3d "trimesh[easy]" rtree mapbox-earcut vhacdx \\')
    print("    coacd imageio imageio-ffmpeg scikit-image matplotlib pandas tqdm \\")
    print("    psutil rich tenacity")
sys.exit(1 if n_fail else 0)
PY
