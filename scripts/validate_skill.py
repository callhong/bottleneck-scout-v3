#!/usr/bin/env python3
"""Validate the bottleneck-scout-v3 skill project."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


REQUIRED_FILES = [
    "SKILL.md",
    "agents/openai.yaml",
    "references/router.md",
    "references/value-chain-types.md",
    "references/evidence-gate.md",
    "references/chokepoint-gate.md",
    "references/red-team.md",
    "references/cross-check.md",
    "references/graph-edges.md",
    "references/source-playbook.md",
    "references/report-template.md",
    "references/output-standards.md",
    "references/provenance.md",
    "references/third-party-notices.md",
    "scripts/data_sources/__init__.py",
    "scripts/data_sources/errors.py",
    "scripts/data_sources/a_stock.py",
    "scripts/fetch_a_stock_data.py",
    "scripts/test_a_stock_data.py",
    "scripts/validate_skill.py",
    "scripts/validate_report.py",
    "scripts/graph_edges.py",
    "scripts/compare_old_v2.py",
    "scripts/create_report_skeleton.py",
    "scripts/evidence_matrix.py",
    "scripts/freshness_check.py",
    "scripts/price_position.py",
    "scripts/render_pdf.py",
    "scripts/validate_router.py",
    "scripts/validate_pdf_layout.py",
    "scripts/valuation_rating.py",
]

FORBIDDEN_PATTERNS = [
    r"必须模仿\s*Serenity",
    r"以\s*Serenity\s*身份",
    r"按\s*Kelly\s*(?:公式|仓位)",
    r"建议仓位\s*[:：]",
    r"买入\s*\d+成",
    r"卖出\s*\d+成",
    r"粉丝数.*作为.*证据",
    r"KOL 热度.*(?:可作为|直接作为|用于).*核心推荐",
]

REQUIRED_TERMS = [
    "瓶颈侦察v3",
    "价值传导链",
    "Evidence Gate",
    "Chokepoint",
    "Red-team",
    "Cross-check",
    "Direct",
    "Corroborated",
    "Framework Inference",
    "Unsupported",
    "直接证据",
    "交叉印证",
    "框架推演",
    "待核验/线索级",
    "无支撑",
    "A/H/US",
    "投资标的分析",
    "不要 PDF",
    "事件快评",
    "复盘验证",
    "深度瓶颈研报",
    "交付QA",
    "默认单 agent",
    "a-stock-data",
    "fetch_a_stock_data.py",
    "third-party-notices",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_simple_yaml(text: str) -> dict[str, object]:
    """Parse the small YAML subset used by SKILL.md and agents/openai.yaml."""
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if not value:
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        elif value.lower() == "true":
            parent[key] = True
            continue
        elif value.lower() == "false":
            parent[key] = False
            continue
        parent[key] = value
    return root


def validate_frontmatter(root: Path, errors: list[str]) -> None:
    skill_md = root / "SKILL.md"
    content = read_text(skill_md)
    match = re.match(r"^---\n(.*?)\n---", content, re.S)
    if not match:
        errors.append("SKILL.md frontmatter missing or malformed")
        return
    frontmatter = parse_simple_yaml(match.group(1))
    if frontmatter.get("name") != "bottleneck-scout-v3":
        errors.append("frontmatter name must remain hyphen-case: bottleneck-scout-v3")
    metadata = frontmatter.get("metadata") or {}
    if metadata.get("display_name") != "瓶颈侦察v3":
        errors.append("metadata.display_name must be 瓶颈侦察v3")
    description = str(frontmatter.get("description", ""))
    if len(description) < 120:
        errors.append("frontmatter description is too short for reliable triggering")


def validate_openai_yaml(root: Path, errors: list[str]) -> None:
    config = parse_simple_yaml(read_text(root / "agents/openai.yaml"))
    interface = config.get("interface", {})
    if interface.get("display_name") != "瓶颈侦察v3":
        errors.append("agents/openai.yaml display_name must be 瓶颈侦察v3")
    prompt = interface.get("default_prompt", "")
    if "$bottleneck-scout-v3" not in prompt:
        errors.append("default_prompt must mention $bottleneck-scout-v3")
    short = interface.get("short_description", "")
    if not (25 <= len(short) <= 64):
        errors.append("short_description must be 25-64 characters")


def validate_references(root: Path, errors: list[str]) -> None:
    all_text = "\n".join(read_text(path) for path in root.rglob("*.md"))
    for term in REQUIRED_TERMS:
        if term not in all_text:
            errors.append(f"required term missing: {term}")
    skill_text = read_text(root / "SKILL.md")
    for ref in REQUIRED_FILES:
        if ref.startswith("references/") and ref not in skill_text:
            name = Path(ref).name
            if name not in skill_text:
                errors.append(f"SKILL.md does not reference {ref}")
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, all_text, flags=re.I):
            errors.append(f"forbidden pattern present: {pattern}")


def validate_git(root: Path, errors: list[str]) -> None:
    if not (root / ".git").exists():
        errors.append("skill project is not initialized as a git repo")
        return
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--short"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        errors.append(f"git status failed: {result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("--skip-git", action="store_true")
    args = parser.parse_args()

    root = args.skill_dir.resolve()
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            errors.append(f"missing required file: {rel}")

    if not errors:
        validate_frontmatter(root, errors)
        validate_openai_yaml(root, errors)
        validate_references(root, errors)
        if not args.skip_git:
            validate_git(root, errors)

    if errors:
        print("VALIDATE_SKILL_FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("VALIDATE_SKILL_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
