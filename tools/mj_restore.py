# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""
mj_restore.py  v4.3.1  把 GPT 修正图的色彩 / 明暗 / 雾气 / 虚化 / 柔光 / 颗粒还原到 MJ 原图

输出是 GPT 画布尺寸；GPT 的裁切 / 外扩 / 平移会自动对齐；MJ 覆盖不到的区域（GPT 外扩、补黑边）
按邻近区域平滑外推校正。

用法:
  python mj_restore.py MJ原图 GPT输出 输出.png [选项]

模式:
  --mode composite  (默认) 以 MJ 原图为底，只把 GPT 改动过的区域贴回来；
                    贴片的颜色、虚化、颗粒按周围 MJ 匹配。MJ 美学保真度最高。
  --mode transfer   保留 GPT 全图结构，把 MJ 的颜色、局部明暗、雾气、虚化、颗粒迁移过去。
                    适合 GPT 改动范围很大、不方便贴片的情况。

选项:
  --mask 路径       手动蒙版（白=用 GPT，黑=用 MJ），按 GPT 图的画面来画，尺寸任意（会缩放到 GPT 画布）；
                    提供时不做自动检测。
  --thr 数值        自动检测改动的灵敏度，越小越敏感（默认 3.5）。
  --size gpt|mj     输出尺寸：gpt（默认，和 GPT 出图一样大）/ mj（缩到 MJ 原图的像素密度）。
  --debug           额外输出改动区域图和对比拼图，并打印还原前后的指标。
  --force           配对检查不通过时仍强制还原（一般不要用）。
"""
from i18n import tr
import argparse
import os

import cv2
import numpy as np

from mj_io import InputError, imread_alpha, imread_u, imwrite_u, with_alpha

SIG_LEVELS = [0, 0.5, 0.8, 1.2, 1.7, 2.4, 3.3, 4.5]   # blur levels (MJ px) the blur matcher picks from
LUT_N = 17              # 3D colour LUT size per axis
RESID_SIGMA = 0.005     # low-frequency colour / tone / haze residual, fraction of the diagonal
BLUR_PRE = 1.2          # pre-smoothing for the blur-matching edge energy (MJ px)


class PairMismatch(InputError):
    """The MJ reference and the GPT image are not the same picture."""


# ---------------------------------------------------------------- basics
def to_f(img):
    return img.astype(np.float32) / 255.0


def to_u8(img):
    return np.clip(img * 255.0 + 0.5, 0, 255).astype(np.uint8)


def lum(img_f):
    return cv2.cvtColor(img_f, cv2.COLOR_BGR2LAB)[..., 0]


def gblur(x, s):
    if s <= 0:
        return x
    return cv2.GaussianBlur(x, (0, 0), s)


def highpass(L):
    """Sigma-1 high-pass: what every grain measurement in the tool uses."""
    return L - gblur(L, 1.0)


def fill_smooth(val, w, sigma):
    """Normalized convolution; progressively larger sigma fills big holes."""
    wv = w[..., None] if val.ndim == 3 else w
    out = np.zeros_like(val)
    done = np.zeros(w.shape, bool)
    s = sigma
    for _ in range(6):
        num = gblur(val * wv, s)
        den = gblur(w, s)
        ok = (den > 1e-3) & ~done
        out[ok] = num[ok] / (den[ok][:, None] if val.ndim == 3 else den[ok])
        done |= ok
        if done.all():
            break
        s *= 2.5
    return out


# ---------------------------------------------------------------- letterbox / pillarbox bars
# 不看原始噪点，而看“平滑后是否平”：噪点被平滑压掉，真实画面的结构压不掉。再加两道保险：黑边必须在
# 几行内突然结束（渐变的暗部不算），边界必须是横贯画面的直线（天际线等不规则轮廓不算）。
# 实测：合成黑边 2100 例检出 96%（旧的“行均值 ≤ 12”规则 6%），漏检 0；真实暗部边缘 168 例误判 0；
# 19 张标定图结果与旧规则完全一致。已知局限：黑边紧挨着几乎同样亮度的画面时，那一侧会漏检。
BAR_BLACK_MAX = 48      # 偏灰黑边上限（限幅后 28 级黑边会到 40）
BAR_WHITE_MIN = 207
BAR_LEVEL_TOL = 3.0     # 黑边内部各行亮度几乎不变
BAR_FLAT_MAX = 4.0      # 平滑后行内起伏（p90-p10）。实测：强噪点黑边 ≤2.0、强颗粒 ≤3.9；真实暗部 ≥4.3
BAR_STEP = 6.0          # 进入画面：行亮度跳变
BAR_CONTENT_FLAT = 8.0  # 或行内出现明显结构
BAR_MIN = 2
BAR_LIMIT = 0.45        # 单侧最多 45%
BAR_SMOOTH = 8.0        # 横向平滑 σ（像素）
BAR_SMOOTH_Y = 2.0      # 判断“平不平”时再加一点纵向平滑，消掉行与行之间的随机噪点


def _bar_row_stats(g, sy=0.0):
    kx = int(2 * round(3 * BAR_SMOOTH) + 1)
    ky = int(2 * round(3 * sy) + 1) if sy > 0 else 1
    gx = cv2.GaussianBlur(g, (kx, ky), sigmaX=BAR_SMOOTH, sigmaY=sy if sy > 0 else 0)
    m = np.median(gx, axis=1)
    p10, p90 = np.percentile(gx, [10, 90], axis=1)
    return m, p90 - p10


def _bar_straight(g, L0, lo, hi):
    """边界必须是一条横贯画面的直线（黑边），而不是天际线之类的不规则轮廓。"""
    win = cv2.GaussianBlur(g[lo:hi], (0, 0), 1.5)[:, ::4]
    dev = np.abs(win - L0)
    mx = dev.max(axis=0)
    has = mx > BAR_STEP
    if has.mean() < 0.3:
        return False
    cross = (dev >= 0.5 * mx[None, :]).argmax(axis=0)[has]   # 每列越过半高的位置（不受振铃影响）
    return float(np.mean(np.abs(cross - np.median(cross)) <= 3)) >= 0.8


def _bar_rows(g):
    """从 g 的上边缘起，算作人工黑/白边的行数；没有则 0。"""
    H, W = g.shape
    lim = int(H * BAR_LIMIT)
    if lim < BAR_MIN or W < 16:
        return 0
    T = int(max(6, round(H * 0.011)))                  # 允许的过渡行（缩放软边、JPEG 振铃）
    sub = g[:min(H, lim + T + 4)]
    ms, fs = _bar_row_stats(sub, BAR_SMOOTH_Y)         # 判断黑边：横纵都平滑，抗噪点
    m, flat = _bar_row_stats(sub)                      # 定位边界：只横向平滑，边界不被抹软
    L0 = float(np.median(ms[:2]))
    if not (L0 <= BAR_BLACK_MAX or L0 >= BAR_WHITE_MIN):
        return 0

    def is_bar(i):
        return abs(ms[i] - L0) <= BAR_LEVEL_TOL and fs[i] <= BAR_FLAT_MAX

    n = i = 0
    while i < lim:
        if is_bar(i):
            i += 1
            n = i
        elif i + 1 < lim and is_bar(i + 1):            # 容忍单行偶然超标
            i += 1
        else:
            break
    if n < BAR_MIN:
        return 0
    r = None
    for i in range(n, min(len(m), n + T)):             # 必须在 T 行内明确进入画面（突变），渐变的暗部不算
        if abs(m[i] - L0) > BAR_STEP or flat[i] > BAR_CONTENT_FLAT:
            r = i
            break
    if r is None:
        return 0
    if not _bar_straight(g, L0, max(0, n - 2), min(H, r + T)):
        return 0
    return r


def bar_box(img_u8):
    """Letterbox / pillarbox detection. Returns (y0, y1, x0, x1) of the picture area."""
    g = cv2.cvtColor(img_u8, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = g.shape
    y0 = _bar_rows(g)
    y1 = H - _bar_rows(g[::-1])
    if y1 - y0 < H * 0.1:
        y0, y1 = 0, H
    x0 = _bar_rows(np.ascontiguousarray(g[y0:y1].T))
    x1 = W - _bar_rows(np.ascontiguousarray(g[y0:y1, ::-1].T))
    if x1 - x0 < W * 0.1:
        x0, x1 = 0, W
    return y0, y1, x0, x1


def picture_mask(img_u8):
    """True inside the picture area (letterbox bars excluded)."""
    y0, y1, x0, x1 = bar_box(img_u8)
    v = np.zeros(img_u8.shape[:2], bool)
    v[y0:y1, x0:x1] = True
    return v


# ---------------------------------------------------------------- 1. alignment
# 坐标约定：像素中心在整数坐标上（cv2.warpAffine 的约定）；缩放 (sx, sy) 后的图里，原坐标 x 在 sx*x + 0.5*sx - 0.5
# （cv2.resize 的约定）。所有换算都按这个来，否则会有零点几个像素的系统偏移（GPT 比 MJ 大 1.9 倍时约 0.44 个 GPT 像素）。
SHRINK_AA = 0.95        # 变换把源图缩小到这个比例以下时，先用 INTER_AREA 缩小（抗锯齿），再做剩下的仿射


def _m3(M):
    return np.vstack([np.asarray(M, np.float64)[:2], [0.0, 0.0, 1.0]])


def scale_mat(sx, sy):
    """Pixel-centre mapping: coords in an image -> coords in that image resized by (sx, sy)."""
    return np.array([[sx, 0.0, 0.5 * sx - 0.5], [0.0, sy, 0.5 * sy - 0.5], [0.0, 0.0, 1.0]])


def warp_affine(src, M, size, interp=cv2.INTER_LINEAR, border=cv2.BORDER_CONSTANT, value=0):
    """cv2.warpAffine with M mapping src -> dst pixel coords. When the warp shrinks src (by more than SHRINK_AA),
    src is first reduced with INTER_AREA so fine detail and grain are averaged instead of aliased
    (warpAffine itself silently treats INTER_AREA as plain bilinear)."""
    S = _m3(M)
    k = float(np.sqrt(abs(np.linalg.det(S[:2, :2]))))          # dst px per src px
    if k < SHRINK_AA:
        h, w = src.shape[:2]
        ws, hs = max(1, int(round(w * k))), max(1, int(round(h * k)))
        src = cv2.resize(src, (ws, hs), interpolation=cv2.INTER_AREA)
        S = S @ np.linalg.inv(scale_mat(ws / w, hs / h))
    return cv2.warpAffine(src, S[:2], size, flags=interp, borderMode=border, borderValue=value)
def estimate_warp(mj8, g8, work=1000, mj_box=None):
    """2x3 affine F mapping GPT pixel coords -> MJ pixel coords (handles GPT crop / zoom / shift).
    GPT 按提示词把某一侧黑边补成画面时，那一侧的 MJ 黑边不参与对齐——否则整图匹配会把 MJ 画面
    硬拉伸去填满 GPT 画布（实测纵向拉伸约 16% 并带斜切）。GPT 也保留着的黑边是两边共有的直线，
    照常参与对齐（实测这样内容对得更准）。MJ 没有黑边时不受影响。"""
    Hm, Wm = mj8.shape[:2]
    Hg, Wg = g8.shape[:2]
    if mj_box is None:
        mj_box = bar_box(mj8)
    sm = work / max(Hm, Wm)
    sg = work / max(Hg, Wg)
    a = cv2.cvtColor(cv2.resize(mj8, None, fx=sm, fy=sm, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(g8, None, fx=sg, fy=sg, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    y0, y1, x0, x1 = mj_box
    ma = None                                    # 屏蔽 MJ 一侧（ECC 的 inputMask 作用于 MJ）
    if (y0, y1, x0, x1) != (0, Hm, 0, Wm):
        gy0, gy1, gx0, gx1 = bar_box(g8)
        cut = [side for side, mj_bar, gpt_bar in (('top', y0 > 0, gy0 > 0), ('bottom', y1 < Hm, gy1 < Hg),
                                                  ('left', x0 > 0, gx0 > 0), ('right', x1 < Wm, gx1 < Wg))
               if mj_bar and not gpt_bar]
        if cut:
            ma = np.full(a.shape, 255, np.uint8)
            h, w, m = a.shape[0], a.shape[1], 3          # m：交界线本身也不用
            if 'top' in cut:
                ma[:min(h, int(np.ceil(y0 * sm)) + m)] = 0
            if 'bottom' in cut:
                ma[max(0, int(y1 * sm) - m):] = 0
            if 'left' in cut:
                ma[:, :min(w, int(np.ceil(x0 * sm)) + m)] = 0
            if 'right' in cut:
                ma[:, max(0, int(x1 * sm) - m):] = 0
    # init: plain stretch of canvas onto canvas (pixel-centre exact)
    sx, sy = a.shape[1] / b.shape[1], a.shape[0] / b.shape[0]
    A = np.array([[sx, 0, 0.5 * sx - 0.5], [0, sy, 0.5 * sy - 0.5]], np.float32)
    how = tr('按尺寸缩放')
    try:
        orb = cv2.ORB_create(5000)
        ka, da = orb.detectAndCompute(a, ma)
        kb, db = orb.detectAndCompute(b, None)
        if da is not None and db is not None and len(ka) > 50 and len(kb) > 50:
            mt = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(db, da, k=2)
            good = [m[0] for m in mt if len(m) == 2 and m[0].distance < 0.8 * m[1].distance]
            if len(good) >= 30:
                pb = np.float32([kb[m.queryIdx].pt for m in good])
                pa = np.float32([ka[m.trainIdx].pt for m in good])
                M, inl = cv2.estimateAffinePartial2D(pb, pa, method=cv2.RANSAC, ransacReprojThreshold=3)
                if M is not None and inl.sum() >= 25:
                    A = M.astype(np.float32)
                    how = tr('特征点（{v} 点）', v=int(inl.sum()))
    except cv2.error:
        pass
    try:
        _, A2 = cv2.findTransformECC(b.astype(np.float32) / 255, a.astype(np.float32) / 255, A.copy(),
                                     cv2.MOTION_AFFINE,
                                     (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), ma, 5)
        A = A2
        how += tr(' + ECC 精对齐')
    except cv2.error:
        how += tr('（ECC 未收敛）')
    # A maps the work-size GPT image onto the work-size MJ image; convert to full-size pixel coords
    Ta = scale_mat(a.shape[1] / Wm, a.shape[0] / Hm)
    Tb = scale_mat(b.shape[1] / Wg, b.shape[0] / Hg)
    return (np.linalg.inv(Ta) @ _m3(A) @ Tb)[:2], how


def _out_to_mj(F, gpt_size, out_size):
    """3x3 map: pixel coords of the GPT canvas resized to out_size -> MJ pixel coords."""
    D = scale_mat(out_size[0] / gpt_size[0], out_size[1] / gpt_size[1])
    return _m3(F) @ np.linalg.inv(D)


def warp_mj(mj, F, gpt_size, out_size, interp=cv2.INTER_CUBIC):
    """Resample MJ onto the GPT canvas resized to out_size (W, H). Anti-aliased when that shrinks MJ."""
    return warp_affine(mj, np.linalg.inv(_out_to_mj(F, gpt_size, out_size)), out_size, interp, cv2.BORDER_REPLICATE)


def footprint(mj_valid, F, gpt_size, out_size):
    """Where the MJ picture area lands on that grid (eroded a little so the border is safely inside)."""
    m = cv2.warpAffine(mj_valid.astype(np.uint8) * 255, _out_to_mj(F, gpt_size, out_size)[:2], out_size,
                       flags=cv2.INTER_NEAREST + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return cv2.erode(m, np.ones((5, 5), np.uint8)) > 127


# ---- 配错参考图拦截
# 20 组正常配对：结构相关 >= 0.908、MJ 覆盖 >= 92.7%；故意配错的一组：0.44 / 38%，且特征点对齐失败。
PAIR_CORR_MIN = 0.80     # 低于此值判定为不是同一张图，停止
PAIR_COVER_MIN = 0.50    # MJ 覆盖低于此值停止（GPT 外扩过多或配错）
PAIR_COVER_WARN = 0.80   # 介于两者之间只提醒（GPT 外扩/补黑边属于正常用法）


def _pair_corr(ms, gs, vs):
    """Correlation of heavily smoothed luminance inside the MJ footprint (focus/colour-insensitive)."""
    if vs.sum() < 100:
        return float('nan')
    a = gblur(cv2.cvtColor(ms.astype(np.float32), cv2.COLOR_BGR2GRAY), 3)[vs]
    b = gblur(cv2.cvtColor(gs.astype(np.float32), cv2.COLOR_BGR2GRAY), 3)[vs]
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 1.0 if abs(float(a.mean() - b.mean())) < 0.05 else float('nan')
    return float(np.corrcoef(a, b)[0, 1])


def how_by_features(how):
    """对齐方式是“特征点”（不是退回按尺寸缩放）。中英文界面的说明文字都认（英文译文里有 feature）。"""
    return '特征点' in how or 'feature' in how.lower()


def check_pair(corr, coverage, how):
    """Returns (ok, message). message is also a warning when ok is True but coverage is low."""
    if not np.isfinite(corr) or corr < PAIR_CORR_MIN or coverage < PAIR_COVER_MIN:
        reason = (tr('结构相关 {corr:.2f}（正常 ≥ {PAIR_CORR_MIN:.2f}），MJ 覆盖 {v:.0f}%', corr=corr, PAIR_CORR_MIN=PAIR_CORR_MIN, v=coverage * 100)
                  + ('' if how_by_features(how) else tr('，特征点对齐失败')))
        return False, (tr('两张图对不上：') + reason + tr('。\n多半是 MJ 参考图选错了：请确认选的是交给 GPT 的那一张 MJ 图（宫格图要选切出来的同一格）。为避免输出错位拼贴，本次已停止，也不会加入标定。'))
    if coverage < PAIR_COVER_WARN:
        return True, (tr('[提醒] MJ 原图只覆盖 GPT 画面的 {v:.0f}%，其余是 GPT 外扩的区域，那部分只能按邻近区域推算。', v=coverage * 100))
    return True, ''


# ---- 换头（①页“修错 + 换头”）：主角的头是新画的，位置、脸型、发型都和 MJ 旧头不一样
# V4.5.1：头部范围 = GPT 新头（头发 + 脸）∪ MJ 旧头，用 mj_head 按人脸 + GrabCut 分出来（失败时退回下面的椭圆）。
#  · 头部范围不参加按位置的统计（配对检查、色彩映射、局部明暗、虚化、颗粒），旁边的背景按周围背景推算——
#    否则 MJ 旧头会被“印”到新头和背景上（实测：发际边一圈暗影、脸颊边被压暗）；
#  · GPT 的头发 / 皮肤 / 嘴唇按 MJ 同类区域还原颜色和明暗（mj_head.recolor），长相仍是 GPT 的。
# V4.5 只做了“头部不混入旧头”，头部只剩整体色彩映射，发色、肤色没有还原到 MJ（用户反馈），已改。
HEAD_CY, HEAD_AX, HEAD_AY = 0.40, 0.80, 0.85
HEAD_PAIR_K = 1.4
HEAD_PAD = 0.012          # 头部范围向外扩（画面对角线的比例），盖住发丝边缘的过渡


def head_mask(img_f, k=1.0):
    """The largest face's whole head (face + hair) as a bool mask on img_f's grid; None when no face is found."""
    import mj_face
    faces = mj_face.detect_faces(to_u8(img_f))
    if not faces:
        return None
    x, y, w, h = faces[0]['box']
    m = np.zeros(img_f.shape[:2], np.uint8)
    cv2.ellipse(m, (int(round(x + w / 2)), int(round(y + h * HEAD_CY))),
                (max(1, int(w * HEAD_AX * k)), max(1, int(h * HEAD_AY * k))), 0, 0, 360, 1, -1)
    return m > 0


def _heads(gs, ms, vs, k):
    """Union of the main head in GPT and in the (aligned) MJ image: the old head must go, the new one must stay."""
    ms_in = ms * vs[..., None]
    out = None
    for img in (gs, ms_in):
        m = head_mask(img, k)
        if m is not None:
            out = m if out is None else out | m
    return out


def swap_kind(swap):
    """True / 'head' -> 'head'（换头），'person' -> 'person'（换整个角色），其余 -> None。"""
    return 'person' if swap == 'person' else ('head' if swap else None)


def _person_box(img_f):
    """Fallback figure region from the largest face: head ellipse x1.4 + a column under the face."""
    import mj_face
    faces = mj_face.detect_faces(to_u8(img_f))
    if not faces:
        return None
    x, y, w, h = faces[0]['box']
    H, W = img_f.shape[:2]
    m = head_mask(img_f, HEAD_PAIR_K)
    cx = x + w / 2
    m[int(y + h / 2):, int(max(0, cx - 2.6 * w)):int(min(W, cx + 2.6 * w))] = True
    return m


def _head_zone(mj8, g8, F, Wg, Hg, Ws, Hs, vs, kind='head'):
    """(zone on the analysis grid, parts dict(g, m) or None). zone = GPT's new head ∪ MJ's old head (hair + face),
    padded; kind='person': the whole new figure ∪ the whole old one. Falls back to face-based shapes when the
    figures cannot be segmented."""
    import mj_head
    parts = mj_head.person_parts if kind == 'person' else mj_head.head_parts
    gp, mp = parts(g8), parts(mj8)
    if gp is None or mp is None:
        gs = to_f(cv2.resize(g8, (Ws, Hs), interpolation=cv2.INTER_AREA))
        ms = to_f(warp_mj(mj8, F, (Wg, Hg), (Ws, Hs)))
        if kind == 'person':
            zs = [z for z in (_person_box(gs), _person_box(ms * vs[..., None])) if z is not None]
            return (np.logical_or.reduce(zs) if zs else None), None
        return _heads(gs, ms, vs, HEAD_PAIR_K), None
    zg = cv2.resize(gp['char'], (Ws, Hs), interpolation=cv2.INTER_AREA) > 0.3
    zm = warp_mj(mp['char'].astype(np.float32), F, (Wg, Hg), (Ws, Hs), cv2.INTER_LINEAR) > 0.3
    k = max(5, int(np.hypot(Ws, Hs) * HEAD_PAD)) | 1
    zone = cv2.dilate((zg | (zm & vs)).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    return zone, dict(g=gp, m=mp)


def prepare(mj8, g8, swap=False):
    """Align MJ onto the GPT canvas and resample both to the analysis grid (GPT canvas at MJ pixel density),
    then check that they are the same picture. Shared by restore(), the calibration and tab ④.
    swap=True / 'head'（换头）：配对检查不计主角头部；结果里的 'head' 是头部范围（还原时整块按 GPT 改动处理）。
    swap='person'（换整个角色）：同上，范围是整个人物（新人物 ∪ 旧人物）。"""
    kind = swap_kind(swap)
    Hg, Wg = g8.shape[:2]
    box = bar_box(mj8)
    y0, y1, x0, x1 = box
    mj_valid = np.zeros(mj8.shape[:2], bool)
    mj_valid[y0:y1, x0:x1] = True
    F, how = estimate_warp(mj8, g8, mj_box=box)
    lin = float(np.sqrt(abs(np.linalg.det(F[:, :2]))))          # MJ px per GPT px
    r = min(1.0, lin)                                           # analysis grid = MJ density
    Ws, Hs = int(round(Wg * r)), int(round(Hg * r))
    gs = to_f(cv2.resize(g8, (Ws, Hs), interpolation=cv2.INTER_AREA))
    ms = to_f(warp_mj(mj8, F, (Wg, Hg), (Ws, Hs)))
    vs = footprint(mj_valid, F, (Wg, Hg), (Ws, Hs))
    head, parts = (_head_zone(mj8, g8, F, Wg, Hg, Ws, Hs, vs, kind) if kind else (None, None))
    vc = vs & ~head if head is not None and (vs & ~head).mean() > 0.2 else vs
    corr, cov = _pair_corr(ms, gs, vc), float(vs.mean())
    ok, msg = check_pair(corr, cov, how)
    return dict(F=F, how=how, lin=lin, r=r, Ws=Ws, Hs=Hs, gs=gs, ms=ms, vs=vs,
                corr=corr, coverage=cov, ok=ok, message=msg, swap=kind, head=head, head_parts=parts,
                head_share=float(head.mean()) if head is not None else 0.0)


def pair_quality(mj8, g8, swap=False):
    """prepare() result; 'ok' / 'message' / 'corr' / 'coverage' tell whether the two images match."""
    return prepare(mj8, g8, swap)


# ---------------------------------------------------------------- 2. colour LUT
def gaussian_filter(v, sigma):
    """Separable 3D gaussian on a small LUT volume (numpy only; edge = nearest)."""
    r = int(3 * sigma + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    out = v.astype(np.float64)
    for ax in range(3):
        pad = [(0, 0)] * 3
        pad[ax] = (r, r)
        p = np.pad(out, pad, mode='edge')
        out = sum(k[i] * np.take(p, np.arange(i, i + v.shape[ax]), axis=ax) for i in range(2 * r + 1))
    return out


def fit_lut(src, ref, valid):
    """Smooth 3D colour LUT (offsets) GPT -> MJ, fitted on lightly blurred images so grain is not amplified.
    Empty cells are filled from neighbours and then fade to the global offset (no wild extrapolation)."""
    a = gblur(src, 1.5).reshape(-1, 3)
    b = gblur(ref, 1.5).reshape(-1, 3)
    idx = np.flatnonzero(valid.ravel())
    rng = np.random.default_rng(0)
    if idx.size > 600000:
        idx = rng.choice(idx, 600000, replace=False)
    x = a[idx]
    d = b[idx] - a[idx]
    # drop the worst 15 % residuals (misregistered / changed pixels)
    med = np.median(d, 0)
    e = np.linalg.norm(d - med, axis=1)
    k = e < np.percentile(e, 85)
    x, d = x[k], d[k]
    n = LUT_N
    q = np.clip(np.rint(x * (n - 1)).astype(int), 0, n - 1)
    flat = (q[:, 0] * n + q[:, 1]) * n + q[:, 2]
    cnt = np.bincount(flat, minlength=n ** 3).astype(np.float32).reshape(n, n, n)
    acc = np.stack([np.bincount(flat, d[:, c], minlength=n ** 3) for c in range(3)], 1).astype(np.float32)
    acc = acc.reshape(n, n, n, 3)
    g = np.median(d, 0).astype(np.float32)
    w = np.minimum(cnt / 20.0, 1.0)
    mean = acc / np.maximum(cnt, 1)[..., None]
    out = np.zeros_like(mean)
    for c in range(3):
        num = mean[..., c] * w
        den = w.copy()
        nn, dd = gaussian_filter(num, 1.0), gaussian_filter(den, 1.0)
        nn2, dd2 = gaussian_filter(num, 3.0), gaussian_filter(den, 3.0)
        v1 = nn / np.maximum(dd, 1e-6)
        v2 = nn2 / np.maximum(dd2, 1e-6)
        a1 = np.clip(dd / 0.3, 0, 1)
        a2 = np.clip(dd2 / 0.05, 0, 1)
        far = v2 * a2 + g[c] * (1 - a2)
        out[..., c] = v1 * a1 + far * (1 - a1)
    return out.astype(np.float32)


def apply_lut(img, lut):
    """img + trilinear interpolation of the LUT offsets. The LUT is laid out as an (n*n) x n image (rows = axis 0
    and 1, columns = axis 2), so the lookup is two bilinear cv2.remap calls plus one linear blend along axis 0 —
    the same values as an explicit 8-corner trilinear sum (< 0.001 level apart), about 6x faster."""
    n = lut.shape[0]
    x = np.clip(img, 0, 1) * (n - 1)
    i0 = np.minimum(x[..., 0].astype(np.int32), n - 2)
    f0 = (x[..., 0] - i0)[..., None]
    plane = np.ascontiguousarray(lut.reshape(n * n, n, 3), np.float32)
    mx = np.ascontiguousarray(x[..., 2], np.float32)
    row = (i0 * n).astype(np.float32) + x[..., 1]
    lo = cv2.remap(plane, mx, np.ascontiguousarray(row), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    hi = cv2.remap(plane, mx, np.ascontiguousarray(row + n), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return np.clip(img + lo * (1 - f0) + hi * f0, 0, 1).astype(np.float32)


# ---------------------------------------------------------------- 3. change detection
def _ellipse(s):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (s, s))


def detect_changes(mj, g1, valid, thr):
    valid = cv2.erode(valid.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)  # ignore bar borders
    Lm, Lg = lum(mj), lum(g1)
    bm = gblur(Lm, 1.5) - gblur(Lm, 12)
    bg = gblur(Lg, 1.5) - gblur(Lg, 12)
    d_struct = gblur(np.abs(bm - bg), 4)
    d_color = gblur(np.linalg.norm(cv2.cvtColor(gblur(mj, 3), cv2.COLOR_BGR2LAB) -
                                   cv2.cvtColor(gblur(g1, 3), cv2.COLOR_BGR2LAB), axis=2), 4)
    v = d_struct[valid]
    med = np.median(v)
    mad = np.median(np.abs(v - med)) * 1.4826 + 1e-6
    k = max(3, int(round(min(mj.shape[:2]) * 0.004)))
    # seeds: clearly changed; grow: moderately different and connected to a seed (hysteresis)
    seed = (((d_struct > med + thr * mad * 2.0) | (d_color > 18)) & valid).astype(np.uint8)
    seed = cv2.morphologyEx(seed, cv2.MORPH_OPEN, _ellipse(k))
    grow = ((d_struct > med + thr * mad * 1.1) & valid).astype(np.uint8)
    grow = cv2.morphologyEx(grow, cv2.MORPH_CLOSE, _ellipse(3 * k)) | seed
    n, lab_, st, _ = cv2.connectedComponentsWithStats(grow)
    min_area = mj.shape[0] * mj.shape[1] * 0.0004
    keep = np.zeros_like(grow)
    for i in np.unique(lab_[seed > 0]):
        if i > 0 and st[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab_ == i] = 1
    # fill holes so a changed object is taken as a whole, not as patches
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, _ellipse(4 * k))
    cnts, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(keep)
    cv2.drawContours(filled, cnts, -1, 1, thickness=-1)
    return filled.astype(bool)


# ---------------------------------------------------------------- 4. per-tile statistics
def tile_stat(fn, H, W, tile, weight):
    """fn(slice) on every tile x tile block (from the top-left) that is > 60 % covered by `weight`."""
    gh, gw = int(np.ceil(H / tile)), int(np.ceil(W / tile))
    val = np.zeros((gh, gw), np.float32)
    wt = np.zeros((gh, gw), np.float32)
    for i in range(gh):
        for j in range(gw):
            sl = (slice(i * tile, min(H, (i + 1) * tile)), slice(j * tile, min(W, (j + 1) * tile)))
            if weight[sl].mean() > 0.6:
                val[i, j] = fn(sl)
                wt[i, j] = 1
    return val, wt


def tile_sum(x, tile):
    """Sum over the same tile x tile blocks as tile_stat (from the top-left; partial blocks at the edges)."""
    H, W = x.shape[:2]
    gh, gw = int(np.ceil(H / tile)), int(np.ceil(W / tile))
    p = np.zeros((gh * tile, gw * tile), np.float64)
    p[:H, :W] = x
    return p.reshape(gh, tile, gw, tile).sum((1, 3))


def tile_cover(mask, tile):
    """Fraction of each tile that is inside `mask`."""
    return tile_sum(mask.astype(np.float32), tile) / tile_sum(np.ones(mask.shape, np.float32), tile)


def grid_up(grid, H, W, tile, interp=cv2.INTER_LINEAR):
    """Map a per-tile grid onto H x W pixels with every tile centre at its true position (tile may be fractional,
    e.g. the analysis tile measured in full-resolution pixels). Plain cv2.resize would spread the cells evenly over
    the image, which drifts by up to almost a tile toward the right / bottom edge."""
    xs = (np.arange(W, dtype=np.float32) + 0.5) / tile - 0.5
    ys = (np.arange(H, dtype=np.float32) + 0.5) / tile - 0.5
    mx = np.ascontiguousarray(np.broadcast_to(xs[None, :], (H, W)))
    my = np.ascontiguousarray(np.broadcast_to(ys[:, None], (H, W)))
    return cv2.remap(np.ascontiguousarray(grid, np.float32), mx, my, interp, borderMode=cv2.BORDER_REPLICATE)


def distance_weight(valid, reach):
    """1 inside the MJ reference, smoothly decaying to 0 at `reach` px outside it."""
    d = cv2.distanceTransform((~valid).astype(np.uint8), cv2.DIST_L2, 5)
    return np.exp(-(d / max(reach, 1.0)) ** 2).astype(np.float32)


def fill_grid(val, wt, valid, tile):
    """Fill tiles without a measurement from confident neighbours (weight > 0.5); outside the MJ reference
    fade toward the median measured value."""
    filled = fill_smooth(val, wt, 1.0)
    med = float(np.median(val[wt > 0.5])) if (wt > 0.5).any() else 0.0
    k = distance_weight(tile_cover(valid, tile) > 0.3, 3.0)
    return filled * k + med * (1 - k)


def extrapolate(val, w, sigma, valid, reach):
    """Fill `val` (known where w>0) everywhere; far from the reference fade to the global average."""
    near = fill_smooth(val, w, sigma)
    wv = w if val.ndim == 2 else w[..., None]
    glob = (val * wv).reshape(-1, *val.shape[2:]).sum(0) / max(w.sum(), 1e-6)
    k = distance_weight(valid, reach)
    if val.ndim == 3:
        k = k[..., None]
    return (near * k + glob * (1 - k)).astype(np.float32)


# ---------------------------------------------------------------- 5. focus-safe blur matching
# 每个分块把 GPT 模糊到和 MJ 一样的边缘能量，但：
#  1. MJ 自己的虚化用 mj_measure 的再模糊估计（与反差无关）测量；MJ 里清晰的分块最多只补 SHARP_CAP_SIG 的模糊
#     （否则 GPT 多画的细节、多加的局部反差会被误读成“MJ 更虚”，清晰的主体被糊掉）；
#  2. 先用平滑的 DIS 光流把 MJ 局部对齐到 GPT，再做分块统计；
#  3. 结构对不上（GPT 重画过）的分块不测量，只从可信的邻块继承。
NCC_LO, NCC_HI = 0.35, 0.65       # band-pass structure correlation: no vote below, full vote above
SOFTER_LO, SOFTER_HI = 0.3, 1.2   # MJ-minus-GPT defocus (2048 scale) where blur matching starts / is fully allowed
MJ_SIG_Q = 50                     # tile defocus = median of edge estimates
MJ_EVID_MIN = 0.25                # MJ tile readings below this (2048 scale) count as 'no evidence'
SHARP_CAP_SIG = 0.8               # max extra blur (MJ px) in tiles that are sharp in MJ


def fine_energy_map(L):
    g = gblur(L, BLUR_PRE)
    return np.sqrt(cv2.Sobel(g, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(g, cv2.CV_32F, 0, 1) ** 2)


def local_align(ms, gs, tile):
    """Warp MJ (already globally aligned) onto GPT with smoothed dense flow. Returns warped MJ, flow."""
    a = cv2.cvtColor(to_u8(gs), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(to_u8(ms), cv2.COLOR_BGR2GRAY)
    try:
        fl = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM).calc(a, b, None)
    except cv2.error:
        return ms, np.zeros(ms.shape[:2] + (2,), np.float32)
    s = tile * 0.75
    fl = np.dstack([gblur(fl[..., 0], s), gblur(fl[..., 1], s)])
    cap = 0.02 * np.hypot(*ms.shape[:2])
    mag = np.hypot(fl[..., 0], fl[..., 1])
    fl = (fl * np.minimum(1, cap / np.maximum(mag, 1e-6))[..., None]).astype(np.float32)
    H, W = ms.shape[:2]
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    out = cv2.remap(ms, gx + fl[..., 0], gy + fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out.astype(np.float32), fl


def mj_defocus_grid(img, valid, H, W, tile):
    """Per-tile median defocus sigma (px), NaN where no edges."""
    import mj_measure
    m8 = to_u8(img)
    E = mj_measure.edge_mask(m8, valid)
    sig = mj_measure.blur_sigma_at(m8, E)
    ys, xs = np.nonzero(E)
    gh, gw = int(np.ceil(H / tile)), int(np.ceil(W / tile))
    g = np.full((gh, gw), np.nan, np.float32)
    tid = (ys // tile) * gw + (xs // tile)
    ok = np.isfinite(sig)
    for t in np.unique(tid[ok]):
        v = sig[ok][tid[ok] == t]
        if v.size >= 15:
            g.flat[t] = np.percentile(v, MJ_SIG_Q)
    return g


def struct_conf_grid(a, b, H, W, tile):
    """Band-pass NCC per tile between two same-grid images (both pre-blurred, so focus differences
    matter little and content differences dominate)."""
    def band(x):
        L = lum(x)
        return gblur(L, 2.0) - gblur(L, 6.0)
    A, B = band(a), band(b)
    gh, gw = int(np.ceil(H / tile)), int(np.ceil(W / tile))
    c = np.zeros((gh, gw), np.float32)
    for i in range(gh):
        for j in range(gw):
            sl = (slice(i * tile, min(H, (i + 1) * tile)), slice(j * tile, min(W, (j + 1) * tile)))
            x = A[sl] - A[sl].mean()
            y = B[sl] - B[sl].mean()
            d = np.sqrt((x * x).sum() * (y * y).sum())
            c[i, j] = (x * y).sum() / d if d > 1e-6 else 1.0   # flat tile: nothing to disagree on
    return c


def blur_levels_map(P, ref, stat_w, valid, tile):
    """Per pixel index into SIG_LEVELS so that blurred P has the fine-edge energy of ref (same grid), but a
    tile only gets more than SHARP_CAP_SIG of blur when there is no evidence that MJ is as sharp as GPT there.
    Evidence = mj_measure's contrast-invariant re-blur estimator on both images; tiles where it finds no edges
    (dense blurred crowds, haze) keep plain energy matching."""
    H, W = ref.shape[:2]
    Em = fine_energy_map(lum(ref))
    Es = [fine_energy_map(lum(gblur(P, s))) for s in SIG_LEVELS]

    def pick(sl):
        target = Em[sl].mean()
        e = np.array([E[sl].mean() for E in Es])      # decreasing with blur level
        if e[0] <= target:
            return 0.0
        below = np.flatnonzero(e <= target)
        if below.size == 0:
            return float(len(e) - 1)
        k = int(below[0])
        t = (e[k - 1] - target) / max(e[k - 1] - e[k], 1e-6)
        return k - 1 + float(np.clip(t, 0, 1))

    conf = struct_conf_grid(ref, P, H, W, tile)
    val, wt = tile_stat(pick, H, W, tile, stat_w)
    wt = wt * np.clip((conf - NCC_LO) / (NCC_HI - NCC_LO), 0, 1)
    filled = fill_grid(val, wt, valid, tile)
    sm = mj_defocus_grid(ref, valid, H, W, tile)
    sp = mj_defocus_grid(P, valid, H, W, tile)
    sc = max(H, W) / 2048.0
    gate = np.clip(((sm - sp) / sc - SOFTER_LO) / (SOFTER_HI - SOFTER_LO), 0, 1)   # how much softer MJ is
    # no evidence -> plain energy matching: no edges found, or the estimator saturated at ~0 (it does that
    # on dense small detail such as blurred crowds, so a 0 reading is not proof of sharpness)
    evid = np.isfinite(sm) & np.isfinite(sp) & (np.nan_to_num(sm) / sc > MJ_EVID_MIN)
    gate = np.where(evid, np.nan_to_num(gate, nan=1.0), 1.0)
    # 4-neighbour margin round sharp tiles (a full 3x3 margin cost edge 1.03 -> 1.13 on pair 02)
    gate = cv2.erode(gate.astype(np.float32), cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3)))
    cap_lv = float(np.interp(SHARP_CAP_SIG, SIG_LEVELS, np.arange(len(SIG_LEVELS))))
    lv = np.minimum(filled, cap_lv + gate * (len(SIG_LEVELS) - 1 - cap_lv))
    lv = cv2.medianBlur(lv.astype(np.float32), 3)
    return np.clip(grid_up(lv, H, W, tile), 0, len(SIG_LEVELS) - 1)


def apply_blur_levels(P, kmap, px_scale):
    out = np.zeros_like(P)
    for k, s in enumerate(SIG_LEVELS):
        wk = np.clip(1.0 - np.abs(kmap - k), 0, 1)
        if wk.max() > 0:
            out += gblur(P, s * px_scale) * wk[..., None]
    return out.astype(np.float32)


# ---------------------------------------------------------------- 6. band energy (diffusion / local contrast)
BAND_SIGS = [1.0, 2.0, 4.0, 8.0, 16.0]   # MJ px; bands = G(s_k) - G(s_k+1)
BAND_GMIN = 0.35        # strongest per-band reduction
BAND_DEAD = 0.08        # ignore reductions smaller than this
# the finest band (1-2 px) is left to the blur matcher (applying both undershot it: edge 0.87)


def _bands(L, sigs, scale=1.0):
    Gs = [gblur(L, s * scale) for s in sigs]
    return [Gs[k] - Gs[k + 1] for k in range(len(sigs) - 1)]


def _tile_energy(B, w, tile):
    """Per-tile RMS of band B weighted by w, and the tile's weight coverage (0..1)."""
    wsum = tile_sum(w, tile)
    num = tile_sum(B * B * w, tile)
    cover = wsum / tile_sum(np.ones(w.shape, np.float32), tile)
    return np.sqrt(num / np.maximum(wsum, 1e-6)).astype(np.float32), cover.astype(np.float32)


def band_gain_maps(P, ref, stat_w, tile):
    """Per tile, per band: gain = E_MJ / E_P, reduction only (never sharpens / adds contrast).
    Tiles where structure disagrees (GPT changed content) or with little reference get no vote."""
    H, W = P.shape[:2]
    gh, gw = int(np.ceil(H / tile)), int(np.ceil(W / tile))
    conf = struct_conf_grid(ref, P, H, W, tile)
    cw = np.clip((conf - NCC_LO) / (NCC_HI - NCC_LO), 0, 1)
    bp, bm = _bands(lum(P), BAND_SIGS), _bands(lum(ref), BAND_SIGS)
    gains = [np.ones((gh, gw), np.float32)]
    for Bp, Bm in list(zip(bp, bm))[1:]:
        ep, den = _tile_energy(Bp, stat_w, tile)
        em, _ = _tile_energy(Bm, stat_w, tile)
        g = np.clip(em / np.maximum(ep, 1e-5), BAND_GMIN, 1.0)
        g = np.where(g > 1 - BAND_DEAD, 1.0, g)
        wt = (den > 0.6).astype(np.float32) * cw * (ep > 2e-4)
        g = np.where(wt > 0, g, 1.0)
        f = fill_smooth(g.astype(np.float32), wt.astype(np.float32), 1.0)
        f = np.where(np.isfinite(f) & (f > 0), f, 1.0)
        f = cv2.medianBlur(np.clip(f, BAND_GMIN, 1).astype(np.float32), 3)
        gains.append(gblur(f, 0.7))
    return gains


def apply_band_gains(P, gains, scale, tile):
    """scale = P pixels per analysis-grid pixel; tile = analysis tile size."""
    H, W = P.shape[:2]
    d = np.zeros_like(P)
    for B, g in zip(_bands(P, BAND_SIGS, scale), gains):   # per channel, same gain (lum measured)
        gm = grid_up(g, H, W, tile * scale, cv2.INTER_CUBIC)
        d += ((np.clip(gm, BAND_GMIN, 1) - 1)[..., None] * B).astype(np.float32)
    return np.clip(P + d, 0, 1).astype(np.float32)


# ---------------------------------------------------------------- 7. grain
def _tile_grain(hp):
    return lambda sl: np.median(np.abs(hp[sl])) * 1.4826


def grain_deficit_map(Ps, ref, stat_w, valid, tile):
    """Per pixel grain that has to be added to Ps so that each tile has ref's grain (L units)."""
    H, W = ref.shape[:2]
    grain_m, grain_p = _tile_grain(highpass(lum(ref))), _tile_grain(highpass(lum(Ps)))

    def deficit(sl):
        a, b = grain_m(sl), grain_p(sl)
        return np.sqrt(max(a * a - b * b, 0.0))

    val, wt = tile_stat(deficit, H, W, tile, stat_w)
    filled = cv2.medianBlur(fill_grid(val, wt, valid, tile).astype(np.float32), 3)
    return np.clip(grid_up(filled, H, W, tile), 0, None)


def tile_grain_map(img, stat_w, valid, tile):
    H, W = img.shape[:2]
    val, wt = tile_stat(_tile_grain(highpass(lum(img))), H, W, tile, stat_w)
    filled = cv2.medianBlur(fill_grid(val, wt, valid, tile).astype(np.float32), 3)
    return grid_up(filled, H, W, tile)


def make_grain(shape_s, size_full, seed=0):
    """Unit white grain at full (GPT) resolution, scaled so that its sigma-1 high-pass measured at MJ pixel
    density is exactly 1 (what the grain statistics measure)."""
    Hs, Ws = shape_s
    W, H = size_full
    n = np.random.default_rng(seed).standard_normal((H, W)).astype(np.float32)
    ns = cv2.resize(n, (Ws, Hs), interpolation=cv2.INTER_AREA)
    return n * (1.0 / ((ns - gblur(ns, 1.0)).std() + 1e-6))


# ---------------------------------------------------------------- metrics
def edge_energy_map(L):
    g = gblur(L, 1.2)
    return np.sqrt(cv2.Sobel(g, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(g, cv2.CV_32F, 0, 1) ** 2)


def tile_focus_err(a, b, w, tile):
    """Median |log2| ratio of local edge energy per tile (0 = blur/focus distribution matches)."""
    Ea, Eb = edge_energy_map(lum(a)), edge_energy_map(lum(b))
    H, W = w.shape
    errs = []
    for y in range(0, H - tile + 1, tile):
        for x in range(0, W - tile + 1, tile):
            sl = (slice(y, y + tile), slice(x, x + tile))
            if w[sl].mean() > 0.8:
                errs.append(abs(np.log2((Eb[sl].mean() + 1e-3) / (Ea[sl].mean() + 1e-3))))
    return float(np.median(errs)) if errs else float('nan')


def metrics(a, b, w, tile):
    La = cv2.cvtColor(a, cv2.COLOR_BGR2LAB)
    Lb = cv2.cvtColor(b, cv2.COLOR_BGR2LAB)
    de = np.linalg.norm(gblur(La, 2) - gblur(Lb, 2), axis=2)[w].mean()
    d = (Lb - La)[w].mean(0)
    ea = edge_energy_map(La[..., 0])[w].mean()
    eb = edge_energy_map(Lb[..., 0])[w].mean()
    ga = np.median(np.abs(highpass(La[..., 0])[w])) * 1.4826
    gb = np.median(np.abs(highpass(Lb[..., 0])[w])) * 1.4826
    return dict(dE=de, dL=d[0], da=d[1], db=d[2], edge_ratio=eb / ea, grain_ratio=gb / ga,
                focus_err=tile_focus_err(a, b, w, tile))


# ---------------------------------------------------------------- pipeline
def restore(mj8, g8, mode='composite', mask8=None, thr=3.5, size='gpt', log=print, seed=0, force=False, prep=None,
            swap=False, face_light=1.0):
    """Returns dict(out=uint8 image, changed, outside, report rows, previews).
    Raises PairMismatch when the MJ reference does not match the GPT image (unless force=True).
    `prep` = an earlier prepare(mj8, g8) result (saves aligning twice). swap=True: 换头的结果（见 prepare）。"""
    Hg, Wg = g8.shape[:2]
    Hm, Wm = mj8.shape[:2]
    p = prep or prepare(mj8, g8, swap)
    F, lin, r, Ws, Hs = p['F'], p['lin'], p['r'], p['Ws'], p['Hs']
    gs, ms, vs = p['gs'], p['ms'], p['vs']
    head = p.get('head')
    log(tr('[1] 对齐：{how}。MJ {Wm}x{Hm} -> GPT 画布 {Wg}x{Hg}（MJ 每像素 = GPT {v:.2f} 像素）', how=p["how"], Wm=Wm, Hm=Hm, Wg=Wg, Hg=Hg, v=1 / lin))
    hp = p.get('head_parts')
    kind = p.get('swap')
    if kind == 'person':
        if hp is not None:
            log(tr('    换角色模式：GPT 新人物 {info}；MJ 旧人物 {info2}（工作尺寸占比）', info=hp["g"]["info"], info2=hp["m"]["info"]))
            log(tr('    新人物 ∪ 旧人物约占画面 {v:.0f}%：不参加按位置的统计；头发、皮肤、嘴唇按 MJ 同类区域还原，衣服的颜色按 GPT（只做整幅调色），柔度按 MJ', v=p["head_share"] * 100))
        elif head is not None:
            log(tr('    换角色模式：人物没分出头发 / 皮肤 / 衣服，按人脸位置框出（约占画面 {v:.0f}%），人物只做整体色彩映射', v=p["head_share"] * 100))
        else:
            log(tr('    换角色模式：两张图里都没找到人脸，人物按普通改动自动检测'))
    elif kind:
        if hp is not None:
            log(tr('    换头模式：GPT 新头 {info}；MJ 旧头 {info2}（工作尺寸占比）', info=hp["g"]["info"], info2=hp["m"]["info"]))
            log(tr('    新头 ∪ 旧头约占画面 {v:.0f}%：不参加按位置的统计，头部颜色按 MJ 同类区域还原', v=p["head_share"] * 100))
        elif head is not None:
            log(tr('    换头模式：头部没分出头发 / 皮肤，按人脸椭圆处理（约占画面 {v:.0f}%），头部只做整体色彩映射', v=p["head_share"] * 100))
        else:
            log(tr('    换头模式：两张图里都没找到人脸，头部按普通改动自动检测'))
    log(tr('    配对检查：结构相关 {corr:.3f}，MJ 覆盖 {v:.1f}%', corr=p["corr"], v=vs.mean() * 100))
    if not p['ok']:
        if not force:
            raise PairMismatch(p['message'])
        log(tr('[强制继续] ') + p['message'])
    elif p['message']:
        log(p['message'])
    out_share = 1 - vs.mean()
    log(tr('    GPT 画面中 MJ 原图覆盖 {v:.1f}%', v=vs.mean() * 100) +
        (tr('，其余 {v:.1f}% 是 GPT 外扩/补黑边的区域（没有 MJ 参照，校正按邻近区域平滑外推）', v=out_share * 100)
         if out_share > 0.002 else ''))

    # 2. colour LUT (fit -> detect changes -> refit without them)
    M = fit_lut(gs, ms, vs)
    g1s = apply_lut(gs, M)
    if mask8 is not None:
        changed = cv2.resize(mask8, (Ws, Hs), interpolation=cv2.INTER_LINEAR) > 127
    else:
        changed = detect_changes(ms, g1s, vs, thr)
        if head is not None:
            changed = changed | head          # 新头整块用 GPT 的，不混入 MJ 旧头
    fitw = vs & ~cv2.dilate(changed.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    if fitw.mean() > 0.05:
        M = fit_lut(gs, ms, fitw)
        g1s = apply_lut(gs, M)
    log(tr('[2] 全局色彩映射已拟合；GPT 改动区域 {v:.1f}%', v=changed[vs].mean() * 100)
        + (tr('（手动蒙版）') if mask8 is not None else tr('（自动检测）')))
    stat_w = (vs & ~cv2.dilate(changed.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)).astype(np.float32)
    diag_s = np.hypot(Hs, Ws)

    # 3. low-frequency local colour / tone / haze residual
    sig = diag_s * RESID_SIGMA
    Rs = extrapolate(gblur(ms, sig) - gblur(g1s, sig), stat_w, sig, vs, diag_s * 0.12)
    Ps = np.clip(g1s + Rs, 0, 1)
    log(tr('[3] 局部色彩 / 明暗 / 雾气已迁移（MJ 覆盖不到处平滑外推）'))

    # 4. blur + band energy measured on the analysis grid, applied at full res
    tile = int(max(24, round(diag_s / 60)))
    ml, flow = local_align(ms, Ps, tile)          # MJ follows GPT's locally moved content
    fmag = np.hypot(flow[..., 0], flow[..., 1])[vs]
    log(tr('    局部对齐：光流平均 {v:.2f} px，最大 {v2:.2f} px（MJ 像素）', v=fmag.mean(), v2=fmag.max()))
    kmap_s = blur_levels_map(Ps, ml, stat_w, vs, tile)
    Ps_b = apply_blur_levels(Ps, kmap_s, 1.0)
    bgains = band_gain_maps(Ps_b, ml, stat_w, tile)
    Ps_b = apply_band_gains(Ps_b, bgains, 1.0, tile)
    log(tr('    柔光/局部反差匹配：各频段平均增益 ') + ' '.join(f'{float(g.mean()):.2f}' for g in bgains))
    # 5. grain deficit (statistics on the unwarped MJ: the flow remap would soften its grain)
    dmap_s = grain_deficit_map(Ps_b, ms, stat_w, vs, tile)

    # full-resolution build
    full = (Wg, Hg)
    P = np.clip(apply_lut(to_f(g8), M) + cv2.resize(Rs, full, interpolation=cv2.INTER_LINEAR), 0, 1)
    if hp is not None:          # 换头：新头的头发 / 皮肤 / 嘴唇按 MJ 旧头的同类区域还原（不按位置）
        import mj_head
        Hc, Wc = mj_head.recolor(to_f(g8), to_f(mj8), hp['g'], hp['m'], log, face_light=face_light)
        P = (P * (1 - Wc[..., None]) + Hc * Wc[..., None]).astype(np.float32)
    P0 = P
    P = apply_blur_levels(P, cv2.resize(kmap_s, full, interpolation=cv2.INTER_LINEAR), 1.0 / r)
    P = apply_band_gains(P, bgains, 1.0 / r, tile)
    if hp is not None:          # 换头：新头的柔度不用按位置推算的值（那是周围背景的），头发对头发、皮肤对皮肤按 MJ 旧头
        wc = hp['g']['char'][..., None]
        P = mj_head.match_texture((P * (1 - wc) + P0 * wc).astype(np.float32), to_f(mj8), hp['g'], hp['m'], lin, log)
        if kind == 'person':
            P = mj_head.soften_cloth(P, to_f(mj8), hp['g'], hp['m'], lin, log)
    del P0
    # one feedback pass: measure what the grain really adds after the full-res chain, rescale per tile
    n = make_grain((Hs, Ws), full, seed)

    def down(x):
        return to_f(cv2.resize(to_u8(x), (Ws, Hs), interpolation=cv2.INTER_AREA))

    trial = np.clip(P + (n * cv2.resize(dmap_s, full, interpolation=cv2.INTER_LINEAR) / 100.0)[..., None], 0, 1)
    a_, b_, c_ = (tile_grain_map(x, stat_w, vs, tile) for x in (ms, down(P), down(trial)))
    gainmap = np.sqrt(np.maximum(a_ ** 2 - b_ ** 2, 0)) / np.sqrt(np.maximum(c_ ** 2 - b_ ** 2, 1e-4))
    dmap_s = dmap_s * np.clip(gainmap, 0, 3)
    P = np.clip(P + (n * cv2.resize(dmap_s, full, interpolation=cv2.INTER_LINEAR) / 100.0)[..., None], 0, 1)
    P = P.astype(np.float32)
    sig_px = np.interp(kmap_s, np.arange(len(SIG_LEVELS)), SIG_LEVELS)
    log(tr('[4] 虚化匹配：平均补模糊 sigma={v:.2f}（MJ 像素），最大 {v2:.2f}', v=sig_px[vs].mean(), v2=sig_px.max()))
    log(tr('[5] 颗粒匹配：平均补颗粒 {v:.3f} L（强度按 MJ 像素密度标定）', v=dmap_s[vs].mean()))

    changed_f = cv2.resize(changed.astype(np.uint8), full, interpolation=cv2.INTER_NEAREST) > 0
    outside_f = ~(cv2.resize(vs.astype(np.uint8), full, interpolation=cv2.INTER_NEAREST) > 0)
    if mode == 'composite':
        mj_up = to_f(warp_mj(mj8, F, full, full, cv2.INTER_LANCZOS4))
        sel = (changed_f | outside_f).astype(np.float32)
        k = max(5, int(np.hypot(Hg, Wg) * 0.006))
        alpha = gblur(cv2.dilate(sel, _ellipse(k)), k / 2.0)
        alpha = np.clip(np.maximum(alpha, sel), 0, 1)[..., None]
        out = mj_up * (1 - alpha) + P * alpha
    else:
        out = P
    out8 = to_u8(out)
    if size == 'mj' and r < 1:
        out8 = cv2.resize(out8, (Ws, Hs), interpolation=cv2.INTER_AREA)

    # metrics on the analysis grid, unchanged + inside reference
    w = cv2.erode((vs & ~changed).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    o_s = to_f(cv2.resize(to_u8(out), (Ws, Hs), interpolation=cv2.INTER_AREA))
    rows = [(tr('GPT原样'), metrics(ms, gs, w, tile)), (tr('还原后'), metrics(ms, o_s, w, tile))]
    return dict(out=out8, changed=changed_f, outside=outside_f, rows=rows, mj_up=warp_mj(mj8, F, full, full),
                F=F, changed_share=float(changed[vs].mean()), outside_share=float(out_share))


def print_rows(rows, log=print):
    log(tr('\n指标（MJ 覆盖且 GPT 未改动的区域，按 MJ 像素密度比较；dE→0，edge/grain→1，focus→0）'))
    log(f"{'':10s}{'dE':>7s}{'dL':>7s}{'da':>7s}{'db':>7s}{'edge':>7s}{'grain':>7s}{'focus':>7s}")
    for nm, m in rows:
        log(f"{nm:10s}{m['dE']:7.2f}{m['dL']:+7.2f}{m['da']:+7.2f}{m['db']:+7.2f}"
            f"{m['edge_ratio']:7.2f}{m['grain_ratio']:7.2f}{m['focus_err']:7.2f}")


def save_debug(base, res, g8, out8):
    """<base>_mask.jpg (red = GPT changed, blue = outside MJ) and <base>_compare.jpg (MJ | GPT | restored)."""
    mj_up = res['mj_up']
    H, W = g8.shape[:2]
    ov = g8.copy()
    red = np.zeros_like(ov)
    red[..., 2] = 255
    blue = np.zeros_like(ov)
    blue[..., 0] = 255
    ov[res['changed']] = cv2.addWeighted(g8, 0.45, red, 0.55, 0)[res['changed']]
    ov[res['outside']] = cv2.addWeighted(g8, 0.45, blue, 0.55, 0)[res['outside']]
    imwrite_u(base + '_mask.jpg', ov, [cv2.IMWRITE_JPEG_QUALITY, 88])
    o = out8 if out8.shape[:2] == (H, W) else cv2.resize(out8, (W, H))
    s = (900 if H > W else 420) / H
    tiles = [cv2.resize(x, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) for x in (mj_up, g8, o)]
    for t, nm in zip(tiles, ['MJ', 'GPT', 'RESTORED']):
        cv2.putText(t, nm, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    if H > W:
        sep = np.full((tiles[0].shape[0], 6, 3), 255, np.uint8)
        sheet = np.hstack([tiles[0], sep, tiles[1], sep, tiles[2]])
    else:
        sep = np.full((6, tiles[0].shape[1], 3), 255, np.uint8)
        sheet = np.vstack([tiles[0], sep, tiles[1], sep, tiles[2]])
    imwrite_u(base + '_compare.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])


def restore_file(mj_path, gpt_path, out_path, mode='composite', mask_path=None, thr=3.5, size='gpt',
                 debug=False, force=False, log=print, prep=None, swap=False, face_light=1.0):
    """File-level entry (GUI and command line). Writes out_path (+ _compare.jpg / _mask.jpg with debug).
    Raises PairMismatch (images do not match) or InputError (unreadable input)."""
    mj8, (g8, g_alpha) = imread_u(mj_path), imread_alpha(gpt_path)   # transparent GPT areas: over white
    if mj8 is None or g8 is None:
        raise InputError(tr('读不到图片：') + (mj_path if mj8 is None else gpt_path))
    mask8 = None
    if mask_path:
        mask8 = imread_u(mask_path, cv2.IMREAD_GRAYSCALE)
        if mask8 is None:
            raise InputError(tr('读不到蒙版：') + mask_path)
    res = restore(mj8, g8, mode, mask8, thr, size, log=log, force=force, prep=prep, swap=swap, face_light=face_light)
    imwrite_u(out_path, with_alpha(res['out'], g_alpha))
    if g_alpha is not None and res['out'].shape[:2] == g_alpha.shape:
        log(tr('    GPT 图有透明区域：结果保留了同样的透明通道'))
    log(tr('[OK] 输出: {out_path}  尺寸 {v}x{v2}（GPT 原图 {v3}x{v4}）', out_path=out_path, v=res["out"].shape[1], v2=res["out"].shape[0], v3=g8.shape[1], v4=g8.shape[0]))
    if debug:
        print_rows(res['rows'], log)
        save_debug(os.path.splitext(out_path)[0], res, g8, res['out'])
    return res


def main():
    ap = argparse.ArgumentParser(description=tr('把 GPT 修正图的色彩、虚化、颗粒还原到 MJ 原图'))
    ap.add_argument('mj')
    ap.add_argument('gpt')
    ap.add_argument('out')
    ap.add_argument('--mode', choices=['composite', 'transfer'], default='composite')
    ap.add_argument('--mask')
    ap.add_argument('--thr', type=float, default=3.5)
    ap.add_argument('--size', choices=['gpt', 'mj'], default='gpt')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--force', action='store_true', help=tr('配对检查不通过时仍强制还原（一般不要用）'))
    a = ap.parse_args()
    try:
        restore_file(a.mj, a.gpt, a.out, a.mode, a.mask, a.thr, a.size, a.debug, a.force)
    except ValueError as e:
        raise SystemExit(str(e))


if __name__ == '__main__':
    main()
