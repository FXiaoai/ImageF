# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""④页「同一场景重画」的远近估计：Depth Anything V2 Small（Apache-2.0，权重以 fp16 存放，随工具带在 tools 里，
说明见 depth_anything_v2_NOTICE.txt）。只用 OpenCV DNN，不需要额外安装包；模型从内存加载（OpenCV 打不开中文路径）。

输出是“相对远近”：0 = 最远（天空、远山），1 = 画面里最近的东西。它只用来把画面分成远 / 中 / 近几层，
不是真实距离，也不保证物体边缘逐像素准确（边缘用原图做引导滤波贴合）。模型缺失或读不了时 available() 为 False，
调用方退回原来的整幅统一调色。"""
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.realpath(__file__))
MODEL = os.path.join(HERE, 'depth_anything_v2_small_w16.onnx')
SIDE = 518                 # model input: short side 518, both sides multiples of 14 (the model's patch size)
LONG_MAX = 1400            # cap the long side (very wide images) to bound time and memory
WORK = 960                 # long side of the returned depth map's working copy before the final resize
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
_NET = []
_FAILED = []


def available():
    return os.path.isfile(MODEL) and not _FAILED and hasattr(cv2, 'dnn')


def _net():
    if not _NET:
        try:
            _NET.append(cv2.dnn.readNetFromONNX(np.fromfile(MODEL, np.uint8)))
        except Exception as e:     # corrupt file / OpenCV too old: remember, fall back for the rest of the session
            _FAILED.append(repr(e))
            raise
    return _NET[0]


def _guided(I, p, r, eps):
    def box(x):
        return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1))
    mI, mp = box(I), box(p)
    a = (box(I * p) - mI * mp) / (box(I * I) - mI * mI + eps)
    return box(a) * I + box(p - a * mI)


def relative_depth(img8):
    """img8: BGR uint8 (any size). Returns float32 map of the same size, 0 = far .. 1 = nearest (p99.5),
    edges snapped to the image with a guided filter. Raises when the model cannot run."""
    H, W = img8.shape[:2]
    s = SIDE / min(H, W)
    if max(H, W) * s > LONG_MAX:
        s = LONG_MAX / max(H, W)
    h, w = (max(14, int(round(v * s / 14)) * 14) for v in (H, W))
    rgb = cv2.cvtColor(img8, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = (cv2.resize(rgb, (w, h), interpolation=cv2.INTER_CUBIC) - MEAN) / STD
    net = _net()
    net.setInput(x.transpose(2, 0, 1)[None].astype(np.float32))
    d = np.squeeze(net.forward()).astype(np.float32)          # relative disparity (larger = nearer)
    d = np.maximum(d, 0)
    d /= max(float(np.percentile(d, 99.5)), 1e-6)
    # snap edges to the picture at a working size, then resize to the full image
    sw = min(1.0, WORK / max(H, W))
    ws = (max(1, int(round(W * sw))), max(1, int(round(H * sw))))
    small = cv2.resize(img8, ws, interpolation=cv2.INTER_AREA)
    guide = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    dd = cv2.resize(d, ws, interpolation=cv2.INTER_CUBIC)
    dd = _guided(guide, dd, max(2, int(round(4 * ws[0] / 960))), 2e-3)
    return np.clip(cv2.resize(dd, (W, H), interpolation=cv2.INTER_LINEAR), 0, 1.2).astype(np.float32)
