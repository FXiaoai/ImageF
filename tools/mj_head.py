# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""换头（①页「修错 + 换头」→ ②页「这是修错 + 换头的结果」）：主角的头按“同类对同类”还原颜色。

GPT 换头后，新头的位置、脸型、发型和 MJ 的旧头都不一样，按位置逐像素对照会把 MJ 旧头的颜色、轮廓
“印”到新头和旁边的背景上（发际边上一圈暗影、脸颊边被压暗）。所以头部单独处理：
  1) 两张图各自找主角：人脸模型（YuNet）定位脸，脸颊取肤色样本、额头上方取发色样本，
     GrabCut 把人物（头发 + 脸）从背景里分出来，再按样本颜色分成「头发」「皮肤」；
  2) GPT 的头发按 MJ 头发的明暗分布和颜色还原，皮肤按 MJ 皮肤（嘴唇另外按 MJ 嘴唇，见 mj_face）；
  3) 头部范围（GPT 新头 ∪ MJ 旧头）不参加按位置的统计，旁边的背景按周围背景推算，不会印出旧头的影子。
长相（五官、脸型、发型轮廓）完全来自 GPT，颜色、明暗来自 MJ 的同类区域。只依赖 numpy / cv2。"""
from i18n import tr
import cv2
import numpy as np

import mj_face
from mj_region import _transform, guided, region_stats, to_bgr, to_lab

WORK = 640                       # 分割时把长边缩到这个尺寸
CAP = dict(hair=(25.0, 18.0), skin=(15.0, 10.0))   # (L 平移上限, a/b 平移上限)：换头时按 MJ 完整还原，只防极端
TONE_K, COL_K = 1.0, 1.0
# 新头和旧头的头发（或皮肤）颜色差得太多 = 角色本来就是这个发色 / 肤色（提示词要求发色取 @图片2），不能硬改成 MJ 的：
# 差别 ≤ SAME_LO 时完整按 MJ 同类区域还原（差别主要是调色：偏暖 / 偏冷、明暗），≥ SAME_HI 时只按整幅调色，中间渐变。
# 差别 = sqrt(ΔL² + Δa² + Δb²)（各自平均色）。实测那组白发换头：头发 15.5、皮肤 12.9、嘴唇 14.6；黑发对白发约 60。
SAME_LO, SAME_HI = 20.0, 35.0
LOCAL_SIG = 0.35                 # 同类区域里的明暗 / 冷暖分布（受光面、背光面）：按脸宽的这个比例平滑后对照
LOCAL_K = 0.8                    # 分布差别用多少
LOCAL_CAP = (8.0, 6.0)           # 分布差别上限（L, a/b）
POSE_TOL = 0.08                  # 两张脸的五个关键点按相似变换对齐后的误差（脸宽的比例）超过它 = 角度 / 表情不同，不套用受光分布
LIPS_CAP = (15.0, 15.0)          # 嘴唇也按 MJ 完整还原（④页角色为主时是 (6, 12)，那里不动）
CLASS_MAX = 20.0                 # 像素与头发 / 皮肤样本的颜色距离超过它 = 其他（眼睛、首饰、衣服）
MIN_SEED = 40                    # 样本像素至少这么多（工作尺寸）
TEX_SMOOTH = 0.55                # 工作尺寸下的细纹理能量低于它 = 光滑（皮肤），发丝一般 1 以上
HAIR_DOWN_WHOLE = 7.0            # 换整个角色：长发最多垂到脸框顶下 7 个脸高
SKIN_BODY_MAX = 12.0             # 换整个角色：身上的皮肤（手臂、肩、腿）要和脸颊样本的颜色（明暗也算）够近才算
HAIR_MAX_WHOLE = 16.0            # 换整个角色：头发和发色样本的颜色距离（明暗也算）上限
WL_WHOLE = 0.6                   # 换整个角色时颜色距离里明暗的权重
WL = 0.3                         # 颜色距离里明暗的权重：头发从发根到发梢明暗差得多，主要按色相 / 彩度区分
# ---- V4.6.2：脸上不再按颜色分“头发 / 皮肤”。米白、浅金的新头发和背光的皮肤颜色很近，以前背光侧脸、下巴阴影、眼睛周围
# 会被认成头发，按 MJ 白发上色 → 暗面发白、眼睛发白，和旁边按皮肤上色的部分之间出现明暗交界线（白发 / 红格子两组实测）。
# 现在：按人脸关键点画出“脸”（眉毛往下到下巴的椭圆），里面一律算脸（五官也在内），只有脸外面才按颜色分头发 / 皮肤。
FACE_CORE = (0.42, 0.50, 0.55)   # 脸芯椭圆（半宽、半高、中心距框顶，单位：脸框宽 / 高）：一律算脸，肤色也只在这里统计
FACE_OUTER = (0.62, 0.66, 0.58)  # 脸边椭圆：脸芯外面这一圈，平滑（没有发丝纹理）、连着脸芯、颜色不离谱的也算脸
FACE_NECK = (0.38, 0.32, 1.20)   # 下巴正下方的脖子也按同样的办法判断（平滑的是皮肤，不是头发）
BROW_UP = 0.30                   # 脸的上沿 = 两眼连线往上 0.30 个眼距（眉毛下沿附近；再往上是刘海 / 额头，仍按颜色分）
TEX_FACE_W = 220                 # 量纹理时把脸缩到这么宽（像素；原图脸更小就不放大）
TEX_RATIO_MIN = 2.2              # 发丝纹理至少是皮肤的这么多倍才用纹理分脸边（MJ 原图常常很柔，分不开时脸边沿用颜色）
SPLIT_SIG = 0.05                 # 头发 / 皮肤之间的过渡宽度（脸框宽的比例，高斯 sigma）：两类上色不同，过渡太窄会出硬线
# 皮肤（脸 + 身上露出的皮肤）只迁移“调色”：整体明暗、轻微反差、冷暖，不照搬 MJ 那张脸的明暗分布
# （MJ 的眼妆、背光、下巴阴影会被搬到新脸上，暗处压得发黑 —— 11-06 那组实测）。脸上原有的明暗起伏、妆容、五官阴影都保留。
SKIN_L_CAP = 12.0                # 皮肤整体明暗最多改这么多（L）；实际改多少再乘「脸部明暗跟随 MJ」的百分比
SKIN_AB_CAP = 6.0                # 皮肤冷暖最多改这么多（a / b）
SKIN_K = (0.93, 1.07)            # 皮肤反差最多改到 0.93～1.07 倍（瞳孔、睫毛不被压死）


def _ellipse(shape, c, ax, val=1):
    m = np.zeros(shape[:2], np.uint8)
    cv2.ellipse(m, (int(round(c[0])), int(round(c[1]))), (max(1, int(ax[0])), max(1, int(ax[1]))), 0, 0, 360, val, -1)
    return m > 0


def _centers(x, k):
    x = np.ascontiguousarray(x, np.float32)
    k = int(min(k, max(1, len(x) // 20)))
    if k <= 1:
        return x.mean(0, keepdims=True)
    cv2.setRNGSeed(0)
    _, _, c = cv2.kmeans(x, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5), 2,
                         cv2.KMEANS_PP_CENTERS)
    return c


def _dist(lab, centers, wL):
    w = np.array([wL, 1.0, 1.0], np.float32)
    return np.min([np.sqrt((((lab - c) * w) ** 2).sum(-1)) for c in centers], axis=0)


def _keep_big(m, area):
    n, lbl, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= area
    return keep[lbl]


def _trim(x, wL=0.5, q=80):
    """Drop the samples farthest from the median (hair strands over a cheek, background between hair strands)."""
    d = np.sqrt((((x - np.median(x, 0)) * [wL, 1, 1]) ** 2).sum(-1))
    return x[d <= np.percentile(d, q)]


def _face_zone(shape, x, y, fw, fh, pts):
    """(core, outer, clean) on a grid where the face box is (x, y, fw, fh) and the landmarks pts.
    core = 眉毛往下的脸芯椭圆（五官都在里面），一律算脸；outer = 外面一圈的上限；
    clean = core 去掉眼睛（含眼妆）、嘴、鼻孔、下巴以下，只留干净皮肤，用来统计肤色。"""
    h, w = shape[:2]
    eye_y = pts[:2, 1].mean()
    e = float(np.hypot(*(pts[1] - pts[0])))
    top = int(max(0, eye_y - BROW_UP * e))
    zones = []
    for ax, ay, cy in (FACE_CORE, FACE_OUTER):
        z = _ellipse((h, w), (x + fw / 2, y + cy * fh), (ax * fw, ay * fh))
        z[:top] = False
        zones.append(z)
    core, outer = zones
    neck = _ellipse((h, w), (x + fw / 2, y + FACE_NECK[2] * fh), (FACE_NECK[0] * fw, FACE_NECK[1] * fh))
    outer |= neck
    feat = np.zeros((h, w), bool)
    for p in pts[:2]:
        feat |= _ellipse((h, w), p, (0.20 * fw, 0.13 * fh))
    m = (pts[3] + pts[4]) / 2
    feat |= _ellipse((h, w), m, (0.26 * fw, 0.12 * fh))
    feat |= _ellipse((h, w), (pts[2][0], pts[2][1] + 0.03 * fh), (0.13 * fw, 0.07 * fh))
    clean = core & ~feat
    clean[int(y + 0.98 * fh):] = False
    return core, outer, clean, neck


def _smooth_map(img8, face, s, shape, smp):
    """脸边一圈哪里是平滑的皮肤（没有发丝纹理）：在原图上把脸附近裁出来、缩到脸宽 TEX_FACE_W 量细节能量，
    阈值取脸芯皮肤和发色样本处纹理的几何平均；结果画到工作尺寸上。图太柔（发丝纹理不到皮肤的 TEX_RATIO_MIN 倍）
    或没有头发样本时返回 (None, 原因)。"""
    if not smp['have_hair']:
        return None, tr('没有头发样本')
    H, W = img8.shape[:2]
    x, y, w, h = [float(v) for v in face['box']]
    ax, ay, cyf = FACE_OUTER
    x0, x1 = int(max(0, x + w / 2 - (ax + 0.1) * w)), int(min(W, x + w / 2 + (ax + 0.1) * w))
    y0, y1 = int(max(0, y - 0.45 * h)), int(min(H, y + (FACE_NECK[2] + FACE_NECK[1] + 0.1) * h))
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None, tr('脸太小')
    k = min(1.0, TEX_FACE_W / max(w, 1))
    crop = cv2.resize(img8[y0:y1, x0:x1], None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img8[y0:y1, x0:x1]
    lab = to_lab(crop.astype(np.float32) / 255)
    L = lab[..., 0]
    fwc = w * k
    s1, s3 = max(0.7, fwc / TEX_FACE_W), 3.0 * fwc / TEX_FACE_W
    tex = cv2.GaussianBlur(np.abs(L - cv2.GaussianBlur(L, (0, 0), s1)), (0, 0), s3)
    pts = (np.asarray(face['pts'], np.float64) - [x0, y0]) * k
    core, _, clean, _ = _face_zone(L.shape, (x - x0) * k, (y - y0) * k, w * k, h * k, pts)
    hs = cv2.resize(smp['hair_seed'].astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    hs = cv2.resize(hs[y0:y1, x0:x1], (L.shape[1], L.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    hs &= _dist(lab, smp['hc'], WL) < 8
    if clean.sum() < 50 or hs.sum() < 50:
        return None, tr('样本太少')
    t_skin, t_hair = float(np.median(tex[clean])), float(np.median(tex[hs]))
    ratio = t_hair / max(t_skin, 1e-4)
    if ratio < TEX_RATIO_MIN:
        return None, tr('图偏柔，发丝和皮肤的纹理只差 {ratio:.1f} 倍', ratio=ratio)
    smooth = (tex < np.sqrt(t_skin * t_hair)).astype(np.uint8)
    hw, ww = shape[:2]
    out = np.zeros((hw, ww), bool)
    a0, a1, b0, b1 = int(round(y0 * s)), int(round(y1 * s)), int(round(x0 * s)), int(round(x1 * s))
    a1, b1 = min(hw, max(a1, a0 + 1)), min(ww, max(b1, b0 + 1))
    out[a0:a1, b0:b1] = cv2.resize(smooth, (b1 - b0, a1 - a0), interpolation=cv2.INTER_AREA) > 0
    return out, tr('纹理分脸边（发丝纹理是皮肤的 {ratio:.1f} 倍）', ratio=ratio)


def _samples(lab, x, y, fw, fh, pts, roi):
    """Colour samples on the working-size Lab image: skin on both cheeks + nose bridge, hair above the forehead and in
    the bangs (minus skin-like and far-background-like pixels), and colour centres of the background outside roi."""
    h, w = lab.shape[:2]
    eye_y, mouth_y = pts[:2, 1].mean(), pts[3:, 1].mean()
    skin_seed = np.zeros((h, w), bool)
    for e, m in ((pts[0], pts[3]), (pts[1], pts[4])):
        c = (e[0] * 0.75 + m[0] * 0.25, e[1] + 0.45 * (m[1] - e[1]))
        skin_seed |= _ellipse((h, w), c, (0.08 * fw, 0.06 * fh))
    skin_seed |= _ellipse((h, w), (pts[2][0], (eye_y + pts[2][1]) / 2), (0.05 * fw, 0.05 * fh))   # 鼻梁
    sk = _trim(lab[skin_seed], WL)
    hair_seed = np.zeros((h, w), bool)
    y0, y1 = int(max(0, y - 0.25 * fh)), int(max(0, y + 0.03 * fh))   # YuNet 的框顶在额头：框顶上方一小段是头顶 / 刘海
    hair_seed[y0:y1, int(max(0, x + 0.2 * fw)):int(min(w, x + 0.8 * fw))] = True
    ex0, ex1 = sorted((pts[0][0], pts[1][0]))                 # 刘海：框顶到眉毛上方（露额头时这里是皮肤，下面会剔掉）
    fy1 = eye_y - 0.35 * (mouth_y - eye_y)
    if fy1 > y + 0.05 * fh:
        hair_seed[int(max(0, y + 0.02 * fh)):int(fy1), int(max(0, ex0)):int(min(w, ex1))] = True
    if len(sk) < MIN_SEED:
        return None
    skc = _centers(sk, 2)
    far = lab[~roi]
    bgc = _centers(far[np.random.default_rng(0).choice(len(far), min(len(far), 6000), replace=False)], 4) \
        if len(far) > 200 else None
    hs = lab[hair_seed]
    if len(hs):
        hs = hs[_dist(hs, skc, WL) > 6]                       # 光额头 / 盘发：像皮肤的不算头发
    if len(hs) and bgc is not None:                            # 框到头顶外面的背景（深色头发配深色背景时留着）
        keep = _dist(hs, bgc, 0.5) > 6
        if keep.mean() > 0.4:
            hs = hs[keep]
    have_hair = len(hs) >= MIN_SEED
    hc = _centers(_trim(hs, WL, 90), 4) if have_hair else None
    return dict(skin_seed=skin_seed, hair_seed=hair_seed, skc=skc, hc=hc, have_hair=have_hair, bgc=bgc)


def _split(lab, person, smp, x, y, fw, fh, pts, whole=False, smooth=None):
    """Hair / skin inside the person mask (working size). whole=False: skin = face only (head swap);
    whole=True: skin anywhere on the person (arms, shoulders, legs), hair may hang lower.
    Returns (hair, skin, face_skin, dict(face = 脸椭圆, clean = 干净皮肤))."""
    h, w = lab.shape[:2]
    skin_seed, hair_seed, skc, hc, have_hair = (smp[k] for k in ('skin_seed', 'hair_seed', 'skc', 'hc', 'have_hair'))
    eye_y, mouth_y = pts[:2, 1].mean(), pts[3:, 1].mean()
    cx, cy = x + fw / 2, y + fh / 2
    # ---- hair / skin inside the person: soft split by colour (pale skin and platinum hair can be close)
    ds = _dist(lab, skc, WL)
    dh = _dist(lab, hc, WL) if have_hair else np.full((h, w), 1e3, np.float32)
    head_zone = _ellipse((h, w), (cx, cy + 0.05 * fh), (0.62 * fw, 0.62 * fh))           # 脸（含下巴、耳朵）
    head_zone[:int(max(0, eye_y)), int(max(0, cx - 0.75 * fw)):int(min(w, cx + 0.75 * fw))] = True   # 额头
    inner = _ellipse((h, w), (pts[2][0], (eye_y + mouth_y) / 2 + 0.05 * fh), (0.42 * fw, 0.48 * fh))
    prior = np.where(inner, 4.0, 0.0)                                       # 脸中间优先算皮肤（刘海要明显像头发才算）
    p_skin = 1 / (1 + np.exp(np.clip((ds - dh - prior) / 2.5, -30, 30)))  # 1 = 皮肤，0 = 头发
    # 下巴以下光滑的大块 = 脖子 / 肩背（浅色皮肤和浅金发颜色很近，靠发丝纹理区分），不算头发
    L = lab[..., 0]
    tex = cv2.GaussianBlur(np.abs(L - cv2.GaussianBlur(L, (0, 0), 1.0)), (0, 0), 2.0)
    body = (np.arange(h)[:, None] > mouth_y + 0.35 * fh) & (tex < TEX_SMOOTH) & (p_skin > 0.1)
    body = cv2.morphologyEx(body.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    body = _keep_big(body, 0.25 * fw * fh)                  # 肩背是一大块；发丝间偶尔光滑的小块不算
    hair = person & (p_skin < 0.5) & (dh < CLASS_MAX * 1.3) & ~body
    if have_hair:      # 明暗也不能离发色样本太远（黑色蕾丝裙 vs 白发、白衬衫 vs 黑发）
        hair &= (L > hc[:, 0].min() - 45) & (L < hc[:, 0].max() + 40)
    if whole and have_hair:
        # 换整个角色：身上还有衣服，颜色可能和头发很近（深色衬衫 vs 深色头发、白裙 vs 白发），收紧：
        # 明暗也算进颜色距离；下巴以下大块光滑的（不管什么颜色）是衣服 / 皮肤，不是发丝
        dh2 = _dist(lab, hc, WL_WHOLE)
        smooth = (np.arange(h)[:, None] > mouth_y + 0.35 * fh) & (tex < TEX_SMOOTH)
        smooth = _keep_big(cv2.morphologyEx(smooth.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)),
                           0.25 * fw * fh)
        hair &= (dh2 < HAIR_MAX_WHOLE) & ~smooth & (L > hc[:, 0].min() - 25) & (L < hc[:, 0].max() + 25)
    if have_hair:      # hair = what is connected to the hair samples (same colour lower down could be clothing)
        n, lbl = cv2.connectedComponents(hair.astype(np.uint8), connectivity=8)
        ids = np.unique(lbl[hair & hair_seed])
        hair = np.isin(lbl, ids[ids > 0])
        hair &= np.arange(h)[:, None] < y + (HAIR_DOWN_WHOLE if whole else 4.0) * fh
    else:
        hair[:] = False
    core, outer, clean, neck = _face_zone((h, w), x, y, fw, fh, pts)
    face = core.copy()                                       # 脸芯（眉毛往下）一律是脸：背光面、下巴阴影、眼睛都在里面
    if smooth is not None:                                   # 脸边一圈：平滑、连着脸芯、颜色不离谱的也是脸；有发丝纹理的仍是头发
        ring = (outer & ~core & smooth & person & (ds < CLASS_MAX)).astype(np.uint8)
        ring = cv2.morphologyEx(ring, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lbl, st, _ = cv2.connectedComponentsWithStats(((ring > 0) | core).astype(np.uint8), connectivity=8)
        ids = set(np.unique(lbl[core]).tolist())
        for i in np.unique(lbl[neck & (ring > 0)]):          # 脖子：下巴那道明暗边隔开了也算，只要是够大的一整块平滑皮肤
            if i > 0 and st[i, cv2.CC_STAT_AREA] >= 0.04 * fw * fh:
                ids.add(int(i))
        ids.discard(0)
        face = np.isin(lbl, sorted(ids))
        face = cv2.morphologyEx(face.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
        face &= outer | core
    hair &= ~face
    face_skin = (person & ~hair & (p_skin > 0.5) & (ds < CLASS_MAX) & head_zone) | face
    if whole and face_skin.sum() > 30:
        # 身上的皮肤：和脸颊颜色够近，而且不比脸亮太多、不比脸的彩度淡太多（白碗、米色桌面、白衬衫在暖光下也像肤色）
        fs = lab[face_skin]
        C = np.hypot(lab[..., 1], lab[..., 2])
        like = ((_dist(lab, skc, WL_WHOLE) < SKIN_BODY_MAX) & (L <= np.percentile(fs[:, 0], 95) + 6)
                & (C >= 0.55 * float(np.median(np.hypot(fs[:, 1], fs[:, 2])))))
        skin = (person & ~hair & like) | face_skin
    else:
        skin = face_skin
    return hair, skin, face_skin, dict(face=face, clean=clean)


def _soft_masks(lab, full, char, classes, fw, fz, hair):
    """Full-size soft masks. char（人物和背景的分界）贴着明暗边（引导滤波），保持干净；人物内部各类之间（头发 / 皮肤 / 衣服）
    用宽一点的高斯过渡 —— 各类上色不同，分界再贴着明暗边就会变成一条硬线。另给统计用的：
    skin_stat = 干净皮肤（脸上去掉五官），hair_stat = 可靠的头发（离脸远一点），face_zone = 脸。"""
    H, W = full
    h, w = lab.shape[:2]
    guide = (lab[..., 0] / 100).astype(np.float32)
    r = max(2, int(0.006 * max(h, w)))
    sig = max(1.5, SPLIT_SIG * fw)

    def up(v):
        return np.clip(cv2.resize(v.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR), 0, 1)

    def edge(m):
        return up(np.clip(guided(guide, cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.8), r, 1e-3), 0, 1))

    def wide(m):
        return up(cv2.GaussianBlur(m.astype(np.float32), (0, 0), sig))

    def plain(m):
        return up(cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.8))
    sc = edge(char)
    ws = {k: wide(v) for k, v in classes.items()}
    tot = np.maximum(sum(ws.values()), 1e-4)
    out = {k: sc * v / tot for k, v in ws.items()}
    k = int(4 * sig) | 1
    conf = hair & ~(cv2.dilate(fz['face'].astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0)
    out.update(char=sc, skin_stat=plain(fz['clean']), hair_stat=plain(conf), face_zone=wide(fz['face']))
    return out


def head_parts(img8, face=None):
    """Main character's head on img8 (BGR uint8, full size). Returns None when no face is found, else dict:
    char / hair / skin = soft masks 0..1 at full size (hair + face skin; neck and shoulders below the chin are not
    'skin' here), face = YuNet face, info = text for the log."""
    face = face or (mj_face.detect_faces(img8) or [None])[0]
    if face is None:
        return None
    H, W = img8.shape[:2]
    s = min(1.0, WORK / max(H, W))
    small = cv2.resize(img8, (max(1, int(round(W * s))), max(1, int(round(H * s)))), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    lab = to_lab(small.astype(np.float32) / 255)
    x, y, fw, fh = (np.asarray(face['box'], np.float64) * s).tolist()
    pts = np.asarray(face['pts'], np.float64) * s
    eye_y, mouth_y = pts[:2, 1].mean(), pts[3:, 1].mean()
    cx, cy = x + fw / 2, y + fh / 2
    roi = _ellipse((h, w), (cx, cy - 0.1 * fh), (1.55 * fw, 1.25 * fh))
    roi[int(cy):, int(max(0, cx - 1.5 * fw)):int(min(w, cx + 1.5 * fw))] = True     # 长发垂到胸前、身体
    smp = _samples(lab, x, y, fw, fh, pts, roi)
    if smp is None:
        return None
    skin_seed, hair_seed, skc, hc, have_hair, bgc = (smp[k] for k in ('skin_seed', 'hair_seed', 'skc', 'hc', 'have_hair',
                                                                       'bgc'))
    # ---- person vs background (GrabCut seeded with the samples)
    gc = np.full((h, w), cv2.GC_BGD, np.uint8)
    gc[roi] = cv2.GC_PR_BGD
    if bgc is not None:            # 头部范围里不像远处背景的颜色先算“可能是人物”（垂下来的长发、发梢）
        gc[roi & (_dist(lab, bgc, 0.5) > 10)] = cv2.GC_PR_FGD
    gc[_ellipse((h, w), (cx, cy), (0.55 * fw, 0.62 * fh))] = cv2.GC_PR_FGD
    near_skin = _dist(lab, skc, WL) < 5
    near_hair = (_dist(lab, hc, WL) < 4) if have_hair else np.zeros((h, w), bool)
    gc[skin_seed & near_skin] = cv2.GC_FGD
    if have_hair:
        gc[hair_seed & near_hair] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.setRNGSeed(0)
        cv2.grabCut(np.ascontiguousarray(small), gc, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    person = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
    # keep the component(s) that contain the face
    n, lbl = cv2.connectedComponents(person.astype(np.uint8), connectivity=8)
    ids = np.unique(lbl[_ellipse((h, w), (cx, cy), (0.3 * fw, 0.3 * fh)) & person])
    person = np.isin(lbl, ids[ids > 0])
    smooth, how_face = _smooth_map(img8, face, s, (h, w), smp)
    hair, skin, _, fz = _split(lab, person, smp, x, y, fw, fh, pts, smooth=smooth)
    char = skin | hair
    out = _soft_masks(lab, (H, W), char, dict(hair=hair, skin=skin), fw, fz, hair)
    out.update(face=face, scale=s, small=small,
               hard=dict(char=char, hair=hair, skin=skin, hair_seed=hair_seed, skin_seed=skin_seed, face=fz['face']))
    out['info'] = (tr('头发 {v:.1f}%、脸部皮肤 {v2:.1f}%', v=hair.mean() * 100, v2=skin.mean() * 100)
                   + ('' if have_hair else tr('（额头上方没找到头发，头发不单独还原）'))
                   + (tr('；脸边：') + how_face if smooth is not None else tr('；脸边按颜色分（') + how_face + tr('）')))
    return out


# ------------------------------------------------------------------ whole character (换整个角色)
PERSON_W = 2.6                   # 人物范围最宽：脸中心左右各 2.6 个脸宽（张开的手臂），从脸往下到画面底
BODY_W0, BODY_GROW = 1.4, 0.45   # 下巴处半宽 1.4 个脸宽，每往下 1 个脸高放宽 0.45 个脸宽（肩、手臂），到 PERSON_W 为止
DEPTH_TOL = 0.15                 # 远近图（0 远 ~ 1 近）里比脸远不超过它 = 和人物同一层（不超过脸与旁边背景差的一半）
DEPTH_UP = 0.2                   # 脸不是画面里最近的东西时（前面有桌子、碗、栏杆）：比脸近超过它的不算人物
DEPTH_NEAR_FACE = 0.6            # 脸的远近值到这么高 = 人本身就是最近的，肩膀、手伸向镜头都算人物，不设上限
DEPTH_MIN_CONTRAST = 0.08        # 脸和旁边背景在远近图里差得比这还小（人贴着墙）：远近图分不开，改用颜色（GrabCut）


def person_parts(img8, face=None):
    """The main character's whole figure on img8 (head, body, clothes, shoes), split into hair / skin / cloth.
    Returns None without a face, else dict like head_parts plus cloth, skin_stat (face skin, used for the colour
    statistics so that a bare shoulder in one image and a covered one in the other do not skew the skin match).
    Figure = the region as near as the face in the depth map (mj_depth), connected to the face, inside a column under
    the face; without the depth model a GrabCut over that column. The head part (hair edges) is added from head_parts."""
    face = face or (mj_face.detect_faces(img8) or [None])[0]
    if face is None:
        return None
    H, W = img8.shape[:2]
    s = min(1.0, WORK / max(H, W))
    small = cv2.resize(img8, (max(1, int(round(W * s))), max(1, int(round(H * s)))), interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    lab = to_lab(small.astype(np.float32) / 255)
    x, y, fw, fh = (np.asarray(face['box'], np.float64) * s).tolist()
    pts = np.asarray(face['pts'], np.float64) * s
    cx, cy = x + fw / 2, y + fh / 2
    roi = _ellipse((h, w), (cx, cy - 0.1 * fh), (1.6 * fw, 1.35 * fh))      # 头 + 头发
    chin = cy + 0.5 * fh
    rows = np.arange(h)[:, None]
    half = np.minimum(BODY_W0 + BODY_GROW * np.maximum(rows - chin, 0) / fh, PERSON_W) * fw
    roi |= (rows >= chin - 0.3 * fh) & (np.abs(np.arange(w)[None, :] - cx) <= half)   # 身体：往下逐渐变宽
    smp = _samples(lab, x, y, fw, fh, pts, roi)
    if smp is None:
        return None
    face_core = _ellipse((h, w), (cx, cy), (0.3 * fw, 0.3 * fh))
    how = 'GrabCut'
    person = None
    try:
        import mj_depth
        if mj_depth.available():
            d = cv2.resize(mj_depth.relative_depth(img8).astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)
            fd = float(np.median(d[face_core]))
            around = []                                   # 头两侧、头顶上方的背景
            for sx in (-1, 1):
                a0, a1 = sorted((int(cx + sx * 1.3 * fw), int(cx + sx * 2.2 * fw)))
                a0, a1 = max(0, a0), min(w, a1)
                if a1 - a0 > 2:
                    around.append(float(np.median(d[int(max(0, y - 0.3 * fh)):int(y + 0.6 * fh) + 1, a0:a1])))
            t0, t1 = int(max(0, y - 1.2 * fh)), int(max(0, y - 0.6 * fh))
            if t1 - t0 > 2:
                around.append(float(np.median(d[t0:t1, int(max(0, cx - 0.5 * fw)):int(cx + 0.5 * fw) + 1])))
            contrast = fd - min(around) if around else 0.0
            if contrast >= DEPTH_MIN_CONTRAST:
                tol = min(DEPTH_TOL, 0.5 * contrast)
                upper = fd + DEPTH_UP if fd < DEPTH_NEAR_FACE else np.inf
                near = (d >= fd - tol) & (d <= upper) & roi
                near = cv2.morphologyEx(near.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
                person, how = near, tr('远近图')
            else:
                how = tr('GrabCut（人和背景远近分不开）')
    except Exception:
        person = None
    if person is None:
        gc = np.full((h, w), cv2.GC_BGD, np.uint8)
        gc[roi] = cv2.GC_PR_BGD
        if smp['bgc'] is not None:
            gc[roi & (_dist(lab, smp['bgc'], 0.5) > 10)] = cv2.GC_PR_FGD
        gc[_ellipse((h, w), (cx, cy), (0.55 * fw, 0.62 * fh))] = cv2.GC_PR_FGD
        gc[smp['skin_seed'] & (_dist(lab, smp['skc'], WL) < 5)] = cv2.GC_FGD
        if smp['have_hair']:
            gc[smp['hair_seed'] & (_dist(lab, smp['hc'], WL) < 4)] = cv2.GC_FGD
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        try:
            cv2.setRNGSeed(0)
            cv2.grabCut(np.ascontiguousarray(small), gc, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
        except cv2.error:
            return None
        person = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
    hp = head_parts(img8, face)
    if hp is not None:
        person = person | hp['hard']['char']
    person = cv2.morphologyEx(person.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
    n, lbl = cv2.connectedComponents(person.astype(np.uint8), connectivity=8)
    ids = np.unique(lbl[face_core & person])
    person = np.isin(lbl, ids[ids > 0])
    smooth, how_face = _smooth_map(img8, face, s, (h, w), smp)
    hair, skin, face_skin, fz = _split(lab, person, smp, x, y, fw, fh, pts, whole=True, smooth=smooth)
    person = person | skin
    cloth = person & ~hair & ~skin
    out = _soft_masks(lab, (H, W), person, dict(hair=hair, skin=skin, cloth=cloth), fw, fz, hair)
    out.update(face=face, scale=s, kind='person', small=small,
               hard=dict(char=person, hair=hair, skin=skin, cloth=cloth, hair_seed=smp['hair_seed'],
                         skin_seed=smp['skin_seed'], face=fz['face']))
    out['info'] = (tr('人物 {v:.1f}%（{how}）：头发 {v2:.1f}%、皮肤 {v3:.1f}%、服装等 {v4:.1f}%', v=person.mean() * 100, how=how, v2=hair.mean() * 100, v3=skin.mean() * 100, v4=cloth.mean() * 100) + (tr('；脸边：') + how_face if smooth is not None else
                                                     tr('；脸边按颜色分（') + how_face + tr('）')))
    return out


def _tag(parts):
    return tr('换角色') if parts.get('kind') == 'person' else tr('换头')


def _stats_full(lab_full, soft_mask, thr=0.6):
    m = soft_mask > thr
    return region_stats(lab_full, m) if m.sum() > 300 else None


def _same_kind(gs, ms):
    d = float(np.sqrt((gs['mL'] - ms['mL']) ** 2 + (gs['ma'] - ms['ma']) ** 2 + (gs['mb'] - ms['mb']) ** 2))
    return float(np.clip((SAME_HI - d) / (SAME_HI - SAME_LO), 0, 1)), d


def _skin_grade(lab, gs, ms, face_light):
    """皮肤只迁移调色：中位明暗平移（≤ SKIN_L_CAP）和轻微反差都乘 face_light（0 = 保持 GPT 的脸部明暗，1 = 跟 MJ 一样），
    冷暖（a / b 平均）按 MJ 平移（≤ SKIN_AB_CAP）。脸上原有的明暗起伏、妆容、五官阴影不变。返回 (Lab, 信息)。"""
    L = lab[..., 0]
    mg, mm = float(gs['q'][16]), float(ms['q'][16])
    dL0 = float(np.clip(mm - mg, -SKIN_L_CAP, SKIN_L_CAP))
    kc0 = float(np.clip((ms['q'][24] - ms['q'][8]) / max(gs['q'][24] - gs['q'][8], 1e-3), *SKIN_K))
    dL, kc = dL0 * face_light, 1 + (kc0 - 1) * face_light
    da = float(np.clip(ms['ma'] - gs['ma'], -SKIN_AB_CAP, SKIN_AB_CAP))
    db = float(np.clip(ms['mb'] - gs['mb'], -SKIN_AB_CAP, SKIN_AB_CAP))
    out = np.dstack([mg + dL + (L - mg) * kc, lab[..., 1] + da, lab[..., 2] + db]).astype(np.float32)
    return out, dict(mg=mg, mm=mm, dL=dL, dL0=dL0, da=da, db=db)


def recolor(gf, mjf, gp, mp, log=print, face_light=1.0):
    """GPT head recoloured class by class onto MJ's head: returns (colour image float BGR at GPT size,
    weight 0..1 where it applies). gf / mjf: float BGR (each in its own coordinates).
    头发：按 MJ 头发的明暗分布和颜色还原（白发还原成白发）。皮肤（脸 + 露出的皮肤）：只迁移调色，见 _skin_grade；
    face_light = 「脸部明暗跟随 MJ」0～1。"""
    face_light = float(np.clip(face_light, 0.0, 1.0))
    lab_g, lab_m = to_lab(gf), to_lab(mjf)
    out = gf.copy()
    wsum = np.zeros(gf.shape[:2], np.float32)
    acc = np.zeros_like(gf)
    names = dict(hair=tr('头发'), skin=tr('皮肤'))
    for cls in ('hair', 'skin'):
        gs = _stats_full(lab_g, gp.get(cls + '_stat', gp[cls]))     # 皮肤只按脸上的干净皮肤统计，头发只按可靠的头发
        ms = _stats_full(lab_m, mp.get(cls + '_stat', mp[cls]))
        if gs is None or ms is None:
            log(tr('    {v}：{v2} 在{v3} 图里没找到，按周围区域处理', v=_tag(gp), v2=names[cls], v3="GPT" if gs is None else "MJ"))
            continue
        k, dist = _same_kind(gs, ms)
        txt = (tr('    {v}：{v2} GPT L{mL:.0f} a{ma:+.1f} b{mb:+.1f} → MJ L{mL2:.0f} a{ma2:+.1f} b{mb2:+.1f}', v=_tag(gp), v2=names[cls], mL=gs["mL"], ma=gs["ma"], mb=gs["mb"], mL2=ms["mL"], ma2=ms["ma"], mb2=ms["mb"]))
        if k <= 0:
            log(txt + tr('：颜色差别 {dist:.0f}，太大，多半是角色本来的{v}颜色 → 只按整幅调色，不改成 MJ 的', dist=dist, v=names[cls]))
            continue
        if cls == 'skin':
            Tl, gi = _skin_grade(lab_g, gs, ms, face_light)
            txt = (tr('    {v}：皮肤只按 MJ 调色（脸上原有的明暗起伏、妆容保留）：明暗 L{mg:.0f} → L{v2:.0f}（MJ L{mm:.0f}，跟随 {v3:.0f}%', v=_tag(gp), mg=gi["mg"], v2=gi["mg"] + gi["dL"], mm=gi["mm"], v3=face_light * 100)
                   + (tr('，已到上限') if abs(gi['dL0']) >= SKIN_L_CAP - 1e-6 and abs(gi['mm'] - gi['mg']) > SKIN_L_CAP else '')
                   + tr('），冷暖 a{da:+.1f} b{db:+.1f}', da=gi["da"], db=gi["db"]))
        else:
            Tl = _transform(lab_g, gs, ms, CAP[cls], TONE_K, COL_K)
        T = to_bgr(Tl)
        wt = gp[cls].astype(np.float32) * k
        acc += T * wt[..., None]
        wsum += wt
        log(txt + ('' if k >= 1 else tr('（颜色差别 {dist:.0f}，偏大，按 MJ 还原 {v:.0f}%，其余按整幅调色）', dist=dist, v=k * 100)))
    wt = np.clip(wsum, 0, 1)
    out = np.where(wsum[..., None] > 1e-4, acc / np.maximum(wsum, 1e-4)[..., None], gf)
    out = _local_light(out, lab_m, gp, mp, log)
    # lips: MJ's lips (only inside the GPT face, after the skin)
    gl = mj_face.lips_mask((np.clip(gf, 0, 1) * 255).astype(np.uint8), gp['face'])
    ml = mj_face.lips_mask((np.clip(mjf, 0, 1) * 255).astype(np.uint8), mp['face'])
    k = 1.0
    if gl is not None and ml is not None and gl.sum() > 30 and ml.sum() > 30:
        k, dist = _same_kind(region_stats(lab_g, gl), region_stats(lab_m, ml))
        if k < 1:
            log(tr('    {v}：嘴唇颜色差别 {dist:.0f}，', v=_tag(gp), dist=dist) + (tr('太大，多半是角色本来的唇色 → 只按整幅调色') if k <= 0 else
                                                  tr('偏大，按 MJ 还原 {v:.0f}%', v=k * 100)))
    if k > 0:
        lips = mj_face.apply_lips(out.astype(np.float32), gf, mjf, gl, ml, lambda t: log(tr('    {v}：', v=_tag(gp)) + t.strip()),
                                  cap=LIPS_CAP)
        out = out + (lips - out) * k
        if gl is not None:
            wt = np.maximum(wt, cv2.GaussianBlur(gl.astype(np.float32), (0, 0), 2) * k)
    return np.clip(out, 0, 1).astype(np.float32), wt


def _local_light(out, lab_m, gp, mp, log, work=800):
    """Hair only: where MJ's hair is lit / in shade / warmer / cooler, the GPT hair follows — fields are averaged only
    over confident hair (hair_stat, away from the face), MJ's head is laid over GPT's by the five face landmarks, mean of
    each field difference = 0 (the class means are already matched), not applied on the face (face_zone).
    皮肤不套用：脸上的受光 / 背光保持 GPT 自己的（V4.6.2 起）。"""
    src, dst = np.asarray(mp['face']['pts'], np.float32), np.asarray(gp['face']['pts'], np.float32)
    A, _ = cv2.estimateAffinePartial2D(src, dst)
    if A is None:
        return out
    err = float(np.sqrt(((src @ A[:, :2].T + A[:, 2] - dst) ** 2).sum(1)).mean() / max(gp['face']['box'][2], 1))
    if err > POSE_TOL:
        log(tr('    {v}：新旧人物的角度 / 表情差得多（五官对齐误差 {v2:.0f}% 脸宽），受光分布不套用，只按整体颜色还原', v=_tag(gp), v2=err * 100))
        return out
    H, W = out.shape[:2]
    s = min(1.0, work / max(H, W))
    h, w = int(round(H * s)), int(round(W * s))
    A = np.vstack([A, [0, 0, 1]])
    A = np.array([[s, 0, 0.5 * s - 0.5], [0, s, 0.5 * s - 0.5], [0, 0, 1]]) @ A
    lab_o = to_lab(cv2.resize(out, (w, h), interpolation=cv2.INTER_AREA))
    lab_mw = cv2.warpAffine(lab_m, A[:2], (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    sig = max(2.0, LOCAL_SIG * gp['face']['box'][2] * s)
    lab_full = to_lab(out)
    names = dict(hair=tr('头发'), skin=tr('皮肤'))
    for cls in ('hair',):
        mm = cv2.warpAffine(mp.get(cls + '_stat', mp[cls]).astype(np.float32), A[:2], (w, h), flags=cv2.INTER_LINEAR) > 0.6
        gm = cv2.resize(gp.get(cls + '_stat', gp[cls]), (w, h), interpolation=cv2.INTER_AREA) > 0.6
        if mm.sum() < 200 or gm.sum() < 200:
            continue
        bm = cv2.GaussianBlur(mm.astype(np.float32), (0, 0), sig)
        bg = cv2.GaussianBlur(gm.astype(np.float32), (0, 0), sig)
        fm = cv2.GaussianBlur(lab_mw * mm[..., None], (0, 0), sig) / np.maximum(bm, 1e-4)[..., None]
        fg = cv2.GaussianBlur(lab_o * gm[..., None], (0, 0), sig) / np.maximum(bg, 1e-4)[..., None]
        conf = np.clip(bm / 0.25, 0, 1) * np.clip(bg / 0.25, 0, 1)
        res = (fm - fg) * conf[..., None]
        wv = (conf * gm)[..., None]
        res -= (res * wv).sum((0, 1)) / max(float(wv.sum()), 1e-4)
        res[..., 0] = np.clip(res[..., 0], -LOCAL_CAP[0], LOCAL_CAP[0])
        res[..., 1:] = np.clip(res[..., 1:], -LOCAL_CAP[1], LOCAL_CAP[1])
        res *= LOCAL_K * conf[..., None]
        rf = cv2.resize(res, (W, H), interpolation=cv2.INTER_LINEAR)
        lab_full += rf * (gp[cls] * (1 - gp.get('face_zone', 0)))[..., None]
        span = np.percentile(res[gm][:, 0], [5, 95])
        log(tr('    {v}：{v2}的受光 / 背光分布按 MJ（明暗起伏 {v3:+.1f}～{v4:+.1f}）', v=_tag(gp), v2=names[cls], v3=span[0], v4=span[1]))
    return to_bgr(lab_full)


def overlay(gp, img8, h=600):
    """Preview: hair green, skin red, samples outlined."""
    sm = gp['small']
    ov = sm.copy()
    hd = gp['hard']
    ov[hd['hair']] = (40, 200, 40)
    ov[hd['skin']] = (60, 60, 230)
    if 'cloth' in hd:
        ov[hd['cloth']] = (230, 140, 40)
    v = cv2.addWeighted(sm, 0.45, ov, 0.55, 0)
    for k, col in (('hair_seed', (0, 255, 255)), ('skin_seed', (255, 255, 0))):
        cnts, _ = cv2.findContours(hd[k].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(v, cnts, -1, col, 1)
    return cv2.resize(v, (int(v.shape[1] * h / v.shape[0]), h), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------ texture (softness) of the new head
TEX_SIGS = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0)   # 分析密度（MJ 像素）下的频段：G(s_k) - G(s_k+1)
TEX_PASSES = 2                            # 量 → 调 → 再量一次（频段互相重叠，一次调不到位）
TEX_GAIN = (0.45, 1.0)                    # 每个频段最多减到 0.45 倍，只柔化不锐化（细颗粒由后面的补颗粒补上）


def _band_rms(L, m, sigs):
    Gs = [cv2.GaussianBlur(L, (0, 0), s) for s in sigs]
    return np.array([float(np.sqrt(np.mean(((Gs[k] - Gs[k + 1])[m]) ** 2))) for k in range(len(sigs) - 1)])


def match_texture(P, mjf, gp, mp, lin, log=print):
    """Make the new head as soft as MJ's old head, class by class (hair to hair, skin to skin): per-band energy
    measured at the common pixel density, applied as band gains under the class masks. lin = MJ px per GPT px."""
    sP, sM = min(1.0, lin), min(1.0, 1.0 / lin)            # 两张图缩到同一像素密度（较低的那个）再比较
    H, W = P.shape[:2]
    ys, xs = np.nonzero(gp['char'] > 0.01)
    if len(ys) == 0:
        return P
    pad = int(3 * TEX_SIGS[-1] / sP) + 2
    y0, y1, x0, x1 = max(0, ys.min() - pad), min(H, ys.max() + pad + 1), max(0, xs.min() - pad), min(W, xs.max() + pad + 1)
    crop = P[y0:y1, x0:x1].copy()

    def small(img, s):
        return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
    Lm = to_lab(small(mjf, sM))[..., 0]
    se = np.ones((5, 5), np.uint8)
    names = dict(hair=tr('头发'), skin=tr('皮肤'))
    masks, total = {}, {}
    for cls in ('hair', 'skin'):
        h0, w0 = int(round(crop.shape[0] * sP)) if sP < 1 else crop.shape[0], int(round(crop.shape[1] * sP)) if sP < 1 else crop.shape[1]
        gst, mst = gp.get(cls + '_stat', gp[cls]), mp.get(cls + '_stat', mp[cls])   # 量：干净皮肤 / 可靠头发；调：整类
        mg = cv2.erode((cv2.resize(gst[y0:y1, x0:x1], (w0, h0), interpolation=cv2.INTER_AREA) > 0.6).astype(np.uint8), se) > 0
        mm = cv2.erode((cv2.resize(mst, (Lm.shape[1], Lm.shape[0]), interpolation=cv2.INTER_AREA) > 0.6).astype(np.uint8), se) > 0
        if mg.sum() >= 500 and mm.sum() >= 500:
            masks[cls] = (mg, _band_rms(Lm, mm, TEX_SIGS))
            total[cls] = np.ones(len(TEX_SIGS) - 1)
    for _ in range(TEX_PASSES):
        Lp = to_lab(small(crop, sP))[..., 0]
        Gs = [cv2.GaussianBlur(crop, (0, 0), s / sP) for s in TEX_SIGS]
        d = np.zeros_like(crop)
        for cls, (mg, em) in masks.items():
            if mg.shape != Lp.shape:
                mg = cv2.resize(mg.astype(np.uint8), (Lp.shape[1], Lp.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
            gains = np.clip(em / np.maximum(_band_rms(Lp, mg, TEX_SIGS), 1e-4), *TEX_GAIN)
            gains = np.clip(gains, TEX_GAIN[0] / total[cls], TEX_GAIN[1] / total[cls])     # 累计也不超过上下限
            gains = np.where(np.abs(gains - 1) < 0.03, 1.0, gains)
            total[cls] *= gains
            wcls = gp[cls][y0:y1, x0:x1][..., None]
            for k, gk in enumerate(gains):
                if gk != 1.0:
                    d += (gk - 1) * (Gs[k] - Gs[k + 1]) * wcls
        crop = np.clip(crop + d, 0, 1)
    for cls in masks:
        log(tr('    {v}：{v2}柔度按 MJ 原来的人，各频段（细→粗）', v=_tag(gp), v2=names[cls]) + ' '.join(f'×{v:.2f}' for v in total[cls]))
    out = P.copy()
    out[y0:y1, x0:x1] = crop
    return out


# ------------------------------------------------------------------ softness of the new clothes (换整个角色)
CLOTH_SIGS = (0.0, 0.4, 0.7, 1.0, 1.4, 2.0, 2.8)   # 试的补模糊（MJ 像素）
CLOTH_MIN_EDGES = 300


def _edge_sigma(img8, m):
    import mj_measure
    E = mj_measure.edge_mask(img8, np.ones(img8.shape[:2], bool)) & m
    if E.sum() < CLOTH_MIN_EDGES:
        return None
    v = mj_measure.blur_sigma_at(img8, E)
    v = v[np.isfinite(v)]
    return float(np.median(v)) if len(v) >= CLOTH_MIN_EDGES else None


def soften_cloth(P, mjf, gp, mp, lin, log=print):
    """New clothes have no counterpart in MJ (different garment), so their softness is matched with a content-
    independent measure: the median edge blur (mj_measure's re-blur estimator) of MJ's old clothes (or the whole old
    figure when the clothes show few edges) — the GPT clothes get the smallest extra blur that reaches it.
    lin = MJ px per GPT px. Only blurs, never sharpens."""
    if 'cloth' not in gp or 'cloth' not in mp:
        return P
    to8 = lambda x: np.clip(x * 255 + 0.5, 0, 255).astype(np.uint8)
    m8 = to8(mjf)
    target = _edge_sigma(m8, mp['cloth'] > 0.6)
    src = tr('旧衣服')
    if target is None:
        target, src = _edge_sigma(m8, mp['char'] > 0.6), tr('旧人物')
    wc = gp['cloth']
    ys, xs = np.nonzero(wc > 0.05)
    if target is None or len(ys) < 2000:
        return P
    H, W = P.shape[:2]
    pad = int(4 * CLOTH_SIGS[-1] / max(lin, 1e-3)) + 4
    y0, y1, x0, x1 = max(0, ys.min() - pad), min(H, ys.max() + pad + 1), max(0, xs.min() - pad), min(W, xs.max() + pad + 1)
    crop = P[y0:y1, x0:x1]
    s = min(1.0, lin)
    msk = wc[y0:y1, x0:x1] > 0.6
    if s < 1:
        msk_s = cv2.resize(msk.astype(np.uint8), None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) > 0
    else:
        msk_s = msk
    prev = None                                     # (补模糊, 测得的虚化)
    pick, now = 0.0, None
    for sg in CLOTH_SIGS:
        b = cv2.GaussianBlur(crop, (0, 0), sg / lin) if sg > 0 else crop
        bs = cv2.resize(b, (msk_s.shape[1], msk_s.shape[0]), interpolation=cv2.INTER_AREA) if s < 1 else b
        m = _edge_sigma(to8(bs), msk_s)
        if m is None:
            return P
        if m >= target:                             # 在上一档和这一档之间按测得值插值，免得一档跳过头
            if prev is None:
                pick, now = sg, m
            else:
                t = float(np.clip((target - prev[1]) / max(m - prev[1], 1e-3), 0, 1))
                pick, now = prev[0] + t * (sg - prev[0]), target
            break
        prev = (sg, m)
        pick, now = sg, m
    if pick > 0:
        cur = cv2.GaussianBlur(crop, (0, 0), pick / lin)
        out = P.copy()
        w = wc[y0:y1, x0:x1][..., None]
        out[y0:y1, x0:x1] = crop * (1 - w) + cur * w
        P = out
    log(tr('    换角色：新衣服的柔度按 MJ {src}（边缘虚化 {target:.2f}，MJ 像素）：补模糊 {pick:.2f}，补后约 {now:.2f}', src=src, target=target, pick=pick, now=now))
    return P
