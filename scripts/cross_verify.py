#!/usr/bin/env python3
"""多模型独立核验 —— 发散 / 红队 / 接地三模式，并行执行。

它不是事实判官：模型不联网、记忆滞后，所以**不要让它凭记忆断言时效性事实**
（份额、价格、认证、进链）。它只发挥推理多样性：

- `--diverge`  发散：对主题提出候选卡点假设 + 必须为真的离散事实 + 待验证项。
- `--redteam`  红队（默认）：对一个结论找最强反证、断点和必须用一手证据核验的清单。
- `--evidence FILE`  接地：只依据提供的原文判断是否支持某结论，逐条引用。

声音来源（自动探测、并行调用、单个失败/额度用尽自动跳过、能整体降级）：

默认尽量都用上 ——
1. OpenCode Go API 面板（有 config/opencode.env 密钥时）：DeepSeek / Qwen / MiniMax 等。
2. 已安装的兄弟 CLI（自动探测，无需开关）：claude -p / codex exec，零额外密钥的第二意见。
3. 都没有 → 不报错，打印成"待人工/主 agent 核验的清单"。

不投票。并列各家结论与分歧，最终按证据强度裁决（见 references/cross-check.md）。
某个模型调用失败或订阅额度用尽时，该声音自动缺位，不影响其余结果。

用法：
    python3 scripts/cross_verify.py --diverge "AI 服务器电源谁最卡"
    python3 scripts/cross_verify.py --redteam "公司X在卡点Y份额≥90%"
    python3 scripts/cross_verify.py --evidence snapshot.txt "公司X披露了该业务收入"
    python3 scripts/cross_verify.py --no-cli "..."     # 只用 OpenCode 模型，不调兄弟 CLI
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://opencode.ai/zen/go/v1"

# 模型 -> 协议风格。"openai"=/chat/completions，"anthropic"=/messages。
MODELS = {
    "deepseek-v4-pro": "openai",
    "qwen3.7-max": "anthropic",
    "minimax-m3": "anthropic",
}

API_TIMEOUT = 60
CLI_TIMEOUT = 120

SYSTEM = {
    "redteam": (
        "你是独立的研究质询者。不要凭记忆断言份额、价格、认证、进链等时效性事实。"
        "针对给定结论，输出：1) 最强反方论点与该结论最可能断裂的环节；"
        "2) 必须用一手证据证实的离散事实清单，每条注明该去哪种来源（公告/年报/交易所/监管/行业数据）；"
        "3) 逻辑漏洞或被高估的假设。不要给投资建议。"
    ),
    "diverge": (
        "你是瓶颈研究的发散伙伴。针对给定主题，独立提出："
        "1) 真正的卡点可能在哪几个节点（产能/工艺/认证/客户/资源/标准/数据优势）；"
        "2) 每个候选要成立必须为真的离散事实，以及用什么一手来源验证；"
        "3) 多头与空头各自最强的一句话。只给候选假设与待验证项，不下结论、不凭记忆断言事实。"
    ),
    "evidence": (
        "你是接地核验者。只依据下面提供的【证据文本】判断它是否支持【待核验结论】。"
        "逐条引用证据原文中的支持句或反对句；证据未覆盖的部分明确写“文本未覆盖”。"
        "不要用文本之外的记忆补充，不要给投资建议。"
    ),
}


def load_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if key:
        return key
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(os.path.dirname(here), "config", "opencode.env")
    try:
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("#") or "OPENCODE_API_KEY" not in line:
                    continue
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val.strip()
    except FileNotFoundError:
        pass
    return ""


def _api_request(url: str, body: dict, key: str, anthropic: bool) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "bottleneck-scout-v3-cross-verify/2.0",
        "Accept": "application/json",
    }
    if anthropic:
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} {exc.reason} | {detail}") from None


def call_api_model(model: str, style: str, key: str, system: str, user: str) -> str:
    if style == "openai":
        data = _api_request(
            f"{BASE}/chat/completions",
            {"model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}]},
            key, anthropic=False)
        return data["choices"][0]["message"]["content"]
    data = _api_request(
        f"{BASE}/messages",
        {"model": model, "max_tokens": 1500, "system": system,
         "messages": [{"role": "user", "content": user}]},
        key, anthropic=True)
    return "".join(b.get("text", "") for b in data.get("content", []))


def call_cli(binary: str, system: str, user: str) -> str:
    prompt = f"{system}\n\n---\n{user}"
    cmd = {
        "claude": [binary, "-p", prompt],
        "codex": [binary, "exec", prompt],
    }[os.path.basename(binary)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT)
    out = (proc.stdout or "").strip()
    if not out and proc.returncode != 0:
        raise RuntimeError((proc.stderr or "CLI 无输出").strip()[:300])
    return out


def detect_host() -> str:
    """尽力识别当前宿主 CLI，便于叫"另一个"做第二意见。"""
    env = os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if env.get("CODEX_SANDBOX") or env.get("CODEX_SANDBOX_NETWORK_DISABLED"):
        return "codex"
    return ""


def build_voices(key: str, models: list[str], use_cli: bool):
    """返回 [(name, callable)]，并行调用。"""
    voices = []
    if key:
        for model in models:
            style = MODELS.get(model)
            if style:
                voices.append((f"api:{model}",
                               lambda s, u, m=model, st=style: call_api_model(m, st, key, s, u)))
    if use_cli:
        host = detect_host()
        for name in ("claude", "codex"):
            if name == host:
                continue
            path = shutil.which(name)
            if path:
                voices.append((f"cli:{name}", lambda s, u, p=path: call_cli(p, s, u)))
    return voices


def run_parallel(voices, system: str, user: str) -> list[tuple[str, str, bool]]:
    results: dict[str, tuple[str, bool]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(voices))) as pool:
        futs = {pool.submit(fn, system, user): name for name, fn in voices}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = (fut.result().strip(), True)
            except Exception as exc:  # noqa: BLE001
                results[name] = (f"[调用失败] {exc}", False)
    return [(name, *results[name]) for name, _ in voices]


def main() -> int:
    p = argparse.ArgumentParser(description="多模型独立核验（发散/红队/接地，并行）")
    p.add_argument("prompt", nargs="*", help="主题或待核验结论")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--diverge", action="store_true", help="发散：列候选卡点与待验证项")
    mode.add_argument("--redteam", action="store_true", help="红队（默认）：找反证与核验清单")
    p.add_argument("--evidence", metavar="FILE", help="接地：只读该原文判断是否支持结论")
    p.add_argument("--no-cli", action="store_true",
                   help="不调用兄弟 CLI（默认会自动用上已装的 Codex/Claude Code）")
    p.add_argument("--models", help="覆盖默认模型，逗号分隔")
    args = p.parse_args()

    prompt = " ".join(args.prompt).strip() or sys.stdin.read().strip()
    if not prompt:
        print("用法: cross_verify.py [--diverge|--redteam|--evidence FILE] '主题/结论'", file=sys.stderr)
        return 2

    if args.evidence:
        mode_name = "evidence"
        try:
            with open(args.evidence, encoding="utf-8") as fh:
                evidence_text = fh.read()
        except OSError as exc:
            print(f"读取证据文件失败: {exc}", file=sys.stderr)
            return 2
        user = f"【待核验结论】: {prompt}\n\n【证据文本】:\n{evidence_text[:12000]}"
    elif args.diverge:
        mode_name = "diverge"
        user = f"【主题】: {prompt}"
    else:
        mode_name = "redteam"
        user = f"【待核验结论】: {prompt}"
    system = SYSTEM[mode_name]

    key = load_key()
    models = [m.strip() for m in args.models.split(",")] if args.models else list(MODELS)
    # 默认尽量都用上：有 OpenCode 密钥就用那几个模型，装了 Codex/Claude 就自动叠加。
    voices = build_voices(key, models, use_cli=not args.no_cli)

    label = {"diverge": "发散", "redteam": "红队", "evidence": "接地"}[mode_name]
    if not voices:
        print(f"# 交叉验证（{label}）— 当前无可用模型声音")
        print("没有 OpenCode 密钥，也没探测到 Codex/Claude。按 cross-check.md 降级：以下作为待核验清单，")
        print("由主 agent 联网取一手证据后再判定，高风险结论先降级为 待验证/弹性关注。\n")
        print(user)
        return 0

    print(f"# 交叉验证（{label}）· {len(voices)} 个独立声音 · 并行 · 不投票")
    print(f"输入：{prompt}\n")
    for name, text, ok in run_parallel(voices, system, user):
        print(f"\n===== {name} {'' if ok else '（缺位，按降级处理）'} =====")
        print(text)
    print("\n---")
    print("合并去重与裁决交由主 agent：分歧只表示该回到一手证据，按证据强度链裁决，不做模型投票。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
