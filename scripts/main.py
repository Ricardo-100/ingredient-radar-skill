# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
成分雷达 · 命令行入口

    python scripts/main.py <图片> [--goal cut] [--allergen 花生 --allergen 乳]

其它常用参数：
    --json            只打印契约 JSON（管道友好）
    --no-media        不渲染 result.jpg（只看判定，省一次 PIL）
    --probe           本地环境自检（规则表 / 依赖 / skill_pin，不联网）
    --dump-agent-template  打印 Agent 模式的空白 JSON 模板
    --verbose         打印每一步耗时

第①②步（定位四区 + 逐区抽取）由 **Agent 自己看图** 产出 JSON 交给 --agent-json，
本 skill 不调用任何外部推理端点。零第三方依赖（除 Pillow）；Python 3.8+。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让自己作为「scripts 包」被导入，从任何工作目录都能直接跑
_HERE = Path(__file__).resolve().parent
_SKILL = _HERE.parent
sys.path.insert(0, str(_SKILL))

from scripts import agent_mode as AM  # noqa: E402
from scripts import config  # noqa: E402
from scripts import pipeline as P  # noqa: E402
from scripts import profile as PR  # noqa: E402


def _parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="ingredient-radar",
        description="拍一张配料表，按你的健身目标判定该不该吃（本地推理 · 可复现 · 禁推断）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/main.py samples/label.jpg --goal cut --allergen 花生\n"
            "  python scripts/main.py samples/label.jpg --goal keto --allergen 乳 坚果\n"
            "  python scripts/main.py --probe\n"
        ),
    )
    ap.add_argument("image", nargs="?", help="配料表照片路径（jpg/png/webp）")
    ap.add_argument("--goal", default="cut", choices=sorted(config.GOALS),
                    help="你的健身目标（手动指定，Agent 不推断）")
    ap.add_argument("--all-goals", action="store_true",
                    help="一次算出全部目标的结论（视觉链路只跑一次，切换目标不再等待）")
    ap.add_argument("--allergen", action="append", default=[],
                    help="过敏 / 忌口，可重复；命中即告警。可选：" + " ".join(config.ALLERGEN_OPTIONS))
    ap.add_argument("--serving-g", type=float, default=None,
                    help="一次吃多少克。**留空 = 整包**（默认口径：一袋薯片按 170.8 g 算，"
                         "不按标签建议的 28 g 算）。填了就按你填的算，并在 notes 里声明覆盖了包装口径")
    ap.add_argument("--servings", type=float, default=None,
                    help="已废弃：口径改为「留空=整包/手填=一次吃的克数」，"
                         "「每包份数」由包装识别，不再需要人工指定。传了会被忽略")
    # 个人资料：四个字段缺一个就整体回落人口 NRV，Agent 不推断、不给默认值
    ap.add_argument("--age", type=float, default=None, help="年龄（岁，10–100）")
    ap.add_argument("--sex", default=None, choices=["male", "female"],
                    help="生理性别，仅用于 Mifflin-St Jeor 公式：male 男 / female 女")
    ap.add_argument("--weight-kg", type=float, default=None, help="体重（kg，20–300）")
    ap.add_argument("--height-cm", type=float, default=None, help="身高（cm，100–250）")
    ap.add_argument("--activity", default=None,
                    choices=sorted(config.ACTIVITY_FACTORS),
                    help="活动水平：" + " / ".join(
                        f"{k}={v}" for k, v in config.ACTIVITY_FACTORS.items()))
    ap.add_argument("--goal-adjust", action="store_true",
                    help="在维持热量上再按目标增减（减脂 ×0.85 / 增肌 ×1.1）。"
                         "默认关闭：维持热量是能算的，减脂该减多少属于饮食处方")
    ap.add_argument("--json", action="store_true", help="只输出契约 JSON")
    ap.add_argument("--no-media", action="store_true", help="跳过 result.jpg 渲染")
    ap.add_argument("--agent-json", default=None,
                    help="Agent 模式：读入 Agent 自己看图产出的 JSON（含四区定位框与抽取），"
                         "不调用任何外部推理端点。配合 --dump-agent-template 取模板")
    ap.add_argument("--dump-agent-template", nargs="?", const="-", default=None,
                    metavar="PATH",
                    help="打印 / 写入 Agent 模式的空白 JSON 模板（带合法 verdict id 与字段表）。"
                         "不给 PATH 则打印到标准输出")
    ap.add_argument("--out-dir", default=None, help="产物目录")
    ap.add_argument("--probe", action="store_true", help="只做环境探测")
    ap.add_argument("--show-config", action="store_true", help="打印当前生效配置")
    ap.add_argument("--verbose", "-v", action="store_true", help="打印每步耗时")
    return ap.parse_args(argv)


def _cmd_probe() -> int:
    """环境自检：全部本地，**不连任何网络**。

    2026-09-25 起 skill 移除了外部推理端点，第①②步由 Agent 自己看图产出。
    所以这里不再探测端点 / 模型 / 双通道，只确认本地依赖、规则表和内容指纹就绪。
    """
    print("成分雷达 · 环境自检（纯本地，不联网）")
    print("-" * 56)
    print(f"规则表               : {config.RULES_PATH} "
          f"({'存在' if Path(config.RULES_PATH).exists() else '缺失!'})")
    print(f"规则版本             : {AM.J.load_rules().get('version')}")
    print(f"seed / temperature   : {config.SEED} / {config.TEMPERATURE}")
    print(f"每日能量分母         : 人口 NRV {config.NRV_KCAL} kcal"
          f"（= {config.NRV_ENERGY_KJ:.0f} kJ ÷ 4.184）；蛋白 {config.NRV_PROTEIN_G:.0f} g / "
          f"脂肪 {config.NRV_FAT_G:.0f} g / 碳水 {config.NRV_CARBS_G:.0f} g / "
          f"钠 {config.NRV_SODIUM_MG:.0f} mg")
    print("活动系数             : " + " / ".join(
        f"{k}={v}" for k, v in config.ACTIVITY_FACTORS.items()))
    try:
        import PIL  # noqa: F401

        print(f"Pillow               : {PIL.__version__}")
    except ImportError:
        print("Pillow               : 未安装 → 无法渲染 result.jpg"
              "（pip install pillow）")
    print("-" * 56)
    print("视觉来源             : agent（Agent 自己看图，本 skill 不含 HTTP 代码）")
    print(f"skill_pin（内容指纹）: {P.skill_fingerprint()}")
    return 0


def main(argv=None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    if args.show_config:
        print(json.dumps(config.snapshot(), ensure_ascii=False, indent=2))
        return 0
    if args.dump_agent_template:
        # 模板不带下划线说明键之外的默认值，Agent 照着填即可
        from scripts import agent_mode

        tpl = agent_mode.template()
        text = json.dumps(tpl, ensure_ascii=False, indent=2)
        if args.dump_agent_template == "-":
            print(text)
        else:
            p = Path(args.dump_agent_template)
            p.write_text(text + "\n", encoding="utf-8")
            print(f"已写入模板：{p.resolve()}")
            print("填好后用 --agent-json 指回这个文件。schema："
                  f"{agent_mode.SCHEMA}")
        return 0
    if args.probe or not args.image:
        if not args.image:
            print("提示：未指定图片。加 --probe 可只做环境探测。\n", file=sys.stderr)
            if not args.probe:
                return 2
        return _cmd_probe()

    unknown = [a for a in args.allergen if a not in config.ALLERGEN_OPTIONS]
    if unknown:
        print(f"警告：未知忌口项 {unknown}（可选：{config.ALLERGEN_OPTIONS}）", file=sys.stderr)

    # 个人资料：要么四项齐全，要么一个都不填（半填状态宁可回落人口 NRV 也不猜）
    profile = None
    partial = [args.age, args.sex, args.weight_kg, args.height_cm, args.activity]
    if any(v is not None for v in partial):
        if any(v is None for v in partial):
            print("警告：个人资料需要 年龄/性别/体重/身高/活动水平 五项齐全；"
                  "缺项将回落为人口 NRV 口径。", file=sys.stderr)
        profile = {
            "age": args.age, "sex": args.sex, "weight_kg": args.weight_kg,
            "height_cm": args.height_cm, "activity": args.activity,
        }
        daily = PR.build(profile, goal=args.goal, goal_adjust=args.goal_adjust)
        if daily:
            print(f"个人口径：每日所需 ≈ {daily['daily_kcal']} kcal"
                  f"（BMR {daily['bmr_kcal']} × 活动系数 {daily['activity_factor']}"
                  f" {daily['activity_label']}"
                  + (f"，已按目标 ×{daily['goal_adjust_factor']}" if daily["goal_adjusted"] else "")
                  + "）", file=sys.stderr)
        else:
            print("个人资料无效（越界或性别/活动水平不认识），已回落人口 NRV 口径。",
                  file=sys.stderr)
            profile = None

    # prog 在 agent 模式里用，定义在分支之前
    def prog(msg: str):
        if args.verbose:
            print(msg, flush=True)

    # ---------------- Agent 模式：不调外部端点，Agent 自己看图产出 JSON ----------------
    if args.agent_json:
        from scripts import agent_mode

        try:
            payload = agent_mode.load_payload(args.agent_json)
            for w in agent_mode.validate(payload):
                print(f"警告：{w}", file=sys.stderr)
        except agent_mode.AgentPayloadError as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2

        try:
            result = agent_mode.run_agent_mode(
                args.image,
                payload,
                goal=args.goal,
                allergens=args.allergen,
                goals=list(config.GOALS) if args.all_goals else None,
                serving_override=({"serving_g": args.serving_g}
                                  if args.serving_g else None),
                profile=profile,
                goal_adjust=args.goal_adjust,
                out_dir=Path(args.out_dir) if args.out_dir else None,
                verbose=args.verbose,
                progress=prog,
            )
        except FileNotFoundError as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2
        except agent_mode.AgentPayloadError as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2
        except Exception as e:  # noqa: BLE001
            print(f"运行失败：{type(e).__name__}: {e}", file=sys.stderr)
            if args.verbose:
                raise
            return 1

        if result["status"] == "rejected":
            print(result["final_reply"])
            return 3
        if args.json:
            print(json.dumps(result["contract"], ensure_ascii=False, indent=2))
        else:
            print(result["final_reply"])
        return 0

    print("请用 --agent-json 指定 Agent 产出的抽取 JSON；"
          "用 --dump-agent-template 取模板。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
