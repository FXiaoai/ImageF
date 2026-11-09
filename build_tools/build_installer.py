# -*- coding: utf-8 -*-
"""生成 Image F（原名 MJ 还原工具）的单文件安装程序（NSIS 3.11，免安装版，就在本文件夹里）。
用法：双击同目录的 build.bat，或  python build_installer.py
产物：工作区根目录  ImageF_V<版本>_Setup.exe（中英双语，安装时选语言）

打进安装包的文件 = 工作区里分发需要的文件（见 SHIP_ROOT / tools 规则），其中核心模块换成 compile_modules.py 编译好的 .pyd
（先在 build\stage 里拼出要装的文件，再交给 NSIS）。不含：
  tools\\calib（标定图片，同事用内置的 calib_base.json 即可）、__pycache__、日志、例子、输出、无用可删除、.workbuddy。
卸载程序只删除这份清单里的文件 + 运行时生成的缓存 / 日志，绝不整目录递归删除安装目录（防止同事把安装目录选成 D:\\ 时误删）。
"""
import hashlib
import os
import subprocess
import sys

VERSION = '4.9.1'
APP = 'Image F'
HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.abspath(os.path.join(HERE, '..'))                # 工作区根目录（本文件夹在工作区根目录下）
MAKENSIS = os.path.join(HERE, 'nsis-3.11', 'makensis.exe')
OUT_EXE = os.path.join(WS, f'ImageF_V{VERSION}_Setup.exe')
NSI = os.path.join(HERE, 'installer.nsi')

SHIP_ROOT = ['ImageF.pyw', 'ImageF.bat', 'Manual_zh-CN.html', 'Manual_en.html', 'LICENSE.txt', 'LICENSE.zh-CN.txt']
STAGE = os.path.join(HERE, 'build', 'stage')
TOOLS_SKIP_DIRS = {'calib', '__pycache__'}
TOOLS_SKIP_FILES = {'setup.log', 'setup.log.old', 'gui_error.log'}
KEEP_ON_UNINSTALL = {'tools\\gpt_bias.json'}                  # 同事自己加了标定时会更新它：选“保留”时不删
# 运行时才会生成的文件 / 文件夹（卸载时一并清掉）
RUNTIME_FILES = ['tools\\setup.log', 'tools\\setup.log.old', 'tools\\gui_error.log']
RUNTIME_DIRS = ['tools\\__pycache__', '__pycache__']


def collect():
    files = []
    for f in SHIP_ROOT:
        p = os.path.join(WS, f)
        if not os.path.isfile(p):
            raise SystemExit('缺少文件：' + p)
        files.append(f)
    tools = os.path.join(WS, 'tools')
    for root, dirs, names in os.walk(tools):
        rel = os.path.relpath(root, WS)
        if rel == 'tools':
            dirs[:] = [d for d in dirs if d not in TOOLS_SKIP_DIRS]
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for n in sorted(names):
            if n in TOOLS_SKIP_FILES or n.endswith('.pyc'):
                continue
            files.append(os.path.join(rel, n))
    need = ['tools\\launcher.pyw', 'tools\\mj_gui.pyw', 'tools\\bootstrap.ps1', 'tools\\runtime\\manifest.json',
            'tools\\depth_anything_v2_small_w16.onnx', 'tools\\face_detection_yunet_2023mar.onnx',
            'tools\\calib_base.json', 'tools\\ImageF.ico', 'tools\\prompt_v4.txt', 'tools\\prompt_headswap.txt', 'tools\\mj_head.py', 'tools\\prompt_charswap.txt',
            # 随工具带的第三方模型的许可声明（MIT / Apache-2.0 要求随软件附上），缺了不许打包
            'tools\\face_detection_yunet_LICENSE.txt', 'tools\\depth_anything_v2_LICENSE.txt', 'tools\\depth_anything_v2_NOTICE.txt',
            'LICENSE.txt', 'LICENSE.zh-CN.txt', 'tools\\THIRD_PARTY_NOTICES.txt', 'tools\\mj_app.py',
            'tools\\i18n.py', 'tools\\lang\\en.json', 'Manual_en.html', 'Manual_zh-CN.html']
    for n in need:
        if n not in files:
            raise SystemExit('打包清单里缺少关键文件：' + n)
    return files


def stage(files):
    """把要装的文件拼到 build\\stage：核心模块的 .py 换成编译好的 .pyd，其余原样复制。返回 stage 里的相对路径清单。"""
    import shutil
    import compile_modules
    pyd = compile_modules.main()
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    out = []
    for f in files:
        d, n = os.path.split(f)
        mod = n[:-3] if n.endswith('.py') else None
        if d == 'tools' and mod in pyd:
            rel = os.path.join('tools', os.path.basename(pyd[mod]))
            src = pyd[mod]
        else:
            rel, src = f, os.path.join(WS, f)
        dst = os.path.join(STAGE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        out.append(rel)
    miss = [m for m in pyd if os.path.join('tools', os.path.basename(pyd[m])) not in out]
    if miss:
        raise SystemExit('这些模块编译了但源码不在打包清单里：' + '、'.join(miss))
    return out, sorted(pyd)


def nsis_str(s):
    return s.replace('$', '$$').replace('"', '$\\"')


def main():
    files, compiled = stage(collect())
    import make_welcome
    make_welcome.make(VERSION)                              # 欢迎图上的版本号跟着改
    total = sum(os.path.getsize(os.path.join(STAGE, f)) for f in files)
    dirs = sorted({os.path.dirname(f) for f in files if os.path.dirname(f)}, key=lambda d: (-d.count('\\'), d))
    # ---------------- install section: group files by directory
    by_dir = {}
    for f in files:
        by_dir.setdefault(os.path.dirname(f), []).append(f)
    inst = []
    for d in sorted(by_dir, key=lambda d: (d.count('\\'), d)):
        inst.append(f'  SetOutPath "$INSTDIR{nsis_str(chr(92) + d) if d else ""}"')
        for f in by_dir[d]:
            inst.append(f'  File "{nsis_str(os.path.join(STAGE, f))}"')
    inst.append('  SetOutPath "$INSTDIR"')
    # 从源码版升级：同名的 .py 和旧的字节码缓存删掉（.pyd 优先加载，但旧源码留在电脑上没有意义，还可能和新版对不上）
    for m in compiled:
        inst.append(f'  Delete "$INSTDIR\\tools\\{m}.py"')
    inst.append('  RMDir /r "$INSTDIR\\tools\\__pycache__"')
    # ---------------- uninstall: exactly the shipped files
    un = []
    for f in files:
        if f in KEEP_ON_UNINSTALL:
            continue
        un.append(f'  Delete "$INSTDIR\\{nsis_str(f)}"')
    for m in compiled:                                       # 以前源码版装过的 .py（覆盖升级时已删，保险起见）
        un.append(f'  Delete "$INSTDIR\\tools\\{m}.py"')
    for f in RUNTIME_FILES:
        un.append(f'  Delete "$INSTDIR\\{nsis_str(f)}"')
    for d in RUNTIME_DIRS:
        un.append(f'  RMDir /r "$INSTDIR\\{nsis_str(d)}"')
    un_dirs = [f'  RMDir "$INSTDIR\\{nsis_str(d)}"' for d in dirs]
    lics = {}
    for key, name in (('EN', 'LICENSE.txt'), ('ZH', 'LICENSE.zh-CN.txt')):       # NSIS 许可页的文本用 UTF-16（带 BOM）
        lics[key] = os.path.join(HERE, 'build', f'LICENSE_{key}_utf16.txt')
        with open(lics[key], 'w', encoding='utf-16', newline='\r\n') as fh:
            fh.write(open(os.path.join(WS, name), encoding='utf-8-sig').read())
    tpl = open(os.path.join(HERE, 'installer_template.nsi'), encoding='utf-8').read()
    v4 = '.'.join((VERSION.split('.') + ['0'] * 4)[:4])           # VIProductVersion 必须是 4 段
    nsi = (tpl.replace('@@VERSION4@@', v4).replace('@@VERSION@@', VERSION)
              .replace('@@OUTFILE@@', nsis_str(OUT_EXE))
              .replace('@@ICON@@', nsis_str(os.path.join(WS, 'tools', 'ImageF.ico')))
              .replace('@@BITMAP@@', nsis_str(os.path.join(HERE, 'welcome.bmp')))
              .replace('@@SIZE_KB@@', str(total // 1024))
              .replace('@@LICENSE_EN@@', nsis_str(lics['EN'])).replace('@@LICENSE_ZH@@', nsis_str(lics['ZH']))
              .replace('@@INSTALL_FILES@@', '\n'.join(inst))
              .replace('@@UNINSTALL_FILES@@', '\n'.join(un))
              .replace('@@UNINSTALL_DIRS@@', '\n'.join(un_dirs)))
    with open(NSI, 'w', encoding='utf-8-sig') as f:       # NSIS 3 reads UTF-8 with BOM as Unicode
        f.write(nsi)
    print(f'清单：{len(files)} 个文件，{total / 2**20:.1f} MB')
    r = subprocess.run([MAKENSIS, '/V2', '/INPUTCHARSET', 'UTF8', NSI])
    if r.returncode != 0:
        raise SystemExit('makensis 失败')
    h = hashlib.sha256(open(OUT_EXE, 'rb').read()).hexdigest()
    with open(os.path.join(HERE, 'manifest_last_build.txt'), 'w', encoding='utf-8') as f:
        f.write(f'{os.path.basename(OUT_EXE)}  {os.path.getsize(OUT_EXE)} bytes  sha256 {h}\n')
        f.write('\n'.join(files) + '\n')
    print(f'完成：{OUT_EXE}  {os.path.getsize(OUT_EXE) / 2**20:.1f} MB  sha256 {h}')


if __name__ == '__main__':
    main()
