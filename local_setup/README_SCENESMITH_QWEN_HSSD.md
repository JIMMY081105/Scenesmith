# SceneSmith — Minimal Qwen + HSSD Furniture Pipeline (local notes)

These notes describe a **minimal, reproducible** SceneSmith run on Windows 11 + WSL
Ubuntu that uses Alibaba Qwen (via the DashScope OpenAI-compatible API) for the LLM
agents and **HSSD retrieval only** for assets. The pipeline is intentionally stopped
at the furniture stage.

## Goal

One prompt, one minimal scene:

```
A small office room with one desk and one office chair.
```

Pipeline used:

```
text prompt → floor plan → room geometry → furniture stage → HSSD asset retrieval → STOP
```

We deliberately do **not** run full text-to-3D generation:

- No SAM3D / Hunyuan3D / generated-asset path.
- No full Objaverse / full HSSD download (HSSD meshes are pulled **one GLB at a time**, on demand).
- No articulated objects, no materials/thin-covering stage.

## Why Qwen needs Chat Completions mode

The OpenAI Agents SDK defaults to the **Responses API**. Qwen's OpenAI-compatible
endpoint does not support that path the same way and fails with:

```
result_format parameter must be "message" when enable_thinking is true
```

So `main.py` forces Chat Completions and disables tracing before any agent runs:

```python
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)
```

This is already patched in `main.py`.

## Why the API key must be entered every new WSL session

After `wsl --shutdown` (or opening a fresh shell), exported environment variables are
gone. A run that relies on a previously-exported key will fail with:

```
Missing credentials ... set the OPENAI_API_KEY environment variable
```

Therefore `local_setup/setup_env.sh` prompts for the DashScope key with `read -s`
**every time you source it**. The key is never written to any file and never printed —
only its length is shown. We map it onto the OpenAI-compatible variables:

```bash
export DASHSCOPE_API_KEY=<entered>
export OPENAI_API_KEY="$DASHSCOPE_API_KEY"
export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## Why the WSL localhost proxy warning is OK

This machine routes outbound traffic through a Windows proxy. WSL needs the proxy set
manually each session:

```bash
WIN_HOST=$(ip route | awk '/default/ {print $3}')
export ALL_PROXY="socks5h://${WIN_HOST}:10818"
export all_proxy="socks5h://${WIN_HOST}:10818"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
```

`setup_env.sh` exports these for you. With `NO_PROXY` covering `127.0.0.1,localhost`,
the local Flask servers (HSSD retrieval, Blender render, convex decomposition) talk to
each other directly. The **WSL localhost proxy warning is expected** in this setup and
can be ignored — the manual exports above are what actually route traffic.

## Why HSSD-only (and how on-demand download works)

We want a fast, low-memory path that does not require GPU 3D generation or large
checkpoints. HSSD retrieval picks an existing mesh per furniture request.

- `furniture_agent.asset_manager.general_asset_source=hssd` selects HSSD.
- `furniture_agent.asset_manager.router.enabled=false` takes the **non-router** path,
  which dispatches straight to `_retrieve_hssd_assets` (no generated / articulated /
  thin-covering strategies are ever tried).
- When a single HSSD GLB is missing locally, `data_loader.py` downloads exactly that
  one file:

  ```bash
  hf download hssd/hssd-models objects/<first_char>/<mesh_id>.glb \
      --repo-type dataset --local-dir data/hssd-models
  ```

  This is **one mesh at a time** — never the full dataset. (You must have authenticated
  to Hugging Face for `hssd/hssd-models` at least once.)

### Servers / ports in this minimal run

| Server                | Port        | Used here? |
|-----------------------|-------------|------------|
| HSSD retrieval        | `7006`      | yes        |
| Blender render        | `8000–8350` | yes        |
| Convex decomposition  | `7100+`     | yes        |
| Articulated retrieval | `7007`      | **no** (skipped) |
| Materials retrieval   | —           | **no** (skipped) |
| Geometry generation   | `7005`      | **no** (skipped) |

The articulated and materials servers are intentionally **not started** (commented out
in `scenesmith/experiments/indoor_scene_generation.py`).

## Files in this folder

| File | What it does |
|------|--------------|
| `setup_env.sh` | `source` it: activates `.venv`, prompts for the DashScope key, exports OpenAI-compatible + proxy vars, gives a `test_qwen_api` helper. |
| `check_deps.sh` | Import-tests the packages this pipeline needs and prints OK/FAIL. Installs nothing. |
| `run_hssd_furniture.sh` | Runs the minimal HSSD-only furniture pipeline (assumes you've sourced `setup_env.sh`). |
| `README_SCENESMITH_QWEN_HSSD.md` | This file. |

## Operations / troubleshooting

Check memory and swap (run #4 once died loading OpenCLIP weights — `Killed` — due to
low memory; swap has since been increased):

```bash
free -h
```

See which relevant processes are running:

```bash
ps aux | grep -E "main.py|python|blender|hssd|floor_plan" | grep -v grep
```

Tail the most recent run's log live (`latest-run` is a symlink that `main.py`
points at the current run, so this needs no date/glob):

```bash
tail -f outputs/latest-run/experiment.log
```

Fallback if the symlink is stale (e.g. an interrupted run) — pick today's newest
run explicitly:

```bash
LATEST=$(ls -td outputs/$(date +%Y-%m-%d)/* | head -1)
tail -f "$LATEST/experiment.log"
```

Kill a leftover HSSD server holding port 7006 (e.g. after a crashed run):

```bash
kill -9 $(lsof -t -i :7006) 2>/dev/null || true
```

## Typical session

```bash
cd ~/research/scenesmith-main
chmod +x local_setup/*.sh
source local_setup/setup_env.sh     # prompts for DashScope key (every session)
test_qwen_api                        # optional: confirms Qwen responds
bash local_setup/check_deps.sh       # confirms imports
bash local_setup/run_hssd_furniture.sh
```

Monitor:

```bash
tail -f outputs/latest-run/experiment.log
```

If it fails, collect:

```bash
tail -n 120 outputs/latest-run/experiment.log
```

Fallback (stale symlink — newest run of today):

```bash
LATEST=$(ls -td outputs/$(date +%Y-%m-%d)/* | head -1)
tail -n 120 "$LATEST/experiment.log"
```
