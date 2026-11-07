# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""把 tools 里的核心模块用 Nuitka 编译成 .pyd（机器码），给安装包用。源码本身不动。
用法：python compile_modules.py（build_installer.py 打包前会自动调用）
  · 编译结果在 build\\pyd\\，按源码内容的哈希缓存：源码没改的模块不会重新编译。
  · 第一次运行 Nuitka 会自动下载 MinGW 编译器（约 250 MB，放在 %LOCALAPPDATA%\\Nuitka）。
  · 编出来的 .pyd 只依赖 Windows 自带的 DLL 和 python310.dll（Python 3.10 的任何小版本都能用）。
不编译的：launcher.pyw（要先在任意 Python 版本下运行，检查环境、换到 3.10）、mj_gui.pyw（入口小壳）、selftest.py（自测）。"""
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.abspath(os.path.join(HERE, '..'))
TOOLS = os.path.join(WS, 'tools')
OUT = os.path.join(HERE, 'build', 'pyd')
CACHE = os.path.join(OUT, 'cache.json')
COMPILE = ['clipboard_win', 'gpt_bias', 'mj_app', 'mj_depth', 'mj_face', 'mj_head', 'mj_io', 'mj_measure', 'mj_region',
           'mj_restore', 'mj_scene', 'mj_style_only', 'mj_tool_core', 'ui_lumen']
SUFFIX = '.cp310-win_amd64.pyd'
FLAGS = ['--python-flag=no_docstrings',       # 说明文字（docstring）不带进 .pyd；代码里没有用到 __doc__ 的地方
         '--lto=no']                          # GCC 15 + 链接时优化会把 PyInit_xxx 导出函数丢掉，编出来的 .pyd 加载不了
NUITKA_VER = None


def find_py310():
    """本机的 Python 3.10（编译出来的 .pyd 只能给 3.10 用）：当前就是 3.10 就用它，否则用 py 启动器或默认安装位置找。"""
    if sys.version_info[:2] == (3, 10):
        return sys.executable
    try:
        r = subprocess.run(['py', '-3.10', '-c', 'import sys; print(sys.executable)'], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except OSError:
        pass
    p = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Python', 'Python310', 'python.exe')
    if os.path.isfile(p):
        return p
    raise SystemExit('找不到 Python 3.10：编译和打包需要 Python 3.10（64 位）。')


PY = find_py310()


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def nuitka_version():
    r = subprocess.run([PY, '-m', 'nuitka', '--version'], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('没装 Nuitka：' + PY + ' -m pip install nuitka ordered-set zstandard')
    return r.stdout.split()[0]


def one(name):
    src = os.path.join(TOOLS, name + '.py')
    tmp = tempfile.mkdtemp(prefix='nk_' + name + '_')
    try:
        shutil.copy2(src, tmp)
        t = time.time()
        env = dict(os.environ)
        gcc = sorted(glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Nuitka', 'Nuitka', 'Cache', 'download*', 'gcc',
                                            'x86_64', '*', 'mingw64', 'bin')))
        if gcc:          # Nuitka 自己找下载好的 MinGW 时，偶尔判断不出编译器架构而失败；放进 PATH 就稳定了
            env['PATH'] = gcc[-1] + os.pathsep + env.get('PATH', '')
        r = subprocess.run([PY, '-m', 'nuitka', '--mode=module', name + '.py', '--mingw64', '--assume-yes-for-downloads',
                            '--nofollow-imports', '--no-pyi-file', '--remove-output', '--output-dir=out', '--quiet', *FLAGS],
                           cwd=tmp, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        pyd = os.path.join(tmp, 'out', name + SUFFIX)
        if r.returncode != 0 or not os.path.isfile(pyd):
            return name, False, (r.stdout + r.stderr)[-3000:]
        shutil.copy2(pyd, os.path.join(OUT, name + SUFFIX))
        return name, True, f'{time.time() - t:.0f}s'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(log=print):
    os.makedirs(OUT, exist_ok=True)
    ver = nuitka_version() + ' ' + ' '.join(FLAGS)
    cache = {}
    if os.path.isfile(CACHE):
        try:
            cache = json.load(open(CACHE, encoding='utf-8'))
        except ValueError:
            cache = {}
    todo = []
    for n in COMPILE:
        h = sha(os.path.join(TOOLS, n + '.py'))
        if cache.get(n) == [h, ver] and os.path.isfile(os.path.join(OUT, n + SUFFIX)):
            continue
        todo.append((n, h))
    log(f'Nuitka {ver}：{len(COMPILE)} 个模块，{len(todo)} 个要重新编译' + ('（其余源码没改，用缓存）' if len(todo) < len(COMPILE) else ''))
    fails = []
    hs = dict(todo)

    def done(name, ok, info, last):
        if ok:
            cache[name] = [hs[name], ver]
            log(f'  编译好 {name}{SUFFIX}（{info}）')
            json.dump(cache, open(CACHE, 'w', encoding='utf-8'), indent=1)
        elif last:
            fails.append(name)
            log(f'  [失败] {name}\n{info}')
        else:
            retry.append(name)

    retry = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:        # 几个同时开始时，Nuitka 偶尔探测编译器版本会撞车：失败的再单独编一次
        futs = []
        for k, (n, _) in enumerate(todo):
            futs.append(ex.submit(lambda n=n, k=k: (time.sleep(min(k, 3) * 4), one(n))[1]))
        for f in futs:
            done(*f.result(), last=False)
    for n in retry:
        done(*one(n), last=True)
    for p in glob.glob(os.path.join(OUT, '*' + SUFFIX)):          # 不在清单里的旧模块删掉
        if os.path.basename(p)[:-len(SUFFIX)] not in COMPILE:
            os.remove(p)
    if fails:
        raise SystemExit('编译失败：' + '、'.join(fails))
    verify(log)
    return {n: os.path.join(OUT, n + SUFFIX) for n in COMPILE}


def verify(log=print):
    """在只有 .pyd 的临时目录里逐个 import，确认每个都是能加载的编译模块（不是源码、也不是坏的 .pyd）。"""
    tmp = tempfile.mkdtemp(prefix='nk_verify_')
    try:
        for n in COMPILE:
            shutil.copy2(os.path.join(OUT, n + SUFFIX), tmp)
        # 不编译、以源码分发的 i18n.py（和它读的英文表）也要在，编译模块 import 它
        shutil.copy2(os.path.join(TOOLS, 'i18n.py'), tmp)
        shutil.copytree(os.path.join(TOOLS, 'lang'), os.path.join(tmp, 'lang'))
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import importlib\n'
                'bad = []\n'
                'for n in sys.argv[2:]:\n'
                '    m = importlib.import_module(n)\n'
                '    if "__compiled__" not in dir(m): bad.append(n)\n'
                'print("BAD", bad) if bad else print("OK")')
        r = subprocess.run([PY, '-c', code, tmp, *COMPILE], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           cwd=tmp)
        if r.returncode != 0 or not r.stdout.strip().endswith('OK'):
            raise SystemExit('编译好的模块加载失败：\n' + (r.stdout + r.stderr)[-3000:])
        log(f'  {len(COMPILE)} 个 .pyd 都能正常加载（编译版）')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
