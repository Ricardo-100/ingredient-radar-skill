# -*- coding: utf-8 -*-
"""成分雷达 · 自研 Skill 业务脚本包

约定：所有模块之间用**扁平绝对导入**（import config / from backends import get_backend），
入口脚本（main.py / server.py）负责把自己所在目录插到 sys.path[0]。
这样 `python scripts/main.py ...` 从任何工作目录都能直接跑，不需要装包、不需要 PYTHONPATH。
"""
