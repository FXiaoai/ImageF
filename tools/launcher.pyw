#! python3.10
# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""Image F（原名 MJ 还原工具）启动器：检查运行环境（numpy / OpenCV / Pillow），缺什么自动装什么，
安装时显示进度条，全部就绪后打开操作面板。只用 Python 标准库，所以在什么都没装时也能运行。

安装顺序：先用 tools/runtime/wheels 里的离线安装文件（与公司电脑实测版本相同，先校验哈希），
用不了（Python 版本不同、文件缺失或损坏）再联网，按响应速度选清华 / 阿里云 / 官方源。
日志：tools/setup.log

双击 .pyw 时 Windows 可能用别的 Python 版本打开（例如默认是 3.12）：这台电脑装有 Python 3.10 时会自动换到 3.10
重新启动（离线安装文件只适配 3.10）；没有 3.10 才用当前版本，缺组件时联网安装。

测试用环境变量（日常不用）：MJ_LAUNCHER_TRACE=文件（记录每个阶段与窗口位置）、
MJ_LAUNCHER_FORCE_ONLINE=1（跳过离线文件）、MJ_LAUNCHER_SELFTEST=图片路径（面板截图后自动关闭）。
"""
from i18n import tr
import ctypes
import hashlib
import importlib
import importlib.util
import json
import math
import os
import queue
import runpy
import site
import subprocess
import sys
import sysconfig
import threading
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
WHEELS = os.path.join(RUNTIME, 'wheels')
GUI = os.path.join(HERE, 'mj_gui.pyw')
LOG = os.path.join(HERE, 'setup.log')
NO_WINDOW = 0x08000000
TRACE = os.environ.get('MJ_LAUNCHER_TRACE')
FORCE_ONLINE = os.environ.get('MJ_LAUNCHER_FORCE_ONLINE') == '1'
WANT_PY = (3, 10)
PIP_TIMEOUT = 900                                   # 单个组件安装最多 15 分钟
CV2_NEEDS = ('DISOpticalFlow_create', 'findTransformECC', 'ORB_create', 'estimateAffinePartial2D')
NO_SUCH_VERSION = ('no matching distribution', 'could not find a version')   # pip：这个 Python 版本没有那一版


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2_000_000:
            os.replace(LOG, LOG + '.old')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('[%Y-%m-%d %H:%M:%S] ') + str(msg).rstrip() + '\n')
    except OSError:
        pass


def fatal_box(text):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, 'Image F', 0x10)
    except Exception:
        print(text, file=sys.stderr)


def find_py310():
    """An installed 64-bit Python 3.10 with tkinter (pythonw.exe when present), or None."""
    cands = []
    try:
        r = subprocess.run(['py', '-3.10', '-c', 'import sys; print(sys.executable)'], capture_output=True, text=True,
                           timeout=20, creationflags=NO_WINDOW)
        if r.returncode == 0 and r.stdout.strip():
            cands.append(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r'Software\Python\PythonCore\3.10\InstallPath', 0,
                                        winreg.KEY_READ | view) as k:
                        for name in ('ExecutablePath', ''):
                            try:
                                v = winreg.QueryValueEx(k, name)[0]
                            except OSError:
                                continue
                            cands.append(v if name else os.path.join(v, 'python.exe'))
                except OSError:
                    pass
    except ImportError:
        pass
    for base, rel in ((os.environ.get('LOCALAPPDATA'), r'Programs\Python\Python310\python.exe'),
                      (os.environ.get('ProgramFiles'), r'Python310\python.exe')):
        if base:
            cands.append(os.path.join(base, rel))
    probe = 'import sys, tkinter; sys.exit(0 if sys.version_info[:2] == (3, 10) and sys.maxsize > 2**32 else 3)'
    for c in dict.fromkeys(cands):
        try:
            if os.path.isfile(c) and subprocess.run([c, '-c', probe], timeout=60, creationflags=NO_WINDOW,
                                                    capture_output=True).returncode == 0:
                w = os.path.join(os.path.dirname(c), 'pythonw.exe')
                return w if os.path.isfile(w) else c
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def switch_to_py310():
    """当前不是 Python 3.10 时，找到 3.10 就用它重新启动本程序并返回 True；找不到返回 False（继续用当前版本）。"""
    if sys.version_info[:2] == WANT_PY or os.environ.get('MJ_LAUNCHER_REEXEC') == '1':
        return False
    py = find_py310()
    log(tr('当前是 Python {v}（{executable}）；', v=sys.version.split()[0], executable=sys.executable) + (tr('改用 Python 3.10：{py}', py=py) if py else
                                                                     tr('没找到 Python 3.10，继续用当前版本')))
    if not py:
        return False
    subprocess.Popen([py, os.path.abspath(__file__)] + sys.argv[1:], cwd=HERE,
                     env=dict(os.environ, MJ_LAUNCHER_REEXEC='1'))
    return True


if __name__ == '__main__' and switch_to_py310():
    sys.exit(0)

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:                                   # Python 装的时候没勾选界面组件
    log(tr('tkinter 不可用：') + traceback.format_exc())
    fatal_box(tr('这台电脑的 Python 缺少界面组件（tkinter），工具打不开。\n\n请改为双击文件夹里的「ImageF.bat」，它会自动安装一份完整的 Python 3.10。'))
    sys.exit(1)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 和操作面板保持一致，避免高分屏模糊
except Exception:
    pass

with open(os.path.join(RUNTIME, 'manifest.json'), encoding='utf-8') as _f:
    MANIFEST = json.load(_f)
PACKAGES = MANIFEST['packages']

# 在独立进程里检查：不把 numpy / OpenCV 加载进本进程，之后安装或修复时文件不会被占用
CHECK_CODE = ('\nimport json\nres = {}\ndef probe(key, code):\n    try:\n        ns = {}\n '
                '       exec(code, ns)\n        res[key] = {"ok": True, "version": str(ns.get("v", '
                '""))}\n    except BaseException as e:\n        res[key] = {"ok": False, '
                '"error": (type(e).__name__ + ": " + str(e))[:300]}\nprobe("numpy", "import '
                'numpy as m; v = m.__version__; m.zeros(3).sum()")\nprobe("cv2", "import '
                'cv2 as m; v = m.__version__\\n"\n             "for a in %r:\\n"\n         '
                '    "    assert hasattr(m, a), \'OpenCV 缺少 \' + a")\nprobe("PIL", "import '
                'PIL, PIL.Image, PIL.ImageTk; v = PIL.__version__")\nprint("MJCHECK" + json.dumps(res)'
                ')\n') % (CV2_NEEDS,)


def vtuple(s):
    out = []
    for part in str(s).replace('-', '.').split('.'):
        num = ''.join(ch for ch in part if ch.isdigit())
        if not num:
            break
        out.append(int(num))
    return tuple(out)


def console_python():
    d, b = os.path.split(sys.executable)
    if b.lower() == 'pythonw.exe' and os.path.exists(os.path.join(d, 'python.exe')):
        return os.path.join(d, 'python.exe')
    return sys.executable


def run_quiet(args, timeout=120):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, creationflags=NO_WINDOW, env=child_env())


def child_env():
    env = dict(os.environ)
    env.update(PYTHONIOENCODING='utf-8', PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1')
    return env


def check_env():
    """Returns {module: {'ok':bool,'version'/'error'}} measured in a separate process."""
    r = run_quiet([console_python(), '-c', CHECK_CODE], timeout=180)
    line = [l for l in r.stdout.splitlines() if l.startswith('MJCHECK')]
    if not line:
        raise RuntimeError(tr('环境检查没有返回结果：') + (r.stderr or r.stdout)[-400:])
    res = json.loads(line[-1][7:])
    for p in PACKAGES:
        st = res[p['module']]
        if st['ok'] and vtuple(st['version']) < vtuple(p['min']):
            st.update(ok=False, error=tr('版本 {version} 太旧（至少需要 {min}）', version=st["version"], min=p["min"]))
    return res


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def offline_usable():
    return (not FORCE_ONLINE and sys.version_info[:2] == tuple(int(x) for x in MANIFEST['wheels_python'].split('.'))
            and sysconfig.get_platform() == MANIFEST['wheels_platform'])


def rank_indexes():
    """Fastest-responding package index first; unreachable ones last."""
    timed = []
    for url in MANIFEST['indexes']:
        t = time.perf_counter()
        try:
            urllib.request.urlopen(url.rstrip('/') + '/pip/', timeout=5).read(256)
            timed.append((time.perf_counter() - t, url))
        except Exception as e:
            log(tr('镜像不可用 {url}: {e}', url=url, e=e))
            timed.append((99.0, url))
    return [u for _, u in sorted(timed)], any(t < 99.0 for t, _ in timed)


# ---------------------------------------------------------------- window
class Launcher:
    def __init__(self, root, repair):
        self.root, self.repair = root, repair
        self.k = root.winfo_fpixels('1i') / 96.0
        self.q = queue.Queue()
        self.state = 'busy'
        self.seg = (0.0, 0.0, 1.0, time.perf_counter())   # from, to, expected seconds, start
        self.value = 0.0
        root.title(MANIFEST['ui']['title'])
        try:
            root.iconbitmap(default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ImageF.ico'))
        except tk.TclError:
            pass
        root.resizable(False, False)
        st = ttk.Style()
        if 'vista' in st.theme_names():
            st.theme_use('vista')
        f = ttk.Frame(root, padding=self.px(18))
        f.pack(fill='both', expand=True)
        self.title = ttk.Label(f, text=tr('正在启动 Image F……'), font=('Microsoft YaHei UI', 12, 'bold'))
        self.title.pack(anchor='w')
        self.status = ttk.Label(f, text=tr('正在检查运行环境……'), font=('Microsoft YaHei UI', 10),
                                wraplength=self.px(500), justify='left')
        self.status.pack(anchor='w', pady=(self.px(8), self.px(6)))
        row = ttk.Frame(f)
        row.pack(fill='x')
        self.bar = ttk.Progressbar(row, mode='indeterminate', length=self.px(450), maximum=100)
        self.bar.pack(side='left')
        self.pct = ttk.Label(row, text='', width=5, anchor='e', font=('Microsoft YaHei UI', 10))
        self.pct.pack(side='left', padx=(self.px(8), 0))
        self.detail = ttk.Label(f, text='', foreground='#777777', font=('Microsoft YaHei UI', 9),
                                wraplength=self.px(500), justify='left')
        self.detail.pack(anchor='w', pady=(self.px(6), 0))
        self.btns = ttk.Frame(f)
        self.btns.pack(anchor='e', pady=(self.px(10), 0))
        self.bar.start(12)
        root.update_idletasks()
        w, h = self.px(560), root.winfo_reqheight()
        root.geometry(f'{w}x{max(h, self.px(170))}+{(root.winfo_screenwidth() - w) // 2}+'
                      f'{(root.winfo_screenheight() - h) // 3}')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(80, self.poll)
        self.start()

    def px(self, v):
        return int(v * self.k)

    # ---------------- worker -> UI
    def post(self, **kw):
        self.q.put(kw)

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if 'status' in m:
                    self.status.configure(text=m['status'])
                if 'detail' in m:
                    self.detail.configure(text=m['detail'])
                if 'title' in m:
                    self.title.configure(text=m['title'])
                if 'segment' in m:                      # (from %, to %, expected seconds)
                    a, b, sec = m['segment']
                    if str(self.bar.cget('mode')) != 'determinate':
                        self.bar.stop()
                        self.bar.configure(mode='determinate')
                    self.seg = (max(a, self.value), b, max(sec, 0.5), time.perf_counter())
                if 'set' in m:                          # 进度只增不减
                    self.value = max(self.value, m['set'])
                    self.seg = (self.value, self.value, 1.0, time.perf_counter())
                if m.get('final'):
                    self.finish(m['final'], m.get('error', ''))
                self.trace()
        except queue.Empty:
            pass
        if str(self.bar.cget('mode')) == 'determinate':
            a, b, sec, t0 = self.seg
            frac = 1 - math.exp(-2.2 * (time.perf_counter() - t0) / sec)    # eases toward 95 % of the step
            self.value = max(self.value, a + (b - a) * 0.95 * frac)
            self.bar['value'] = self.value
            self.pct.configure(text=f'{int(self.value)}%')
        if self.state == 'busy':
            self.root.after(80, self.poll)

    def trace(self):
        if not TRACE:
            return
        try:
            r = self.root
            with open(TRACE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(dict(t=time.time(), status=self.status.cget('text'), title=self.title.cget('text'),
                                        detail=self.detail.cget('text'), value=round(self.value, 1),
                                        geom=[r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height()]),
                                   ensure_ascii=False) + '\n')
        except Exception:
            pass

    # ---------------- flow
    def start(self):
        for w in self.btns.winfo_children():
            w.destroy()
        self.state = 'busy'
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        try:
            log(tr('启动：Python {v} {v2} @ {executable}；修复模式={repair}', v=sys.version.split()[0], v2=sysconfig.get_platform(), executable=sys.executable, repair=self.repair))
            res = check_env()
            need = [p for p in PACKAGES if not res[p['module']]['ok']]
            if self.repair and not need:              # 本进程加载失败但单独检查又正常：全部重装一遍
                need = list(PACKAGES)
            for p in PACKAGES:
                log(f'  {p["module"]}: {res[p["module"]]}')
            if not need:
                self.post(final='ready')
                return
            names = tr('、').join(p['label'].split('（')[0] for p in need)
            self.cur = 5.0                            # 进度由后台线程自己记账：检查 5% / pip 5% / 安装 82% / 确认 7%
            self.post(title=tr('第一次使用，正在自动安装所需组件'), set=self.cur,
                      status=tr('缺少 {names}，正在自动安装（只需要一次，之后双击直接打开）', names=names))
            self.install(need, res)
            self.post(status=tr('正在确认安装结果……'), segment=(92, 99, 3))
            res = check_env()
            bad = [p for p in PACKAGES if not res[p['module']]['ok']]
            if bad:
                raise RuntimeError(tr('装完以后仍无法使用：') + tr('；').join(f'{p["label"]} {res[p["module"]]["error"]}' for p in bad))
            log(tr('全部组件就绪'))
            self.post(set=100.0, status=tr('全部就绪，正在打开操作面板……'), detail='', final='ready')
        except Exception as e:
            log(tr('失败：') + traceback.format_exc())
            self.post(final='error', error=str(e))

    def ensure_pip(self, py):
        if run_quiet([py, '-m', 'pip', '--version']).returncode == 0:
            return
        self.post(status=tr('正在准备安装工具 pip……'), segment=(self.cur, self.cur + 5, 15))
        r = run_quiet([py, '-m', 'ensurepip', '--upgrade', '--default-pip'], timeout=300)
        log('ensurepip: ' + (r.stdout + r.stderr)[-800:])
        if run_quiet([py, '-m', 'pip', '--version']).returncode != 0:
            raise RuntimeError(tr('这台电脑的 Python 没有安装工具 pip，自动补装也没成功。'))
        self.cur += 5
        self.post(set=self.cur)

    def install(self, need, res):
        py = console_python()
        self.ensure_pip(py)
        offline = offline_usable()
        log(tr('离线安装文件可用：{offline}', offline=offline))
        indexes = None
        total = sum(p['mb'] for p in need)
        lo = start = self.cur
        for i, p in enumerate(need):
            hi = lo + (92 - start) * p['mb'] / total      # 按文件大小分配，三个库合计走到 92%
            attempts = []
            whl = os.path.join(WHEELS, p['wheel'])
            if offline and os.path.exists(whl):
                if sha256(whl) == p['sha256']:
                    attempts.append((tr('离线安装文件'), ['--no-index', '--find-links', WHEELS, f'{p["pip"]}=={p["pin"]}'],
                                     2 + p['mb'] * 0.2))
                else:
                    log(tr('离线文件校验不通过，改为联网：{whl}', whl=whl))
            attempts.append((tr('联网'), None, 6 + p['mb'] * 0.8))       # 离线不行时的后备
            st = res[p['module']]
            # 已经装了但坏了 / 太旧 -> 强制重装；完全没装 -> 正常安装
            force = [] if str(st.get('error', '')).startswith('ModuleNotFoundError') and not self.repair \
                else ['--force-reinstall']
            err = ''
            for how, extra, sec in attempts:
                if extra is None:
                    if indexes is None:
                        self.post(detail=tr('正在选择最快的下载源……'))
                        indexes, reachable = rank_indexes()
                        if not reachable:
                            raise RuntimeError(tr('需要联网下载，但连不上任何下载源（清华 / 阿里云 / 官方）。请确认网络正常后点「重试」。'))
                    ok = False
                    for idx in indexes:
                        host = idx.split('/')[2]
                        self.post(status=tr('正在联网安装 {label}（{v}/{n}，来源 {host}）', label=p["label"], v=i + 1, n=len(need), host=host),
                                  segment=(lo, hi, sec))
                        net = ['-i', idx, '--timeout', '20', '--retries', '1']
                        # 先装和实测环境相同的版本；这个 Python 版本没有那一版时，才装满足最低要求的版本
                        ok, err = self.pip(py, net + [f'{p["pip"]}=={p["pin"]}'] + force)
                        if not ok and any(x in err.lower() for x in NO_SUCH_VERSION):
                            ok, err = self.pip(py, net + [f'{p["pip"]}>={p["min"]}'] + force)
                        if ok:
                            break
                    if ok:
                        break
                else:
                    self.post(status=tr('正在安装 {label}（{v}/{n}）', label=p["label"], v=i + 1, n=len(need)), segment=(lo, hi, sec))
                    ok, err = self.pip(py, extra + force)
                    if ok:
                        break
            else:
                raise RuntimeError(tr('{label} 安装失败。{err}', label=p["label"], err=err))
            self.post(set=hi, detail='')
            lo = self.cur = hi

    def pip(self, py, args):
        cmd = [py, '-m', 'pip', 'install', '--only-binary=:all:', '--no-warn-script-location',
               '--disable-pip-version-check'] + args
        log(tr('执行：') + ' '.join(cmd))
        tail = []
        try:
            pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                  errors='replace', creationflags=NO_WINDOW, env=child_env())
        except OSError as e:
            return False, str(e)
        timed_out = threading.Event()

        def watchdog():                              # pip 卡住不输出时也能按时停止
            timed_out.set()
            pr.kill()
        timer = threading.Timer(PIP_TIMEOUT, watchdog)
        timer.daemon = True
        timer.start()
        try:
            for line in pr.stdout:
                line = line.strip()
                if not line:
                    continue
                log('  pip| ' + line)
                tail = (tail + [line])[-6:]
                if line.lower().startswith(('collecting', 'downloading', 'processing', 'installing', 'successfully',
                                            'requirement')):
                    self.post(detail=line[:150])
            pr.wait()
        finally:
            timer.cancel()
        if timed_out.is_set():
            return False, tr('安装超过 {v} 分钟没有完成，已停止。', v=PIP_TIMEOUT // 60)
        if pr.returncode == 0:
            return True, ''
        msg = next((l for l in reversed(tail) if 'error' in l.lower()), tail[-1] if tail else '')
        return False, msg[:300]

    # ---------------- end states
    def finish(self, kind, error):
        if kind == 'ready':
            self.state = 'ready'
            self.bar.stop()
            if str(self.bar.cget('mode')) == 'determinate':
                self.bar['value'] = 100
                self.pct.configure(text='100%')
            self.trace()
            self.root.after(450, self.root.destroy)
            return
        self.state = 'error'
        self.bar.stop()
        self.title.configure(text=tr('自动安装没有完成'), foreground='#B00020')
        self.status.configure(text=error[:400])
        self.detail.configure(text=tr('常见原因：网络不通，或安全软件拦截。可以点「重试」；还不行就把日志发给我。\n日志：') + LOG)
        ttk.Button(self.btns, text=tr('打开日志'),
                   command=lambda: os.path.exists(LOG) and os.startfile(LOG)).pack(side='left', padx=4)
        ttk.Button(self.btns, text=tr('重试'), command=self.start_retry).pack(side='left', padx=4)
        ttk.Button(self.btns, text=tr('关闭'), command=self.close).pack(side='left', padx=4)
        self.root.update_idletasks()                    # 窗口按内容长高，按钮不会被挡住
        self.root.geometry(f'{self.root.winfo_width()}x{self.root.winfo_reqheight()}')
        self.root.update()
        self.trace()

    def start_retry(self):
        self.title.configure(text=tr('正在重试……'), foreground='')
        self.bar.configure(mode='indeterminate')
        self.bar.start(12)
        self.value = 0.0
        self.pct.configure(text='')
        self.start()
        self.root.after(80, self.poll)

    def close(self):
        self.state = 'closed'
        self.root.destroy()


# ---------------------------------------------------------------- start-up
def quick_ready():
    """Normal start: everything installed -> import here and open the panel without extra delay.
    Returns 'ok', 'missing' (nothing loaded yet, safe to install in this process) or 'broken'."""
    if any(importlib.util.find_spec(m) is None for m in ('numpy', 'cv2', 'PIL')):
        return 'missing'
    try:
        import numpy
        import cv2
        import PIL.Image
        import PIL.ImageTk  # noqa: F401
        for p in PACKAGES:
            mod = {'numpy': numpy, 'cv2': cv2, 'PIL': PIL}[p['module']]
            if vtuple(mod.__version__) < vtuple(p['min']):
                raise ImportError(tr('{module} {version__} 太旧', module=p["module"], version__=mod.__version__))
        for a in CV2_NEEDS:
            if not hasattr(cv2, a):
                raise ImportError(tr('OpenCV 缺少 ') + a)
        return 'ok'
    except Exception:
        log(tr('组件无法正常加载，转入修复：') + traceback.format_exc())
        return 'broken'


def open_panel(argv):
    importlib.invalidate_caches()
    try:
        us = site.getusersitepackages()
        if os.path.isdir(us) and us not in sys.path:
            site.addsitedir(us)
    except Exception:
        pass
    sys.path.insert(0, HERE)
    os.chdir(HERE)
    sys.argv = [GUI] + argv
    runpy.run_path(GUI, run_name='__main__')


def main():
    args = sys.argv[1:]
    repair = '--repair' in args
    args = [a for a in args if a != '--repair']
    if os.environ.get('MJ_LAUNCHER_SELFTEST') and '--selftest' not in args:   # 测试用：面板截图后自动关闭
        args += ['--selftest', os.environ['MJ_LAUNCHER_SELFTEST']]
    if not repair:
        state = quick_ready()
        if state == 'ok':
            open_panel(args)
            return
        if state == 'broken':                     # 本进程已加载了部分文件，换一个干净进程来修复
            subprocess.Popen([sys.executable, os.path.abspath(__file__), '--repair'] + args, cwd=HERE)
            return
    root = tk.Tk()
    app = Launcher(root, repair)
    root.mainloop()
    if app.state == 'ready':
        open_panel(args)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log(tr('启动器异常：') + traceback.format_exc())
        fatal_box(tr('启动时出错，详情已写入日志：\n') + LOG)
