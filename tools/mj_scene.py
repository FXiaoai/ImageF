# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""④页「同一场景重画」的按远近分层调色（v4.4）。
旧做法是整幅一条明暗曲线 + 按亮度分 8 段对齐偏色 + 全局柔化 / 锐化：远景和近景用同一套参数，
所以 GPT 画得太清楚、太黑的远山 / 对岸 / 远处楼阁没法单独“推远”，全局锐化还会让远景更清楚。

现在（MJ 和 GPT 各自估一张远近图，mj_depth）：
 1) 远近分 5 档（天空 / 远景 → 最近），每档一条明暗曲线（MJ 同一档的明暗分布），档内再按暗 / 中 / 亮三段
    对齐偏色（只看非高彩度的像素：灯笼、花、招牌不参与读偏色），每档一个饱和度系数；档与档之间按远近平滑过渡。
    某一档在任一张图里像素太少时，按比例退回整幅的曲线和偏色。
 2) 层内色相族微调：远 / 中 / 近三层里，红、橙、黄、绿、青、蓝、紫、品红 8 个色族分别把色相角、彩度（和一点明度）
    往 MJ 同层同色族靠，两边都要有足够的像素才做，带上限（屋檐、树木、湖面这类固有色差异）。
 3) 按层柔化：每档比较 MJ 与 GPT 在 2–16 像素尺度上的结构细节量，只减弱不加强（远处画得太清楚就压到 MJ 的程度）。
颗粒、柔光、防发灰、保留纯黑仍由 mj_style_only 统一处理。"""
from i18n import tr
import cv2
import numpy as np

import mj_depth
from mj_region import to_bgr, to_lab

WORK = 960                                   # long side of the statistics copy
U_C = np.array([0.08, 0.28, 0.48, 0.68, 0.88])   # bin centres in u = sqrt(relative depth); 0 = sky / far, 1 = nearest
U_W = 0.20
BIN_NAMES = (tr('天空/最远'), tr('远景'), tr('中景'), tr('中近景'), tr('近景'))
LAYERS = ((tr('远景'), (0, 1)), (tr('中景'), (2,)), (tr('近景'), (3, 4)))   # coarse layers (hue step, report)
QS = np.linspace(1, 99, 33)
LUT_X = np.linspace(0, 100, 201)
CONF_SHARE = 0.03          # a bin needs >= 3 % of each image for full confidence
CAP_L = 8.0                # per-bin tone curve may deviate this much (L) from the whole-frame curve
CAP_AB = 10.0              # per-bin / zone cast shift cap (Lab a/b)
CHROMA_LIM = (0.75, 1.25)
BIN_CHROMA_REL = (0.88, 1.14)   # a bin's saturation factor relative to the whole frame's
# How much of a bin's own tone / cast / saturation difference is used on top of the whole-frame grade.
# Aerial perspective lives in the distance; near the camera the per-bin difference is mostly CONTENT (a big white
# curtain in one image, a lamp in the other) and the depth ranking of thin bins is not stable between two images
# (ground-truth test, 13 pairs: full per-bin tone everywhere made the per-pixel colour error worse in 10 of 13).
BIN_PRIOR = (1.0, 1.0, 0.35, 0.2, 0.2)
ACCENT_C = 35.0            # lanterns, blossoms, signs: not used to read the cast / chroma
FAM_C = np.arange(8) * 45.0 + 22.5           # hue-family centres (Lab hue angle, deg)
FAM_NAMES = (tr('红'), tr('橙'), tr('黄绿'), tr('绿'), tr('青'), tr('蓝'), tr('紫蓝'), tr('品红'))
FAM_HALF = 45.0            # cos^2 windows, spacing 45 deg -> partition of unity
FAM_MIN = 0.004            # family needs >= 0.4 % of the layer in both images
FAM_CONF = 0.02            # full confidence at 2 %
CAP_HUE = 12.0             # deg
FAM_CHROMA = (0.8, 1.2)
CAP_FAM_L = 3.0
BANDS = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)   # band k = G(s_k) - G(s_k+1), at MJ pixel density
SOFT_BANDS = (1, 2, 3, 4, 5)   # 2-4 … 32-64 px; 1-2 px follows the 2-4 px gain (it is mostly grain)
GMIN = (0.45, 0.45, 0.45, 0.5, 0.5, 0.5)    # strongest reduction per band (16-64 px = haze over distant
                                            # ridges / buildings; the per-bin tone curve can stretch them first)
# Softness is compared with a ROBUST per-bin statistic (median |band|): thin dark branches in front of the sky,
# the moon and lamps are sparse but very strong edges; with an RMS they dominate the far bins and hide that the
# hills / far shore themselves are more contrasty in GPT (measured on the moon pair: RMS said GPT 0.81x softer
# than MJ at 2-4 px in the far bin, the median says 1.28x crisper — the visible truth).
EDGE_R = 0.010             # depth-edge window radius (x long side): pixels on a near/far boundary are a MIX of the
EDGE_RANGE = (0.08, 0.20)  # two sides, so they get the near and far transforms mixed (not the middle bins' transform)
SUPPORT_PAD = 8.0          # a bin's own tone / cast correction fades out this far (L) outside its GPT L range p2..p98


# ------------------------------------------------------------------ depth / weights
def depth_pair(mjc8, g8, log):
    """(MJ relative depth, GPT relative depth) or None when the model is unavailable / fails."""
    if not mj_depth.available():
        log(tr('[提醒] 远近模型不可用（缺少 depth_anything_v2_small_w16.onnx 或 OpenCV 太旧），退回整幅统一调色'))
        return None
    try:
        dm = mj_depth.relative_depth(mjc8)
        return dm, match_depth(mj_depth.relative_depth(g8), dm)
    except Exception as e:
        log(tr('[提醒] 远近估计出错（{name__}），退回整幅统一调色', name__=type(e).__name__))
        return None


def _plain_weights(depth):
    u = np.sqrt(np.clip(depth, 0, 1))[..., None]
    w = np.clip(1 - np.abs(u - U_C) / U_W, 0, 1)
    w[..., 0] = np.where(u[..., 0] <= U_C[0], 1.0, w[..., 0])
    w[..., -1] = np.where(u[..., 0] >= U_C[-1], 1.0, w[..., -1])
    return (w / (w.sum(-1, keepdims=True) + 1e-6)).astype(np.float32)


def depth_edges(depth):
    """(edge strength 0..1, local min depth, local max depth). Edge = near/far boundary inside the window."""
    r = max(2, int(round(EDGE_R * max(depth.shape))))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    dmax, dmin = cv2.dilate(depth, k), cv2.erode(depth, k)
    rng = np.sqrt(np.clip(dmax, 0, 1)) - np.sqrt(np.clip(dmin, 0, 1))
    edge = np.clip((rng - EDGE_RANGE[0]) / (EDGE_RANGE[1] - EDGE_RANGE[0]), 0, 1).astype(np.float32)
    return edge, dmin, dmax


def match_depth(dg, dm):
    """Map GPT's relative depth onto MJ's depth distribution (rank to rank, monotone).
    Each depth map is normalised by ITS nearest object, so the same content can land in different bins in the two
    images (measured: a 6 % crop moved 'middle distance' from 5 % of MJ to 14 % of GPT and the per-bin curves then
    paired unrelated content). The scene path is only taken when both images have the same content proportions,
    so the k-th farthest percent of GPT corresponds to the k-th farthest percent of MJ."""
    qs = np.linspace(0, 100, 201)
    src, dst = np.percentile(dg[::3, ::3], qs), np.percentile(dm[::3, ::3], qs)
    su, idx = np.unique(src, return_index=True)
    return np.interp(dg, su, np.maximum.accumulate(dst[idx])).astype(np.float32)


def bin_weights(depth):
    """(H, W, 5) soft weights over the depth bins (triangular in u = sqrt(depth), sums to 1).
    On near/far boundaries the depth map is smoothed, so a pixel there reads as 'middle distance' although it is a
    mix of the near object and the far background (out-of-focus edges, guided-filter transition): it gets
    alpha x near-side weights + (1 - alpha) x far-side weights instead — no light / dark halo along silhouettes."""
    w = _plain_weights(depth)
    edge, dmin, dmax = depth_edges(depth)
    if float(edge.max()) <= 0:
        return w
    alpha = np.clip((depth - dmin) / np.maximum(dmax - dmin, 1e-4), 0, 1)[..., None]
    mix = alpha * _plain_weights(dmax) + (1 - alpha) * _plain_weights(dmin)
    e = edge[..., None]
    return (e * mix + (1 - e) * w).astype(np.float32)


def layer_weights(wb):
    return np.stack([wb[..., list(ix)].sum(-1) for _, ix in LAYERS], -1)


def _small(img, depth):
    s = min(1.0, WORK / max(img.shape[:2]))
    if s < 1:
        size = (int(round(img.shape[1] * s)), int(round(img.shape[0] * s)))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        depth = cv2.resize(depth, size, interpolation=cv2.INTER_AREA)
    return img, depth


# ------------------------------------------------------------------ 1) per-bin tone / cast / chroma
def _curve(src, dst):
    """LUT over LUT_X: quantile map src -> dst, slope-1 extension outside, monotone."""
    su, idx = np.unique(src, return_index=True)
    du = np.maximum.accumulate(dst[idx])
    y = np.interp(LUT_X, su, du) + np.where(LUT_X < su[0], LUT_X - su[0], 0) + np.where(LUT_X > su[-1], LUT_X - su[-1], 0)
    return np.maximum.accumulate(y)


def _zone_cast(Lg, ag, bg, cg, Lm, am, bm, cm):
    """Per brightness third (by each side's own rank): (da, db) from non-accent pixels; None where too few."""
    out = []
    qg, qm = np.percentile(Lg, [33.3, 66.7]), np.percentile(Lm, [33.3, 66.7])
    for zg, zm in (((Lg <= qg[0]), (Lm <= qm[0])), ((Lg > qg[0]) & (Lg <= qg[1]), (Lm > qm[0]) & (Lm <= qm[1])),
                   ((Lg > qg[1]), (Lm > qm[1]))):
        g, m = zg & (cg < ACCENT_C), zm & (cm < ACCENT_C)
        if g.sum() < 150 or m.sum() < 150:
            g, m = zg, zm
        out.append((float(am[m].mean() - ag[g].mean()), float(bm[m].mean() - bg[g].mean()))
                   if g.sum() >= 150 and m.sum() >= 150 else None)
    return out


def _cast_at(L, zq, cast):
    zq = np.maximum.accumulate(np.asarray(zq, np.float64) + np.arange(3) * 1e-3)
    return np.interp(L, zq, [c[0] for c in cast]), np.interp(L, zq, [c[1] for c in cast])


def _chroma_ratio(Lg, ag, bg, cg, zq, cast, cm, ng, nm):
    """MJ / GPT median chroma of non-accent pixels, GPT measured AFTER its cast shift (GPT's greys are neutral where
    MJ's carry a tint: measured before the shift, the ratio would also 'add' that tint a second time as saturation)."""
    if ng.sum() < 200 or nm.sum() < 200:
        return None
    da, db = _cast_at(Lg[ng], zq, cast)
    c2 = np.hypot(ag[ng] + da, bg[ng] + db)
    return float(np.clip(np.median(cm[nm]) / max(float(np.median(c2)), 1e-3), *CHROMA_LIM))


def fit_bins(labg, dg, labm, dm):
    """Per-bin transform parameters, measured on the statistics copies (depth-edge pixels excluded: they are mixes)."""
    eg, em = depth_edges(dg)[0], depth_edges(dm)[0]
    hg = np.where(eg < 0.3, _plain_weights(dg).argmax(-1), -1)
    hm = np.where(em < 0.3, _plain_weights(dm).argmax(-1), -1)
    Lg, ag, bg = (labg[..., i] for i in range(3))
    Lm, am, bm = (labm[..., i] for i in range(3))
    cg, cm = np.hypot(ag, bg), np.hypot(am, bm)
    glob_lut = _curve(np.percentile(Lg, QS), np.percentile(Lm, QS))
    glob_cast = _zone_cast(Lg, ag, bg, cg, Lm, am, bm, cm)
    glob_cast = [tuple(np.clip(c, -CAP_AB, CAP_AB)) if c is not None else (0.0, 0.0) for c in glob_cast]
    glob_zq = np.percentile(Lg, [16.7, 50, 83.3])
    ng, nm = (cg < ACCENT_C), (cm < ACCENT_C)
    glob_k = _chroma_ratio(Lg, ag, bg, cg, glob_zq, glob_cast, cm, ng, nm) or 1.0
    glob = dict(lut=glob_lut, cast=glob_cast, zq=glob_zq, kc=glob_k)
    bins = []
    for k in range(len(U_C)):
        g, m = hg == k, hm == k
        share = (float(g.mean()), float(m.mean()))
        conf = float(np.clip(min(share) / CONF_SHARE, 0, 1)) if min(g.sum(), m.sum()) >= 400 else 0.0
        conf_stat = conf
        conf *= BIN_PRIOR[k]
        if conf > 0:
            lut = _curve(np.percentile(Lg[g], QS), np.percentile(Lm[m], QS))
            lut = glob_lut + np.clip(lut - glob_lut, -CAP_L, CAP_L) * conf
            zq = np.percentile(Lg[g], [16.7, 50, 83.3])        # GPT brightness ranks of the three cast zones
            zc = _zone_cast(Lg[g], ag[g], bg[g], cg[g], Lm[m], am[m], bm[m], cm[m])
            gz = [tuple(v) for v in np.stack(_cast_at(zq, glob_zq, glob_cast), -1)]
            cast = [tuple(np.clip(np.array(z if z is not None else q) * conf + np.array(q) * (1 - conf), -CAP_AB, CAP_AB))
                    for z, q in zip(zc, gz)]
            kc = _chroma_ratio(Lg[g], ag[g], bg[g], cg[g], zq, cast, cm[m], ng[g], nm[m])
            kc = glob_k * float(np.clip((kc if kc is not None else glob_k) / glob_k, *BIN_CHROMA_REL))
            kc = glob_k + (kc - glob_k) * conf
            support = np.percentile(Lg[g], [2, 98])
        else:
            lut, cast, kc, zq, support = glob_lut, glob_cast, glob_k, glob_zq, (0.0, 100.0)
        bins.append(dict(lut=lut, cast=cast, kc=float(kc), zq=zq, share=share, conf=conf, conf_stat=conf_stat,
                         support=support))
    return bins, glob


def apply_bins(lab, wb, bins, glob):
    """Blend the per-bin transforms by the soft depth weights (full resolution). A bin's own correction applies
    only inside the brightness range it was measured on (GPT p2..p98 of that bin) and fades to the whole-frame
    correction outside it — a bin fitted on dark distant hills must not decide what happens to bright sky pixels."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    gL = np.interp(L, LUT_X, glob['lut'])
    gda, gdb = _cast_at(L, glob['zq'], glob['cast'])
    out = np.zeros_like(lab)
    for k, p in enumerate(bins):
        w = wb[..., k]
        if float(w.max()) < 1e-4:
            continue
        lo, hi = p['support']
        s = np.clip(1 - np.maximum(np.maximum(lo - L, L - hi), 0) / SUPPORT_PAD, 0, 1)
        L2 = gL + (np.interp(L, LUT_X, p['lut']) - gL) * s
        da, db = _cast_at(L, p['zq'], p['cast'])
        da, db = gda + (da - gda) * s, gdb + (db - gdb) * s
        kc = glob['kc'] + (p['kc'] - glob['kc']) * s
        out[..., 0] += w * L2
        out[..., 1] += w * (a + da) * kc
        out[..., 2] += w * (b + db) * kc
    return out


# ------------------------------------------------------------------ 2) hue families inside each layer
def _fam_weights(a, b):
    """(N, 8) cos^2 hue-family memberships x chroma ramp (neutral greys have no hue -> ~0)."""
    h = np.degrees(np.arctan2(b, a)) % 360
    d = (h[..., None] - FAM_C + 180) % 360 - 180
    m = np.where(np.abs(d) < FAM_HALF, np.cos(np.radians(d) * 90 / FAM_HALF) ** 2, 0)
    r = np.clip((np.hypot(a, b) - 3) / 7, 0, 1)
    return (m * r[..., None]).astype(np.float32)


def fit_families(labp, lwp, labm, lwm):
    """Per (layer, family): hue rotation (deg), chroma scale, L shift, confidence. labp = graded GPT (stats copy)."""
    fp, fm = _fam_weights(labp[..., 1], labp[..., 2]), _fam_weights(labm[..., 1], labm[..., 2])
    res = np.zeros((len(LAYERS), 8, 3), np.float32)
    res[..., 1] = 1.0
    info = []
    for l in range(len(LAYERS)):
        Np, Nm = float(lwp[..., l].sum()), float(lwm[..., l].sum())
        if Np < 500 or Nm < 500:
            continue
        for f in range(8):
            Wp, Wm = lwp[..., l] * fp[..., f], lwm[..., l] * fm[..., f]
            sp, sm = float(Wp.sum()) / Np, float(Wm.sum()) / Nm
            if min(sp, sm) < FAM_MIN:
                continue
            conf = float(np.clip(min(sp, sm) / FAM_CONF, 0, 1))

            def stats(lab, W):
                s = W.sum()
                a, b = (lab[..., 1] * W).sum() / s, (lab[..., 2] * W).sum() / s
                return (float(np.degrees(np.arctan2(b, a))), float((np.hypot(lab[..., 1], lab[..., 2]) * W).sum() / s),
                        float((lab[..., 0] * W).sum() / s))
            hp, cp, Lp = stats(labp, Wp)
            hm, cm, Lm = stats(labm, Wm)
            dh = float(np.clip((hm - hp + 180) % 360 - 180, -CAP_HUE, CAP_HUE)) * conf
            kc = float(np.clip(cm / max(cp, 1e-3), *FAM_CHROMA)) ** conf
            dL = float(np.clip(Lm - Lp, -CAP_FAM_L, CAP_FAM_L)) * 0.5 * conf
            res[l, f] = (dh, kc, dL)
            info.append(dict(layer=LAYERS[l][0], family=FAM_NAMES[f], share_gpt=round(sp, 4), share_mj=round(sm, 4),
                             hue_shift=round(dh, 1), chroma_x=round(kc, 3), L_shift=round(dL, 2)))
    return res, info


def apply_families(lab, lw, fam):
    a, b = lab[..., 1], lab[..., 2]
    fw = _fam_weights(a, b)                                       # already includes the chroma ramp
    lw3 = lw[..., :, None]                                        # (H, W, layers, 1)
    W = lw3 * fw[..., None, :]                                    # (H, W, layers, 8)
    dh = (W * fam[:, :, 0]).sum((-1, -2))
    lk = (W * np.log(fam[:, :, 1])).sum((-1, -2))
    dL = (W * fam[:, :, 2]).sum((-1, -2))
    C, h = np.hypot(a, b), np.arctan2(b, a) + np.radians(dh)
    C = C * np.exp(lk)
    return np.dstack([lab[..., 0] + dL, C * np.cos(h), C * np.sin(h)]).astype(np.float32)


# ------------------------------------------------------------------ 3) per-layer softness
def _blur(x, s):
    """Gaussian blur; large sigmas computed on a reduced copy (same result for these smooth low-passes, ~10x faster:
    sigma 64 at full size needs a ~400 px kernel)."""
    if s <= 6:
        return cv2.GaussianBlur(x, (0, 0), s)
    f = 2 ** int(np.floor(np.log2(s / 3)))
    H, W = x.shape[:2]
    small = cv2.resize(x, (max(1, W // f), max(1, H // f)), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), np.sqrt(max(s * s - (0.5 * f) ** 2, 1.0)) / f)
    return cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)


def _layer_bands(img, w, scale):
    """Band decomposition of img INSIDE one depth layer: local means are normalised convolutions over that layer's
    pixels only, G(img * w) / G(w). With ordinary blurs a bright near object (blonde hair) raises the local mean
    of the dark far background next to it, and reducing that band lifts the background into a glow ring."""
    W = w if img.ndim == 2 else w[..., None]
    Gs = []
    for s in BANDS:
        num = _blur(img * W, s * scale)
        den = _blur(w, s * scale)
        Gs.append(num / np.maximum(den if img.ndim == 2 else den[..., None], 1e-3))
    return [Gs[i] - Gs[i + 1] for i in range(len(BANDS) - 1)]


def _hard_layers(d):
    e = depth_edges(d)[0]
    return np.where(e < 0.3, layer_weights(_plain_weights(d)).argmax(-1), -1)


def fit_soft(Lp, dp, sp, Lm, dm, sm, bins, step=2):
    """gains[layer, band] <= 1 so that each depth layer's structure contrast (2-64 px, robust median |band|) is not
    above MJ's same layer: distant ridges / buildings that GPT drew crisp and contrasty are pushed back into the haze.
    Never sharpens. Measured on the statistics copies: sp / sm = band-sigma multipliers that express MJ pixels in
    each copy's pixels. Confidence of a layer = mean statistical confidence of its bins."""
    wp, wm = layer_weights(bin_weights(dp)), layer_weights(bin_weights(dm))
    hp, hm = _hard_layers(dp)[::step, ::step], _hard_layers(dm)[::step, ::step]
    gains = np.ones((len(LAYERS), len(BANDS) - 1), np.float32)
    for l, (_, ix) in enumerate(LAYERS):
        conf = float(np.mean([bins[k]['conf_stat'] for k in ix]))
        g, m = hp == l, hm == l
        if conf <= 0 or g.sum() < 200 or m.sum() < 200:
            continue
        bp, bm = _layer_bands(Lp, wp[..., l], sp), _layer_bands(Lm, wm[..., l], sm)
        for j in SOFT_BANDS:
            ep = float(np.median(np.abs(bp[j][::step, ::step][g])))
            em = float(np.median(np.abs(bm[j][::step, ::step][m])))
            gains[l, j] = 1 + (float(np.clip(em / max(ep, 1e-4), GMIN[j], 1.0)) - 1) * conf
        gains[l, 0] = min(1.0, gains[l, 1])
    return gains


def apply_soft(img, lw, gains, scale):
    """img += sum_layer w_l(x) sum_band (g_l,band - 1) * band_l(img), bands computed inside each layer."""
    d = np.zeros_like(img)
    for l in range(len(LAYERS)):
        if float(np.abs(gains[l] - 1).max()) < 0.02:
            continue
        w = lw[..., l]
        for j, B in enumerate(_layer_bands(img, w, scale)):
            if abs(gains[l, j] - 1) >= 0.01:
                d += (gains[l, j] - 1) * w[..., None] * B
    return np.clip(img + d, 0, 1)


# ------------------------------------------------------------------ whole step
STEPS = dict(families=True, soft=True)   # test switches (eval scripts); always on in the tool
# (A final whole-frame re-centring to MJ's dark / mid / light averages was tried and removed: it lowered the
#  whole-frame zone metric on the moon pair 1.75 -> 0.65 but made the ground-truth per-pixel error worse —
#  12/13 -> 8/13 pairs better than v4.3, far-layer error 0.55 -> 0.73 — because it pushes layers that already
#  match MJ's same layer off again.)


def layered_grade(gf, mjc, dg, dm, scale, log):
    """gf / mjc: float BGR (GPT full size / MJ picture area); dg / dm: their relative depth maps.
    Returns (graded float BGR, info dict for the report)."""
    sg, dgs = _small(gf, dg)
    sm, dms = _small(mjc, dm)
    labg_s, labm_s = to_lab(sg), to_lab(sm)
    bins, glob = fit_bins(labg_s, dgs, labm_s, dms)
    wb_full = bin_weights(dg)
    lab = to_lab(gf)
    lab1 = apply_bins(lab, wb_full, bins, glob)
    # hue families, measured after step 1 on the statistics copy
    wbs_g = bin_weights(dgs)
    lab1_s = apply_bins(labg_s, wbs_g, bins, glob)
    fam, fam_info = fit_families(lab1_s, layer_weights(wbs_g), labm_s, layer_weights(bin_weights(dms)))
    if not STEPS['families']:
        fam[..., 0], fam[..., 1], fam[..., 2], fam_info = 0, 1, 0, []
    lab2 = apply_families(lab1, layer_weights(wb_full), fam)
    P = to_bgr(lab2)
    # softness per layer (structure bands): graded GPT vs MJ, both on their statistics copies.
    # Band sigmas are in MJ pixels: in the GPT copy one MJ pixel = scale x (copy / full) GPT-copy pixels.
    P_s = cv2.resize(P, (sg.shape[1], sg.shape[0]), interpolation=cv2.INTER_AREA)
    sp = scale * sg.shape[1] / gf.shape[1]
    smul = sm.shape[1] / mjc.shape[1]
    gains = fit_soft(to_lab(P_s)[..., 0], dgs, sp, to_lab(sm)[..., 0], dms, smul, bins)
    if not STEPS['soft']:
        gains[:] = 1
    P = apply_soft(P, layer_weights(wb_full), gains, scale)
    for k, (nm, p) in enumerate(zip(BIN_NAMES, bins)):
        lo = float(np.interp(10, LUT_X, p['lut']) - 10)
        hi = float(np.interp(70, LUT_X, p['lut']) - 70)
        log(tr('  {nm:6s} 占 GPT {v:4.1f}% / MJ {v2:4.1f}%（采用 {conf:.2f}）：暗部 {lo:+.1f}、'
               '亮部 {hi:+.1f}，偏色 暗 a{v3:+.1f} b{v4:+.1f} / 亮 a{v5:+.1f} b{v6:+.1f}，饱和 ×{kc:.2f}', nm=nm, v=p['share'][0] * 100, v2=p['share'][1] * 100, conf=p['conf'], lo=lo, hi=hi, v3=p['cast'][0][0], v4=p['cast'][0][1], v5=p['cast'][2][0], v6=p['cast'][2][1], kc=p['kc']))
    log(tr('  清晰度（2-8 / 8-32 / 32-64 像素，<1 = 柔化）：') + tr('；').join(
        f"{nm} ×{gains[l, 1]:.2f}/{gains[l, 3]:.2f}/{gains[l, 5]:.2f}" for l, (nm, _) in enumerate(LAYERS)))
    if fam_info:
        log(tr('  色相族微调：') + tr('；').join(tr('{layer}{family} 色相{hue_shift:+.0f}° 彩度×{chroma_x:.2f}', layer=f['layer'], family=f['family'], hue_shift=f['hue_shift'], chroma_x=f['chroma_x'])
                                    for f in fam_info if abs(f['hue_shift']) >= 1 or abs(f['chroma_x'] - 1) >= 0.03))
    return P, dict(bins=[dict(name=n, share_gpt=round(p['share'][0], 4), share_mj=round(p['share'][1], 4),
                              conf=round(p['conf'], 3), chroma_x=round(p['kc'], 3),
                              cast=[[round(v, 2) for v in c] for c in p['cast']])
                         for k, (n, p) in enumerate(zip(BIN_NAMES, bins))],
                   soft_gain={nm: [round(float(v), 3) for v in gains[l]] for l, (nm, _) in enumerate(LAYERS)},
                   families=fam_info)


# ------------------------------------------------------------------ report / preview
def layer_stats(img, depth):
    """Per coarse layer: L p5 / p50 / p95, L std, mean chroma, neutral cast — for the metrics file and the log."""
    lab = to_lab(img)
    lw = layer_weights(bin_weights(depth))
    hard = lw.argmax(-1)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    C = np.hypot(a, b)
    out = {}
    for l, (nm, _) in enumerate(LAYERS):
        m = hard == l
        if m.sum() < 200:
            continue
        # whole-layer mean a / b: a "neutral pixels only" subset is unstable here (the grade itself changes which
        # pixels are near-neutral, e.g. 11 % -> 20 % of the far layer on the moon pair)
        out[nm] = dict(share=round(float(m.mean()), 4), L_p5=round(float(np.percentile(L[m], 5)), 2),
                       L_p50=round(float(np.percentile(L[m], 50)), 2), L_p95=round(float(np.percentile(L[m], 95)), 2),
                       L_std=round(float(L[m].std()), 2), chroma=round(float(C[m].mean()), 2),
                       a=round(float(a[m].mean()), 2), b=round(float(b[m].mean()), 2))
    return out


LAYER_COLORS = ((255, 120, 40), (60, 200, 60), (40, 60, 230))   # BGR: far blue, mid green, near red


def layer_map(img8, depth, h):
    """Picture with the far / mid / near layers tinted (for the compare sheet / preview)."""
    lw = layer_weights(bin_weights(depth))
    col = (lw[..., :, None] * np.array(LAYER_COLORS, np.float32)).sum(-2)
    out = (0.45 * img8.astype(np.float32) + 0.55 * col).astype(np.uint8)
    return cv2.resize(out, (int(out.shape[1] * h / out.shape[0]), h), interpolation=cv2.INTER_AREA)
