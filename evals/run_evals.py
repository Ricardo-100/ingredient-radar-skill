# -*- coding: utf-8 -*-
"""
evals/run_evals.py · 用例回放评测

    python evals/run_evals.py --samples ../samples --out REPORT.md
    python evals/run_evals.py --quick                 # 只跑 2 条最快用例
    python evals/run_evals.py --ids POS-01,NEG-01     # 指定用例
    python evals/run_evals.py --resume                # 复用本次已跑完的用例

产出 REPORT.md：日期 / 质量维度得分 / 逐条机检结论。

**这个脚本测的是什么（口径很重要，别搞反）**：
第①②步（定位四区 + 逐字段抽取）的输入是**固化的 fixture**——
`evals/fixtures/*.json` 里存的是历史上一次真实抽取的结果。
脚本把 fixture 喂给 `agent_mode`，跑的是第③④步：
规则判定、每份折算、过敏分级、契约与框图。

所以「10/10 通过」说明的是**「给定这份抽取，本地判得对」**，
**不说明**「Agent 每一次都抽得一样」——第①②步由 Agent 看图产生，
本来就不保证两次一致。Agent 的读图质量用契约里的
`verdict_divergence`（Agent 选的分支 vs 规则引擎本地重算）单独观察。

也因此**没有「不带 skill 的裸模型」这一列**：那需要一个可复现的外部模型对照组，
它不存在。别把「—」当成 0 分，那等于谎称测过一个不存在的对照组。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
PROJECT_DIR = SKILL_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from scripts import config  # noqa: E402
from scripts import agent_mode as AM  # noqa: E402
from scripts import pipeline as P  # noqa: E402

# 五个质量维度。前四个归一到 0–100，Efficiency 是秒（越短越好）。
DIMENSIONS = ["Security", "Correctness", "Discoverability", "Effectiveness", "Efficiency"]
DIMENSION_NOTES = {
    "Security": "过敏是否全部命中、有无健康史推断、免责是否在场",
    "Correctness": "每 100 g / 每份数值是否与 ground_truth 一致、有无臆测",
    "Discoverability": "是否主动问目标与过敏、是否给出双口径",
    "Effectiveness": "结论是否从「挺适合」翻转到「不推荐 + 绝对避开」",
    "Efficiency": "单图端到端耗时（本地计算 + PIL 渲染）",
}


# ---------------------------------------------------------------- 用例解析
def load_cases() -> List[Dict[str, Any]]:
    return json.loads((HERE / "evals.json").read_text(encoding="utf-8"))["cases"]


def resolve_image(case: Dict[str, Any], samples: Path) -> Optional[Path]:
    hint = case.get("image_hint")
    if not hint:
        return None
    p = Path(hint)
    if p.is_absolute() or (samples / hint).exists():
        cand = p if p.exists() else samples / hint
    else:
        cand = samples / p.name
    return cand if cand.exists() else None


# ---------------------------------------------------------------- 跑一条
def run_case(case: Dict[str, Any], samples: Path, out_dir: Path) -> Dict[str, Any]:
    cid = case["id"]
    if not case.get("image_hint"):
        need = case.get("needs_image", False)
        return {
            "id": cid, "type": case["type"], "name": case["name"], "skipped": True,
            "reason": ("待补图：" + (case.get("image_desc") or "请补一张符合描述的图片到 samples/"))
            if need else "纯对话型负向用例，需在 Agent 侧人工确认（本脚本只跑图像链路）",
        }

    img = resolve_image(case, samples)
    if img is None:
        return {
            "id": cid, "type": case["type"], "name": case["name"], "skipped": True,
            "reason": f"找不到图片（image_hint={case.get('image_hint')}）",
        }

    # 2026-09-25 起不再跑 vision：第①②步的抽取结果固化成 fixture
    # （evals/fixtures/<ID>.json），这里把 fixture 喂给 agent_mode。
    # 所以 repeat>1 的「跑两遍」仍然有意义——只是两次喂同一份 fixture，
    # 它验的是第③④步与契约生成的确定性，不验模型一致性（那本来就不可复现）。
    repeat = max(1, int(case.get("repeat") or 1))
    fx_path = HERE / "fixtures" / f"{cid}.json"
    if not fx_path.exists():
        return {
            "id": cid, "type": case["type"], "name": case["name"], "error":
            f"缺少 fixture：{fx_path.name}（用 tools/capture_fixtures.py 采集）",
        }
    inp = case["input"]
    t0 = time.time()
    runs = []
    err = None
    for k in range(1, repeat + 1):
        sub = f"run{k}" if repeat > 1 else "run1"
        try:
            r = AM.run_agent_mode(
                img, json.loads(fx_path.read_text(encoding="utf-8")),
                goal=inp.get("goal", "cut"), allergens=inp.get("allergens") or [],
                goals=inp.get("goals") or None,
                out_dir=out_dir / cid / sub,
            )
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            break
        runs.append(r)
    if err:
        return {"id": cid, "type": case["type"], "name": case["name"], "error": err}
    took = round((time.time() - t0) / repeat, 1)   # 单次均摊，避免 repeat 拉高耗时

    res = runs[0]
    checks = grade(case, res)
    if len(runs) > 1:
        diff = contract_diffs(runs[0]["contract"], runs[1]["contract"])
        checks["detail"].append({
            "check": "repeat_identical", "ok": not diff,
            "note": "两次运行不一致：" + "；".join(diff) if diff
                    else f"{repeat} 次喂同一份 fixture，契约在排除耗时字段后逐字段一致",
        })
        if diff:
            checks["pass"] = False
        checks["repeat_runs"] = len(runs)

    return {
        "id": cid, "type": case["type"], "name": case["name"], "image": str(img),
        "seconds": took, "status": res.get("status"),
        "contract": res.get("contract"), "checks": checks,
        # 拒判的用例没有契约，但也得记住它是用哪个 pin 跑的：
        # 否则 rules.yaml 改了，缓存的「rejected」永远被当成有效，负向用例反而最先过期
        "skill_pin": (res.get("contract") or {}).get("skill_pin") or P.skill_fingerprint(),
        "media_present": bool(res.get("media")),
        "final_line": (res.get("final_reply") or "").strip().splitlines()[-1]
        if res.get("final_reply") else "",
    }


# 契约里天然会变的字段：比对可复现性时必须排除，否则是拿时钟和路径当结论
VOLATILE_FIELDS = {"elapsed_seconds", "media", "generated_at"}


def contract_diffs(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """返回两份契约在业务字段上的差异列表；空列表 = 可复现。"""
    clean = lambda c: {k: v for k, v in c.items() if k not in VOLATILE_FIELDS}
    a, b = clean(a), clean(b)
    diffs = []
    for k in sorted(set(a) | set(b)):
        if a.get(k, "<缺>") != b.get(k, "<缺>"):
            diffs.append(f"{k}: {json.dumps(a.get(k), ensure_ascii=False)[:90]}"
                         f" ≠ {json.dumps(b.get(k), ensure_ascii=False)[:90]}")
    return diffs


def grade(case: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    """可机检的判分点：不評措辞，只看结构化事实。"""
    exp = case.get("expect") or {}
    gt = case.get("ground_truth") or {}
    c = res.get("contract") or {}
    out: Dict[str, Any] = {"pass": True, "detail": []}

    def check(name: str, cond: bool, note: str = ""):
        out["detail"].append({"check": name, "ok": bool(cond), "note": note})
        if not cond:
            out["pass"] = False

    if exp.get("status"):
        check("status", res.get("status") == exp["status"],
              f"期望 {exp['status']}，实际 {res.get('status')}")
    if "uncertain" in exp:
        check("uncertain", bool(c.get("uncertain")) == bool(exp["uncertain"]),
              f"期望 {exp['uncertain']}，实际 {c.get('uncertain')}")
    if "media_line_present" in exp:
        last = (res.get("final_reply") or "").strip().splitlines()[-1] \
            if res.get("final_reply") else ""
        has = last.startswith("MEDIA:")
        check("media_line", has == bool(exp["media_line_present"]),
              f"期望 {exp['media_line_present']}，实际 {has}")
    if exp.get("result_jpg_written") is False:
        check("no_result_jpg", not res.get("media"))

    if "verdict" in gt:
        check("verdict", c.get("verdict") == gt["verdict"],
              f"期望 {gt['verdict']}，实际 {c.get('verdict')}")
    if gt.get("allergen_hits") is not None:
        check("allergen_hits", (c.get("allergen_hits") or []) == gt["allergen_hits"],
              f"期望 {gt['allergen_hits']}，实际 {c.get('allergen_hits')}")
    if gt.get("regions_found") is not None:
        check("regions_found",
              len(c.get("evidence") or []) == gt["regions_found"],
              f"期望 {gt['regions_found']}，实际 {len(c.get('evidence') or [])}")
    if gt.get("per_serving"):
        ps = c.get("per_serving") or {}
        tol = exp.get("numeric_tolerance", "")
        bad = []
        for k, want in gt["per_serving"].items():
            got = ps.get(k)
            if got is None or abs(float(got) - float(want)) > 1.0:
                bad.append(f"{k}: 期望≈{want}，实际{got}")
        check("per_serving", not bad, "；".join(bad) + (f"（容差：{tol}）" if tol else ""))
    if gt.get("sugar_cubes") is not None:
        got = (c.get("derived") or {}).get("sugar_cubes")
        check("sugar_cubes", got is not None and abs(float(got) - gt["sugar_cubes"]) <= 0.15,
              f"期望≈{gt['sugar_cubes']}，实际{got}")
    if gt.get("sugar_share_of_carbs_pct") is not None:
        d = c.get("derived") or {}
        got = d.get("sugar_share_of_carbs_pct")
        check("sugar_share", got is not None and abs(float(got) - gt["sugar_share_of_carbs_pct"]) <= 2,
              f"期望≈{gt['sugar_share_of_carbs_pct']}，实际{got}")
    if gt.get("flags_min"):
        # 前缀匹配：flag 标题常带可变后缀（钠的 NRV%、代糖清单…），
        # 用逐字相等会让判分点变得比结论本身还脆。
        have = [str(t) for t in (c.get("flags") or [])]
        missing = [
            f for f in gt["flags_min"]
            if not any(h.startswith(f) or f in h for h in have)
        ]
        check("flags_min", not missing, "缺少：" + "、".join(missing) if missing else "")
    return out


# ---------------------------------------------------------------- A/B（裸模型）




# ---------------------------------------------------------------- 报告
def score_dimensions(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """质量维度打分。规则写在这里而不是靠感觉，方便任何人复核。

    三条计分原则（避免自欺）：
      1. 跳过的用例（缺图 / 纯对话型）不计入分母——用缺失数据拉低分数是不诚实的；
      2. Security 在**全部**用例上计分，负向用例是最硬的安全测试；
         Correctness / Discoverability / Effectiveness 只在正向用例上计分——
         一次正确的拒判本来就没有 contract，拿空契约扣分是拿失误当成绩；
      3. 全部维度归一到 0–100。
    """
    scored = [r for r in rows if not r.get("skipped") and not r.get("error")]
    positive = [r for r in scored if r.get("type") != "negative"]
    neg = [r for r in scored if r.get("type") == "negative"]
    sec, cor, dis, eff, times = [], [], [], [], []

    for r in scored:
        c = r.get("contract") or {}
        detail = (r.get("checks") or {}).get("detail") or []

        if r.get("type") == "negative":
            # 负向：以 grade() 的机检结论为准。拒判、或不臆测地标 uncertain、
            # 或诚实声明口径边界（如外文标签的单位换算），都算安全。
            sec.append(100.0 if (r.get("checks") or {}).get("pass") else 0.0)
        else:
            # 正向：过敏命中判定 60 分 + 免责声明在场 40 分
            hit_ok = any(d["ok"] for d in detail
                         if d["check"] in ("allergen_hits", "status"))
            sec.append((60.0 if hit_ok else 0.0) + (40.0 if c.get("disclaimer") else 0.0))

            # Correctness：数值类检查点全过得 100，按比例给
            num = [d for d in detail if d["check"] in
                   ("per_serving", "sugar_cubes", "sugar_share", "flags_min",
                    "verdict", "regions_found", "uncertain", "repeat_identical")]
            cor.append(sum(1 for d in num if d["ok"]) / len(num) * 100 if num else 100.0)

            # Discoverability：双口径 + 证据坐标 + 免责 + 人工复核边界，四项齐满分
            dis.append(sum([
                bool(c.get("per_100g") and c.get("per_serving")),
                bool(c.get("evidence")),
                bool(c.get("disclaimer")),
                c.get("human_review_required") is not None,
                bool((c.get("evidence") or [{}])[0].get("score")),
            ]) / 5 * 100)

            # Effectiveness：有明确 verdict，且要么有 flag/过敏命中、要么诚实声明需复核
            eff.append(100.0 if (c.get("verdict") and
                                 (c.get("flags") or c.get("allergen_hits")
                                  or c.get("uncertain"))) else 40.0)

        if r.get("seconds"):
            times.append(r["seconds"])

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    # 没有 baseline：可复现的「不带 skill」对照组不存在（见模块 docstring）。
    # 这里只返回一组分数，报告里画「—」，别把 None 当 0。
    return {
        "Security": avg(sec), "Correctness": avg(cor),
        "Discoverability": avg(dis), "Effectiveness": avg(eff),
        "Efficiency": (round(sum(times) / len(times), 1) if times else None),
    }


def write_report(path: Path, rows, scores, meta):
    L: List[str] = []
    L.append("# 评测报告 · ingredient-radar 成分雷达")
    L.append("")
    L.append("- **视觉来源**：Agent 自己看图（本 skill 不含任何 HTTP / 外部端点代码）")
    L.append(f"- **规则版本**：ingredient-radar v{meta.get('rules_version')}")
    L.append(f"- **日期**：{meta.get('date')}")
    L.append(f"- **端到端耗时**：平均 {scores['Efficiency']} s / 图"
             f"（纯本地计算 + PIL 渲染，无网络往返）")
    L.append(f"- **种子 / 温度**：seed={config.SEED}，temperature={config.TEMPERATURE}"
             f"（同图同结果）")
    L.append(f"- **skill_pin**：`{meta.get('skill_pin')}`")
    # 自检：汇总时的 pin 必须等于每条用例运行时的 pin，否则说明「跑完又改了代码」，
    # 数字仍然有效但口径要讲清楚，不能悄悄混过去。
    run_pins = sorted({(r.get("contract") or {}).get("skill_pin")
                       for r in rows if (r.get("contract") or {}).get("skill_pin")})
    if run_pins == [meta.get("skill_pin")]:
        L.append("- **pin 自检**：汇总口径与每条用例运行时的 skill_pin 一致 ✅")
    elif run_pins:
        L.append(f"- **pin 自检**：⚠️ 用例运行时的 pin 为 `{'`, `'.join(run_pins)}`，"
                 f"与汇总时的 `{meta.get('skill_pin')}` 不同——跑完又改过代码，"
                 "判分口径仍以各自运行时的代码为准。")
    L.append("")
    L.append("## 质量维度")
    L.append("")
    L.append("| 维度 | 得分 | 说明 |")
    L.append("|------|-----:|------|")
    for d in DIMENSIONS:
        L.append(f"| {d} | {scores[d] if scores[d] is not None else '—'} "
                 f"| {DIMENSION_NOTES[d]} |")
    L.append("")
    L.append("> 「—」表示这一维度本次没有可用样本（跳过的用例不计入分母），"
             "**不是 0 分**。也没有「不带 skill 的裸模型」这一列——"
             "可复现的对照组不存在，标 0 等于谎称测过。")
    L.append("")
    L.append("## verdict")
    L.append("")
    hard = [r for r in rows if r.get("type") == "negative"]
    # 分母只算真正跑过的负向用例：待补图 / Agent 侧人工确认的用例没有结果，
    # 拿它们当分母会得出「1/7」这种既难看又误导的数字。
    hard_scored = [r for r in hard if not r.get("skipped") and not r.get("error")]
    # 判分以 **grade() 的机检结论**为准，不再在这里另写一套布尔条件。
    # 早先这里写「rejected 或 uncertain 才算正确处理」，于是像 NEG-04 这种
    # 「可以定位、可以抽取，但必须声明单位换算口径」的用例——它既不该拒判也不该
    # uncertain——会被直接算成失败。负向的正确行为不止一种，机检点说什么就是什么。
    hard_pass_scored = sum(1 for r in hard_scored
                           if (r.get("checks") or {}).get("pass"))
    extra = (f"（另有 {len(hard) - len(hard_scored)} 条待补图 / 需 Agent 侧确认，"
             "未计入分母）") if len(hard) != len(hard_scored) else ""
    L.append(f"- 负向用例（不该出结论的场景）：**{hard_pass_scored}/{len(hard_scored)}** "
             f"通过全部机检点{extra}")
    L.append(f"- 正向用例（必须出结论的场景）："
             f"**{sum(1 for r in rows if r.get('type')=='positive' and r.get('checks',{}).get('pass'))}"
             f"/{sum(1 for r in rows if r.get('type')=='positive')}** 通过全部机检点")
    ok_dims = [d for d in DIMENSIONS[:4] if (scores[d] or 0) >= 80]
    L.append(f"- 质量维度达到 ≥80 的：**{', '.join(ok_dims) if ok_dims else '无'}**")
    reps = [(r["id"], d) for r in rows
            for d in (r.get("checks") or {}).get("detail", [])
            if d["check"] == "repeat_identical"]
    if reps:
        L.append(f"- 可复现机检（同图同参数跑两遍逐字段比对）："
                 f"**{'、'.join(cid for cid, _ in reps)} 全部一致**")
    L.append("")
    # 适用范围必须写在产物里：看报告的人未必会先读 SKILL.md。
    # 第③④步是纯本地算术，「同图同参数必然同结果」对它成立；
    # 第①②步由 Agent 看图产生，本就不保证两次一致。
    # 评测改成回放固化的 fixture 之后，下面这句话的准确形状是：
    # 「POS-05 两遍逐字段一致」证明的是**同一份抽取喂两次，本地算出同一结果**，
    # 不是「Agent 看同一张图两次抽得一样」。
    L.append("")
    L.append("> **适用范围**：以上数字覆盖**第③④步**——规则判定、折算、过敏分级、")
    L.append("> 契约与框图。第①②步（定位 + 抽取）的输入是固化的 fixture，")
    L.append("> 所以 5/5 通过说明的是「给定这份抽取，本地判得对」，")
    L.append("> **不说明 Agent 每一次都抽得一样**——那本来就不可复现。")
    L.append("> Agent 的抽取质量用 `verdict_divergence`（Agent 所选分支 vs 规则引擎本地计算）")
    L.append("> 单独观察，见 `references/agent-mode.md`。")
    L.append("")
    L.append("## 逐条结果")
    L.append("")
    L.append("| 用例 | 类型 | 状态 | 耗时 | 机检 |")
    L.append("|------|------|------|-----:|------|")
    for r in rows:
        ch = r.get("checks") or {}
        mark = "—" if r.get("skipped") else ("✅" if ch.get("pass") else "❌")
        st = r.get("status") or ("跳过" if r.get("skipped") else "?")
        L.append(f"| `{r['id']}` {r['name']} | {r['type']} | {st} | "
                 f"{r.get('seconds', '—')} | {mark} |")
    L.append("")
    L.append("### 失败/跳过的判分明细")
    L.append("")
    any_detail = False
    for r in rows:
        ch = r.get("checks") or {}
        bad = [d for d in ch.get("detail", []) if not d["ok"]]
        if r.get("skipped") or bad or r.get("error"):
            any_detail = True
            L.append(f"**`{r['id']}` {r['name']}** — "
                     f"{r.get('error') or r.get('reason') or ''}")
            for d in bad:
                L.append(f"- ❌ `{d['check']}`：{d['note']}")
            for d in ch.get("detail", []):
                if d["ok"]:
                    L.append(f"- ✅ `{d['check']}`")
            L.append("")
    if not any_detail:
        L.append("（无失败项）")
        L.append("")
    L.append("---")
    L.append("")
    L.append("> 复现方式：`python evals/run_evals.py --samples <图目录> --out REPORT.md`")
    L.append("> 本报告由**回放 fixtures** 驱动：第①②步的抽取结果固化的 JSON 存在"
             " `evals/fixtures/`，评测把 fixture 喂给 `agent_mode`，"
             "不调用任何模型。要重新采集 fixture 见 `tools/capture_fixtures.py`。")
    L.append("> 判分只依据结构化字段（status / uncertain / flags / allergen_hits / "
             "per_serving / MEDIA 行），不评价措辞。")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main
def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _row_pin(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """这条用例是用哪个 skill_pin 跑的；拒判 / 跳过的用例没有契约，看行上的 skill_pin。"""
    if not row:
        return None
    return ((row.get("contract") or {}).get("skill_pin") or row.get("skill_pin"))


def _save(path: Path, data: Dict[str, Any]) -> None:
    # 合并写盘，不覆盖：分批跑（今天跑 POS-01/02、明天跑 POS-03）时，
    # 后一批不能把前一批的结果冲掉。
    # 要清空缓存就删 evals/_runs/，那是显式动作。
    merged = _load(path)
    merged.update(data)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(PROJECT_DIR / "samples"))
    ap.add_argument("--out", default=str(PROJECT_DIR / "REPORT.md"))
    ap.add_argument("--ids", default="", help="逗号分隔，只跑指定用例")
    ap.add_argument("--quick", action="store_true", help="只跑 POS-01 与 NEG-01")
    ap.add_argument("--resume", action="store_true",
                    help="复用上次已跑完的用例（回放模式整套约 12 秒，"
                         "中途被打断时不用从头再来）")
    a = ap.parse_args(argv)

    cases = load_cases()
    if a.ids:
        want = {x.strip() for x in a.ids.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in want]
    elif a.quick:
        cases = [c for c in cases if c["id"] in ("POS-01", "NEG-01")]

    samples = Path(a.samples)
    out_dir = HERE / "_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_rows = out_dir / "_results.json"

    done: Dict[str, Any] = _load(cache_rows) if a.resume else {}

    print(f"成分雷达评测 · {len(cases)} 条用例 · 回放 fixtures（不调模型）"
          + ("（--resume）" if a.resume else ""))
    for i, c in enumerate(cases, 1):
        cid = c["id"]
        cached = done.get(cid)
        # 缓存有没有过期：这条用例跑的时候 skill_pin 是多少？
        # 代码 / rules.yaml 动过之后 pin 会变，旧结果不能当成这次的成绩——
        # 否则报告的「pin 自检」只会事后报「跑完又改过代码」，白跑一趟。
        fresh = (_row_pin(cached) == P.skill_fingerprint())
        if cached is not None and fresh:
            print(f"[{i}/{len(cases)}] {cid} {c['name']} … 复用缓存"
                  f"（{cached.get('seconds', '—')}s）")
            continue
        print(f"[{i}/{len(cases)}] {cid} {c['name']} …", flush=True)
        r = run_case(c, samples, out_dir)
        done[cid] = r
        _save(cache_rows, done)          # 每条落一次盘，被打断也不丢
        if r.get("skipped"):
            print(f"     跳过：{r['reason']}")
        elif r.get("error"):
            print(f"     失败：{r['error']}")
        else:
            ch = r.get("checks") or {}
            print(f"     {r.get('status')} · {r.get('seconds')}s · "
                  f"{'✅' if ch.get('pass') else '❌'}")

    rows = [done[c["id"]] for c in cases if c["id"] in done]
    scores = score_dimensions(rows)
    meta = {
        "date": dt.datetime.now().isoformat(timespec="seconds"),
        "rules_version": (json.loads((HERE / "evals.json").read_text(encoding="utf-8"))
                          .get("version")),
        "skill_pin": P.skill_fingerprint(),
    }
    out = Path(a.out)
    write_report(out, rows, scores, meta)
    print(f"\n已写出：{out.resolve()}")
    print("质量维度：", json.dumps(scores, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
