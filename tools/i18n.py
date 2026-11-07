# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""界面语言（中文 / English）。

· 当前语言存在安装文件夹根目录的 lang.json（{"lang": "en"} 或 {"lang": "zh"}），安装程序按安装时选的语言写，
  工具里「关于」旁边可以随时切换（切换后自动重启一次）。没有这个文件时按 Windows 的显示语言（中文 → 中文，其他 → 英文）。
· 程序里的文字都用 tr('中文原文', 名字=值) 包起来：中文时原样返回（带参数时等于原来的 f-string），
  英文时到 lang/en.json 里按中文原文查英文；查不到就显示中文，不会出错。
· 只用标准库（启动器在装好 numpy 等之前就要用它），不编译成 .pyd。
"""
import json
import os

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
LANG_FILE = os.path.join(ROOT, 'lang.json')
LANGS = ('zh', 'en')
_TABLE_FILE = os.path.join(HERE, 'lang', 'en.json')


def _system_lang():
    """还没选过语言时：Windows 显示语言是中文就用中文，否则英文。"""
    try:
        import ctypes
        return 'zh' if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04 else 'en'
    except Exception:
        return 'zh'


def _read_lang():
    env = os.environ.get('IMAGEF_LANG', '').strip().lower()      # 测试用：不改 lang.json 就能临时切语言
    if env in LANGS:
        return env
    try:
        with open(LANG_FILE, encoding='utf-8-sig') as f:
            v = str(json.load(f).get('lang', 'zh')).strip().lower()
        return v if v in LANGS else 'zh'
    except FileNotFoundError:
        return _system_lang()
    except (OSError, ValueError, AttributeError):
        return 'zh'


def _read_table():
    try:
        with open(_TABLE_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return {k: v for k, v in d.items() if isinstance(v, str) and v and not k.startswith('//')}
    except (OSError, ValueError):
        return {}


LANG = _read_lang()
EN = _read_table() if LANG == 'en' else {}


def tr(s, /, **kw):
    """s = 中文原文（带 {名字} 占位）。中文：原样；英文：查 en.json。带参数时 format；英文译文的占位对不上时退回中文，不报错。"""
    t = EN.get(s, s) if EN else s
    if not kw:
        return t
    try:
        return t.format(**kw)
    except (KeyError, IndexError, ValueError):
        return s.format(**kw)


def is_en():
    return LANG == 'en'


def set_lang(lang):
    """写 lang.json（下次启动生效）。"""
    if lang not in LANGS:
        raise ValueError(lang)
    tmp = LANG_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'lang': lang}, f)
    os.replace(tmp, LANG_FILE)
