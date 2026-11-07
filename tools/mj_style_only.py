# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""只还原风格（④页）：GPT 图和 MJ 图构图、长宽、内容不同时，把 MJ 的颜色、明暗、柔化 / 局部反差、柔光、颗粒迁移到 GPT 图上。
四条路（kind='auto' 时按顺序自动判断，也可以在④页手动选）：
  · 构图一致（结构相关 ≥ 0.80）：和②页相同的逐位置还原；
  · 同一场景重画（内容比例相同，只是布局 / 角度变了）：按远近分层调色（mj_scene，远 / 中 / 近各自对齐 MJ 的明暗、
    偏色、饱和与清晰度，层内再按色相族微调；远近模型不可用时退回整幅统一调色），天空、背景一起调；
  · 角色为主（两张图都有够大的脸）：按区域对应，嘴唇再单独按 MJ 的嘴唇配色；
  · 其余（四视图、白底设定图、不同取景）：按区域对应（皮肤↔皮肤、头发↔头发、相近颜色↔相近颜色）。
按区域对应时，纯白 / 近白、低纹理的大块背景自动保护（不加色、不加颗粒、不加柔光），颜色统计只用主体像素。
「保留纯黑」：GPT 图里接近纯黑的衣物 / 鞋，限制提亮和染色，保持真黑。
用法：python mj_style_only.py MJ.png GPT.png OUT.png [--kind auto|scene|region|character] [--strength 1.0]
      [--keep-black] [--bg-follow] [--scale 1.0]"""
from i18n import tr
import argparse
import os

import cv2
import numpy as np

import mj_face
import mj_region as region
import mj_restore as engine
import mj_scene as scene
from mj_io import InputError, imread_alpha, imread_u, imwrite_u, unique_path, with_alpha, write_json
from mj_region import to_bgr, to_lab
from mj_restore import gblur

HERE = os.path.dirname(os.path.realpath(__file__))
STYLE_OUT = os.path.join(os.path.dirname(HERE), 'Output', 'style_only')   # 本页全部输出都放这里，和其他页签 / 标定分开

BANDS = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]   # px at MJ density; band k = G(s_k) - G(s_k+1)
GMIN = 0.45            # strongest per-band reduction (softness)
GMAX = 1.30            # strongest per-band boost (MJ sharper than GPT), fine bands only
GLOW_MAX_REG = 0.15    # max screen amount of added halation (glow index is content-dependent -> tight cap)
NEUTRAL_C = 15.0       # zone_stats: cast read from near-neutral pixels only (content colours excluded)
ALIGN_CORR = 0.80      # pair counts as 'same composition' above this structural correlation
SAME_SCENE_MAX = 1.3   # scene_distance at or below this = the same scene redrawn (measured: same 0.2–1.13, different ≥ 1.52)
SCENE_QS = np.linspace(0.5, 99.5, 100)
SCENE_BANDS = 8        # brightness bands for the colour cast of the whole-frame grade
ACCENT_C = 35.0        # chroma above this = accent colour (lantern, blossom, sign): not used to read the cast
SCENE_CHROMA = (0.85, 1.2)   # overall saturation scale limits of the whole-frame grade
KINDS = {'auto': tr('自动判断'), 'scene': tr('同一场景重画'), 'region': tr('构图 / 内容不同'), 'character': tr('角色为主')}
LOOK_TOL = dict(contrast=0.05, range=0.05, sat=0.12)   # max loss vs min(GPT, MJ); saturation is content-dependent
KB_L0, KB_L1 = 20.0, 40.0   # 保留纯黑：原 L 低于 KB_L0 全保护，到 KB_L1 渐变为不保护（黑色衣物实测 L 15~35）
KB_LIFT = 2.0               # 保护区最多提亮（L 单位）
KB_CHROMA = 1.5             # 保护区最多增加的彩度


# ------------------------------------------------------------------ masks
def bg_mask(img):
    """Soft weight 1 = pure-white/near-white low-texture background."""
    lab = to_lab(img)
    L, C = lab[..., 0], np.hypot(lab[..., 1], lab[..., 2])
    tex = np.sqrt(np.maximum(gblur(L * L, 3) - gblur(L, 3) ** 2, 0))
    hard = ((L > 90) & (C < 6) & (tex < 1.5)).astype(np.uint8)
    # keep only large connected areas (white shirt highlights inside the subject are not background).
    # 8-connectivity: the old call connectedComponentsWithStats(hard, 4) passed 4 as the `labels` argument,
    # so it always ran with the default 8 — that is what the thresholds were tuned with.
    hard = region._keep_large(hard, 0.002, 8)[0].astype(np.float32)
    hard = cv2.erode(hard, np.ones((5, 5), np.uint8))
    return np.clip(gblur(hard, 4), 0, 1)


def mj_valid(mj8):
    """MJ subject pixels: inside the letterbox AND not white/near-white background (screenshots, white-bg
    character sheets). Without this the white background was counted as 'highlights/glow' and the tone
    curve mapped GPT's subject onto a histogram full of white -> washed-out result."""
    v = engine.picture_mask(mj8)
    s = v & (bg_mask(engine.to_f(mj8)) < 0.5)
    return s if s.sum() > v.sum() * 0.05 else v


def look_stats(img, w):
    """Subject contrast (L std, L p95-p5) and saturation (mean Lab chroma)."""
    lab = to_lab(img)
    L = lab[..., 0][w]
    C = np.hypot(lab[..., 1], lab[..., 2])[w]
    p = np.percentile(L, [5, 95])
    return dict(contrast=float(L.std()), range=float(p[1] - p[0]), sat=float(C.mean()))


# ------------------------------------------------------------------ measurements
def zone_stats(lab, w):
    L, a, b = lab[..., 0][w], lab[..., 1][w], lab[..., 2][w]
    n = np.hypot(a, b) < NEUTRAL_C
    q = np.percentile(L, [15, 85])
    out = []
    for m in (L <= q[0], (L > q[0]) & (L < q[1]), L >= q[1]):
        mn = m & n if (m & n).sum() > 200 else m
        out.append(dict(L=float(L[m].mean()), a=float(a[m].mean()), b=float(b[m].mean()),
                        na=float(a[mn].mean()), nb=float(b[mn].mean()),
                        sa=float(a[m].std()), sb=float(b[m].std())))
    return out


def grain(img, w, scale=1.0):
    """Flat-area high-pass sigma (L units) at MJ density (resize by 1/scale): (sigma-1 band, 1-2 px band)."""
    if abs(scale - 1) > 1e-3:
        img = cv2.resize(img, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA)
        w = cv2.resize(w.astype(np.uint8), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    L = to_lab(img)[..., 0]
    hp = L - gblur(L, 1.0)
    m = np.abs(gblur(gblur(L, 1) - gblur(L, 3), 4))
    flat = w & (m < np.percentile(m[w], 30)) & (L > 8) & (L < 92)
    return (float(np.median(np.abs(hp[flat])) * 1.4826),
            float(np.median(np.abs((gblur(L, 1) - gblur(L, 2))[flat])) * 1.4826))


def band_profile(img, w, scale=1.0):
    """Band energies normalised by the coarsest band -> spectral shape (roughly content-size independent)."""
    L = to_lab(img)[..., 0]
    Gs = [gblur(L, s * scale) for s in BANDS]
    e = [float(np.sqrt(((Gs[k] - Gs[k + 1]) ** 2)[w].mean())) for k in range(len(BANDS) - 1)]
    return np.array(e) / (e[-1] + 1e-6)


def glow_index(img, w, scale=1.0):
    """Halation: light spilled into the ring just outside highlights, relative to highlight excess."""
    L = to_lab(img)[..., 0]
    t = np.percentile(L[w], 92)
    hl = (L > t) & w
    d = cv2.distanceTransform((~hl).astype(np.uint8), cv2.DIST_L2, 3)
    ring = (d > 2 * scale) & (d < 12 * scale) & w
    far = (d > 24 * scale) & (d < 48 * scale) & w
    if ring.sum() < 100 or far.sum() < 100:
        return float('nan')
    return float((L[ring].mean() - L[far].mean()) / (L[hl].mean() - L[far].mean() + 1e-6))


def chroma_grain(img, w):
    lab = to_lab(img)

    def sigma(x):
        return float(np.median(np.abs((x - gblur(x, 1.0))[w])) * 1.4826)
    return sigma(lab[..., 1]), sigma(lab[..., 2])


# ------------------------------------------------------------------ transforms
def soften(img, w_s, prof_m, scale, strength=1.0, sharpen=False):
    prof_g = band_profile(img, w_s > 0.9, scale)
    gains = np.clip(prof_m / (prof_g + 1e-6), GMIN, GMAX if sharpen else 1.0)
    if sharpen:
        gains[2:] = np.minimum(gains[2:], 1.0)        # boost only the 1-4 px bands (no halo-y mid sharpening)
    gains = 1 + (gains - 1) * strength
    gains = np.where(np.abs(gains - 1) < 0.05, 1.0, gains)
    Gs = [gblur(img, s * scale) for s in BANDS]
    d = sum((g - 1) * (Gs[k] - Gs[k + 1]) for k, g in enumerate(gains))
    return np.clip(img + d * w_s[..., None], 0, 1), gains, prof_g


def halation(img, w_s, amt, tint, scale):
    L = to_lab(img)[..., 0]
    t = np.percentile(L[w_s > 0.9], 85)
    e = np.clip((L - t) / (100 - t), 0, 1) * w_s
    h = 0.6 * gblur(e, 6 * scale) + 0.4 * gblur(e, 20 * scale)
    col = to_bgr(np.array([[[70.0, tint[0], tint[1]]]], np.float32))[0, 0]
    col = col / col.max()
    add = amt * h[..., None] * col
    return 1 - (1 - img) * (1 - add)   # screen


def _unit_noise(rng, H, W, size):
    n = rng.standard_normal((H, W)).astype(np.float32)
    if size > 0.3:
        n = gblur(n, size)
    n /= (n - gblur(n, 1.0)).std() + 1e-6             # unit sigma-1 high-pass (what grain() measures)
    return n


def add_grain(img, w_s, sig_add, size, seed=0, chroma=(0.0, 0.0)):
    rng = np.random.default_rng(seed)
    H, W = img.shape[:2]
    n = _unit_noise(rng, H, W, size)
    L = to_lab(img)[..., 0]
    tonal = np.clip(np.minimum(L / 15.0, (100 - L) / 12.0), 0, 1)   # less in deep black / near-white
    lab = to_lab(img)
    lab[..., 0] += n * sig_add * tonal * w_s
    for c, amp in ((1, chroma[0]), (2, chroma[1])):
        if amp > 0.05:
            lab[..., c] += _unit_noise(rng, H, W, size) * amp * tonal * w_s
    return to_bgr(lab)


def keep_black(orig, img):
    """Deep-shadow guard: limit lift and tint where the GPT original is near-black."""
    lo, li = to_lab(orig), to_lab(img)
    w = np.clip((KB_L1 - lo[..., 0]) / (KB_L1 - KB_L0), 0, 1)
    L = np.minimum(li[..., 0], lo[..., 0] + KB_LIFT)
    co, ci = np.hypot(lo[..., 1], lo[..., 2]), np.hypot(li[..., 1], li[..., 2])
    k = np.minimum(1.0, (co + KB_CHROMA) / np.maximum(ci, 1e-6))
    out = np.dstack([L, li[..., 1] * k, li[..., 2] * k]).astype(np.float32)
    return to_bgr(li * (1 - w[..., None]) + out * w[..., None])


def finish(gf, full, wsh, mj_look, strength, keep_black_on, log):
    """Strength scales every component linearly (one blend of the full-strength effect), then the
    anti-washout guard: subject contrast/saturation must not fall below min(GPT, MJ) minus LOOK_TOL; if they do,
    the effect is scaled back automatically. 保留纯黑 is applied last."""
    g_look = look_stats(gf, wsh)
    floor = {k: min(g_look[k], mj_look[k]) * (1 - t) for k, t in LOOK_TOL.items()}

    def make(k):
        o = gf + (full - gf) * k
        return keep_black(gf, o) if keep_black_on else o

    def bad(o):
        st = look_stats(o, wsh)
        return any(st[k] < floor[k] for k in floor)

    k = float(strength)
    out = make(k)
    if k > 0 and bad(out):
        lo, hi = 0.0, k
        for _ in range(8):
            mid = (lo + hi) / 2
            if bad(make(mid)):
                hi = mid
            else:
                lo = mid
        log(tr('防发灰：反差/饱和度会低于 GPT 与 MJ 的较低者，强度自动从 {k:.2f} 回退到 {lo:.2f}', k=k, lo=lo))
        k = lo
        out = make(k)
    if keep_black_on:
        log(tr('保留纯黑：已限制深色区域的提亮和染色'))
    r = look_stats(out, wsh)
    log(tr('反差 GPT {contrast:.1f} → 结果 {contrast2:.1f}（MJ {contrast3:.1f}）；饱和度 GPT '
           '{sat:.1f} → 结果 {sat2:.1f}（MJ {sat3:.1f}）', contrast=g_look['contrast'], contrast2=r['contrast'], contrast3=mj_look['contrast'], sat=g_look['sat'], sat2=r['sat'], sat3=mj_look['sat']))
    return out


# ------------------------------------------------------------------ MJ texture (shared by the scene and region paths)
def mj_texture(mjc, wm, log):
    """MJ subject texture statistics: grain, band profile (softness), glow, chroma grain, highlight tint."""
    st = dict(grain=grain(mjc, wm), prof=band_profile(mjc, wm), glow=glow_index(mjc, wm), cg=chroma_grain(mjc, wm))
    labm = to_lab(mjc)
    hl = labm[..., 0] > np.percentile(labm[..., 0][wm], 90)
    st['tint'] = (float(labm[..., 1][hl & wm].mean()), float(labm[..., 2][hl & wm].mean()))
    log(tr('MJ 主体：颗粒 {v:.2f}/{v2:.2f}，彩色颗粒 {v3:.2f}/{v4:.2f}，柔光 {glow:.3f}，高光色 a{v5:+.1f} b{v6:+.1f}', v=st["grain"][0], v2=st["grain"][1], v3=st["cg"][0], v4=st["cg"][1], glow=st["glow"], v5=st["tint"][0], v6=st["tint"][1]))
    return st


def add_texture(P, ws, wsh, st, scale, log, soften_on=True):
    """Soften / slightly sharpen to MJ's band profile, capped halation, luminance + chroma grain (weights ws).
    soften_on=False: the caller already matched softness per depth layer (scene path, mj_scene)."""
    m_grain, m_glow, tint = st['grain'], st['glow'], st['tint']
    if soften_on:
        P, gains, _ = soften(P, ws, st['prof'], scale, 1.0, sharpen=True)
        log(tr('频段增益（<1 柔化，>1 锐化）{v}', v=np.round(gains, 3)))
    amt = 0.0
    g0 = glow_index(P, wsh, scale)
    if np.isfinite(m_glow) and np.isfinite(g0) and g0 < m_glow:
        lo, hi = 0.0, GLOW_MAX_REG
        for _ in range(10):
            mid = (lo + hi) / 2
            if glow_index(halation(P, ws, mid, tint, scale), wsh, scale) < m_glow:
                lo = mid
            else:
                hi = mid
        amt = lo
        P = halation(P, ws, amt, tint, scale)
    log(tr('柔光量 {amt:.3f}', amt=amt))
    size = 0.0 if m_grain[1] / max(m_grain[0], 1e-6) < 0.45 else 0.6 * scale
    gc = grain(P, wsh, scale)[0]
    add = np.sqrt(max(m_grain[0] ** 2 - gc ** 2, 0))
    pc = chroma_grain(P, wsh)
    cadd = tuple(min(float(np.sqrt(max(m ** 2 - p ** 2, 0))), 1.5) for m, p in zip(st['cg'], pc))
    Q = add_grain(P, ws, add, size, chroma=cadd)
    gq = grain(Q, wsh, scale)[0]
    if gq > 0 and add > 0:   # one feedback pass: rescale so the measured grain lands on MJ's
        add *= np.clip(max(m_grain[0] ** 2 - gc ** 2, 0) ** 0.5 / max(max(gq ** 2 - gc ** 2, 0) ** 0.5, 1e-6),
                       0.5, 2.0)
        Q = add_grain(P, ws, add, size, chroma=cadd)
    log(tr('颗粒补充 {add:.2f}（尺寸 {size:.2f}），彩色颗粒 {v:.2f}/{v2:.2f}', add=add, size=size, v=cadd[0], v2=cadd[1]))
    return Q


# ------------------------------------------------------------------ which path
def aligned_check(mj8, g8, swap=False):
    """prepare() result when the two images are the same composition, else None. swap = 换头的结果（见 mj_restore）。"""
    try:
        q = engine.pair_quality(mj8, g8, swap)
    except Exception:
        return None
    return q if q['ok'] and np.isfinite(q['corr']) and q['corr'] >= ALIGN_CORR else None


def _lab_sample(img8, n=40000, long_side=400):
    s = long_side / max(img8.shape[:2])
    small = cv2.resize(img8, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img8
    lab = to_lab(engine.to_f(small)).reshape(-1, 3)
    return lab[np.random.default_rng(0).choice(len(lab), min(len(lab), n), replace=False)]


def scene_distance(mj8, g8):
    """How different the two images' content proportions are, independent of the grade: sliced Wasserstein
    distance between the Lab colour distributions after GPT's is shifted / scaled to MJ's mean and spread.
    Measured on 270 pairs: same scene 0.2–1.13, different content (character sheet vs photo, other scenes) ≥ 1.52."""
    A, B = _lab_sample(mj8), _lab_sample(g8)
    B = (B - B.mean(0)) / (B.std(0) + 1e-6) * A.std(0) + A.mean(0)
    dirs = np.random.default_rng(1).standard_normal((64, 3))
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    qs = np.linspace(1, 99, 50)
    return float(np.mean([np.mean(np.abs(np.percentile(A @ d, qs) - np.percentile(B @ d, qs))) for d in dirs]))


def character_faces(mjc8, g8, log):
    """(GPT main face, MJ main face) when both images are character-centric, else None."""
    if not mj_face.available():
        log(tr('[提醒] 人脸模型不可用（缺少 face_detection_yunet_2023mar.onnx 或 OpenCV 太旧），嘴唇不单独配色'))
        return None
    fg, fm = mj_face.main_face(g8), mj_face.main_face(mjc8)
    return (fg, fm) if fg is not None and fm is not None else None


def decide(mj8, g8, kind, log, swap=False):
    """('aligned', prepare result) / ('scene', None) / ('character', (GPT face, MJ face)) / ('region', None)."""
    y0, y1, x0, x1 = engine.bar_box(mj8)
    mjc8 = mj8[y0:y1, x0:x1]
    if kind == 'scene':
        log(tr('按选择：同一场景重画'))
        return 'scene', None
    if kind == 'region':
        log(tr('按选择：构图 / 内容不同 → 按区域对应'))
        return 'region', None
    if kind == 'character':
        faces = character_faces(mjc8, g8, log)
        if faces is None:
            log(tr('[提醒] 没在两张图里都找到够大的脸（脸高至少占画面 {v:.0f}%），嘴唇不单独配色，其余照常按区域对应', v=mj_face.CHAR_MIN * 100))
            return 'region', None
        log(tr('按选择：角色为主 → 按区域对应 + 嘴唇单独配色'))
        return 'character', faces
    q = aligned_check(mj8, g8, swap)
    if q is not None:
        log(tr('构图一致（结构相关 {corr:.2f}，MJ 覆盖 {v:.0f}%）→ 按位置逐区域还原（与 ② 同一引擎）', corr=q['corr'], v=q['coverage'] * 100)
            + ({'person': tr('；这张 MJ 图在①页按“修错 + 换整个角色”生成过提示词 → 人物按 MJ 同类区域还原'),
                'head': tr('；这张 MJ 图在①页按“修错 + 换头”生成过提示词 → 头部按 MJ 同类区域还原')}
               .get(engine.swap_kind(swap), '')))
        return 'aligned', q
    d = scene_distance(mjc8, g8)
    if d <= SAME_SCENE_MAX:
        log(tr('内容比例相同（颜色分布距离 {d:.2f} ≤ {SAME_SCENE_MAX}）→ 同一场景重画', d=d, SAME_SCENE_MAX=SAME_SCENE_MAX))
        return 'scene', None
    faces = character_faces(mjc8, g8, log)
    if faces is not None:
        log(tr('构图 / 内容不同（颜色分布距离 {d:.2f}），两张图都是角色为主 → 按区域对应 + 嘴唇单独配色', d=d))
        return 'character', faces
    log(tr('构图 / 内容不同（颜色分布距离 {d:.2f}）→ 按区域对应迁移风格', d=d))
    return 'region', None


# ------------------------------------------------------------------ the paths
def style_aligned(mj8, g8, prep, strength, keep_black_on, log):
    """Same composition: position-correspondence transfer = tab ②'s restore(mode='transfer') engine
    (aligned 3D LUT + local low-frequency colour/tone/haze + per-tile blur/band gains + per-tile grain),
    then this tab's own parts: white-background protection, linear strength, anti-washout guard, 保留纯黑."""
    gf = engine.to_f(g8)
    wb = bg_mask(gf)
    ws = 1 - wb
    wsh = ws > 0.9
    res = engine.restore(mj8, g8, mode='transfer', log=lambda m: log('    ' + m), prep=prep)
    full = gf * wb[..., None] + engine.to_f(res['out']) * ws[..., None]
    # MJ look measured at the corresponding positions (MJ warped onto the GPT canvas, subject only).
    # Coverage = restore()'s 'outside' map: mj_up is resampled with BORDER_REPLICATE, so "pixel sum > 0" would
    # count GPT's outpainted margins as MJ (and drop MJ's true-black pixels instead).
    mj_up = engine.to_f(res['mj_up'])
    fp = ~res['outside']
    w = wsh & fp if (wsh & fp).sum() > 1000 else wsh
    out = finish(gf, full, w, look_stats(mj_up, w), strength, keep_black_on, log)
    return engine.to_u8(out), wb


def scene_grade(gf, mjc):
    """Whole-frame grade for a redraw of the same scene: lightness mapped quantile to quantile (one monotone tone
    curve), colour cast shifted per brightness rank (8 bands) as read from MJ's non-accent pixels, overall
    saturation scaled to MJ's. Accents (lanterns, blossoms, signs) keep their own colour and only follow the cast."""
    lab, labm = to_lab(gf), to_lab(mjc)
    Lg, Lm = lab[..., 0], labm[..., 0]
    src, dst = np.percentile(Lg, SCENE_QS), np.percentile(Lm, SCENE_QS)
    su, idx = np.unique(src, return_index=True)
    du = np.maximum.accumulate(dst[idx])
    L2 = np.interp(Lg, su, du) + np.where(Lg < su[0], Lg - su[0], 0) + np.where(Lg > su[-1], Lg - su[-1], 0)
    rank_g = np.interp(Lg, su, SCENE_QS[idx])                 # each pixel's brightness rank, 0.5..99.5
    mu, mi = np.unique(dst, return_index=True)
    rank_m = np.interp(Lm, mu, SCENE_QS[mi])
    Cg, Cm = np.hypot(lab[..., 1], lab[..., 2]), np.hypot(labm[..., 1], labm[..., 2])
    edges = np.linspace(0, 100, SCENE_BANDS + 1)
    cen, da, db = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        g, m = (rank_g >= lo) & (rank_g < hi), (rank_m >= lo) & (rank_m < hi)
        if g.sum() < 100 or m.sum() < 100:
            continue
        gn, mn = g & (Cg < ACCENT_C), m & (Cm < ACCENT_C)
        if gn.sum() > 200 and mn.sum() > 200:
            g, m = gn, mn
        cen.append((lo + hi) / 2)
        da.append(labm[..., 1][m].mean() - lab[..., 1][g].mean())
        db.append(labm[..., 2][m].mean() - lab[..., 2][g].mean())
    a2 = lab[..., 1] + np.interp(rank_g, cen, da)
    b2 = lab[..., 2] + np.interp(rank_g, cen, db)
    k = float(np.clip(np.median(Cm) / max(float(np.median(Cg)), 1e-3), *SCENE_CHROMA))
    return to_bgr(np.dstack([L2, a2 * k, b2 * k]).astype(np.float32)), k


def style_scene(mj8, g8, scale=None, strength=1.0, log=print, keep_black_on=False, bg_follow=False, layered=True):
    """Same scene redrawn (same content proportions, layout differs): sky and backdrop included, then MJ's texture.
    layered=True (default) and the depth model available: grade per near / mid / far layer (mj_scene) so the far
    field gets MJ's haze, black level, contrast and softness; otherwise one grade for the whole frame (v4.3).
    Returns (out8, background weight (none), extra)."""
    y0, y1, x0, x1 = engine.bar_box(mj8)
    mjc8 = mj8[y0:y1, x0:x1]
    mjc, gf = engine.to_f(mjc8), engine.to_f(g8)
    if bg_follow:
        log(tr('（同一场景重画时背景本来就一起调整，「背景也跟随MJ」不起作用）'))
    if scale is None:   # texture density: GPT px per MJ px (same framing -> image size ratio)
        scale = float(np.clip(max(g8.shape[:2]) / max(mjc.shape[:2]), 0.5, 4.0))
    depth = scene.depth_pair(mjc8, g8, log) if layered else None
    layers = None
    if depth is not None:
        dm, dg = depth
        log(tr('按远近分层调色：远近分 {n} 档，每档单独对齐 MJ 的明暗、偏色、饱和与清晰度，层内再按色相族微调；纹理密度 {scale:.2f}', n=len(scene.U_C), scale=scale))
        P, layers = scene.layered_grade(gf, mjc, dg, dm, scale, log)
        layers.update(depth_gpt=dg, depth_mj=dm)
    else:
        P, k = scene_grade(gf, mjc)
        log(tr('整幅统一调色：明暗曲线按 MJ，偏色按亮度分 {SCENE_BANDS} 段对齐 MJ，饱和 ×{k:.2f}；纹理密度 {scale:.2f}', SCENE_BANDS=SCENE_BANDS, k=k, scale=scale))
    ws = np.ones(gf.shape[:2], np.float32)
    wsh = ws > 0.9
    wm = np.ones(mjc.shape[:2], bool)
    Q = add_texture(P, ws, wsh, mj_texture(mjc, wm, log), scale, log, soften_on=depth is None)
    out = finish(gf, Q, wsh, look_stats(mjc, wm), strength, keep_black_on, log)
    return engine.to_u8(out), np.zeros(gf.shape[:2], np.float32), \
        dict(seg=None, regions=None, scale=scale, lips=None, layers=layers)


def style_regions(mj8, g8, scale=None, strength=1.0, log=print, keep_black_on=False, bg_follow=False, faces=None):
    """Different framing / aspect / content: region-correspondence transfer (mj_region) for colour & tone,
    then MJ-subject texture (band profile soften/sharpen, capped halation, luminance + chroma grain).
    faces = (GPT main face, MJ main face) for character-centric pairs: the lips are then recoloured separately.
    Returns (out8, background weight, dict(seg=(seg_g, seg_m, pairs), regions=info, scale, lips))."""
    mjf, gf = engine.to_f(mj8), engine.to_f(g8)
    y0, y1, x0, x1 = engine.bar_box(mj8)
    mjc = mjf[y0:y1, x0:x1]
    g_white = bg_mask(gf)
    P, info, sg, sm_, pairs, wbg = region.transfer(gf, mjc, g_white, bg_mask(mjc), log, bg_follow)
    lips = None
    if faces is not None:
        lips = dict(g=mj_face.lips_mask(g8, faces[0]), m=mj_face.lips_mask(mj8[y0:y1, x0:x1], faces[1]))
        P = mj_face.apply_lips(P, gf, mjc, lips['g'], lips['m'], log)
    if scale is None:   # texture density: GPT px per MJ px, from the two faces when both are found
        scale = 1.0
        if sg['face'] is not None and sm_['face'] is not None:
            fg = sg['face'][2] / sg['scale']
            fm = sm_['face'][2] / sm_['scale']
            scale = float(np.clip(fg / max(fm, 1), 0.5, 4.0))
            log(tr('纹理密度：按两张图的脸宽，GPT 每 {scale:.2f} 像素 ≈ MJ 1 像素', scale=scale))
    wb = np.clip(wbg, 0, 1)
    ws = 1 - wb
    wsh = ws > 0.9
    mbg = cv2.resize((sm_['labels'] == 0).astype(np.uint8), (mjc.shape[1], mjc.shape[0]),
                     interpolation=cv2.INTER_NEAREST) > 0
    wm = ~mbg if (~mbg).sum() > 0.05 * mbg.size else np.ones_like(mbg)
    st = mj_texture(mjc, wm, log)
    log(tr('GPT 背景占比 {v:.1f}%', v=wb.mean() * 100) + (tr('（背景跟随 MJ）') if bg_follow else tr('（背景保持不变）')))
    plain = float(((wb > 0.5) & (g_white < 0.5)).mean())     # background that is not white: wall, sky, studio backdrop
    if not bg_follow and plain > 0.05:
        log(tr('[提醒] GPT 图里有 {v:.0f}% 是与画面边缘相连的纯色 / 渐变区域（墙面、天空、影棚底等），按背景处理、保持 GPT 原样；想让它也跟随 MJ 的色调，勾「背景也跟随MJ」。', v=plain * 100))
    if not bg_follow:
        P = gf * wb[..., None] + P * ws[..., None]
    Q = add_texture(P, ws, wsh, st, scale, log)
    full = Q if bg_follow else gf * wb[..., None] + Q * ws[..., None]
    out = finish(gf, full, wsh, look_stats(mjc, wm), strength, keep_black_on, log)
    return engine.to_u8(out), wb, dict(seg=(sg, sm_, pairs), regions=info, scale=scale, lips=lips)


def style_only(mj8, g8, scale=None, strength=1.0, log=print, keep_black_on=False, bg_follow=False, kind='auto',
               swap=False):
    """kind: 'auto' / 'scene' / 'region' / 'character' (see KINDS). Returns (out8, background weight, extra).
    swap = 'head' / 'person'（True = 'head'）：换头 / 换整个角色的结果，构图一致时人物按 MJ 同类区域还原（同②页）。"""
    path, info = decide(mj8, g8, kind, log, swap)
    if path == 'aligned':
        o8, wb = style_aligned(mj8, g8, info, strength, keep_black_on, log)
        return o8, wb, dict(seg=None, regions=None, scale=1.0, lips=None)
    if path == 'scene':
        return style_scene(mj8, g8, scale, strength, log, keep_black_on, bg_follow)
    return style_regions(mj8, g8, scale, strength, log, keep_black_on, bg_follow,
                         faces=info if path == 'character' else None)


# ------------------------------------------------------------------ report / output
def report(mj8, g8, o8, wb, scale=1.0):
    mjf, gf, of = engine.to_f(mj8), engine.to_f(g8), engine.to_f(o8)
    wm = mj_valid(mj8)
    ws = (1 - wb) > 0.9
    bg = wb > 0.99
    zm = zone_stats(to_lab(mjf), wm)

    def zone_err(img):
        z = zone_stats(to_lab(img), ws)
        de = float(np.mean([np.sqrt((x['L'] - y['L']) ** 2 + (x['a'] - y['a']) ** 2 + (x['b'] - y['b']) ** 2)
                            for x, y in zip(z, zm)]))
        dab = float(np.mean([np.hypot(x['a'] - y['a'], x['b'] - y['b']) for x, y in zip(z, zm)]))
        return de, dab, z

    pm = band_profile(mjf, wm)
    lab_g = to_lab(gf)
    rows = {}
    for nm, img in (('GPT', gf), ('result', of)):
        de, dab, z = zone_err(img)
        lab = to_lab(img)
        rows[nm] = dict(zone_dE=de, zone_dab=dab, zones=z, grain=grain(img, ws, scale)[0],
                        glow=glow_index(img, ws, scale),
                        band_err=float(np.mean(np.abs(np.log(band_profile(img, ws, scale) / pm)))),
                        bg_dE_vs_gpt=float(np.sqrt(((lab - lab_g) ** 2).sum(-1))[bg].mean()) if bg.any() else 0.0,
                        bg_grain=(float(np.median(np.abs((lab[..., 0] - gblur(lab[..., 0], 1))[bg])) * 1.4826)
                                  if bg.any() else 0.0),
                        **look_stats(img, ws))
    rows['MJ'] = dict(zones=zm, grain=grain(mjf, wm)[0], glow=glow_index(mjf, wm), bg_share=float(wb.mean()),
                      **look_stats(mjf, wm))
    return rows


def layer_report(mj8, g8, o8, layers, log=print):
    """Per near / mid / far layer statistics (MJ, GPT, result) for the metrics file, plus a short log summary."""
    y0, y1, x0, x1 = engine.bar_box(mj8)
    f = engine.to_f
    st = dict(MJ=scene.layer_stats(f(mj8[y0:y1, x0:x1]), layers['depth_mj']),
              GPT=scene.layer_stats(f(g8), layers['depth_gpt']), result=scene.layer_stats(f(o8), layers['depth_gpt']))
    for ly in (tr('远景'), tr('中景'), tr('近景')):
        if all(ly in st[k] for k in st):
            g, r, m = st['GPT'][ly], st['result'][ly], st['MJ'][ly]
            log(tr('{ly}：暗部 {L_p5:.1f} → {L_p52:.1f}（MJ {L_p53:.1f}），中间调 {L_p50:.1f} → {L_p502:.1f}（MJ '
                   '{L_p503:.1f}），彩度 {chroma:.1f} → {chroma2:.1f}（MJ {chroma3:.1f}）', ly=ly, L_p5=g['L_p5'], L_p52=r['L_p5'], L_p53=m['L_p5'], L_p50=g['L_p50'], L_p502=r['L_p50'], L_p503=m['L_p50'], chroma=g['chroma'], chroma2=r['chroma'], chroma3=m['chroma']))
    return dict(stats=st, bins=layers['bins'], families=layers['families'])


def style_out_path(gpt_path, suffix, extras=()):
    """输出\\只还原风格\\原名+suffix；已有同名文件（含同组附带文件）时自动加 _2、_3……"""
    return unique_path(STYLE_OUT, os.path.splitext(os.path.basename(gpt_path))[0], suffix, extras)


_FONT_CACHE = {}
_ASCII = {'结果': 'Result', 'MJ 区域': 'MJ regions', 'GPT 区域': 'GPT regions',
          'MJ 远近': 'MJ depth', 'GPT 远近': 'GPT depth'}


def _font(px):
    if px not in _FONT_CACHE:
        from PIL import ImageFont
        f = None
        fonts = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
        for name in ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf', 'simsun.ttc'):
            for path in (os.path.join(fonts, name), name):
                try:
                    f = ImageFont.truetype(path, px)
                    break
                except OSError:
                    pass
            if f:
                break
        _FONT_CACHE[px] = f
    return _FONT_CACHE[px]


def label(img, text):
    """左上角角标：黑底白色小字，贴边无外边距；字号约为高度的 3%（至少 14px）。"""
    from PIL import Image, ImageDraw, ImageFont
    px = max(14, int(round(img.shape[0] * 0.03)))
    f = _font(px)
    if f is None:
        f = ImageFont.load_default()
        text = _ASCII.get(text, text)
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(im)
    l, t, r_, b = d.textbbox((0, 0), text, font=f)
    pad = max(3, px // 3)
    d.rectangle([0, 0, r_ - l + 2 * pad, b - t + 2 * pad], fill=(0, 0, 0))
    d.text((pad - l, pad - t), text, font=f, fill=(255, 255, 255))
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def _to_height(x, h):
    return cv2.resize(x, (int(x.shape[1] * h / x.shape[0]), h), interpolation=cv2.INTER_AREA)


def _sheet(tiles, names, path):
    tiles = [label(np.ascontiguousarray(t), n) for t, n in zip(tiles, names)] + list(tiles[len(names):])
    imwrite_u(path, np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])


def _lips_overlays(lips):
    if not lips:
        return (), ()
    return tuple((m, mj_face.LIPS_COLOR) for m in (lips['g'],) if m is not None), \
        tuple((m, mj_face.LIPS_COLOR) for m in (lips['m'],) if m is not None)


def make_compare(mj8, g8, o8, path, seg=None, lips=None, h=600, layers=None):
    """MJ | GPT | result, plus (region path) MJ region map | GPT region map: same colour = matched regions,
    grey = background, dark stripes = no counterpart in MJ (uses the overall subject grade), red = lips;
    or (scene path, layered) MJ / GPT near-mid-far maps: blue = far, green = middle, red = near."""
    tiles = [_to_height(mj8, h), _to_height(g8, h), _to_height(o8, h)]
    names = ['MJ', 'GPT', tr('结果'), tr('MJ 区域'), tr('GPT 区域')]
    if seg:
        og, om = _lips_overlays(lips)
        tiles += list(region.region_maps(*seg, h, extra_g=og, extra_m=om))
    elif layers:
        y0, y1, x0, x1 = engine.bar_box(mj8)
        tiles += [scene.layer_map(mj8[y0:y1, x0:x1], layers['depth_mj'], h), scene.layer_map(g8, layers['depth_gpt'], h)]
        names = ['MJ', 'GPT', tr('结果'), tr('MJ 远近'), tr('GPT 远近')]
    _sheet(tiles, names, path)


def read_pair(mj_path, gpt_path):
    """(MJ, GPT composited over white, GPT alpha or None)."""
    mj8, (g8, g_alpha) = imread_u(mj_path), imread_alpha(gpt_path)
    if mj8 is None or g8 is None:
        raise InputError(tr('读不到图片：') + (mj_path if mj8 is None else gpt_path))
    return mj8, g8, g_alpha


def preview_regions(mj_path, gpt_path, log=print, kind='auto'):
    """「区域对应预览」: segmentation + matching only (a few seconds), no output image. Returns jpg path."""
    mj8, g8, _ = read_pair(mj_path, gpt_path)
    y0, y1, x0, x1 = engine.bar_box(mj8)
    mjc, gf = engine.to_f(mj8[y0:y1, x0:x1]), engine.to_f(g8)
    path_kind, info = decide(mj8, g8, kind, log)
    if path_kind == 'scene':
        depth = scene.depth_pair(mj8[y0:y1, x0:x1], g8, log)
        if depth is not None:
            h = 600
            path = style_out_path(gpt_path, '_depth_layers.jpg')
            _sheet([_to_height(mj8[y0:y1, x0:x1], h), _to_height(g8, h), scene.layer_map(mj8[y0:y1, x0:x1], depth[0], h),
                    scene.layer_map(g8, depth[1], h)], ['MJ', 'GPT', tr('MJ 远近'), tr('GPT 远近')], path)
            for d, who in ((depth[0], 'MJ'), (depth[1], 'GPT')):
                lw = scene.layer_weights(scene.bin_weights(d)).argmax(-1)
                log(tr('  {who}：远景 {v:.0f}%，中景 {v2:.0f}%，近景 {v3:.0f}%', who=who, v=(lw == 0).mean() * 100, v2=(lw == 1).mean() * 100, v3=(lw == 2).mean() * 100))
            log(tr('远近分层图：') + path + tr('（蓝 = 远景，绿 = 中景，红 = 近景；每一档单独对齐 MJ 同一档的明暗、颜色和清晰度）'))
            return path
    if path_kind in ('aligned', 'scene'):
        log(tr('这条路不用区域对应，下面的区域划分只供参考。'))
    lips = None
    if path_kind == 'character':
        lips = dict(g=mj_face.lips_mask(g8, info[0]), m=mj_face.lips_mask(mj8[y0:y1, x0:x1], info[1]))
        log(tr('  嘴唇（红色）：') + tr('，').join(f'{n} {tr("找到了") if m is not None else tr("没找到")}' for n, m in
                                         (('GPT', lips['g']), ('MJ', lips['m']))))
    sg, sm_ = region.segment_pair(gf, mjc, bg_mask(gf), bg_mask(mjc))
    pairs, _ = region.match(sg, sm_)
    for i in range(1, len(sg['names'])):
        j = pairs.get(i)
        log(tr('  GPT「{v}」↔ MJ「{v2}」', v=region.region_name(sg, i), v2=region.region_name(sm_, j) if j is not None else tr('无对应（用整体风格）')))
    h = 600
    path = style_out_path(gpt_path, '_regions.jpg')
    og, om = _lips_overlays(lips)
    maps = region.region_maps(sg, sm_, pairs, h, extra_g=og, extra_m=om)
    _sheet([_to_height(mj8[y0:y1, x0:x1], h), _to_height(g8, h)] + list(maps), ['MJ', 'GPT', tr('MJ 区域'), tr('GPT 区域')], path)
    log(tr('区域对应图：') + path + tr('（同一颜色 = 互相对应；灰 = 背景；暗斜纹 = MJ 里没有对应，用整体风格')
        + (tr('；红 = 嘴唇') if lips else '') + tr('）'))
    return path


def run(mj_path, gpt_path, strength=1.0, keep_black_on=False, log=print, scale=None, bg_follow=False, kind='auto',
        swap=False):
    """GUI entry. Output in 输出\\只还原风格 (never next to the input), GPT size. Returns dict(out, compare, metrics)."""
    mj8, g8, g_alpha = read_pair(mj_path, gpt_path)
    log(tr('MJ 风格图 {v}×{v2}，GPT 图 {v3}×{v4}，类型 {v5}，强度 {strength:.2f}，保留纯黑 {v6}，背景也跟随MJ {v7}', v=mj8.shape[1], v2=mj8.shape[0], v3=g8.shape[1], v4=g8.shape[0], v5=KINDS.get(kind, kind), strength=strength, v6=tr('开') if keep_black_on else tr('关'), v7=tr('开') if bg_follow else tr('关')))
    o8, wb, extra = style_only(mj8, g8, scale, strength, log, keep_black_on, bg_follow, kind, swap)
    out = style_out_path(gpt_path, '_style_restored.png', ('_compare.jpg', '_metrics.json'))
    imwrite_u(out, with_alpha(o8, g_alpha))
    if g_alpha is not None:
        log(tr('GPT 图有透明背景：结果保留了同样的透明通道'))
    base = os.path.splitext(out)[0]
    layers = extra.get('layers')
    make_compare(mj8, g8, o8, base + '_compare.jpg', extra['seg'], extra.get('lips'), layers=layers)
    rep = report(mj8, g8, o8, wb, extra['scale'] or 1.0)
    if extra['regions']:
        rep['regions'] = extra['regions']
    if layers:
        rep['layers'] = layer_report(mj8, g8, o8, layers, log)
    write_json(base + '_metrics.json', rep)
    g, r = rep['GPT'], rep['result']
    log(tr('主体色差（对 MJ）{zone_dE:.2f} → {zone_dE2:.2f}；柔化误差 {band_err:.3f} → {band_err2:.3f}；'
           '柔光 {glow:.3f} → {glow2:.3f}（MJ {glow3:.3f}）；背景变化 {bg_dE_vs_gpt:.3f}', zone_dE=g['zone_dE'], zone_dE2=r['zone_dE'], band_err=g['band_err'], band_err2=r['band_err'], glow=g['glow'], glow2=r['glow'], glow3=rep['MJ']['glow'], bg_dE_vs_gpt=r['bg_dE_vs_gpt']))
    log(tr('反差 {contrast:.1f} → {contrast2:.1f}（MJ {contrast3:.1f}）；饱和度 {sat:.1f} '
           '→ {sat2:.1f}（MJ {sat3:.1f}）', contrast=g['contrast'], contrast2=r['contrast'], contrast3=rep['MJ']['contrast'], sat=g['sat'], sat2=r['sat'], sat3=rep['MJ']['sat']))
    if layers:
        log(tr('（按远近分层时以上面逐层的结果为准；「主体色差」是整幅暗/中/亮的平均，按层对齐后它可能略高于整幅调色，属正常）'))
    log(tr('已保存：') + out)
    return dict(out=out, compare=base + '_compare.jpg', metrics=rep)


def main():
    ap = argparse.ArgumentParser(description=tr('只还原风格（构图不同时）'))
    ap.add_argument('mj')
    ap.add_argument('gpt')
    ap.add_argument('out')
    ap.add_argument('--scale', type=float, default=None)
    ap.add_argument('--bg-follow', action='store_true')
    ap.add_argument('--strength', type=float, default=1.0)
    ap.add_argument('--keep-black', action='store_true')
    ap.add_argument('--kind', choices=list(KINDS), default='auto', help=tr('图片类型（默认自动判断）'))
    a = ap.parse_args()
    try:
        mj8, g8, g_alpha = read_pair(a.mj, a.gpt)
    except ValueError as e:
        raise SystemExit(str(e))
    o8, wb, extra = style_only(mj8, g8, a.scale, a.strength, keep_black_on=a.keep_black, bg_follow=a.bg_follow,
                               kind=a.kind)
    base = os.path.splitext(a.out)[0]
    imwrite_u(a.out, with_alpha(o8, g_alpha))
    imwrite_u(base + '_bgmask.png', (wb * 255).astype(np.uint8))
    rep = report(mj8, g8, o8, wb, extra['scale'] or 1.0)
    write_json(base + '_metrics.json', rep)
    for k in ('GPT', 'result'):
        r = rep[k]
        print(f"{k:7s} zone dE {r['zone_dE']:.2f} (ab {r['zone_dab']:.2f})  grain {r['grain']:.2f}  glow {r['glow']:.3f}  "
              f"band_err {r['band_err']:.3f}  bg dE {r['bg_dE_vs_gpt']:.3f}  bg grain {r['bg_grain']:.3f}  "
              f"contrast {r['contrast']:.1f}  sat {r['sat']:.1f}")
    print(f"MJ      grain {rep['MJ']['grain']:.2f}  glow {rep['MJ']['glow']:.3f}")


if __name__ == '__main__':
    main()
