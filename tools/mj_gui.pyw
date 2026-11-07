#! python3.10
# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""Image F 操作面板的入口（launcher.pyw 用 pythonw 打开它；--selftest 图片路径 = 截图后自动关闭）。
界面和处理代码都在 mj_app 等模块里（安装包里是编译好的 .pyd）。"""
from i18n import tr
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import mj_app
except SystemExit:
    raise
except Exception:
    _log = os.path.join(HERE, 'gui_error.log')
    try:
        with open(_log, 'w', encoding='utf-8') as _f:
            _f.write(traceback.format_exc())
    except OSError:
        pass
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _r = _tk.Tk()
    _r.withdraw()
    _mb.showerror('Image F', tr('启动失败：程序文件不完整或损坏，请重新安装 Image F。\n详情见：') + _log)
    sys.exit(1)

from mj_app import *  # noqa: E402,F401,F403  测试脚本用 runpy 读这个文件时能直接拿到 App、core、ui 等

if __name__ == '__main__':
    mj_app.main()
