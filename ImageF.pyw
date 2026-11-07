#! python3.10
# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
# 双击打开 Image F（原名 MJ 还原工具）（先检查运行环境，缺少组件会自动安装，然后打开操作面板）。
# 这台电脑默认的 Python 不是 3.10 也没关系：装有 3.10 时会自动换过去。
# 换到一台没装过 Python 3.10 的电脑上，请改为双击 ImageF.bat。
import os
import runpy
import sys

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools')
sys.path.insert(0, TOOLS)
os.chdir(TOOLS)
runpy.run_path(os.path.join(TOOLS, 'launcher.pyw'), run_name='__main__')
