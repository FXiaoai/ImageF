# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""④页「角色为主」：找到主角的脸（OpenCV Zoo 的 YuNet 人脸模型，MIT 许可，随工具带在 tools 里），
在脸上找嘴唇，按 MJ 主角嘴唇的颜色单独调色。
只在两张图里都有足够大的脸（脸高 ≥ 画面高的 CHAR_MIN）时使用；找不到就什么都不做（其余区域照常按区域对应）。
瞳孔不单独处理：闭眼、半睁眼、被刘海挡住时识别不准。"""
from i18n import tr
import os

import cv2
import numpy as np

from mj_region import TONE_K, _transform, region_stats, to_bgr, to_lab

HERE = os.path.dirname(os.path.realpath(__file__))
MODEL = os.path.join(HERE, 'face_detection_yunet_2023mar.onnx')
CHAR_MIN = 0.08          # 主角的脸高至少占画面高的 8%（样本：人像 13–45%，地铁远景路人 3–4%）
DETECT_LONG = 1280       # 检测时把长边缩到这个尺寸
LIPS_CAP = (6.0, 12.0)   # 嘴唇调色上限：(L 平移, a/b 平移)
LIPS_COL_K = 1.0         # 嘴唇的颜色完全按 MJ（其余区域是 mj_region.COL_K）
LIPS_COLOR = (60, 60, 255)   # 区域图里嘴唇的标注色（BGR）
_MODEL_BYTES = []


# ------------------------------------------------------------------ face
def available():
    return hasattr(cv2, 'FaceDetectorYN') and os.path.isfile(MODEL)


def _model():
    """Model bytes (read once). Loaded from memory: OpenCV cannot open files on Chinese / non-ASCII paths."""
    if not _MODEL_BYTES:
        _MODEL_BYTES.append(np.fromfile(MODEL, np.uint8))
    return _MODEL_BYTES[0]


def detect_faces(img8, thr=0.6):
    """[dict(box=(x, y, w, h), pts=5x2 [右眼, 左眼, 鼻尖, 右嘴角, 左嘴角], score)], largest first. [] when unavailable."""
    if not available():
        return []
    H, W = img8.shape[:2]
    s = min(1.0, DETECT_LONG / max(H, W))
    small = cv2.resize(img8, (int(round(W * s)), int(round(H * s))), interpolation=cv2.INTER_AREA) if s < 1 else img8
    try:
        det = cv2.FaceDetectorYN.create('onnx', _model(), np.zeros(0, np.uint8), (small.shape[1], small.shape[0]),
                                        thr, 0.3, 50)
        _, faces = det.detect(np.ascontiguousarray(small))
    except (cv2.error, OSError):
        return []
    if faces is None:
        return []
    out = [dict(box=f[:4] / s, pts=f[4:14].reshape(5, 2) / s, score=float(f[14])) for f in faces]
    return sorted(out, key=lambda d: -d['box'][2] * d['box'][3])


def main_face(img8):
    """The main character's face, or None when there is no face at least CHAR_MIN of the image height."""
    faces = detect_faces(img8)
    if faces and faces[0]['box'][3] >= CHAR_MIN * img8.shape[0]:
        return faces[0]
    return None


# ------------------------------------------------------------------ lips
def _ellipse_mask(shape, center, axes, angle):
    m = np.zeros(shape[:2], np.uint8)
    cv2.ellipse(m, (int(round(center[0])), int(round(center[1]))), (max(1, int(axes[0])), max(1, int(axes[1]))),
                float(angle), 0, 360, 1, -1)
    return m > 0


def _largest_filled(mask):
    n, lbl, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n < 2:
        return None
    m = (lbl == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(m)
    cv2.drawContours(filled, cnts, -1, 1, -1)
    return filled > 0


def lips_mask(img8, face):
    """Lips: inside an ellipse spanned by the two mouth corners, the pixels clearly redder than the surrounding skin,
    grown with their own colour so the whole lips are covered even when the corner landmarks are a little off
    (turned or tilted faces). None when the lips cannot be told from the skin (pale / covered lips)."""
    if face is None:
        return None
    lab = to_lab(img8.astype(np.float32) / 255)
    m1, m2 = face['pts'][3], face['pts'][4]
    mw = float(np.hypot(*(m2 - m1)))
    if mw < 8:
        return None
    c = (m1 + m2) / 2
    ang = float(np.degrees(np.arctan2(m2[1] - m1[1], m2[0] - m1[0])))
    inner = _ellipse_mask(lab.shape, c, (0.62 * mw, 0.40 * mw), ang)
    ring = _ellipse_mask(lab.shape, c, (1.0 * mw, 0.75 * mw), ang) & ~_ellipse_mask(lab.shape, c, (0.75 * mw, 0.5 * mw), ang)
    L, a = lab[..., 0], lab[..., 1]
    if inner.sum() < 30 or ring.sum() < 30:
        return None
    sa, sL = float(np.median(a[ring])), float(np.median(L[ring]))
    k = max(3, int(0.06 * mw)) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    cand = inner & (a > sa + 5) & (L < sL + 4)
    core = _largest_filled(cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_CLOSE, se))
    if core is None or core.sum() < 0.15 * inner.sum():
        return None
    lab_core = lab[core].mean(0)
    outer = _ellipse_mask(lab.shape, c, (0.95 * mw, 0.65 * mw), ang)
    similar = outer & (a > sa + 4) & (L < sL + 4) & (np.sqrt(((lab - lab_core) ** 2).sum(-1)) < 14)
    grown = cv2.morphologyEx((similar | core).astype(np.uint8), cv2.MORPH_CLOSE, se)
    n, lbl = cv2.connectedComponents(grown, connectivity=8)
    ids = np.unique(lbl[core])
    m = _largest_filled(np.isin(lbl, ids[ids > 0]))
    return m & outer if m is not None else core


# ------------------------------------------------------------------ colour
def apply_lips(P, gf, mjf, g_lips, m_lips, log=print, cap=LIPS_CAP):
    """Recolour GPT's lips: GPT's original lip pixels are mapped onto MJ's lip statistics (lightness curve + a/b
    mean and spread, capped) and blended in with a soft edge over P (the region-transferred image)."""
    if g_lips is None or m_lips is None:
        where = tr('、').join(n for n, m in (('GPT', g_lips), ('MJ', m_lips)) if m is None)
        log(tr('  嘴唇：{where} 图里没找到，按所在区域处理', where=where))
        return P
    ys, xs = np.nonzero(g_lips)
    sig = max(1.0, 0.03 * (max(np.ptp(ys), np.ptp(xs)) + 1))
    pad = int(4 * sig) + 2
    y0, y1 = max(0, ys.min() - pad), ys.max() + pad + 1
    x0, x1 = max(0, xs.min() - pad), xs.max() + pad + 1
    lab_g = to_lab(gf[y0:y1, x0:x1])
    gs = region_stats(lab_g, g_lips[y0:y1, x0:x1])
    ms = region_stats(to_lab(mjf), m_lips)
    T = to_bgr(_transform(lab_g, gs, ms, cap, TONE_K, LIPS_COL_K))
    alpha = np.clip(cv2.GaussianBlur(g_lips[y0:y1, x0:x1].astype(np.float32), (0, 0), sig) * 1.5, 0, 1)[..., None]
    P = P.copy()
    P[y0:y1, x0:x1] = P[y0:y1, x0:x1] * (1 - alpha) + T * alpha
    log(tr('  嘴唇：GPT L{mL:.0f} a{ma:+.1f} b{mb:+.1f} → MJ L{mL2:.0f} a{ma2:+.1f} b{mb2:+.1f}（单独配色）', mL=gs["mL"], ma=gs["ma"], mb=gs["mb"], mL2=ms["mL"], ma2=ms["ma"], mb2=ms["mb"]))
    return P
