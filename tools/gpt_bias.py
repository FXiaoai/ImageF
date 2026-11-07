# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""
gpt_bias.py  用若干组「MJ 原图 + GPT 输出」标定 GPT 的稳定偏差（偏色、颗粒、清晰度、虚化），写入 gpt_bias.json

用法:
  python gpt_bias.py MJ1 GPT1 [MJ2 GPT2 ...] [--out gpt_bias.json]
  python gpt_bias.py --stats 每组统计.json [MJ GPT ...] [--out gpt_bias.json]
      （纯数值标定：已测好的每组统计直接参与汇总，不需要原图）

说明:
  组数越多越准。只有 ≥80% 的组方向一致、幅度够大、而且 90% 置信区间不含“没有偏差”的项（consistent=true），
  才会被 mj_measure.py 用来写防漂移语句和做预补偿；方向不一致的（比如饱和度一组变艳、一组变灰），
  说明那是 GPT 在“往自己的审美靠”，不是固定偏差，不能用一个固定值去抵消。
"""
from i18n import tr
import argparse
import hashlib
import json
import os

import cv2
import numpy as np

from mj_io import InputError, imread_u, read_json, write_json
from mj_measure import ZONES, REF_LONG, SHARP_T, to_lab, grain_level, edge_energy, edge_mask, blur_sigma_at
from mj_restore import estimate_warp, bar_box, detect_changes, to_f, warp_affine

HERE = os.path.dirname(os.path.realpath(__file__))
STATS_VERSION = 2      # 每组统计的测量方法版本；方法改了就加 1，旧版本的组会自动从图片重测（2 = 抗锯齿缩图 + 半像素对齐）
METHOD = ('v4.3.1: ORB+ECC alignment (pixel-centre exact), GPT reduced with area averaging, GPT-redrawn regions '
          'excluded, median/MAD, consistent = >=80% same sign & 90% bootstrap CI excludes 0')


def read(p):
    im = imread_u(p)
    if im is None:
        raise InputError(tr('读不到图片：') + p)
    return im


def one_pair(mj_p, gpt_p, F=None):
    """Per-pair drift statistics. `F` = GPT->MJ alignment from an earlier restore (saves aligning again)."""
    mj8, g8 = read(mj_p), read(gpt_p)
    Hm, Wm = mj8.shape[:2]
    if F is None:
        F, _ = estimate_warp(mj8, g8)
    # GPT onto the MJ grid. GPT is usually ~1.9x larger: it must be reduced with area averaging, otherwise its grain
    # is aliased instead of averaged and reads 24-37 % too high (cv2.warpAffine has no real INTER_AREA).
    shrink = np.linalg.det(F[:, :2]) < 1
    g8a = warp_affine(g8, F, (Wm, Hm), cv2.INTER_LINEAR if shrink else cv2.INTER_CUBIC)
    foot = cv2.warpAffine(np.full(g8.shape[:2], 255, np.uint8), F, (Wm, Hm), flags=cv2.INTER_NEAREST) > 127
    y0, y1, x0, x1 = bar_box(mj8)
    valid = np.zeros((Hm, Wm), bool)
    valid[y0:y1, x0:x1] = True
    valid &= cv2.erode(foot.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    # exclude regions GPT actually redrew (fixes), so only the "look" drift is measured
    ch = detect_changes(to_f(mj8), to_f(g8a), valid, 3.5)
    valid &= ~cv2.dilate(ch.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    Lm, Lg = to_lab(mj8), to_lab(g8a)
    d = Lg - Lm
    L = Lm[..., 0][valid]
    Cm = np.hypot(Lm[..., 1], Lm[..., 2])[valid]
    Cg = np.hypot(Lg[..., 1], Lg[..., 2])[valid]
    q15, q85 = np.percentile(L, [15, 85])
    r = {'mj': os.path.basename(mj_p), 'gpt': os.path.basename(gpt_p), 'version': STATS_VERSION,  # 只存文件名
         'zones': {}}
    for zn, m in zip(ZONES, (L <= q15, (L > q15) & (L < q85), L >= q85)):
        r['zones'][zn] = dict(dL=float(np.median(d[..., 0][valid][m])), da=float(np.median(d[..., 1][valid][m])),
                              db=float(np.median(d[..., 2][valid][m])),
                              chroma_ratio=float(Cg[m].mean() / max(Cm[m].mean(), 1e-6)))
    r['da'] = float(np.median(d[..., 1][valid]))
    r['db'] = float(np.median(d[..., 2][valid]))
    r['grain_ratio'] = grain_level(g8a, valid) / max(grain_level(mj8, valid), 1e-6)
    r['edge_ratio'] = edge_energy(g8a, valid) / max(edge_energy(mj8, valid), 1e-6)
    E = edge_mask(mj8, valid)
    k = REF_LONG / max(mj8.shape[:2])
    sm, sg = blur_sigma_at(mj8, E) * k, blur_sigma_at(g8a, E) * k
    soft = sm >= SHARP_T
    r['blur_sigma_soft_mj'] = float(np.median(sm[soft])) if soft.any() else float('nan')
    r['blur_sigma_soft_gpt'] = float(np.median(sg[soft])) if soft.any() else float('nan')
    r['blur_ratio_soft'] = r['blur_sigma_soft_gpt'] / r['blur_sigma_soft_mj'] if soft.any() else 1.0
    r['blur_sigma_sharp_mj'] = float(np.median(sm[~soft])) if (~soft).any() else float('nan')
    r['blur_sigma_sharp_gpt'] = float(np.median(sg[~soft])) if (~soft).any() else float('nan')
    r['soft_edge_share'] = float(soft.mean())
    return r


def agg(vals, kind):
    """Robust summary. `mean` keeps its old name for compatibility but holds the median.
    consistent = >=80 % of pairs on the same side AND the median is big enough to matter AND the
    90 % bootstrap interval of the median excludes 'no drift'."""
    v = np.array(vals, float)
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)) * 1.4826)
    ref = 0.0 if kind == 'offset' else 1.0
    tol = 0.5 if kind == 'offset' else 0.08
    same = float(max((v > ref).mean(), (v < ref).mean()))
    rng = np.random.default_rng(0)
    boots = np.median(rng.choice(v, (2000, len(v))), 1)
    lo, hi = np.percentile(boots, [5, 95])
    outl = [i + 1 for i, x in enumerate(v) if abs(x - med) > 3 * max(mad, tol / 2)]
    cons = bool(same >= 0.8 and abs(med - ref) >= tol and not (lo <= ref <= hi))
    conf = 'high' if cons and abs(med - ref) > 2 * mad else ('medium' if cons else 'low')
    return dict(mean=med, median=med, mad=mad, ci90=[float(lo), float(hi)], same_sign=same,
                values=[round(float(x), 3) for x in v], outliers=outl, consistent=cons, confidence=conf)


def loo_precomp_gain(pairs, zn, k):
    """Leave-one-out: if we had subtracted the median bias of the OTHER pairs, how much of this pair's
    drift would be removed?  >0 = precompensation helps on average."""
    v = np.array([p['zones'][zn][k] for p in pairs], float)
    if len(v) < 3:
        return float('nan')
    gains = []
    for i in range(len(v)):
        pred = np.median(np.delete(v, i))
        gains.append(abs(v[i]) - abs(v[i] - pred))
    return float(np.mean(gains))


def stats_signature(pairs):
    """Fingerprint of the per-pair statistics a gpt_bias.json was computed from (to detect stale files)."""
    return hashlib.md5(json.dumps(pairs, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def summarize(pairs):
    res = {'n_pairs': len(pairs), 'pairs': pairs, 'zones': {}, 'global': {}}
    for zn in ZONES:
        res['zones'][zn] = {k: agg([p['zones'][zn][k] for p in pairs], 'ratio' if k == 'chroma_ratio' else 'offset')
                            for k in ('dL', 'da', 'db', 'chroma_ratio')}
    for k in ('da', 'db'):
        res['global'][k] = agg([p[k] for p in pairs], 'offset')
    for k in ('grain_ratio', 'edge_ratio', 'blur_ratio_soft'):
        res['global'][k] = agg([p[k] for p in pairs], 'ratio')
    res['loo_precomp_gain'] = {zn: {k: loo_precomp_gain(pairs, zn, k) for k in ('dL', 'da', 'db')} for zn in ZONES}
    res['method'] = METHOD
    res['inputs_md5'] = stats_signature(pairs)
    return res


def print_report(res, log=print):
    pairs = res['pairs']
    log(tr('== GPT 偏差标定（{n} 组）  ✓ = ≥80% 组方向一致且幅度足够（数值为中位数）', n=len(pairs)))
    log(f"{'':12s}" + ''.join(f'{tr("组") + str(i + 1):>22s}' for i in range(len(pairs))) + f'{tr("中位"):>10s}')

    def row(label, s):
        log(f'{label:12s}' + ''.join(f'{x:22.2f}' for x in s['values']) +
            tr('{mean:10.2f} {v} 一致{v2:.0f}% 离群{outliers}', mean=s["mean"], v="✓" if s["consistent"] else " ", v2=s["same_sign"] * 100, outliers=s["outliers"]))

    for zn, zh in zip(ZONES, (tr('暗部'), tr('中间调'), tr('高光'))):
        for k, lab in (('dL', tr('亮度')), ('da', tr('a 品红+')), ('db', tr('b 黄+')), ('chroma_ratio', tr('饱和度×'))):
            row(zh + ' ' + lab, res['zones'][zn][k])
    for k, lab in (('grain_ratio', tr('颗粒×')), ('edge_ratio', tr('边缘能量×')), ('blur_ratio_soft', tr('虚化区模糊×'))):
        row(lab, res['global'][k])
    log(tr('留一法：用其余组的中位偏差做预补偿，平均能消掉的偏移量（ΔLab，>0 才有用）'))
    for zn, zh in zip(ZONES, (tr('暗部'), tr('中间调'), tr('高光'))):
        g = res['loo_precomp_gain'][zn]
        log(f'  {zh}: L {g["dL"]:+.2f}  a {g["da"]:+.2f}  b {g["db"]:+.2f}')
    for i, p in enumerate(pairs):
        log(tr('  组{v} 虚化区 sigma（长边 2048 等效）MJ {blur_sigma_soft_mj:.2f}px → GPT {blur_sigma_soft_gpt:.2f}p'
               'x；清晰区 MJ {blur_sigma_sharp_mj:.2f}px → GPT {blur_sigma_sharp_gpt:.2f}px；'
               '虚化边缘占比 {v2:.0f}%', v=i + 1, blur_sigma_soft_mj=p["blur_sigma_soft_mj"], blur_sigma_soft_gpt=p["blur_sigma_soft_gpt"], blur_sigma_sharp_mj=p["blur_sigma_sharp_mj"], blur_sigma_sharp_gpt=p["blur_sigma_sharp_gpt"], v2=p["soft_edge_share"] * 100))


def _md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def rebuild_base(base_path, calib_dir, log=print):
    """维护用：测量方法改了以后，用 calib 里的图片重测内置基础数据（calib_base.json）的每组统计。
    图片不在或 md5 对不上的组保留旧数值。返回汇总所需的统计列表。"""
    base = read_json(base_path, [])
    files = os.listdir(calib_dir) if os.path.isdir(calib_dir) else []
    for b in base:
        def find(kind):
            hit = [f for f in files if os.path.splitext(f)[0] == f'pair_{b["id"]:02d}_{kind}']
            return os.path.join(calib_dir, hit[0]) if hit else None
        a, g = find('input'), find('gpt')
        if not (a and g) or _md5(g) != b.get('gpt_md5'):
            log(tr('  第 {id} 组：图片不在或对不上，保留旧数值', id=b["id"]))
            continue
        b['stats'] = one_pair(a, g)
        log(tr('  第 {id} 组：已重测（颗粒比 {grain_ratio:.3f}）', id=b["id"], grain_ratio=b["stats"]["grain_ratio"]))
    write_json(base_path, base)
    return [b['stats'] for b in base]


def main():
    ap = argparse.ArgumentParser(description=tr('标定 GPT 的稳定偏差'))
    ap.add_argument('images', nargs='*')
    ap.add_argument('--stats', help='json list of per-pair stats (one_pair() output) measured earlier')
    ap.add_argument('--rebuild-base', action='store_true',
                    help=tr('维护用：用 calib 里的图片重测 calib_base.json，再汇总写 --out'))
    ap.add_argument('--out', default=os.path.join(HERE, 'gpt_bias.json'))
    a = ap.parse_args()
    if a.rebuild_base:
        pairs = rebuild_base(os.path.join(HERE, 'calib_base.json'), os.path.join(HERE, 'calib'))
        res = summarize(pairs)
        write_json(a.out, res)
        print_report(res)
        print(tr('[已保存] calib_base.json 和 {out}', out=a.out))
        return
    if len(a.images) % 2:
        raise SystemExit(tr('图片要成对给：MJ1 GPT1 MJ2 GPT2 ...'))
    pairs = read_json(a.stats, [], warn=print) if a.stats else []
    try:
        pairs += [one_pair(a.images[i], a.images[i + 1]) for i in range(0, len(a.images), 2)]
    except ValueError as e:
        raise SystemExit(str(e))
    if not pairs:
        raise SystemExit(tr('没有标定数据。'))
    res = summarize(pairs)
    write_json(a.out, res)
    print_report(res)
    print(tr('[已保存] {out}', out=a.out))


if __name__ == '__main__':
    main()
