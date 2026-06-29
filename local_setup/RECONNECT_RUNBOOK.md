# 重启后恢复 Runbook — paracloud / SceneSmith

固定事实(已实测):
- 登录节点 `ln08`,用户 `scvj260`,项目 `~/projects/scenesmith`,venv `~/projects/scenesmith/.venv`
- GPU 作业 `162857` → 节点 `m4gn1601`,**RTX 5090 / 32GB**,作业时限 3 天
- **VPN**:mihomo 一直跑在 `ln08`(tmux 里,持久)。计算节点用 `http://ln08:7890` 即可翻墙(实测 200)
- **HF 镜像**:`https://hf-mirror.com`;**uv 超时**:`UV_HTTP_TIMEOUT=600`

> ⚠️ 两条铁律:
> 1. **`ln08` 会杀掉 >4 核的进程** → 装包、跑 main.py 等所有重活只在**计算节点**做。
> 2. VPN 在服务器上常驻,**电脑重启不影响它**,你只需把环境变量指过去。

---

## ① 本地 → SSH 登录
```bash
ssh scvj260@<你的paracloud登录地址>
```

## ② 在 ln08 → 拿/进 GPU 节点
```bash
squeue -u $USER
JOB=$(squeue -u $USER -h -t R -o "%i" | head -1); echo "JOB=$JOB"
```
- `JOB` 有值 → 进去:
```bash
srun --jobid=$JOB --overlap --pty bash
hostname    # 必须是 m4gn1601;若还是 ln08 = 没进去
```
- `JOB` 为空(作业没了)→ 重新申请(**不要加 --mem**),进去后到③:
```bash
srun -p gpu --qos=gpugpu -A scvj260 --gres=gpu:1 --cpus-per-task=8 -t 1-00:00:00 --pty bash
```

## ③ 在计算节点 → 一键设环境
```bash
source local_setup/compute_node_env.sh
```
(自动:激活 venv + 设 VPN 代理 ln08:7890 + HF 镜像 + uv 超时;会拒绝在 ln08 上运行)

## ④ 仅首次 / torch 没装好时 → 装包 + 验 GPU(只在计算节点!)
```bash
uv sync --no-dev        # 等到 "Installed N packages in ..." 再停
python -c "import torch; print('ver', torch.__version__, '| cuda', torch.version.cuda); x=torch.randn(1000,device='cuda'); print('GPU OK:', float((x*2).sum()))"
```
- 打印 `GPU OK: <数字>` → 环境就绪。
- 报 `no kernel image is available` → torch 太老不认 5090,需换 cu128 新版 torch。

## ⑤ 跑场景(设好 API key 再跑)
**ChatGPT(走 VPN,论文级模型,按 token 计费):**
```bash
export OPENAI_API_KEY=sk-...你的OpenAI key...
# 默认模型就是 gpt-5.2,无需额外覆盖
python main.py +name=room_gpt
```
**Qwen(直连,便宜):**
```bash
export OPENAI_API_KEY=<dashscope key>
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
bash local_setup/run_hssd_furniture.sh     # 或带 qwen-plus 覆盖的 main.py
```

---

## 一句话
登录 ln08 → `--overlap` 进 m4gn1601 → `source local_setup/compute_node_env.sh` → (首次)`uv sync` → 跑。**重活永远不在 ln08。**
