# -*- coding: utf-8 -*-
"""
成分雷达 · 全局配置

**本 skill 不发起任何网络请求**（2026-09-25 移除了全部 HTTP 代码）。
第①②步的视觉能力来自 Agent 自己（见 `agent_mode.py`），
所以这里没有端点地址、没有 API Key、没有模型名——那些都不再需要。

所有配置项都可用环境变量覆盖：

    # Linux / macOS
    export IR_SEED=7
    # Windows PowerShell
    $env:IR_SEED = "7"

优先级：环境变量 > config.py 里的默认值。本模块只读 os.environ，
不解析任何配置文件。

环境变量一览
-------------
IR_SEED          采样种子，默认 7（锁版本 · 同图同结果）
IR_TEMPERATURE   采样温度，默认 0（追求可复现）
IR_OUT_DIR       产物目录，默认 <skill>/output
IR_RULES         规则表路径，默认 <skill>/scripts/rules.yaml
IR_DEBUG         调试开关，默认 0
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
SKILL_DIR = Path(__file__).resolve().parent.parent            # skills-src/ingredient-radar
PROJECT_DIR = SKILL_DIR.parent.parent                        # 成分雷达/
SCRIPTS_DIR = SKILL_DIR / "scripts"
REFERENCES_DIR = SKILL_DIR / "references"
EVALS_DIR = SKILL_DIR / "evals"


def _env(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v not in (None, "") else default


# ---------------------------------------------------------------- 采样
# 以下只影响本地确定性计算；本 skill 不发起任何网络请求，
# 所以没有 IR_BASE_URL / IR_API_KEY / IR_MODEL / IR_TIMEOUT 这些端点了。
SEED = int(_env("IR_SEED", "7"))
TEMPERATURE = float(_env("IR_TEMPERATURE", "0"))


def _flag(key: str, default: str = "") -> bool:
    return _env(key, default).strip().lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------- 无密钥
# 2026-09-25 起本 skill 不发任何网络请求，所以**没有 API Key 这回事**：
# 不再有占位 Key、没有 IR_API_KEY、没有 warn_if_placeholder_key()。
# 视觉来自 Agent 自己的多模态能力（agent_mode.py），不经过任何凭证。
# snapshot() 因此也天然不含密钥字段——不是「显式排除」，是本来就没有。
DEBUG = _flag("IR_DEBUG", "0")

# ---------------------------------------------------------------- 产物
OUT_DIR = Path(_env("IR_OUT_DIR", str(SKILL_DIR / "output")))
RULES_PATH = Path(_env("IR_RULES", str(SCRIPTS_DIR / "rules.yaml")))
MEDIA_FILENAME = "result.jpg"
CONTRACT_FILENAME = "contract.json"
REPORT_FILENAME = "report.json"

# ---------------------------------------------------------------- 业务常量
SUGAR_CUBE_G = 4.0          # 1 块方糖 ≈ 4 g 糖（与静态 Demo 口径一致）
NRV_SODIUM_MG = 2000.0      # GB 28050 钠 NRV（毫克）
# GB 28050 能量的 NRV 是 **8400 kJ**，不是 8400 kcal。
# 早先版本直接把 8400 当 kcal 当分母，于是每份热量占比被算小了 4.184 倍
# （威化 280 kcal 报「3.3%」，实际应约 14%）。kJ 才是国标口径，这里统一折算成 kcal：
NRV_ENERGY_KJ = 8400.0      # GB 28050 能量 NRV（千焦，国标原值）
KJ_PER_KCAL_CONFIG = 4.184  # 与 serving.KJ_PER_KCAL 保持一致
NRV_KCAL = round(NRV_ENERGY_KJ / KJ_PER_KCAL_CONFIG, 1)   # ≈ 2007.6 kcal
# GB 28050 三大营养素 NRV。个人化「你该吃多少蛋白」属于饮食处方，
# 本 Skill 只做包装数字的机械比对，所以这三项固定用人口参考值，
# 只有**能量**会在用户手填个人资料时换成个人的每日所需。
NRV_PROTEIN_G = 60.0        # GB 28050 蛋白质 NRV（g）
NRV_FAT_G = 60.0            # GB 28050 脂肪 NRV（g，国标为 ≤60 g）
NRV_CARBS_G = 300.0         # GB 28050 碳水化合物 NRV（g）
GB_TRANS_ZERO_LIMIT = 0.3   # GB 28050：反式脂肪酸 ≤0.3 g/100 g 可标「0」

# 活动水平 → 系数（scripts/profile.py 的口径，这里放一份给 snapshot / --show-config 看）
ACTIVITY_FACTORS = {
    "sedentary": 1.3,    # 久坐 / 普通上班族
    "active": 1.55,      # 一般健身人群
    "athlete": 1.8,      # 高强度运动 / 专项运动员
}

# 可选的「按目标增减能量」乘数。默认**不启用**（命令行 --goal-adjust 才开）：
# 维持热量是能算的；减脂该减多少、增肌该加多少属于饮食处方，不进默认口径。
GOAL_ADJUST = {"cut": 0.85, "gain": 1.10, "keto": 1.0}


def _round0(v) -> int:
    return int(round(float(v)))


def _round1(v) -> float:
    r = round(float(v), 1)
    return int(r) if r == int(r) else r

# 用户可选目标与过敏原（全部由用户手动勾选，Agent 不推断）
GOALS = {
    "gain": {"emoji": "💪", "label": "增肌"},
    "cut": {"emoji": "🔥", "label": "减脂 · 控糖"},
    "keto": {"emoji": "🥑", "label": "生酮"},
}

ALLERGEN_OPTIONS = ["花生", "乳", "麸质", "坚果", "大豆", "鸡蛋"]

DISCLAIMER = "以上仅为配料与营养成分的机械比对，不替代医嘱、不等同专业营养诊断；一切数值以包装标识为准，过敏请务必人工复核原包装。"


def snapshot() -> dict:
    """返回当前生效配置（用于 report.json 与现场复现留证）。

    2026-09-25 起不含任何端点 / 模型 / 密钥字段——本 skill 不发网络请求，
    视觉来自 Agent 自己。这里不是「显式排除」，是本来就没有那些配置。
    """
    return {
        "vision_source": "agent",          # Agent 自己看图，不走外部端点
        "seed": SEED,
        "temperature": TEMPERATURE,
        "rules": str(RULES_PATH),
        "out_dir": str(OUT_DIR),
    }


def ensure_out_dir() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR
