# -*- coding: utf-8 -*-
"""
miniyaml · 零依赖 YAML 子集解析器

为什么要有它：``rules.yaml`` 里的阈值是「规则即文档」，必须是人能直接读懂的；
但项目又要求「除了 Pillow 之外零第三方依赖」，不能强制装 PyYAML。

因此本模块只解析 **rules.yaml 实际用到的那一个子集**：
  - 注释行（``#`` 开头）与行尾注释（`` #`` 前有空白且不在引号内）
  - 缩进嵌套的 mapping（``key: value`` / ``key:`` + 子块）
  - ``- item`` 形式的标量块序列
  - 行内流序列 ``[a, b, c]``
  - 标量：int / float / bool / null / 单双引号字符串 / 裸字符串

如果环境里装了 PyYAML，``judge.load_rules`` 会优先用它；本模块只在装不了时兜底。
解析失败会抛 ``MiniYamlError`` 并带行号，绝不静默返回错数据。
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple

__all__ = ["MiniYamlError", "loads", "load", "dumps_min", "normalize"]


def normalize(obj):
    """把 PyYAML 会自动推断出的特殊类型归一成基本类型。

    ``updated: 2026-09-23`` 在 PyYAML 下会变成 ``datetime.date``，而 miniyaml 给字符串。
    规则表只需要字符串 / 数字 / 布尔 / null / 列表 / 字典，这里统一收敛，
    保证「装没装 PyYAML 得到的结果完全一致」——否则换台机器判定就可能变。
    """
    import datetime as _dt
    import decimal as _decimal

    if isinstance(obj, dict):
        return {str(k): normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, _decimal.Decimal):
        return float(obj)
    if isinstance(obj, (int, float, str)):
        return obj
    return str(obj)


class MiniYamlError(ValueError):
    pass


_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_BOOL_TRUE = {"true", "yes", "on"}
_BOOL_FALSE = {"false", "no", "off"}
_NULL = {"", "null", "~", "none"}


# ---------------------------------------------------------------- 行预处理
def _strip_comment(line: str) -> str:
    """去掉行尾注释；``#`` 前必须有空白，且不能在引号内。``p#a6f3c21`` 这类值不受影响。"""
    out = []
    quote = ""
    prev = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#" and prev in ("", " ", "\t"):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out).rstrip()


def _tokenize(text: str) -> List[Tuple[int, int, str]]:
    """返回 [(缩进, 原始行号, 去注释后的内容)]，跳过空行。"""
    toks: List[Tuple[int, int, str]] = []
    for n, raw in enumerate(text.splitlines(), 1):
        body = _strip_comment(raw.replace("\t", "    "))
        if not body.strip():
            continue
        if body.lstrip().startswith("#"):
            continue
        indent = len(body) - len(body.lstrip(" "))
        toks.append((indent, n, body.strip()))
    if not toks:
        raise MiniYamlError("空文档")
    if toks[0][0] != 0:
        raise MiniYamlError(
            f"第 {toks[0][1]} 行：文档首行必须顶格（缩进 {toks[0][0]} 空格）"
        )
    return toks


# ---------------------------------------------------------------- 标量
def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _scalar(tok: str, lineno: int) -> Any:
    s = tok.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts, depth, cur, quote = [], 0, "", ""
        for ch in inner:
            if quote:
                cur += ch
                if ch == quote:
                    quote = ""
            elif ch in ("'", '"'):
                quote = ch
                cur += ch
            elif ch == "[":
                depth += 1
                cur += ch
            elif ch == "]":
                depth -= 1
                cur += ch
            elif ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if cur.strip():
            parts.append(cur)
        return [_scalar(p, lineno) for p in parts]

    low = s.lower()
    if low in _NULL:
        return None
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    if _INT_RE.match(s):
        return int(s)
    if _FLOAT_RE.match(s):
        return float(s)
    if s[:1] in ("'", '"') and s[-1:] != s[:1]:
        raise MiniYamlError(f"第 {lineno} 行：引号未闭合 —— {s!r}")
    return _unquote(s)


# ---------------------------------------------------------------- 结构解析
def _parse_map(toks, i, indent):
    result = {}
    while i < len(toks):
        ind, ln, text = toks[i]
        if ind < indent:
            break
        if ind > indent:
            raise MiniYamlError(
                f"第 {ln} 行：缩进异常（期望 {indent} 空格，实际 {ind}）—— {text!r}"
            )
        if text.startswith("- "):
            break
        key, sep, rest = text.partition(":")
        if not sep:
            raise MiniYamlError(f"第 {ln} 行：缺少冒号，无法解析为 mapping —— {text!r}")
        key = _unquote(key.strip())
        rest = rest.strip()
        i += 1
        if rest:
            result[key] = _scalar(rest, ln)
            continue
        # 只有 key —— 往下看是嵌套 map、同级块序列，还是空值
        if i < len(toks) and toks[i][0] > indent:
            result[key], i = _parse_block(toks, i, toks[i][0])
        elif i < len(toks) and toks[i][0] == indent and toks[i][2].startswith("- "):
            result[key], i = _parse_list(toks, i, indent)
        else:
            result[key] = None
    return result, i


def _parse_list(toks, i, indent):
    items = []
    while i < len(toks):
        ind, ln, text = toks[i]
        if ind != indent or not text.startswith("- "):
            break
        item = text[2:].strip()
        i += 1
        if not item:
            if i < len(toks) and toks[i][0] > indent:
                val, i = _parse_block(toks, i, toks[i][0])
                items.append(val)
            else:
                items.append(None)
            continue
        if ":" in item and not item.startswith(("'", '"', "[")):
            # 形如 `- key: value` 的单键映射项
            k, _, v = item.partition(":")
            entry = {_unquote(k.strip()): _scalar(v.strip(), ln) if v.strip() else None}
            if i < len(toks) and toks[i][0] > indent:
                more, i = _parse_map(toks, i, toks[i][0])
                entry.update(more)
            items.append(entry)
            continue
        items.append(_scalar(item, ln))
    return items, i


def _parse_block(toks, i, indent):
    if toks[i][2].startswith("- "):
        return _parse_list(toks, i, indent)
    return _parse_map(toks, i, indent)


def loads(text: str) -> Any:
    toks = _tokenize(text)
    value, _ = _parse_block(toks, 0, toks[0][0])
    return value


def load(path) -> Any:
    from pathlib import Path

    p = Path(path)
    return loads(p.read_text(encoding="utf-8"))


def dumps_min(obj: Any) -> str:
    """把结构转成最基本的 YAML 文本（仅调试用，不追求美观）。"""
    lines: List[str] = []

    def walk(o, ind):
        pad = " " * ind
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}{k}:")
                    walk(v, ind + 2)
                else:
                    lines.append(f"{pad}{k}: {_fmt(v)}")
        elif isinstance(o, list):
            for v in o:
                if isinstance(v, (dict, list)):
                    lines.append(f"{pad}-")
                    walk(v, ind + 2)
                else:
                    lines.append(f"{pad}- {_fmt(v)}")

    def _fmt(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return f'"{v}"'

    walk(obj, 0)
    return "\n".join(lines) + "\n"
