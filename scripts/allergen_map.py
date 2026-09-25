# -*- coding: utf-8 -*-
"""
allergen_map · 致敏原词表 → 标准过敏原键的映射

Demo 原版把过敏原做成了人工常量表；真实链路里它必须从「致敏原提示行」的抽取结果推导。
本模块只做**词面映射与 direct/cross 归类**，不判断食品是否安全、不推断用户的过敏体质。

- ``direct``：提示语明确「含有 / 含」
- ``cross`` ：提示语为「生产线亦加工 / 共线 / 可能含有」
映射表与法规依据见 references/allergen-map.md
"""
from __future__ import annotations

from typing import Any, Dict, List

# 标准过敏原键 → 触发词表（顺序无关，命中任一即算该过敏原出现）
ALLERGEN_KEYS: Dict[str, List[str]] = {
    "花生": ["花生", "groundnut", "peanut"],
    "乳": ["乳及乳制品", "乳制品", "乳糖", "牛奶", "牛乳", "奶", "酪", "milk", "dairy", "lactose"],
    "麸质": ["麸质", "含麸质的谷物", "小麦", "大麦", "黑麦", "燕麦", "gluten", "wheat"],
    "坚果": ["坚果", "核桃", "杏仁", "榛子", "腰果", "开心果", "夏威夷果", "碧根果",
            "松仁", "芝麻", "nut", "tree nut"],
    "大豆": ["大豆", "黄豆", "豆粉", "豆制品", "soy", "soybean"],
    "鸡蛋": ["鸡蛋", "蛋类", "蛋白", "蛋黄", "egg"],
    "鱼": ["鱼", "鱼类", "鳕鱼", "三文鱼", "fish"],
    "甲壳": ["甲壳", "虾", "蟹", "贝", "crustacean", "shellfish"],
}

# cross-contact 的判定词：出现即把该过敏原降级为「产线共线」
CROSS_WORDS = ["生产线", "共线", "同一生产", "同一车间", "可能含有", "交叉污染", "may contain"]

# UI 上暴露给用户的忌口项（与 config.ALLERGEN_OPTIONS 保持一致）
USER_OPTIONS = ["花生", "乳", "麸质", "坚果", "大豆", "鸡蛋"]


def canonical_allergen(word: str) -> str:
    """把一个过敏原词归到标准键；归不进去的原样返回（避免漏报）。"""
    if not word:
        return ""
    w = str(word).strip()
    low = w.lower()
    for key, words in ALLERGEN_KEYS.items():
        for cand in words:
            if cand and (cand in w or cand in low):
                return key
    return w


def derive_present(
    statement: str = "",
    direct_words: List[str] = None,
    cross_words: List[str] = None,
) -> Dict[str, Dict[str, str]]:
    """从致敏原抽取结果推导「产品真实含有的过敏原」。

    返回 ``{标准键: {"type": "direct|cross", "label": 原文}}``。
    direct_words / cross_words 由 referring 抽取给出；statement 作为兜底扫描。
    """
    present: Dict[str, Dict[str, str]] = {}

    for raw in direct_words or []:
        key = canonical_allergen(raw)
        if not key:
            continue
        present[key] = {"type": "direct", "label": str(raw)}

    for raw in cross_words or []:
        key = canonical_allergen(raw)
        if not key:
            continue
        # 已经被判为 direct 的不降级
        present.setdefault(key, {"type": "cross", "label": str(raw)})

    # 兜底：抽取没给出结构化词表时，从原文里扫
    if not direct_words and not cross_words and statement:
        seg_cross = ""
        for cw in CROSS_WORDS:
            idx = statement.find(cw)
            if idx != -1:
                seg_cross = statement[idx:]
                seg_direct = statement[:idx]
                break
        else:
            seg_direct = statement
        for chunk in _split_allergen(seg_direct):
            key = canonical_allergen(chunk)
            if key:
                present[key] = {"type": "direct", "label": chunk.strip()}
        for chunk in _split_allergen(seg_cross):
            key = canonical_allergen(chunk)
            if key:
                present.setdefault(key, {"type": "cross", "label": chunk.strip()})

    return present


def _split_allergen(text: str) -> List[str]:
    if not text:
        return []
    chunks = []
    for buf in str(text).replace("；", ";").replace("，", ",").split(";"):
        for piece in buf.split(","):
            piece = piece.strip().strip("。.、")
            if not piece:
                continue
            # 去掉「含」「含xx的谷物」这类前缀包装词，保留核心名词
            for prefix in ("含有", "含", "含麸质的谷物", "及"):
                if piece.startswith(prefix) and len(piece) > len(prefix):
                    piece = piece[len(prefix):]
            chunks.append(piece)
    return chunks


def cross_check(user_allergens: List[str], present: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    """把用户勾选的过敏/忌口与产品实际含有的致敏原做交叉核验。

    只做词面交集；**不推断用户体质、不做医学判断**。未命中的勾选项一律如实报告「未命中」，
    不会为了凑告警而硬标红。
    """
    hits: List[Dict[str, Any]] = []
    for ua in user_allergens or []:
        key = canonical_allergen(ua)
        hit = present.get(key)
        if hit:
            hits.append(
                {
                    "allergen": ua,
                    "key": key,
                    "kind": hit["type"],
                    "label": hit["label"],
                }
            )
    return hits
