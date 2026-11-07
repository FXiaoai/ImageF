# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""
mj_measure.py  从 MJ 原图的像素测量色彩、明暗、颗粒和虚化，自动生成贴在提示词末尾的 MEASURED LOOK 块。
只看图片本身、不读 MJ 提示词，所以 --profile / --raw / --exp 等参数带来的实际效果都会被如实测到。

用法:
  python mj_measure.py MJ原图.png [--copy] [--bias gpt_bias.json] [--precomp 预补偿输入.png] [--outdir 目录] [--name 前缀]

输出:
  控制台             中文测量报告 + 英文 MEASURED LOOK 块
  *_measured.txt     英文 MEASURED LOOK 块
  *_focusmap.jpg     焦点分区图（绿=清晰，黄=柔，红=强虚化，无色=没有细节、无法判断）
  --copy             把英文块复制到剪贴板（Windows）
  --precomp 路径     【实验】按 gpt_bias.json 中各明暗区“方向稳定”的偏色，预先反向补偿后再交给 GPT
"""
from i18n import tr
import argparse
import os

import cv2
import numpy as np

from mj_io import InputError, imread_u, imwrite_u, read_json, write_text
from mj_restore import bar_box

HERE = os.path.dirname(os.path.realpath(__file__))
REF_LONG = 2048.0           # 虚化 sigma 统一换算到长边 2048px
SHARP_T, SOFT_T = 1.5, 3.2  # 归一化 sigma 阈值：<SHARP_T 清晰，<SOFT_T 柔，否则强虚化
S_PRE, S0 = 2.0, 2.0        # 预平滑 2px：实测对颗粒不敏感（加颗粒前后读数变化 ±1%）
R_TABLE = np.array([1.3743, 1.3670, 1.3409, 1.3154, 1.2779, 1.2178, 1.1531, 1.0948, 1.0578, 1.0338, 1.0200])
SIG_TABLE = np.array([0, 0.4, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0, 5.5, 7.5, 10.0])
GRAIN_KEEP_RATIO = 0.85     # 标定里 GPT 颗粒中位数比值低于此值时，提示词加一句“颗粒最容易丢、要保住”
BLUR_KEEP_RATIO = 0.85      # 虚化区模糊比值低于此值时，提示词强调“边缘一样宽、一样软”
ZONES = ('shadows', 'midtones', 'highlights')
CELL = [['top-left', 'top-center', 'top-right'],
        ['middle-left', 'center', 'middle-right'],
        ['bottom-left', 'bottom-center', 'bottom-right']]


# ------------------------------------------------------------------ basics
def gblur(x, s):
    return cv2.GaussianBlur(x, (0, 0), s) if s > 0 else x


def to_lab(img8):
    return cv2.cvtColor(img8.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)


def lab_hex(L, a, b):
    px = np.array([[[L, a, b]]], np.float32)
    bgr = np.clip(cv2.cvtColor(px, cv2.COLOR_LAB2BGR)[0, 0] * 255 + 0.5, 0, 255).astype(int)
    return '#%02X%02X%02X' % (bgr[2], bgr[1], bgr[0])


def box_mask(shape, box):
    """True inside the picture area (y0, y1, x0, x1) = mj_restore.bar_box(): letterbox bars excluded, while dark
    picture content at an edge (night sky, shadow) is kept — the old 'row mean <= 12' rule cut that away."""
    y0, y1, x0, x1 = box
    v = np.zeros(shape[:2], bool)
    v[y0:y1, x0:x1] = True
    return v


# ------------------------------------------------------------------ color names
HUE_BINS = [(0, 25, 'pink'), (25, 50, 'red'), (50, 75, 'orange'), (75, 95, 'amber-gold'),
            (95, 125, 'yellow-olive'), (125, 170, 'green'), (170, 215, 'teal'), (215, 250, 'teal-blue'),
            (250, 280, 'blue'), (280, 305, 'periwinkle'), (305, 335, 'lavender-violet'),
            (335, 360.01, 'magenta-pink')]
HUE_ZH = {'pink': tr('粉'), 'red': tr('红'), 'orange': tr('橙'), 'amber-gold': tr('琥珀金'), 'yellow-olive': tr('黄橄榄'),
          'green': tr('绿'), 'teal': tr('青'), 'teal-blue': tr('青蓝'), 'blue': tr('蓝'), 'periwinkle': tr('长春花蓝紫'),
          'lavender-violet': tr('薰衣草紫'), 'magenta-pink': tr('品红粉')}


def hue_angle(a, b):
    return float(np.degrees(np.arctan2(b, a)) % 360)


def hue_word(a, b):
    h = hue_angle(a, b)
    for lo, hi, n in HUE_BINS:
        if lo <= h < hi:
            return n
    return 'pink'


def neutral_word(L):
    return ('white' if L > 92 else 'light grey' if L > 72 else 'grey' if L > 45
            else 'charcoal' if L > 18 else 'black')


def color_name(L, a, b):
    C = float(np.hypot(a, b))
    if C < 4:
        return neutral_word(L)
    hw = hue_word(a, b)
    if C < 9:
        return f'{hw}-tinted {neutral_word(L)}'
    mods = []
    if L > 80:
        mods.append('pale')
    elif L > 65:
        mods.append('light')
    elif L < 32:
        mods.append('deep')
    elif L < 45:
        mods.append('dark')
    if C < 16:
        mods.append('dusty')
    elif C > 45:
        mods.append('vivid')
    return ' '.join(mods + [hw])


def art(w):
    return 'an' if w[:1].lower() in 'aeiou' else 'a'


# ------------------------------------------------------------------ measurements
def measure_color(img8, valid):
    Lab = to_lab(img8)
    L, A, B = Lab[..., 0][valid], Lab[..., 1][valid], Lab[..., 2][valid]
    C = np.hypot(A, B)
    q15, q85 = np.percentile(L, [15, 85])
    zones = {}
    for nm, m in zip(ZONES, (L <= q15, (L > q15) & (L < q85), L >= q85)):
        zones[nm] = dict(L=float(L[m].mean()), a=float(A[m].mean()), b=float(B[m].mean()), C=float(C[m].mean()))
    p1 = L <= np.percentile(L, 1)
    rgb = img8[valid]
    r = dict(cast_a=float(A.mean()), cast_b=float(B.mean()), sat=float(C.mean()),
             black=float(np.percentile(L, 1)), white=float(np.percentile(L, 99)), key=float(np.median(L)),
             contrast=float(L.std()), clip=float((rgb.min(1) >= 250).mean() * 100),
             darkest=(float(L[p1].mean()), float(A[p1].mean()), float(B[p1].mean())), zones=zones)
    rng = np.random.default_rng(0)
    idx = rng.choice(L.size, min(80000, L.size), replace=False)
    X = np.stack([L[idx], A[idx], B[idx]], 1).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 0.2)
    cv2.setRNGSeed(0)
    _, lab_, cen = cv2.kmeans(X, 6, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    share = np.bincount(lab_.ravel(), minlength=6) / len(X)
    r['palette'] = [(float(share[i]), *map(float, cen[i])) for i in np.argsort(-share) if share[i] >= 0.04]
    return r


def grain_level(img8, valid):
    L = to_lab(img8)[..., 0]
    hp = L - gblur(L, 1.0)
    m = np.abs(gblur(gblur(L, 1) - gblur(L, 3), 4))
    flat = (m < np.percentile(m[valid], 30)) & valid
    return float(np.median(np.abs(hp[flat])) * 1.4826)


def edge_energy(img8, valid):
    L = gblur(to_lab(img8)[..., 0], 1.2)
    g = np.hypot(cv2.Sobel(L, cv2.CV_32F, 1, 0), cv2.Sobel(L, cv2.CV_32F, 0, 1))
    return float(g[valid].mean())


def grad_mag(x):
    return np.hypot(cv2.Sobel(x, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(x, cv2.CV_32F, 0, 1, ksize=3))


def edge_mask(img8, valid):
    """Edge locations (detected on a smoothed copy so blurred edges are found too)."""
    g = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gs = gblur(g, 1.5)
    G = grad_mag(gs)
    noise = np.median(G[valid])
    hi = max(np.percentile(G[valid], 85), 4 * noise)
    E = cv2.Canny(np.clip(gs, 0, 255).astype(np.uint8), 0.5 * hi, hi, L2gradient=True) > 0
    v = cv2.erode(valid.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    return E & v


def blur_sigma_at(img8, E):
    """Defocus estimate per edge pixel (re-blur gradient ratio, Zhuo & Sim 2011). Contrast-invariant.
    Grain inflates edge gradients (makes grainy images look sharper), so the gradient energy that
    grain contributes - measured in flat areas - is subtracted before taking the ratio."""
    g = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY).astype(np.float32)
    I1 = gblur(g, S_PRE)
    I2 = gblur(I1, S0)
    k = np.ones((3, 3), np.uint8)
    G1 = cv2.dilate(grad_mag(I1), k)
    G2 = cv2.dilate(grad_mag(I2), k)
    m = np.abs(gblur(gblur(g, 1) - gblur(g, 3), 4))
    flat = m < np.percentile(m, 30)
    n1, n2 = np.sqrt(np.mean(G1[flat] ** 2)), np.sqrt(np.mean(G2[flat] ** 2))
    g1 = np.sqrt(np.maximum(G1[E] ** 2 - n1 ** 2, 1e-6))
    g2 = np.sqrt(np.maximum(G2[E] ** 2 - n2 ** 2, 1e-6))
    # 经验标定表：合成边缘加已知高斯模糊后实测的 R（S_PRE=2, S0=2），比理论公式在清晰端更准
    return np.interp(g1 / g2, R_TABLE[::-1], SIG_TABLE[::-1])


def focus_analysis(img8, valid, box):
    H, W = img8.shape[:2]
    E = edge_mask(img8, valid)
    sig = blur_sigma_at(img8, E) * (REF_LONG / max(H, W))
    ys, xs = np.nonzero(E)
    T = int(round(max(H, W) / 24))
    gh, gw = int(np.ceil(H / T)), int(np.ceil(W / T))
    tid = (ys // T) * gw + (xs // T)
    tiles = np.full(gh * gw, np.nan, np.float32)
    order = np.argsort(tid)
    tid_s, sig_s = tid[order], sig[order]
    bounds = np.flatnonzero(np.diff(tid_s)) + 1
    for seg_t, seg_s in zip(np.split(tid_s, bounds), np.split(sig_s, bounds)):
        if len(seg_s) >= 25:
            tiles[seg_t[0]] = np.median(seg_s)
    tiles = tiles.reshape(gh, gw)
    y0, y1, x0, x1 = box
    cells = {}
    for r in range(3):
        for c in range(3):
            ya, yb = y0 + (y1 - y0) * r // 3, y0 + (y1 - y0) * (r + 1) // 3
            xa, xb = x0 + (x1 - x0) * c // 3, x0 + (x1 - x0) * (c + 1) // 3
            m = (ys >= ya) & (ys < yb) & (xs >= xa) & (xs < xb)
            cells[(r, c)] = (int(m.sum()), float(np.median(sig[m])) if m.sum() else np.nan)
    have = tiles[~np.isnan(tiles)]
    frac = dict(sharp=float((have < SHARP_T).mean()) if have.size else 0,
                soft=float(((have >= SHARP_T) & (have < SOFT_T)).mean()) if have.size else 0,
                very=float((have >= SOFT_T).mean()) if have.size else 0)
    sharpest = float(np.percentile(have, 10)) if have.size else np.nan
    return dict(E=E, sig=sig, tiles=tiles, T=T, box=box, cells=cells, frac=frac, sharpest=sharpest,
                median=float(np.median(sig)) if sig.size else np.nan)


def cell_class(cnt, med, min_cnt):
    if cnt < min_cnt or np.isnan(med):
        return 'nodata'
    return 'sharp' if med < SHARP_T else 'soft' if med < SOFT_T else 'very'


def focus_map_image(img8, fa):
    H, W = img8.shape[:2]
    T = fa['T']
    over = img8.copy()
    col = {'sharp': (60, 200, 60), 'soft': (0, 200, 255), 'very': (40, 40, 230)}
    for i in range(fa['tiles'].shape[0]):
        for j in range(fa['tiles'].shape[1]):
            v = fa['tiles'][i, j]
            if np.isnan(v):
                continue
            k = 'sharp' if v < SHARP_T else 'soft' if v < SOFT_T else 'very'
            ya, xa = i * T, j * T
            sub = over[ya:min(H, ya + T), xa:min(W, xa + T)]
            sub[:] = (sub * 0.55 + np.array(col[k]) * 0.45).astype(np.uint8)
    y0, y1, x0, x1 = fa['box']
    for r in (1, 2):
        y = y0 + (y1 - y0) * r // 3
        cv2.line(over, (x0, y), (x1, y), (255, 255, 255), 2)
    for c in (1, 2):
        x = x0 + (x1 - x0) * c // 3
        cv2.line(over, (x, y0), (x, y1), (255, 255, 255), 2)
    return over


# ------------------------------------------------------------------ text
def join_list(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ', '.join(xs[:-1]) + ' and ' + xs[-1]


def _bias_global(bias, key):
    return (bias or {}).get('global', {}).get(key, {}).get('mean', 1.0)


def build_block(c, grain, fa, bias):
    out = ['MEASURED LOOK OF @图片1 (measured from its pixels — keep every item exactly as it is):', '']
    # white balance
    ca, cb = c['cast_a'], c['cast_b']
    cc = float(np.hypot(ca, cb))
    if cc < 3:
        out.append('▸ White balance: neutral — whites and greys carry no color cast. Do not warm it up or cool it down.')
    else:
        strength = 'slight' if cc < 6 else 'clear' if cc < 12 else 'strong'
        temp = 'warm ' if cb > 2 else 'cool ' if cb < -2 else ''
        out.append(f'▸ White balance: {art(strength)} {strength} {temp}{hue_word(ca, cb)} cast over the whole frame, '
                   'including whites and greys. It is intentional — do not neutralize it, '
                   'and do not make it warmer or cooler.')
    nm = {k: color_name(v['L'], v['a'], v['b']) for k, v in c['zones'].items()}
    out.append(f'▸ Tonal color: the shadows are {nm["shadows"]}, the midtones {nm["midtones"]}, '
               f'and the highlights {nm["highlights"]}.')
    # tonal range
    dk = color_name(*c['darkest'])
    if c['black'] > 15:
        blk = f'lifted blacks — the darkest areas are {art(dk)} {dk} at about {c["black"]:.0f}% brightness, never pure black'
    elif c['black'] > 7:
        blk = 'dark shadows that are slightly lifted, not crushed to pure black'
    else:
        blk = 'true deep blacks in the darkest areas'
    if c['clip'] > 1.0:
        wht = 'the brightest highlights clip to pure white — keep them clipped'
    elif c['white'] < 92:
        wht = 'highlights are held back — nothing reaches pure white'
    else:
        wht = 'highlights roll off softly and almost nothing clips to pure white'
    key = ('bright, high-key exposure' if c['key'] > 62 else 'dark, low-key exposure' if c['key'] < 38
           else 'mid-key exposure')
    out.append(f'▸ Tonal range: {blk}; {wht}; {key}.')
    s = c['sat']
    sat = ('very muted, almost desaturated' if s < 10 else ('muted, pastel' if c['key'] > 58 else 'muted, low-saturation')
           if s < 20 else 'moderately saturated' if s < 30 else 'rich, saturated')
    out.append(f'▸ Saturation: {sat} colors overall — do not make them richer or greyer.')
    merged = {}
    for sh, L, a, b in c['palette']:
        n = color_name(L, a, b)
        if n in merged:
            merged[n][0] += sh
        else:
            merged[n] = [sh, L, a, b]
    pal = ', '.join(f'{n} {lab_hex(L, a, b)} ({sh * 100:.0f}%)' for n, (sh, L, a, b) in merged.items())
    out.append(f'▸ Main colors (keep their hue, saturation, and brightness): {pal}.')
    # focus
    min_cnt = max(150, int(fa['E'].sum() * 0.01))
    groups = {'sharp': [], 'soft': [], 'very': [], 'nodata': []}
    for (r, cc_), (cnt, med) in fa['cells'].items():
        groups[cell_class(cnt, med, min_cnt)].append(CELL[r][cc_])
    if not groups['soft'] and not groups['very']:
        slight = [CELL[r][cc_] for (r, cc_), (cnt, med) in fa['cells'].items()
                  if cnt >= min_cnt and not np.isnan(med) and med >= 0.9]
        if slight and len(slight) < 9:
            ftxt = (f'▸ Focus: deep focus — most of the frame is equally sharp, but the {join_list(slight)} '
                    f'{"is" if len(slight) == 1 else "are"} slightly softer (haze, glow, or motion). '
                    'Keep that softness exactly; do not sharpen or add detail anywhere.')
        else:
            ftxt = '▸ Focus: deep focus — the whole frame is at the same level of sharpness. Do not sharpen anything.'
    else:
        parts = []
        if groups['sharp']:
            parts.append(f'in sharp focus: {join_list(groups["sharp"])}')
        if groups['soft']:
            parts.append(f'soft: {join_list(groups["soft"])}')
        if groups['very']:
            parts.append(f'strongly out of focus: {join_list(groups["very"])}')
        ftxt = ('▸ Focus (shallow depth of field) — ' + '; '.join(parts) +
                f'. Only about {fa["frac"]["sharp"] * 100:.0f}% of the detailed areas are sharp. '
                'Every soft or blurred area must stay exactly as blurred')
        ftxt += ((', with edges as wide and soft as in the original'
                  if _bias_global(bias, 'blur_ratio_soft') < BLUR_KEEP_RATIO else '')
                 + ' — no crisp edges, no added detail.')
        if fa['sharpest'] > 0.9:
            ftxt += ' Even the in-focus areas have a soft, filmic edge, not digital crispness.'
    if groups['nodata']:
        ftxt += (f' The {join_list(groups["nodata"])} area has little fine detail — keep it as smooth as it is.'
                 if len(groups['nodata']) == 1 else
                 f' The {join_list(groups["nodata"])} areas have little fine detail — keep them as smooth as they are.')
    out.append(ftxt)
    # grain
    keep = (' This grain is the first thing that gets lost — keep it.'
            if _bias_global(bias, 'grain_ratio') < GRAIN_KEEP_RATIO else '')
    if grain < 0.2:
        out.append('▸ Texture: clean, with almost no visible grain. Do not add grain or noise.')
    elif grain < 0.4:
        out.append('▸ Texture: subtle fine grain across the frame, including flat and blurred areas — '
                   'do not denoise or smooth it.' + keep)
    elif grain < 0.8:
        out.append('▸ Texture: visible fine film grain everywhere, including flat and blurred areas — '
                   'do not denoise or smooth it.' + keep)
    else:
        out.append('▸ Texture: strong, coarse film grain everywhere — do not denoise or smooth it.' + keep)
    # drift guards from calibration
    guards = drift_guards(c, bias)
    if guards:
        out.append('▸ Color drift to avoid: ' + '; '.join(guards) + '.')
    return '\n'.join(out)


def axis_words(da, db):
    w = []
    if da > 0.5:
        w.append('magenta')
    elif da < -0.5:
        w.append('green')
    if db > 0.5:
        w.append('yellow')
    elif db < -0.5:
        w.append('blue')
    return '-'.join(w)


def _zone_bias(bias, zn, key, neutral):
    v = bias['zones'][zn][key]
    return v['mean'] if v['consistent'] else neutral


def drift_guards(c, bias):
    """Only drifts that went the same way in (almost) every calibration pair are used."""
    if not bias:
        return []
    g = []
    for zn in ZONES:
        da, db = _zone_bias(bias, zn, 'da', 0.0), _zone_bias(bias, zn, 'db', 0.0)
        cr = _zone_bias(bias, zn, 'chroma_ratio', 1.0)
        zz = c['zones'][zn]
        parts = []
        if np.hypot(da, db) >= 1.0:
            parts.append(f'do not let them shift toward {axis_words(da, db)}')
        if cr < 0.92:
            parts.append('do not let them turn greyer')
        elif cr > 1.08:
            parts.append('do not make them more saturated')
        if parts:
            g.append(f'keep the {zn} {color_name(zz["L"], zz["a"], zz["b"])} — ' + ' and '.join(parts))
    return g


def precompensate(img8, c, bias, valid):
    Lab = to_lab(img8)
    centers = [c['zones'][z]['L'] for z in ZONES]
    da = [_zone_bias(bias, z, 'da', 0.0) for z in ZONES]
    db = [_zone_bias(bias, z, 'db', 0.0) for z in ZONES]
    L = Lab[..., 0]
    m = valid & (L > 3)
    Lab[..., 1][m] -= np.interp(L[m], centers, da)
    Lab[..., 2][m] -= np.interp(L[m], centers, db)
    out = cv2.cvtColor(Lab, cv2.COLOR_LAB2BGR)
    return np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8), da, db


# ------------------------------------------------------------------ report + entry points
def zh_report(c, grain, fa, log=print):
    z = c['zones']
    log(tr('== 测量报告（Lab：L 亮度 0–100；a +品红/−绿；b +黄/−蓝）'))
    log(tr('  整体偏色      a {cast_a:+.1f}  b {cast_b:+.1f}  → {v}，强度 {v2:.1f}', cast_a=c["cast_a"], cast_b=c["cast_b"], v=HUE_ZH[hue_word(c["cast_a"], c["cast_b"])], v2=np.hypot(c["cast_a"], c["cast_b"])))
    for k, zh in zip(ZONES, (tr('暗部'), tr('中间调'), tr('高光'))):
        v = z[k]
        log(tr('  {zh:6s}      L {L:5.1f}  a {a:+6.1f}  b {b:+6.1f}  饱和 {C:5.1f}  → {v}', zh=zh, L=v["L"], a=v["a"], b=v["b"], C=v["C"], v=color_name(v["L"], v["a"], v["b"])))
    log(tr('  黑位 L {black:.1f}  白位 L {white:.1f}  中位 {key:.1f}  反差 {contrast:.1f} '
           ' 过曝 {clip:.2f}%  平均饱和 {sat:.1f}', black=c["black"], white=c["white"], key=c["key"], contrast=c["contrast"], clip=c["clip"], sat=c["sat"]))
    log(tr('  颗粒（平坦区）{grain:.3f}', grain=grain))
    log(tr('  虚化 sigma（长边 2048 等效）：全图中位 {median:.2f}px，最清晰 10% {sharpest:.2f}px；清晰/柔/强虚化 '
           '= {v:.0f}% / {v2:.0f}% / {v3:.0f}%', median=fa["median"], sharpest=fa["sharpest"], v=fa["frac"]["sharp"] * 100, v2=fa["frac"]["soft"] * 100, v3=fa["frac"]["very"] * 100))
    log(tr('  九宫格（边缘数, sigma）：'))
    for r in range(3):
        log('    ' + '   '.join(f'{CELL[r][cc]:13s}{fa["cells"][(r, cc)][0]:6d} {fa["cells"][(r, cc)][1]:5.2f}'
                                for cc in range(3)))


def load_bias(path, log=print):
    """gpt_bias.json as a dict, or None (missing / damaged -> no drift guards, with a notice)."""
    if not path or not os.path.exists(path):
        return None
    bias = read_json(path, None, warn=log)
    if not (isinstance(bias, dict) and 'zones' in bias and 'global' in bias):
        log(tr('[提醒] gpt_bias.json 不完整，本次没有防漂移语句；到「③ 标定」页点「重新计算」可以重建。'))
        return None
    return bias


def measure_file(mj_path, outdir, name=None, bias=None, precomp=None, log=print):
    """Measure one MJ image. Writes <name>_measured.txt and <name>_focusmap.jpg (+ the pre-compensated
    upload image when `precomp` is a path). `bias` = gpt_bias dict or None. Returns dict(block, measured,
    focus, precomp). Raises InputError when the image cannot be read or precompensation has no bias."""
    img8 = imread_u(mj_path)
    if img8 is None:
        raise InputError(tr('读不到图片：') + mj_path)
    if precomp and not bias:
        raise InputError(tr('预补偿需要标定数据（gpt_bias.json），请先到「③ 标定」页点「重新计算」。'))
    box = bar_box(img8)
    valid = box_mask(img8.shape, box)
    c = measure_color(img8, valid)
    grain = grain_level(img8, valid)
    fa = focus_analysis(img8, valid, box)
    zh_report(c, grain, fa, log)
    block = build_block(c, grain, fa, bias)
    base = os.path.join(outdir, name or os.path.splitext(os.path.basename(mj_path))[0][:40])
    measured, focus = base + '_measured.txt', base + '_focusmap.jpg'
    write_text(measured, block)
    imwrite_u(focus, focus_map_image(img8, fa), [cv2.IMWRITE_JPEG_QUALITY, 88])
    log(tr('\n== 英文 MEASURED LOOK 块（贴在提示词末尾）\n') + block)
    log(tr('\n[已保存] {measured}  |  {focus}', measured=measured, focus=focus) + ('' if bias else tr('  （没有标定数据，没有防漂移语句）')))
    if precomp:
        pc, da, db = precompensate(img8, c, bias, valid)
        imwrite_u(precomp, pc)
        log(tr('[实验] 预补偿输入已保存：{precomp}  （暗/中/亮 反向补偿 a {v}  b {v2}）——后期还原时参考图仍然用 MJ 原图，不要用这张。', precomp=precomp, v=[-round(x, 2) for x in da], v2=[-round(x, 2) for x in db]))
    return dict(block=block, measured=measured, focus=focus, precomp=precomp)


def main():
    ap = argparse.ArgumentParser(description=tr('测量 MJ 原图，生成 MEASURED LOOK 块'))
    ap.add_argument('mj')
    ap.add_argument('--bias', default=os.path.join(HERE, 'gpt_bias.json'))
    ap.add_argument('--precomp')
    ap.add_argument('--copy', action='store_true')
    ap.add_argument('--outdir', default=os.path.join(HERE, 'out'))
    ap.add_argument('--name', help=tr('输出文件名前缀（默认取原图文件名）'))
    a = ap.parse_args()
    try:
        r = measure_file(a.mj, a.outdir, a.name, load_bias(a.bias), a.precomp)
    except ValueError as e:
        raise SystemExit(str(e))
    if a.copy:
        import clipboard_win
        clipboard_win.set_text(r['block'])
        print(tr('[已复制到剪贴板]'))


if __name__ == '__main__':
    main()
