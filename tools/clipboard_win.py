# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""Windows 剪贴板（直接调用系统接口，中文和换行都不会出错，也不会在开头多出不可见字符）。
任何一步失败都会抛出 RuntimeError，调用方据此提示“复制失败”，不会误报“已复制”。"""
from i18n import tr
import ctypes
import time
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_u = ctypes.windll.user32
_k = ctypes.windll.kernel32
_u.OpenClipboard.argtypes = [wintypes.HWND]
_u.OpenClipboard.restype = wintypes.BOOL
_u.EmptyClipboard.restype = wintypes.BOOL
_u.CloseClipboard.restype = wintypes.BOOL
_u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_u.SetClipboardData.restype = wintypes.HANDLE
_k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_k.GlobalAlloc.restype = wintypes.HGLOBAL
_k.GlobalLock.argtypes = [wintypes.HGLOBAL]
_k.GlobalLock.restype = ctypes.c_void_p
_k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_k.GlobalFree.argtypes = [wintypes.HGLOBAL]
_k.GlobalFree.restype = wintypes.HGLOBAL


def set_text(text):
    text = text.replace('\r\n', '\n').replace('\n', '\r\n')
    data = text.encode('utf-16-le') + b'\x00\x00'
    for _ in range(20):
        if _u.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError(tr('剪贴板被其他程序占用，请稍后再试'))
    try:
        if not _u.EmptyClipboard():
            raise RuntimeError(tr('无法清空剪贴板'))
        h = _k.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            raise RuntimeError(tr('内存不足，无法复制'))
        p = _k.GlobalLock(h)
        if not p:
            _k.GlobalFree(h)
            raise RuntimeError(tr('内存不足，无法复制'))
        ctypes.memmove(p, data, len(data))
        _k.GlobalUnlock(h)
        if not _u.SetClipboardData(CF_UNICODETEXT, h):
            _k.GlobalFree(h)                 # 只有设置失败时内存才归我们释放；成功后归系统所有
            raise RuntimeError(tr('写入剪贴板失败'))
    finally:
        _u.CloseClipboard()
