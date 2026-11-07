# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""自测（改完代码跑一次）：python selftest.py
不碰真实数据：所有输出、状态、标定都放在临时目录里，跑完自动删除。
- 一定会跑：合成图测试（黑边检测、暗部画面测量、全暗图、透明 PNG、文件名不撞车、配错图拦截、坏 JSON 留底、
  状态文件并发写、工具产出识别）。
- calib 里有标定图片时（开发机）再跑：还原 / 整图还原的指标门限、④页两条路径、加入标定、提示词生成。
全部通过返回 0，否则返回 1 并列出失败项。"""
import os
import shutil
import sys
import tempfile
import threading
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mj_depth              # noqa: E402
import mj_face               # noqa: E402
import mj_io                 # noqa: E402
import mj_measure            # noqa: E402
import mj_restore            # noqa: E402
import mj_style_only         # noqa: E402
import mj_tool_core as core  # noqa: E402
import i18n                  # noqa: E402

FAILS = []
RNG = np.random.default_rng(7)


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg, flush=True)
    if not cond:
        FAILS.append(msg)


def quiet(_):
    pass


def seen(logs, zh, en):
    """运行记录里有没有这句话（按当前界面语言：中文界面找 zh，英文界面找 en；IMAGEF_LANG=en 时测英文）。"""
    frag = en if i18n.is_en() else zh
    return any(frag in t for t in logs)


def scene(H=720, W=1080, seed=0):
    """Synthetic photo-like image: gradients, shapes, texture, grain."""
    r = np.random.default_rng(seed)
    y, x = np.mgrid[:H, :W].astype(np.float32)
    img = np.dstack([90 + 60 * np.sin(x / 97), 110 + 50 * np.cos(y / 71), 130 + 40 * np.sin((x + y) / 53)])
    for _ in range(25):
        cv2.circle(img, (int(r.integers(0, W)), int(r.integers(0, H))), int(r.integers(10, 80)),
                   [float(v) for v in r.integers(20, 235, 3)], -1)
    img = cv2.GaussianBlur(img, (0, 0), 1.2) + r.normal(0, 3, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def synthetic(tmp):
    print('== 合成图测试')
    img = scene()
    lb = img.copy()
    lb[:70], lb[-70:] = 0, 0
    check(mj_restore.bar_box(lb)[:2] == (70, 650), f'上下黑边 70px 检出：{mj_restore.bar_box(lb)}')
    dark = img.copy()
    top = 216
    dark[:top] = np.clip(RNG.normal(4, 1.5, (top, img.shape[1], 3)), 0, 255).astype(np.uint8)
    for _ in range(300):
        yy, xx = int(RNG.integers(0, top)), int(RNG.integers(0, img.shape[1]))
        dark[yy:yy + 3, xx:xx + 3] = 200
    check(mj_restore.bar_box(dark)[0] == 0, '带灯光的暗部画面不当黑边')
    p = os.path.join(tmp, 'dark.png')
    mj_io.imwrite_u(p, dark)
    r = mj_measure.measure_file(p, tmp, 'dark', None, None, quiet)
    check('true deep blacks' in r['block'], '暗部画面的黑位测成真黑')
    p = os.path.join(tmp, 'all_dark.png')
    mj_io.imwrite_u(p, np.clip(RNG.normal(8, 2, (500, 700, 3)), 0, 255).astype(np.uint8))
    try:
        mj_measure.measure_file(p, tmp, 'all', None, None, quiet)
        check(True, '全暗图可以测量（不崩）')
    except Exception as e:
        check(False, f'全暗图测量出错：{e!r}')
    empty = os.path.join(tmp, 'empty.png')
    mj_io.write_bytes(empty, b'')
    check(mj_io.imread_u(empty) is None, '空文件读图返回 None 而不是报错')

    rgba = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    rgba[:100, :100, 3] = 0
    rgba[:100, :100, :3] = 0
    p = os.path.join(tmp, 'rgba.png')
    mj_io.imwrite_u(p, rgba)
    im, a = mj_io.imread_alpha(p)
    check(a is not None and (im[:100, :100] == 255).all(), '透明区域铺白读入')
    check(mj_io.with_alpha(im, a).shape[2] == 4, '可以把透明通道接回去')

    names = ['ChatGPT Image Nov 4, 2026, 08_12_33 PM', 'ChatGPT Image Nov 4, 2026, 08_59_01 AM',
             'ChatGPT Image 2026年11月4日 20_12_33', 'ChatGPT Image 2026年11月4日 20_12_58', 'x' * 99 + 'a', 'x' * 99 + 'b']
    sn = [core.short_name(n + '.png') for n in names]
    check(len(set(sn)) == len(sn) and max(map(len, sn)) <= core.NAME_MAX, '输出文件名前缀不撞车、不超长')
    check(core.is_tool_output('a_整图还原_2.png') and not core.is_tool_output('ChatGPT 还原.png'), '工具产出按后缀识别')
    stem = os.path.join(tmp, 'u')
    mj_io.write_bytes(stem + '_restored.png', b'')
    check(mj_io.unique_path(tmp, 'u', '_restored.png', ('_compare.jpg',)).endswith('u_restored_2.png'), '同名输出自动加 _2')

    bad = os.path.join(tmp, 'bad.json')
    with open(bad, 'w', encoding='utf-8') as f:
        f.write('{"a": [1, 2')
    w = []
    check(mj_io.read_json(bad, 'D', warn=w.append) == 'D' and w and not os.path.exists(bad), '损坏 JSON：返回默认值并改名留底')
    errs = []

    def hammer(i):
        try:
            for j in range(25):
                core.update_state(lambda st: st['restored_md5'].append(f'{i}-{j}'))
        except Exception as e:
            errs.append(e)
    ths = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    n = sum('-' in x for x in core.load_state()['restored_md5'])
    check(not errs and n == 100, f'状态文件并发写不丢：{n}/100')

    # 配错图拦截 + 同一张图（GPT 放大 1.6 倍、轻微平移、整体偏色）能对齐
    big = cv2.resize(img, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
    M = np.float32([[1, 0, 6], [0, 1, -4]])
    gpt = cv2.warpAffine(big, M, (big.shape[1], big.shape[0]), borderMode=cv2.BORDER_REFLECT)
    gpt = np.clip(gpt.astype(np.int16) + [6, 0, -6], 0, 255).astype(np.uint8)
    q = mj_restore.pair_quality(img, gpt)
    check(q['ok'] and q['corr'] > 0.95, f'同一张图（放大+平移+偏色）配对通过：相关 {q["corr"]:.3f}')
    q2 = mj_restore.pair_quality(img, cv2.resize(scene(seed=5), (gpt.shape[1], gpt.shape[0])))
    check(not q2['ok'], '不同的图被拦截')
    mjp, gp = os.path.join(tmp, 'mj.png'), os.path.join(tmp, 'gpt.png')
    mj_io.imwrite_u(mjp, img)
    mj_io.imwrite_u(gp, gpt)
    t = time.perf_counter()
    res = mj_restore.restore_file(mjp, gp, os.path.join(tmp, 'out.png'), debug=True, log=quiet)
    before, after = res['rows'][0][1], res['rows'][1][1]
    check(after['dE'] < before['dE'] * 0.5, f'合成图还原：色差 {before["dE"]:.2f} → {after["dE"]:.2f}'
                                              f'（{time.perf_counter() - t:.1f}s）')


def head_swap_restore(tmp, a, g, donor_path):
    """模拟换头（把 g 里主角的头换成 donor 里的头），②页换头模式：配对通过、新头整块保留。"""
    g8, d8 = mj_io.imread_u(g), mj_io.imread_u(donor_path)
    f, df = mj_face.main_face(g8), mj_face.main_face(d8)
    if f is None or df is None:
        print('   （标定图里没有找到人脸，跳过换头还原测试）')
        return

    def ell(fc):
        x, y, w, h = fc['box']
        return x + w / 2, y + h * 0.38, w * 0.85, h * 0.95
    cx, cy, ax, ay = ell(f)
    dcx, dcy, dax, _ = ell(df)
    k = ax / dax
    donor = cv2.warpAffine(d8, np.float32([[k, 0, cx - k * dcx], [0, k, cy - k * dcy]]), (g8.shape[1], g8.shape[0]),
                           borderMode=cv2.BORDER_REFLECT)
    m = np.zeros(g8.shape[:2], np.float32)
    cv2.ellipse(m, (int(cx), int(cy)), (int(ax), int(ay)), 0, 0, 360, 1, -1)
    soft = cv2.GaussianBlur(m, (0, 0), max(2.0, ax * 0.06))[..., None]
    sw = (g8 * (1 - soft) + donor * soft).astype(np.uint8)
    swp = os.path.join(tmp, 'swap.png')
    mj_io.imwrite_u(swp, sw)
    logs = []
    res = mj_restore.restore_file(a, swp, os.path.join(tmp, 'swap_out.png'), 'composite', log=logs.append, swap=True)
    inner = cv2.erode(m.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)

    def bp(x):
        L = cv2.cvtColor(x, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return (cv2.GaussianBlur(L, (0, 0), 1) - cv2.GaussianBlur(L, (0, 0), 4))[inner]
    c_new = float(np.corrcoef(bp(res['out']), bp(sw))[0, 1])
    c_old = float(np.corrcoef(bp(res['out']), bp(res['mj_up']))[0, 1])
    split = seen(logs, '换头：头发', 'Head swap: Hair') and seen(logs, '换头：皮肤', 'Head swap: Skin')
    check(res['changed'][inner].mean() > 0.95 and c_new > 0.6 and c_old < 0.3 and split,
          f'②页换头还原：新头的五官细节保留（与新头相关 {c_new:.2f}、与 MJ 旧头 {c_old:.2f}），'
          f'头发 / 皮肤分开按 MJ 同类区域还原：{"是" if split else "否"}')
    hp = mj_restore.prepare(mj_io.imread_u(a), sw, swap=True)['head_parts']
    gm = cv2.resize((hp['g']['char'] > 0.5).astype(np.uint8), (sw.shape[1], sw.shape[0])) > 0 if hp else None
    core_ = np.zeros(m.shape, np.uint8)
    cv2.ellipse(core_, (int(cx), int(cy)), (int(ax * 0.45), int(ay * 0.45)), 0, 0, 360, 1, -1)
    share = gm[core_ > 0].mean() if hp else 0.0
    check(hp is not None and share > 0.8, '换头：新头的头发 + 脸分得出来'
          + (f'（头部中间 {share * 100:.0f}% 被认作头发 / 皮肤）' if hp else ''))


def with_calibration(tmp):
    cal = os.path.join(HERE, 'calib')

    def pair(n):
        found = {}
        for k in ('input', 'gpt'):
            hit = [f for f in os.listdir(cal) if os.path.splitext(f)[0] == f'pair_{n:02d}_{k}'] if os.path.isdir(cal) else []
            found[k] = os.path.join(cal, hit[0]) if hit else None
        return found['input'], found['gpt']

    a3, g3 = pair(3)
    a11, g11 = pair(11)
    if not (a3 and g3 and a11 and g11):
        print('== 没有 calib 标定图片，跳过真实图片测试')
        return
    print('== 真实图片测试（calib 第 3 / 11 组）')
    gates = (('composite', a3, g3, 0.12), ('transfer', a11, g11, 1.2))
    for mode, a, g, max_de in gates:
        res = mj_restore.restore_file(a, g, os.path.join(tmp, f'{mode}.png'), mode, debug=True, log=quiet)
        m = res['rows'][1][1]
        check(m['dE'] < max_de and 0.9 < m['edge_ratio'] < 1.15 and m['focus_err'] < 0.15,
              f'{mode}：dE {m["dE"]:.2f}（< {max_de}）edge {m["edge_ratio"]:.2f} grain {m["grain_ratio"]:.2f} '
              f'focus {m["focus_err"]:.2f}')
    try:
        mj_restore.restore_file(a11, g3, os.path.join(tmp, 'x.png'), log=quiet)
        check(False, '配错的真实图没被拦截')
    except mj_restore.PairMismatch:
        check(True, '配错的真实图被拦截')
    r = core.measure(a3, True, quiet)
    check('MEASURED LOOK' in r['prompt'] and os.path.exists(r['upload']), '①页：生成提示词和预补偿图')
    check(r['prompt'].startswith('Retouch @图片1 :') and '@image' not in r['prompt'] and 'MEASURED LOOK OF @图片1' in r['prompt'],
          '①页：提示词里写的是 @图片1（不再是 @image1）')
    hs = core.measure(a3, False, quiet, headswap=True)
    p = hs['prompt']
    check('HEAD REPLACEMENT' in p and '@图片2' in p and p.index('HEAD REPLACEMENT') < p.index('MEASURED LOOK OF @图片1')
          and p.rstrip().endswith(core.HEADSWAP_NOTE) and core.is_headswap(a3) and hs['prompt_file'].endswith('_headswap.txt'),
          '①页修错 + 换头：换头基础提示词 + MJ 测量 + 换头说明，已记下“换头”')
    ps = core.measure(a3, False, quiet, swap='person')
    p = ps['prompt']
    check('FULL CHARACTER REPLACEMENT' in p and p.index('FULL CHARACTER REPLACEMENT') < p.index('MEASURED LOOK OF @图片1')
          and p.rstrip().endswith(core.CHARSWAP_NOTE) and core.swap_kind(a3) == 'person'
          and ps['prompt_file'].endswith('_charswap.txt'),
          '①页修错 + 换整个角色：换角色基础提示词 + MJ 测量 + 换角色说明，已记下“换角色”')
    core.measure(a3, False, quiet)
    check(not core.is_headswap(a3), '①页改回只修错后，“换头 / 换角色”记录清除')
    t = time.perf_counter()
    logs = []
    rp = mj_restore.restore_file(a11, g11, os.path.join(tmp, 'person.png'), 'transfer', log=logs.append, swap='person')
    r0 = mj_restore.restore_file(a11, g11, os.path.join(tmp, 'plain.png'), 'transfer', log=quiet)
    diff = float(np.abs(rp['out'].astype(int) - r0['out'].astype(int)).mean())
    seg = seen(logs, '换角色模式：GPT 新人物', 'Character swap mode: new GPT person')
    check(seg and diff < 4, f'②页换整个角色：人物分得出来（头发 / 皮肤 / 衣服），GPT 没换人时结果和普通还原接近'
                            f'（平均差 {diff:.1f}，{time.perf_counter() - t:.0f}s）')
    head_swap_restore(tmp, a11, g11, g3)
    rs = core.style_only(a3, g11, 1.0, False, False, quiet, 'region')
    check(os.path.exists(rs['out']) and rs['metrics']['result']['zone_dE'] < rs['metrics']['GPT']['zone_dE'],
          f'④页按区域：主体色差 {rs["metrics"]["GPT"]["zone_dE"]:.2f} → {rs["metrics"]["result"]["zone_dE"]:.2f}')
    core.measure(a11, False, quiet)                    # 中间做点别的（会用到 OpenCV 的全局随机数）
    rs2 = core.style_only(a3, g11, 1.0, False, False, quiet, 'region')
    same = np.array_equal(mj_io.imread_u(rs['out']), mj_io.imread_u(rs2['out']))
    check(same, '④页同一组图在同一次运行里做两遍，结果完全相同')
    # 同一场景重画：GPT 图左右翻转（布局变了，内容比例不变）
    flip = os.path.join(tmp, 'g11_flip.png')
    mj_io.imwrite_u(flip, cv2.flip(mj_io.imread_u(g11), 1))
    d_same = mj_style_only.scene_distance(mj_io.imread_u(a11), mj_io.imread_u(flip))
    d_diff = mj_style_only.scene_distance(mj_io.imread_u(a3), mj_io.imread_u(g11))
    check(d_same <= mj_style_only.SAME_SCENE_MAX < d_diff,
          f'同场景判断：翻转重画 {d_same:.2f}、不同内容 {d_diff:.2f}（门槛 {mj_style_only.SAME_SCENE_MAX}）')
    logs = []
    rs = core.style_only(a11, flip, 1.0, False, False, logs.append)
    layered = mj_depth.available()
    check(seen(logs, '同一场景重画', 'same scene redrawn')
          and (seen(logs, '按远近分层调色', 'Graded by depth layers') if layered else seen(logs, '整幅统一调色', 'niform grade'))
          and (('layers' in rs['metrics']) == layered)
          and rs['metrics']['result']['zone_dE'] < rs['metrics']['GPT']['zone_dE'],
          f'④页同场景：自动走{"按远近分层" if layered else "整幅统一（远近模型不可用）"}调色，主体色差 '
          f'{rs["metrics"]["GPT"]["zone_dE"]:.2f} → {rs["metrics"]["result"]["zone_dE"]:.2f}')
    if layered:
        # 远近模型缺失：自动退回整幅统一调色，不报错
        keep = mj_depth.MODEL
        mj_depth.MODEL = os.path.join(tmp, 'missing.onnx')
        try:
            logs = []
            rs2 = core.style_only(a11, flip, 1.0, False, False, logs.append)
            check(seen(logs, '退回整幅统一调色', 'falling back to a uniform grade') and os.path.exists(rs2['out']) and 'layers' not in rs2['metrics'],
                  '④页同场景：远近模型缺失时退回整幅统一调色')
        finally:
            mj_depth.MODEL = keep
    # 角色为主：嘴唇单独配色
    if mj_face.available():
        logs = []
        rs = core.style_only(a3, g11, 1.0, False, False, logs.append)
        g8, m8, o8 = mj_io.imread_u(g11), mj_io.imread_u(a3), mj_io.imread_u(rs['out'])
        gm, mm = mj_face.lips_mask(g8, mj_face.main_face(g8)), mj_face.lips_mask(m8, mj_face.main_face(m8))
        if gm is not None and mm is not None:
            def mean_ab(img, m):
                return mj_style_only.to_lab(img.astype(np.float32) / 255)[m][:, 1:].mean(0)
            target = mean_ab(m8, mm)
            before, after = (float(np.hypot(*(mean_ab(x, gm) - target))) for x in (g8, o8))
            check(seen(logs, '嘴唇单独配色', 'separate lip colour') and after < before * 0.5,
                  f'④页角色为主：嘴唇和 MJ 的色差 {before:.1f} → {after:.1f}')
        else:
            check(False, '④页角色为主：标定图里没找到嘴唇')
    else:
        print('  （人脸模型不可用，跳过嘴唇测试）')
    a6, g6 = pair(6)
    if a6 and g6:
        rs = core.style_only(a6, g6, 1.0, False, False, quiet)
        check(rs['metrics']['result']['zone_dE'] < rs['metrics']['GPT']['zone_dE'], '④页同构图（按位置）')
    g = os.path.join(tmp, 'g_copy.png')
    shutil.copyfile(g11, g)
    with open(g, 'ab') as f:
        f.write(b'\0')
    check(core.calib_add(a11, g, quiet) is True and len(core.calib_local()) == 1, '③页：加入标定并重算')
    check(core.calib_remove_last(quiet) is True, '③页：移除最后一组')


def main():
    tmp = tempfile.mkdtemp(prefix='mj_selftest_')
    core.OUT = os.path.join(tmp, 'Output')
    core.STATE = os.path.join(core.OUT, '_state.json')
    core.CALIB = os.path.join(tmp, 'calib')
    core.CALIB_LIST = os.path.join(core.CALIB, 'pairs.json')
    core.BIAS_JSON = os.path.join(tmp, 'gpt_bias.json')
    if os.path.exists(os.path.join(HERE, 'gpt_bias.json')):
        shutil.copyfile(os.path.join(HERE, 'gpt_bias.json'), core.BIAS_JSON)
    mj_style_only.STYLE_OUT = os.path.join(core.OUT, '只还原风格')
    t = time.perf_counter()
    try:
        synthetic(tmp)
        with_calibration(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{"全部通过" if not FAILS else str(len(FAILS)) + " 项失败"}（{time.perf_counter() - t:.0f} 秒）')
    for f in FAILS:
        print('  - ' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
