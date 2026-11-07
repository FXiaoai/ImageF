# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""文件读写：中文路径读写图片、原子写入（先写临时文件再替换，写到一半中断也不会留下坏文件）、
读取 JSON（文件损坏时改名留底并提示，而不是悄悄当成空的）。"""
from i18n import tr
import json
import os
import tempfile
import time

import cv2
import numpy as np

ALPHA_EXT = ('.png', '.webp', '.tif', '.tiff')


class InputError(ValueError):
    """A problem with the user's input (unreadable image, wrong pair ...): shown as a message, no traceback."""


def unique_path(folder, stem, suffix, extras=()):
    """folder\\stem+suffix; when that file (or a companion file stem+root+extra) already exists,
    add _2, _3 ... so nothing is ever overwritten. suffix e.g. '_还原.png', extras e.g. ('_compare.jpg',)."""
    os.makedirs(folder, exist_ok=True)
    root, ext = os.path.splitext(suffix)
    n = 1
    while True:
        base = os.path.join(folder, stem + root + ('' if n == 1 else f'_{n}'))
        if not any(os.path.exists(base + e) for e in (ext,) + tuple(extras)):
            return base + ext
        n += 1


# ------------------------------------------------------------------ images
def imread_u(path, flag=cv2.IMREAD_COLOR):
    """cv2.imread that also works with Chinese / non-ASCII Windows paths. Unreadable, empty or broken
    files return None (never raise). IMREAD_COLOR also applies the EXIF orientation."""
    try:
        buf = np.fromfile(path, np.uint8)
        return cv2.imdecode(buf, flag) if buf.size else None
    except (OSError, ValueError, cv2.error):
        return None


def imread_alpha(path):
    """Colour image composited over white + its alpha channel (None when fully opaque).
    Transparent areas otherwise keep whatever colour is stored behind them (often black)."""
    img = imread_u(path)
    if img is None or not path.lower().endswith(ALPHA_EXT):
        return img, None
    raw = imread_u(path, cv2.IMREAD_UNCHANGED)
    if raw is None or raw.ndim != 3 or raw.shape[2] != 4 or raw.shape[:2] != img.shape[:2]:
        return img, None
    a = raw[..., 3]
    if a.dtype != np.uint8:
        a = (a.astype(np.float32) * (255.0 / np.iinfo(a.dtype).max) + 0.5).astype(np.uint8)
    if a.min() == 255:
        return img, None
    af = a.astype(np.float32)[..., None] / 255.0
    flat = img.astype(np.float32) * af + 255.0 * (1.0 - af)
    return np.clip(flat + 0.5, 0, 255).astype(np.uint8), a


def with_alpha(img, alpha):
    """Re-attach an alpha channel (only when the sizes still match)."""
    if alpha is None or img.shape[:2] != alpha.shape[:2]:
        return img
    return np.dstack([img, alpha])


def imwrite_u(path, img, params=None):
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or '.png', img, params or [])
    if not ok:
        raise IOError(tr('无法保存图片：') + path)
    write_bytes(path, buf.tobytes())


# ------------------------------------------------------------------ atomic writes
def write_bytes(path, data):
    """Write to a temporary file in the same folder, then replace the target in one step."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.~' + os.path.basename(path)[:40] + '.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for i in range(20):              # 杀毒软件可能短暂占用刚写好的文件
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_text(path, text):
    """UTF-8 text with the platform's line endings (same bytes as a text-mode open().write())."""
    if os.linesep != '\n':
        text = text.replace('\r\n', '\n').replace('\n', os.linesep)
    write_bytes(path, text.encode('utf-8'))


def write_json(path, obj, indent=1):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=indent))


def read_text(path):
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def read_json(path, default=None, warn=None):
    """Missing file -> default. A file that exists but cannot be parsed is renamed to
    <name>.bad_<time> (so nothing is lost and it is not silently overwritten), `warn` is told, and
    default is returned. A file that is merely locked is left alone."""
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except PermissionError as e:
        if warn:
            warn(tr('[提醒] 暂时读不了 {v}（{e}），本次按空数据处理。', v=os.path.basename(path), e=e))
        return default
    except (OSError, ValueError) as e:
        bad = f'{path}.bad_{time.strftime("%Y%m%d_%H%M%S")}'
        try:
            os.replace(path, bad)
        except OSError:
            bad = None
        if warn:
            warn(tr('[提醒] {v} 已损坏，读不出来（{name__}）', v=os.path.basename(path), name__=type(e).__name__)
                 + (tr('；原文件已改名留底：{bad}', bad=bad) if bad else ''))
        return default
