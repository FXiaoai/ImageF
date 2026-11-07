# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""Image F（原名 MJ 还原工具）的后台逻辑（图形界面 mj_gui.pyw 调用）。所有路径都支持中文。
各函数的 log 参数是“接收一行文字”的函数（界面里显示到「运行记录」）。"""
from i18n import tr
import hashlib
import os
import re
import shutil
import subprocess
import threading

import cv2
import numpy as np
from PIL import Image

import gpt_bias
import mj_measure
import mj_restore
import mj_style_only
from mj_io import InputError, imread_u, imwrite_u, read_json, read_text, unique_path, write_json, write_text

HERE = os.path.dirname(os.path.realpath(__file__))           # tools 目录
ROOT = os.path.dirname(HERE)                                 # 工作区
OUT = os.path.join(ROOT, 'Output')                           # V4.9 起输出文件夹和文件名都是英文
OLD_OUT = os.path.join(ROOT, '输出')                          # V4.8 以前的输出文件夹：旧结果不动，只把记录（_state.json）接过来
CALIB = os.path.join(HERE, 'calib')
CALIB_LIST = os.path.join(CALIB, 'pairs.json')
CALIB_BASE = os.path.join(HERE, 'calib_base.json')          # 内置基础数据：每组已测好的数值统计（不含图片）
BASE_NOTE = tr('内置基础数据')
BIAS_JSON = os.path.join(HERE, 'gpt_bias.json')
PROMPT_VERSIONS = {                                           # 测量页可选的提示词版本（第一个是默认）
    'v4（推荐）': os.path.join(HERE, 'prompt_v4.txt'),
    'v4-B（v4 把该虚的修清晰了时用）': os.path.join(HERE, 'prompt_v4B.txt'),
    'v3.3（上一版，偏保守）': os.path.join(HERE, 'prompt_v3.3.txt'),
}
PROMPT_DEFAULT = next(iter(PROMPT_VERSIONS))
HEADSWAP_VERSIONS = {                                         # ①页“修错 + 换头”：图片1 = MJ 图，图片2 = 角色参考图
    '换头 v1（修错 + 换头，基于 v4）': os.path.join(HERE, 'prompt_headswap.txt'),
}
HEADSWAP_DEFAULT = next(iter(HEADSWAP_VERSIONS))
HEADSWAP_NOTE = ('▸ Head replacement: these measurements describe @图片1\'s light, colour grade, focus, and grain — '
                 'render the new head inside them too. Only the main character\'s hair colour and facial features come '
                 'from @图片2; do not repaint them in the old head\'s hair or face colours listed above.')
CHARSWAP_VERSIONS = {                                         # ①页“修错 + 换整个角色”：图片1 = MJ 图，图片2 = 角色参考图（三视图 / 四视图）
    '换角色 v1（修错 + 换整个角色，基于 v4）': os.path.join(HERE, 'prompt_charswap.txt'),
}
CHARSWAP_DEFAULT = next(iter(CHARSWAP_VERSIONS))
CHARSWAP_NOTE = ('▸ Character replacement: these measurements describe @图片1\'s light, colour grade, focus, and grain — '
                 'render the new character inside them too. Only the main character\'s hair colour, skin tone, outfit, '
                 'and footwear come from @图片2; do not repaint them in the old character\'s hair, skin, or clothing colours '
                 'listed above.')
SWAP_KINDS = {                                                # 换头 / 换整个角色：(提示词版本, 默认版本, 末尾说明, 文件名后缀, 中文)
    'head': (HEADSWAP_VERSIONS, HEADSWAP_DEFAULT, HEADSWAP_NOTE, '_headswap', tr('修错 + 换头')),
    'person': (CHARSWAP_VERSIONS, CHARSWAP_DEFAULT, CHARSWAP_NOTE, '_charswap', tr('修错 + 换整个角色')),
}
STATE = os.path.join(OUT, '_state.json')                     # 预补偿图对应关系、工具产出图的 md5、服装描述
_DEFAULT_OUT = OUT
NAME_MAX = 60                                                # 输出文件名前缀最长字符数（超出部分换成哈希）
MJ_NAME = re.compile(r'([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_(\d)')
TOOL_OUTPUT = re.compile(r'(_(整图|风格)?还原(_\d+)?|_restored(_full)?(_\d+)?|_style_restored(_\d+)?|_compare|_mask'
                         r'|_bgmask|_区域对应(_\d+)?|_regions(_\d+)?|_远近分层(_\d+)?|_depth_layers(_\d+)?)$')  # 新旧名字都认
_STATE_LOCK = threading.RLock()                              # 后台任务和界面都会读写 _state.json


# ------------------------------------------------------------------ helpers
def ensure_dirs():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CALIB, exist_ok=True)


def migrate_state():
    """从 V4.8 以前升级：旧「输出」里的记录（服装描述、脸部明暗、预补偿 / 换头记录、工具产出图的 md5）复制到新的 Output，
    旧文件夹和里面的图片都不动。新记录已经有了就什么也不做。"""
    old = os.path.join(OLD_OUT, '_state.json')
    if OUT != _DEFAULT_OUT:          # 测试、脚本把输出改到别处时不接旧记录
        return
    if os.path.isfile(old) and not os.path.isfile(STATE) and os.path.normcase(OLD_OUT) != os.path.normcase(OUT):
        try:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            shutil.copy2(old, STATE)
        except OSError:
            pass


def short_name(path):
    """输出文件名前缀。MJ 长文件名 -> MJ_efa55fbe_1；其他文件保留完整文件名（不能用的字符换成 _）。
    太长时保留前面的部分，末尾换成原文件名的 6 位哈希，所以不同的图不会撞名、互相覆盖。"""
    b = os.path.splitext(os.path.basename(path))[0]
    m = MJ_NAME.search(b)
    s = f'MJ_{m.group(1)}_{m.group(2)}{b[m.end():]}' if m else b
    s = re.sub(r'[\\/:*?"<>|\s]+', '_', s)
    if len(s) > NAME_MAX:
        s = s[:NAME_MAX - 7] + '_' + hashlib.md5(b.encode('utf-8')).hexdigest()[:6]
    return s


def is_tool_output(path):
    """本工具自己产出的图（还原结果、对比图、改动区域图……），按文件名末尾判断。"""
    return bool(TOOL_OUTPUT.search(os.path.splitext(os.path.basename(path))[0]))


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def load_state(log=None):
    """读取记录；记录损坏（会改名留底）、来自别的电脑、或里面的图已不存在时，自动丢掉无效部分，不报错。"""
    with _STATE_LOCK:
        migrate_state()
        st = read_json(STATE, {}, warn=log)
    if not isinstance(st, dict):
        st = {}
    pc = st.get('precomp')
    st['precomp'] = {k: v for k, v in (pc.items() if isinstance(pc, dict) else ())
                     if isinstance(k, str) and isinstance(v, str) and os.path.isfile(k) and os.path.isfile(v)}
    if not isinstance(st.get('restored_md5'), list):
        st['restored_md5'] = []
    if not isinstance(st.get('cs_outfit', ''), str):
        st['cs_outfit'] = ''
    hs = st.get('headswap')         # MJ 图 -> 'head'（换头）/ 'person'（换整个角色）；V4.5 记的是 True = 换头
    st['headswap'] = {k: (v if v in SWAP_KINDS else 'head') for k, v in (hs.items() if isinstance(hs, dict) else ())
                      if isinstance(k, str) and os.path.isfile(k)}
    return st


def update_state(fn, log=None):
    """读 -> fn(state) 修改 -> 安全写回，整个过程加锁（避免后台任务和界面同时改，丢掉一方的修改）。"""
    with _STATE_LOCK:
        st = load_state(log)
        fn(st)
        ensure_dirs()
        write_json(STATE, st)
        return st


def register_output(path):
    """记下工具自己产出的图，以后被当成 GPT 输出加入标定时拒收。"""
    h = md5(path)

    def add(st):
        lst = st['restored_md5']
        if h not in lst:
            lst.append(h)
            del lst[:-2000]
    update_state(add)


def save_outfit(text):
    update_state(lambda st: st.__setitem__('cs_outfit', text))


def get_face_light():
    """②页「脸部明暗跟随 MJ」上次用的百分比（0～100，默认 100）。"""
    v = load_state().get('face_light', 100)
    return int(min(100, max(0, v))) if isinstance(v, (int, float)) else 100


def save_face_light(pct):
    update_state(lambda st: st.__setitem__('face_light', int(min(100, max(0, pct)))))


def copy_to_clipboard(text):
    import clipboard_win
    clipboard_win.set_text(text)


def open_path(p):
    if p and os.path.exists(p):
        os.startfile(p)


def reveal(p):
    if p and os.path.exists(p):
        subprocess.Popen(['explorer', '/select,', os.path.normpath(p)])


def image_size(p):
    """(width, height) as displayed, i.e. after the EXIF orientation (OpenCV applies it when reading)."""
    with Image.open(p) as im:
        w, h = im.size
        if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):
            w, h = h, w
    return w, h


# ------------------------------------------------------------------ 1. 宫格切分
def _find_split(gray, axis):
    n = gray.shape[axis]
    d = np.abs(np.diff(gray.astype(np.float32), axis=axis)).mean(1 - axis)
    lo, hi = int(n * 0.44), int(n * 0.56)
    seg = d[lo:hi]
    i = int(np.argmax(seg))
    return lo + i + 1 if seg[i] > 4 * np.median(d) else n // 2


def split_grid(path):
    """把 2×2 宫格图切成四张 PNG（无损）。返回 (四个文件路径：左上、右上、左下、右下, (分界 x, y))。"""
    ensure_dirs()
    img = imread_u(path)
    if img is None:
        raise InputError(tr('读不到图片：') + path)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    y, x = _find_split(g, 0), _find_split(g, 1)
    name = short_name(path)
    out = []
    for tag, c in (('cell1_top-left', img[:y, :x]), ('cell2_top-right', img[:y, x:]), ('cell3_bottom-left', img[y:, :x]),
                   ('cell4_bottom-right', img[y:, x:])):
        p = os.path.join(OUT, f'{name}_{tag}.png')
        imwrite_u(p, c)
        out.append(p)
    return out, (x, y)


# ------------------------------------------------------------------ 2. 测量 + 拼提示词
def measure(mj_path, precomp, log, version=None, headswap=False, swap=None):
    """返回 dict：prompt 文本、提示词文件、焦点图、要上传给 GPT 的图。出错时抛出 InputError。
    swap='head'（或 headswap=True）/ 'person'：基础提示词用换头版 / 换整个角色版（图片2 = 角色参考图），
    MEASURED LOOK 照常从 MJ 图测量，末尾加一句换头 / 换角色说明。"""
    swap = swap if swap in SWAP_KINDS else ('head' if headswap else None)
    ensure_dirs()
    bias = current_bias(log)
    name = short_name(mj_path)
    pc_path = os.path.join(OUT, f'{name}_precomp_upload_to_GPT.png') if precomp else None
    r = mj_measure.measure_file(mj_path, OUT, name, bias, pc_path, log)
    if swap:
        vers, dflt = SWAP_KINDS[swap][:2]
        pfile = vers.get(version) or vers[dflt]
    else:
        pfile = PROMPT_VERSIONS.get(version) or PROMPT_VERSIONS[PROMPT_DEFAULT]
    try:
        base = read_text(pfile).strip()
    except OSError as e:
        raise InputError(tr('读不到提示词模板 {v}：{e}', v=os.path.basename(pfile), e=e))
    block = r['block'] + ('\n' + SWAP_KINDS[swap][2] if swap else '')
    prompt = base + '\n\n' + block + '\n'
    pf = os.path.join(OUT, f'{name}_GPT_prompt' + (SWAP_KINDS[swap][3] if swap else '') + '.txt')
    write_text(pf, prompt)
    key = _norm(mj_path)

    def remember(st):
        if pc_path:
            st['precomp'][key] = pc_path
        else:
            st['precomp'].pop(key, None)
        if swap:
            st['headswap'][key] = swap
        else:
            st['headswap'].pop(key, None)
    update_state(remember, log)
    return dict(prompt=prompt, prompt_file=pf, focus=r['focus'], upload=pc_path or mj_path, name=name)


def swap_kind(mj_path):
    """这张 MJ 图最近一次在①页按哪种提示词生成：None = 只修错，'head' = 修错 + 换头，'person' = 修错 + 换整个角色
    （②页据此自动选好“GPT 这次做了什么”）。预补偿图按对应的 MJ 原图查。"""
    hs = load_state()['headswap']
    return hs.get(_norm(mj_path)) or hs.get(_norm(original_of_precomp(mj_path) or mj_path))


def is_headswap(mj_path):
    """换头或换整个角色（两者都不加入标定）。"""
    return bool(swap_kind(mj_path))


def original_of_precomp(path):
    """选成了预补偿图时，返回对应的 MJ 原图；否则 None。"""
    inv = {_norm(v): k for k, v in load_state()['precomp'].items()}
    orig = inv.get(_norm(path))
    return orig if orig and os.path.exists(orig) else None


# ------------------------------------------------------------------ 3. 还原
def restore(mj_path, gpt_path, mode, mask, log, size='gpt', swap=False, face_light=1.0):
    """成功：dict(out, compare, mask, F)。失败：dict(error='mismatch' | 'input', message)。
    输出文件已存在时自动加 _2、_3，不会覆盖以前的结果。"""
    ensure_dirs()
    tag = 'restored' if mode == 'composite' else 'restored_full'
    out = unique_path(OUT, short_name(gpt_path), f'_{tag}.png', ('_compare.jpg', '_mask.jpg'))
    try:
        res = mj_restore.restore_file(mj_path, gpt_path, out, mode, mask, size=size, debug=True, log=log, swap=swap,
                                      face_light=face_light)
    except mj_restore.PairMismatch as e:
        log(tr('\n[未还原] ') + str(e))
        return dict(error='mismatch', message=str(e))
    except InputError as e:
        log(tr('\n[出错] ') + str(e))
        return dict(error='input', message=str(e))
    try:
        register_output(out)
    except OSError:
        pass
    base = os.path.splitext(out)[0]
    return dict(out=out, compare=base + '_compare.jpg', mask=base + '_mask.jpg', F=res['F'])


def aspect_mismatch(a, b):
    (w1, h1), (w2, h2) = image_size(a), image_size(b)
    return abs((w1 / h1) / (w2 / h2) - 1)


# ------------------------------------------------------------------ 4. 只还原风格
def style_only(mj_path, gpt_path, strength, keep_black, bg_follow, log, kind='auto'):
    """kind: 'auto' / 'scene' / 'region' / 'character'（见 mj_style_only.KINDS）。"""
    r = mj_style_only.run(mj_path, gpt_path, strength, keep_black, log=log, bg_follow=bg_follow, kind=kind,
                          swap=swap_kind(mj_path) or False)
    try:
        register_output(r['out'])
    except OSError:
        pass
    return r


def preview_regions(mj_path, gpt_path, log, kind='auto'):
    return mj_style_only.preview_regions(mj_path, gpt_path, log=log, kind=kind)


# ------------------------------------------------------------------ 5. 标定
def _valid_list(v):
    return [p for p in v if isinstance(p, dict)] if isinstance(v, list) else []


def calib_base(log=None):
    """内置基础数据：[{id, gpt_md5, precomp, stats}]，随工具分发，不需要原图，不可单独删除。"""
    return [b for b in _valid_list(read_json(CALIB_BASE, [], warn=log)) if isinstance(b.get('stats'), dict)]


def calib_local(log=None):
    """本机自己加的组（calib/pairs.json），去掉已经在内置基础数据里的。"""
    base = {b.get('gpt_md5') for b in calib_base(log)}
    return [p for p in _valid_list(read_json(CALIB_LIST, [], warn=log)) if p.get('gpt_md5') not in base]


def _save_local(local):
    """安全写回 pairs.json；属于内置基础数据的旧条目原样保留（只是不再需要它们的图片）。"""
    base = {b.get('gpt_md5') for b in calib_base()}
    keep = [p for p in _valid_list(read_json(CALIB_LIST, [])) if p.get('gpt_md5') in base]
    write_json(CALIB_LIST, keep + local)


def calib_pairs(log=None):
    """标定页列表 = 内置基础数据 + 本机的组。"""
    out = [dict(id=b.get('id', 0), note=BASE_NOTE, precomp=b.get('precomp', False), gpt_md5=b.get('gpt_md5'), base=True)
           for b in calib_base(log)]
    return out + calib_local(log)


def _stats_current(s):
    return isinstance(s, dict) and s.get('version', 1) >= gpt_bias.STATS_VERSION


def _pair_stats(p, log=None, measure=True):
    """本机一组的数值统计。已存的统计是当前方法测的就直接用；不是（或没有）就从 calib 里的图片重测并存起来；
    图片已经不在时沿用旧数值。measure=False 时不重测（只用于判断是否需要重算）。"""
    s = p.get('stats')
    if _stats_current(s) or not measure:
        return s
    a, b = os.path.join(CALIB, p.get('input', '')), os.path.join(CALIB, p.get('gpt', ''))
    if os.path.isfile(a) and os.path.isfile(b):
        try:
            p['stats'] = gpt_bias.one_pair(a, b)
            return p['stats']
        except InputError as e:
            if log:
                log(tr('[跳过] 第 {v} 组的图片读不出来：{e}', v=p.get("id"), e=e))
    if s and log:
        log(tr('[提醒] 第 {v} 组是旧方法测的，图片已不在，沿用旧数值。', v=p.get("id")))
    elif not s and log:
        log(tr('[跳过] 第 {v} 组既没有数值统计也找不到图片。', v=p.get("id")))
    return s


def _all_stats(log=None, measure=True):
    base, local = calib_base(log), calib_local(log)
    before = [p.get('stats') for p in local]
    stats = [b['stats'] for b in base] + [s for s in (_pair_stats(p, log, measure) for p in local) if s]
    if measure and [p.get('stats') for p in local] != before:
        _save_local(local)
    return stats, len(base)


def calib_recompute(log):
    """内置基础数据的数值统计 + 本机每组的统计（旧方法 / 缺统计时从图片补测并存下），汇总写 gpt_bias.json。"""
    stats, n_base = _all_stats(log)
    if not stats:
        log(tr('还没有标定数据。'))
        return False
    log(tr('标定数据：{BASE_NOTE} {n_base} 组 + 本机 {v} 组', BASE_NOTE=BASE_NOTE, n_base=n_base, v=len(stats) - n_base))
    res = gpt_bias.summarize(stats)
    write_json(BIAS_JSON, res)
    gpt_bias.print_report(res, log)
    log(tr('[已保存] {BIAS_JSON}', BIAS_JSON=BIAS_JSON))
    return True


def current_bias(log):
    """gpt_bias.json；它和现在的标定数据对不上（升级后、内置数据更新、本机组有变化、文件损坏）时先自动重算。"""
    bias = mj_measure.load_bias(BIAS_JSON, log)
    stats, _ = _all_stats(measure=False)
    stale = any(not _stats_current(p.get('stats')) for p in calib_local())
    if stats and (bias is None or stale or bias.get('inputs_md5') != gpt_bias.stats_signature(stats)):
        log(tr('标定数据有变化，先重新汇总一次……'))
        if calib_recompute(lambda t: None):
            bias = mj_measure.load_bias(BIAS_JSON, log)
    return bias


def calib_add(mj_path, gpt_path, log, note='', F=None):
    """把一组加入标定：GPT 的参照是“当时交给 GPT 的那张图”（用了预补偿就是预补偿图）。
    拒收工具自己的还原结果、与参照完全相同的图、以及对不上的配对。
    F = 刚做完的还原里算好的对齐（同一组图，几何一样），给了就不再重复对齐和配对检查。"""
    ensure_dirs()
    st = load_state(log)
    ref = st['precomp'].get(_norm(mj_path), mj_path)
    if not os.path.exists(ref):
        ref = mj_path
    pairs = calib_pairs(log)
    h = md5(gpt_path)
    if any(p.get('gpt_md5') == h for p in pairs):
        log(tr('这张 GPT 输出已经在标定里了，跳过。'))
        return False
    name = os.path.basename(gpt_path)
    if is_tool_output(gpt_path) or h in st['restored_md5']:
        log(tr('[未加入标定] {name} 是本工具的产出，不是 GPT 原始输出；把它加进来会让统计误以为 GPT 没有偏差。', name=name))
        return False
    if h == md5(ref):
        log(tr('[未加入标定] GPT 输出和参照图是同一个文件。'))
        return False
    if swap_kind(mj_path):
        log(tr('[未加入标定] 这张 MJ 图是按“{v}”交给 GPT 的：人物整块换了，会干扰 GPT 偏色的统计。', v=SWAP_KINDS[swap_kind(mj_path)][4]))
        return False
    if F is None:
        m8, g8 = imread_u(ref), imread_u(gpt_path)
        if m8 is None or g8 is None:
            log(tr('[未加入标定] 读不到图片。'))
            return False
        q = mj_restore.pair_quality(m8, g8)
        if not q['ok']:
            log(tr('[未加入标定] ') + q['message'])
            return False
        F = q['F']
    n = max([p.get('id', 0) for p in pairs] + [0]) + 1
    ia = os.path.join(CALIB, f'pair_{n:02d}_input{os.path.splitext(ref)[1].lower()}')
    ib = os.path.join(CALIB, f'pair_{n:02d}_gpt{os.path.splitext(gpt_path)[1].lower()}')
    shutil.copyfile(ref, ia)       # 图片留一份在本机 calib（数值统计已经存下，删掉图片也不影响）
    shutil.copyfile(gpt_path, ib)
    p = dict(id=n, input=os.path.basename(ia), gpt=os.path.basename(ib), gpt_md5=h,
             source_mj=os.path.basename(mj_path), source_gpt=name, precomp=ref != mj_path, note=note)
    p['stats'] = gpt_bias.one_pair(ia, ib, F=F)                 # 立即存数值统计
    _save_local(calib_local(log) + [p])
    log(tr('已加入标定：第 {n} 组', n=n) + (tr('（参照用的是预补偿图）') if ref != mj_path else ''))
    return calib_recompute(log)


def calib_remove_last(log):
    local = calib_local(log)
    if not local:
        log(tr('没有本机加的组可移除；「{BASE_NOTE}」是随工具带的基础值，不能单独移除。', BASE_NOTE=BASE_NOTE))
        return False
    p = local.pop()
    for k in ('input', 'gpt'):
        try:
            os.remove(os.path.join(CALIB, p.get(k, '')))
        except OSError:
            pass
    _save_local(local)
    log(tr('已移除第 {v} 组。', v=p.get("id")))
    return calib_recompute(log)
