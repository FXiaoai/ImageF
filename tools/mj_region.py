# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""区域对应风格迁移（构图 / 长宽 / 内容不同的 MJ ↔ GPT，④页）。
1) 两张图各自分成软区域：背景（白底 + 与画面边框相连的低纹理底色）、皮肤、头发、其余主体按 Lab 聚类；
2) 区域配对：同语义（皮肤↔皮肤、头发↔头发）优先，其余聚类按 Lab 色相 / 明度相近配对，配不上的用整体主体变换；
3) 每个区域：L 按区域直方图（单调曲线，保留 GPT 明暗结构）、a/b 均值 + 离散度迁移，带上限；皮肤更保守；
4) 软遮罩（引导滤波贴边 + 羽化）混合，无接缝。只依赖 numpy / cv2。"""
from i18n import tr
import cv2
import numpy as np

WORK = 640          # segmentation working size (long side)
K_CLU = 6           # Lab clusters for the remaining subject
MATCH_MAX = 26.0    # max cluster-pair cost (≈ΔE) to accept a correspondence
CAP = dict(skin=(5.0, 4.0), hair=(10.0, 10.0), clu=(8.0, 6.0), glob=(8.0, 5.0))   # (L shift cap, ab shift cap)
TONE_K, COL_K = 0.8, 0.85
RES_K = dict(skin=0.6, hair=0.6, clu=0.4)   # share of a region's own residual on top of the consensus grade
SKIN_HUE = (18.0, 80.0)   # Lab hue angle range kept for skin (deg)
SEMANTIC = ('skin', 'hair')


def to_lab(x):
    return cv2.cvtColor(np.clip(x, 0, 1).astype(np.float32), cv2.COLOR_BGR2LAB)


def to_bgr(x):
    return np.clip(cv2.cvtColor(x.astype(np.float32), cv2.COLOR_LAB2BGR), 0, 1)


def _blur(x, s):
    return cv2.GaussianBlur(x, (0, 0), s) if s > 0 else x


def guided(I, p, r, eps):
    def box(x):
        return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1))
    mI, mp = box(I), box(p)
    a = (box(I * p) - mI * mp) / (box(I * I) - mI * mI + eps)
    b = mp - a * mI
    return box(a) * I + box(b)


def _keep_large(mask, frac, connectivity):
    """Connected components larger than frac x image area. Returns (mask, keep flags, labels, stats)."""
    n, lbl, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=connectivity)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] > frac * mask.size
    return keep[lbl], keep, lbl, st


# ------------------------------------------------------------------ segmentation
def _bg_low(lab, tex, white_bg):
    """Background at working size: white low-texture areas OR the border-connected, low-texture region whose colour
    matches the border (grey / blue / gradient studio backdrops — and equally a plain wall or sky in a photo; tab ④
    tells the user when that happens, 背景也跟随MJ then grades it from MJ's own background)."""
    H, W = lab.shape[:2]
    bw = white_bg > 0.5
    border = np.zeros((H, W), bool)
    b = max(2, int(0.01 * max(H, W)))
    border[:b], border[-b:], border[:, :b], border[:, -b:] = True, True, True, True
    lowtex = tex < max(1.2, np.percentile(tex, 30))
    # colour model from border pixels that are low-texture; allow slow gradients via local reference
    ref = lab[border & lowtex]
    out = bw.copy()
    if len(ref) > 50:
        med = np.median(ref, 0)
        d = np.sqrt(((lab - med) ** 2 * [0.5, 1, 1]).sum(-1))
        cand = (lowtex | (tex < 2.5)) & (d < 14)
        cand = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lbl = cv2.connectedComponents(cand, connectivity=4)
        ids = np.unique(lbl[border & (cand > 0)])
        reg = np.isin(lbl, ids[ids > 0])
        if reg.sum() > 0.04 * H * W:
            out |= reg
    out = cv2.morphologyEx(out.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
    return _keep_large(out, 0.002, 4)[0]          # remove small islands


def _skin(lab, bgr, bgm):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    ycc = cv2.cvtColor((bgr * 255).astype(np.uint8), cv2.COLOR_BGR2YCrCb).astype(np.float32)
    Cr, Cb = ycc[..., 1], ycc[..., 2]
    hue = np.degrees(np.arctan2(b, a))
    C = np.hypot(a, b)
    s1 = (Cr > 133) & (Cr < 180) & (Cb > 77) & (Cb < 132)
    s2 = (hue > 15) & (hue < 85) & (C > 5) & (C < 45) & (a > 3) & (L > 25) & (L < 97)
    m = (s1 & s2 & ~bgm).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m, keep, lbl, st = _keep_large(m, 0.003, 8)
    # face = largest compact skin blob in the upper 70 %
    face, fid, best = None, -1, 0
    for i in np.nonzero(keep)[0]:
        x, y, w, h, A = st[i]
        if y + h / 2 > 0.7 * m.shape[0] or A < 0.006 * m.size:
            continue
        fill = A / (w * h)
        ar = h / max(w, 1)
        sc = A * fill * (1.0 if 0.6 < ar < 2.2 else 0.3) * (1.5 - (y + h / 2) / m.shape[0])
        if sc > best:
            best, face, fid = sc, (x, y, w, h), i
    if face is not None:
        # pale / highlit facial skin often fails the colour test: grow skin inside the face blob's hull
        pts = cv2.findNonZero((lbl == fid).astype(np.uint8))
        hull = np.zeros(m.shape, np.uint8)
        cv2.fillConvexPoly(hull, cv2.convexHull(pts), 1)
        m = m | ((hull > 0) & (hue > 5) & (hue < 95) & (C > 2.0) & (L > 40) & ~bgm)
    # keep only skin that belongs to the person: the face blob plus blobs of similar colour and limb-like size
    # (wood, sand, beige walls have skin hue but are large / far from the face colour)
    n, lbl2, st2, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if face is not None:
        fx, fy, fw, fh = face
        fm = np.zeros(m.shape, bool)
        fm[fy:fy + fh, fx:fx + fw] = True
        fl = lab[fm & m].mean(0)
        farea = st[fid, cv2.CC_STAT_AREA]
        keep = np.zeros(n, bool)
        for i in range(1, n):
            cm = lbl2 == i
            d = np.linalg.norm((lab[cm].mean(0) - fl) * [0.5, 1, 1])
            keep[i] = (cm & fm).sum() > 0 or (d < 10 and st2[i, cv2.CC_STAT_AREA] < 1.5 * farea)
        m = keep[lbl2]
    else:
        tot = st2[1:, cv2.CC_STAT_AREA].sum() if n > 1 else 0
        if tot > 0.25 * (~bgm).sum():       # no face and lots of 'skin' -> probably not skin
            m = np.zeros_like(m)
    return m, face


def segment(img, white_bg):
    """img: float BGR 0..1 (any size); white_bg: soft white-background mask (same size).
    Returns dict(labels (WORK-size int map, 0 = background), names, means (Lab), share, face, small, scale)."""
    H, W = img.shape[:2]
    s = WORK / max(H, W)
    sm = cv2.resize(img, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA)
    wb = cv2.resize(white_bg.astype(np.float32), (sm.shape[1], sm.shape[0]), interpolation=cv2.INTER_AREA)
    lab = to_lab(sm)
    L = lab[..., 0]
    tex = np.sqrt(np.maximum(_blur(L * L, 2) - _blur(L, 2) ** 2, 0))
    bgm = _bg_low(lab, tex, wb)
    skin, face = _skin(lab, sm, bgm)
    lbl = np.full(L.shape, -1, np.int32)
    names = ['bg']
    lbl[bgm] = 0
    subj = ~bgm
    if skin.sum() > 0.002 * skin.size:
        names.append('skin')
        lbl[skin & subj] = 1
    rest = subj & (lbl < 0)
    # k-means on the remaining subject: lightness weighted down so clusters follow colour first
    pts = lab[rest]
    if len(pts) > 200:
        f = np.stack([pts[:, 0] * 0.6, pts[:, 1], pts[:, 2]], 1).astype(np.float32)
        k = int(min(K_CLU, max(2, len(pts) // 2000)))
        sub = f[np.random.default_rng(0).choice(len(f), min(len(f), 40000), replace=False)]
        _, _, cen = cv2.kmeans(sub, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.2), 3,
                               cv2.KMEANS_PP_CENTERS)
        c = ((f[:, None, :] - cen[None]) ** 2).sum(-1).argmin(1)
        cl = np.full(L.shape, -1, np.int32)
        cl[rest] = c
        # spatial clean-up: mode of the labels in a small window via one-hot blur
        oh = np.stack([_blur((cl == j).astype(np.float32), 1.5) for j in range(k)], -1)
        cl2 = np.where(rest, oh.argmax(-1), -1)
        # hair: clusters dominant in the ring above/around the face
        hair_ids = []
        if face is not None:
            x, y, w, h = face
            ring = np.zeros(L.shape, bool)
            ring[max(0, int(y - 0.7 * h)):int(y + 0.9 * h), max(0, int(x - 0.5 * w)):int(x + 1.5 * w)] = True
            ring &= rest & ~cv2.dilate(skin.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            ring[int(y + 0.35 * h):] &= False  # hair sits above / beside the upper face, not on the chest
            if ring.sum() > 50:
                sh = np.array([(cl2[ring] == j).mean() for j in range(k)])
                hair_ids = [j for j in range(k) if sh[j] > 0.25 or (sh[j] > 0.12 and sh[j] == sh.max())]
        if hair_ids:
            hm = np.isin(cl2, hair_ids) & rest
            # keep hair components touching the ring zone (the same colour lower down = clothing)
            n, cc = cv2.connectedComponents(hm.astype(np.uint8), connectivity=8)
            ids = np.unique(cc[ring & hm])
            hm = np.isin(cc, ids[ids > 0])
            # hair stays near the head: limit to a box around the face (long hair reaches the chest, not the knees)
            lim = np.zeros(L.shape, bool)
            lim[max(0, int(y - 1.2 * h)):int(y + 3.0 * h), max(0, int(x - 1.3 * w)):int(x + 2.3 * w)] = True
            hm &= lim
            names.append('hair')
            lbl[hm] = len(names) - 1
        for j in range(k):
            m = (cl2 == j) & (lbl < 0) & rest
            if m.sum() < 0.01 * rest.sum():
                continue
            names.append(f'c{j}')
            lbl[m] = len(names) - 1
        left = rest & (lbl < 0)
        if left.any():   # tiny leftovers -> nearest region by colour
            means = np.array([lab[lbl == i].mean(0) if (lbl == i).any() else [1e3] * 3 for i in range(len(names))])
            means[0] = 1e3
            lbl[left] = ((lab[left][:, None, :] - means[None]) ** 2).sum(-1).argmin(1)
    else:
        lbl[rest] = 1 if 'skin' in names else 0
    means, share = [], []
    for i in range(len(names)):
        m = lbl == i
        means.append(lab[m].mean(0) if m.any() else np.array([50, 0, 0.]))
        share.append(float(m.mean()))
    return dict(labels=lbl, names=names, means=np.array(means), share=share, face=face, small=sm, scale=s)


# ------------------------------------------------------------------ correspondence
def _cost(a, b):
    dL = a[0] - b[0]
    dab = np.hypot(a[1] - b[1], a[2] - b[2])
    ca, cb = np.hypot(a[1], a[2]), np.hypot(b[1], b[2])
    hue = 0.0
    if ca > 8 and cb > 8:   # both chromatic: penalise hue difference
        h = abs(np.degrees(np.arctan2(a[2], a[1]) - np.arctan2(b[2], b[1]))) % 360
        hue = min(h, 360 - h) * 0.4
    return float(np.sqrt((0.5 * dL) ** 2 + dab ** 2) + hue)


def match(sg, sm):
    """Returns (pairs, conf): pairs maps GPT region index -> MJ region index (None = global subject
    transform); conf maps matched GPT region index -> match confidence 0.3..1."""
    pairs = {}
    ng, nm = sg['names'], sm['names']
    for lab_ in SEMANTIC:
        if lab_ in ng and lab_ in nm:
            gi, mi = ng.index(lab_), nm.index(lab_)
            # same label but very different colour (e.g. 'hair' found on a bright wall) -> not a real correspondence
            if sm['share'][mi] > 0.002 and _cost(sg['means'][gi], sm['means'][mi]) < 1.6 * MATCH_MAX:
                pairs[gi] = mi
    gfree = [i for i in range(1, len(ng)) if i not in pairs]
    mfree = [j for j in range(1, len(nm)) if nm[j] != 'skin']
    C = sorted((_cost(sg['means'][i], sm['means'][j]), i, j) for i in gfree for j in mfree)
    usedm = set(pairs.values())
    for c, i, j in C:
        if i in pairs or j in usedm or c > MATCH_MAX:
            continue
        pairs[i] = j
        usedm.add(j)
    for c, i, j in C:   # second pass: many-to-one allowed for close colours
        if i not in pairs and c < 0.6 * MATCH_MAX:
            pairs[i] = j
    conf = {}
    for i, j in pairs.items():
        limit = 1.6 * MATCH_MAX if ng[i] in SEMANTIC else MATCH_MAX
        conf[i] = float(np.clip(1.15 - _cost(sg['means'][i], sm['means'][j]) / limit, 0.3, 1.0))
    return {i: pairs.get(i) for i in range(1, len(ng))}, conf


# ------------------------------------------------------------------ soft masks at full size
def soft_masks(seg, shape, feather=0.012):
    H, W = shape
    lbl = seg['labels']
    guide = (to_lab(seg['small'])[..., 0] / 100.0).astype(np.float32)
    r = max(2, int(0.01 * max(lbl.shape)))
    fs = feather * max(lbl.shape)
    Ms = []
    for i in range(len(seg['names'])):
        m = _blur((lbl == i).astype(np.float32), fs * 0.5)
        Ms.append(np.clip(guided(guide, m, r, 1e-3), 0, 1))
    S = np.stack(Ms, -1)
    S /= S.sum(-1, keepdims=True) + 1e-6
    S = cv2.resize(S, (W, H), interpolation=cv2.INTER_LINEAR)
    if S.ndim == 2:
        S = S[..., None]
    S /= S.sum(-1, keepdims=True) + 1e-6
    return S


def region_stats(lab, w):
    L, a, b = lab[..., 0][w], lab[..., 1][w], lab[..., 2][w]
    return dict(q=np.percentile(L, np.linspace(1, 99, 33)), mL=float(L.mean()), ma=float(a.mean()), mb=float(b.mean()),
                sa=float(a.std()), sb=float(b.std()), n=int(w.sum()))


def _region_full(img, seg, i):
    H, W = img.shape[:2]
    return cv2.resize((seg['labels'] == i).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0


def _transform(lab, gs, ms, cap, kt, kc, skin=False):
    """Per-region transform of a whole Lab image (blended by the region's soft mask later)."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    src, dst = gs['q'], ms['q']
    d = dst - src
    dm = float(d.mean())
    d = np.clip(d - dm, -1.5 * cap[0], 1.5 * cap[0]) + np.clip(dm, -cap[0], cap[0])   # shape + capped mean shift
    dst2 = np.maximum.accumulate(src + kt * d)
    su, idx = np.unique(src, return_index=True)
    L2 = np.interp(L, su, dst2[idx]) + np.where(L < su[0], L - su[0], 0) + np.where(L > su[-1], L - su[-1], 0)
    ka = 1 + (np.clip(ms['sa'] / (gs['sa'] + 1e-6), 0.75, 1.3) - 1) * kc
    kb = 1 + (np.clip(ms['sb'] / (gs['sb'] + 1e-6), 0.75, 1.3) - 1) * kc
    ta = gs['ma'] + np.clip(ms['ma'] - gs['ma'], -cap[1], cap[1]) * kc
    tb = gs['mb'] + np.clip(ms['mb'] - gs['mb'], -cap[1], cap[1]) * kc
    a2 = ta + (a - gs['ma']) * ka
    b2 = tb + (b - gs['mb']) * kb
    if skin:   # skin-tone safety: keep hue in a natural range, chroma not above GPT*1.25 + 3
        C0, C2 = np.hypot(a, b), np.hypot(a2, b2)
        hc = np.radians(np.clip(np.degrees(np.arctan2(b2, a2)), *SKIN_HUE))
        C2 = np.minimum(C2, C0 * 1.25 + 3)
        a2, b2 = C2 * np.cos(hc), C2 * np.sin(hc)
    return np.dstack([L2, a2, b2]).astype(np.float32)


def _wmed(v, w):
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, c[-1] / 2)])


def segment_pair(gf, mjf, g_white, m_white):
    """Segment the GPT image, then the MJ image. k-means++ draws from OpenCV's process-wide RNG, so it is reset
    first: otherwise the result depended on whatever ran earlier in the same session (e.g. a tab ① measurement).
    setRNGSeed(0) = the state a fresh process starts with, so results equal the command-line tool's."""
    cv2.setRNGSeed(0)
    return segment(gf, g_white), segment(mjf, m_white)


def transfer(gf, mjf, g_white, m_white, log=print, bg_follow=False):
    """Region-correspondence colour/tone transfer.
    Returns (out float BGR, info dict, seg_g, seg_m, pairs, W_bg_full)."""
    sg, sm_ = segment_pair(gf, mjf, g_white, m_white)
    pairs, conf = match(sg, sm_)
    H, W = gf.shape[:2]
    S = soft_masks(sg, (H, W))
    lab, labm = to_lab(gf), to_lab(mjf)
    # full-res hard region masks (for statistics)
    gmask = [_region_full(gf, sg, i) for i in range(len(sg['names']))]
    mmask = [_region_full(mjf, sm_, j) for j in range(len(sm_['names']))]
    gsub, msub = ~gmask[0], ~mmask[0]
    if gsub.sum() < 500:
        gsub = np.ones_like(gsub)
    if msub.sum() < 500:
        msub = np.ones_like(msub)
    gs_all, ms_all = region_stats(lab, gsub), region_stats(labm, msub)
    # 1) consensus grade from all region correspondences (robust weighted median of per-pair differences):
    #    content differences of single regions average out, the shared 'look' (cast, brightness, contrast,
    #    saturation) remains. 2) each region adds part of its own residual, scaled by match confidence.
    rows = []
    for i in range(1, len(sg['names'])):
        j = pairs.get(i)
        if j is None or gmask[i].sum() < 300 or mmask[j].sum() < 300:
            continue
        g, m = lab[gmask[i]], labm[mmask[j]]
        cg, cm = np.hypot(g[:, 1], g[:, 2]).mean(), np.hypot(m[:, 1], m[:, 2]).mean()
        w = conf.get(i, 1.0) * np.sqrt(sg['share'][i]) * (1.5 if sg['names'][i] in SEMANTIC else 1.0)
        rows.append((w, m[:, 0].mean() - g[:, 0].mean(), m[:, 1].mean() - g[:, 1].mean(),
                     m[:, 2].mean() - g[:, 2].mean(), (m[:, 0].std() + 1) / (g[:, 0].std() + 1), (cm + 2) / (cg + 2)))
    if rows:
        R_ = np.array(rows)
        dL, da, db, kL, kC = (_wmed(R_[:, k], R_[:, 0]) for k in range(1, 6))
    else:
        dL = ms_all['mL'] - gs_all['mL']
        da = ms_all['ma'] - gs_all['ma']
        db = ms_all['mb'] - gs_all['mb']
        kL = kC = 1.0
    dL = float(np.clip(dL, -CAP['glob'][0], CAP['glob'][0])) * TONE_K
    da, db = (float(np.clip(v, -CAP['glob'][1], CAP['glob'][1])) * COL_K for v in (da, db))
    kL = 1 + (float(np.clip(kL, 0.85, 1.2)) - 1) * TONE_K
    kC = 1 + (float(np.clip(kC, 0.8, 1.25)) - 1) * COL_K
    mu = gs_all['mL']
    T_glob = np.dstack([mu + (lab[..., 0] - mu) * kL + dL, lab[..., 1] * kC + da, lab[..., 2] * kC + db])
    T_glob = T_glob.astype(np.float32)
    log(tr('共同风格：亮度 {dL:+.1f}，反差 ×{kL:.2f}，偏色 a{da:+.1f} b{db:+.1f}，饱和 ×{kC:.2f}（来自 {n} 组区域对应）', dL=dL, kL=kL, da=da, db=db, kC=kC, n=len(rows)))
    out = np.zeros_like(lab)
    info = []
    for i in range(1, len(sg['names'])):
        j = pairs.get(i)
        nm = sg['names'][i]
        if gmask[i].sum() < 300 or j is None or mmask[j].sum() < 300:
            T, j = T_glob, None
        else:
            kind = nm if nm in SEMANTIC else 'clu'
            Tr = _transform(lab, region_stats(lab, gmask[i]), region_stats(labm, mmask[j]), CAP[kind], TONE_K, COL_K,
                            skin=(kind == 'skin'))
            r = RES_K[kind] * conf.get(i, 1.0)
            T = r * Tr + (1 - r) * T_glob
        out += S[..., i:i + 1] * T
        info.append(dict(g=nm, m=(sm_['names'][j] if j is not None else tr('整体')),
                         g_lab=[round(float(v), 1) for v in sg['means'][i]],
                         m_lab=([round(float(v), 1) for v in sm_['means'][j]] if j is not None else None),
                         share=round(sg['share'][i], 3)))
    wbg = S[..., 0]
    # background: untouched unless 背景也跟随MJ and MJ has a backdrop
    bgT = lab
    mbg, gbg = mmask[0], gmask[0]
    if bg_follow and mbg.sum() > 0.02 * mbg.size and gbg.sum() > 0.02 * gbg.size:
        gb, mb = region_stats(lab, gbg), region_stats(labm, mbg)
        bgT = lab.copy()
        bgT[..., 0] = lab[..., 0] + (mb['mL'] - gb['mL']) * 1.0
        bgT[..., 1] = mb['ma'] + (lab[..., 1] - gb['ma']) * np.clip(mb['sa'] / (gb['sa'] + 1e-6), 0.5, 2)
        bgT[..., 2] = mb['mb'] + (lab[..., 2] - gb['mb']) * np.clip(mb['sb'] / (gb['sb'] + 1e-6), 0.5, 2)
        log(tr('背景跟随 MJ：L {mL:.0f}→{mL2:.0f}，a {ma:+.1f}→{ma2:+.1f}，b {mb:+.1f}→{mb2:+.1f}', mL=gb['mL'], mL2=mb['mL'], ma=gb['ma'], ma2=mb['ma'], mb=gb['mb'], mb2=mb['mb']))
    if bg_follow and bgT is not lab:
        # thin hair strands / soft edges over a white backdrop are mostly backdrop colour: let them follow too,
        # otherwise a white fringe remains around the subject
        Lg, Cg = lab[..., 0], np.hypot(lab[..., 1], lab[..., 2])
        whit = np.clip((Lg - 82) / 12, 0, 1) * np.clip((10 - Cg) / 6, 0, 1)
        near = np.clip(cv2.GaussianBlur((wbg > 0.5).astype(np.float32), (0, 0), 0.015 * max(H, W)) * 3, 0, 1)
        e = np.clip(whit * near, 0, 1)[..., None]
        out = out * (1 - e) + bgT * (1 - (1 - wbg[..., None]) * (1 - e))
    else:
        out += wbg[..., None] * bgT
    for r in info:
        log(tr('  区域 GPT「{g}」{g_lab}（占 {v:.0f}%）↔ MJ「{m}」{v2}', g=r['g'], g_lab=r['g_lab'], v=r['share'] * 100, m=r['m'], v2=r['m_lab'] or ''))
    return to_bgr(out), dict(regions=info, bg_share=float(wbg.mean())), sg, sm_, pairs, wbg


# ------------------------------------------------------------------ visualisation
PAL = [(200, 200, 200), (90, 160, 255), (40, 40, 150), (0, 200, 0), (220, 120, 0), (200, 0, 200), (0, 200, 220),
       (120, 60, 200), (60, 140, 90), (180, 180, 0)]
CN = {'bg': tr('背景'), 'skin': tr('皮肤'), 'hair': tr('头发')}


def region_name(seg, i):
    return CN.get(seg['names'][i], tr('颜色区 ') + seg['names'][i][1:])


def _draw_regions(seg, col, h, unmatched=(), extra=()):
    """extra = [(full-resolution bool mask, BGR colour)] painted on top (e.g. the lips)."""
    lbl = seg['labels']
    v = (seg['small'] * 255).astype(np.uint8).copy()
    ov = np.zeros_like(v)
    for i, c in col.items():
        ov[lbl == i] = c
    out = cv2.addWeighted(v, 0.35, ov, 0.65, 0)
    yy, xx = np.mgrid[:lbl.shape[0], :lbl.shape[1]]
    for i in unmatched:
        st = (lbl == i) & (((xx + yy) // 6) % 2 == 0)
        out[st] = (out[st] * 0.4).astype(np.uint8)
    out[cv2.Canny(lbl.astype(np.uint8) * 20, 1, 1) > 0] = 255
    for m, c in extra:
        small = cv2.resize(m.astype(np.uint8) * 255, (lbl.shape[1], lbl.shape[0]), interpolation=cv2.INTER_AREA) > 64
        out[small] = c
    return cv2.resize(out, (int(out.shape[1] * h / out.shape[0]), h), interpolation=cv2.INTER_NEAREST)


def region_maps(sg, sm_, pairs, h=600, extra_g=(), extra_m=()):
    """Colour-coded maps (MJ, GPT): matched regions share a colour; unmatched GPT regions striped (= 整体变换).
    extra_g / extra_m: [(mask, colour)] drawn on top of the GPT / MJ map."""
    colg, colm = {0: PAL[0]}, {0: PAL[0]}
    nxt = 3
    for i in range(1, len(sg['names'])):
        j = pairs.get(i)
        nm = sg['names'][i]
        if j is not None and j in colm:
            colg[i] = colm[j]
            continue
        c = PAL[1] if nm == 'skin' else PAL[2] if nm == 'hair' else None
        if c is None:
            c = (PAL[nxt % len(PAL)] if nxt < len(PAL)
                 else tuple(int(v) for v in np.random.default_rng(nxt).integers(40, 255, 3)))
            nxt += 1
        colg[i] = c
        if j is not None:
            colm[j] = c
    for j in range(1, len(sm_['names'])):
        colm.setdefault(j, (70, 70, 70))
    unmatched = [i for i in range(1, len(sg['names'])) if pairs.get(i) is None]
    return _draw_regions(sm_, colm, h, extra=extra_m), _draw_regions(sg, colg, h, unmatched, extra_g)
