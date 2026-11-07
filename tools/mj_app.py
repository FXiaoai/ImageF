# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""Image F（原名 MJ 还原工具）的图形界面。入口是同目录的 mj_gui.pyw（launcher.pyw 用 pythonw 打开它），
安装包里这个模块是编译好的 mj_app.pyd。
V4.7 界面改版（照「设计稿/Image F 界面改版_静态布局稿.html」）：左侧导航；每页同一套骨架——页头一句话、左边图片、
右边设置面板（主按钮固定在面板最底部）、下方结果（操作在标题栏右侧、图例在下方一行）；运行记录收进底部状态栏。
只改界面和交互，测量 / 还原 / 标定 / 只还原风格 / 角色设定图的处理和输出文件都没动。"""
import i18n
from i18n import tr
import ctypes
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
ERR_LOG = os.path.join(HERE, 'gui_error.log')
APP = 'Image F'
VERSION = '4.9'
ICON = 'ImageF.ico'                    # 工具图标（V4.6.1 起换了文件名：Windows 按文件路径缓存图标，同名换内容不会刷新）
_ROOT = os.path.dirname(HERE)


def _pick(*names):
    """按当前语言选文件：第一个存在的；都不存在时返回第一个（提示“找不到”时显示它）。"""
    paths = [os.path.join(_ROOT, n) for n in names]
    return next((p for p in paths if os.path.isfile(p)), paths[0])


MANUAL = _pick('Manual_en.html', 'Manual_zh-CN.html') if i18n.is_en() else _pick('Manual_zh-CN.html', 'Manual_en.html')
LICENSE = _pick('LICENSE.txt') if i18n.is_en() else _pick('LICENSE.zh-CN.txt', 'LICENSE.txt')
THIRD_PARTY = os.path.join(HERE, 'THIRD_PARTY_NOTICES.txt')
AUTHOR = '老F'                          # Image F 的构思与设计者（署名，见 LICENSE.txt 里的 Required Notice；中英文都写老F）
LICENSE_NAME = 'PolyForm Noncommercial 1.0.0'


def _write_err(text, mode='a'):
    try:
        with open(ERR_LOG, mode, encoding='utf-8') as f:
            f.write(text + '\n')
    except OSError:
        pass


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

try:
    from PIL import Image, ImageOps, ImageTk
    import mj_tool_core as core
    import ui_lumen as ui
    from mj_io import InputError
except Exception:
    _write_err(traceback.format_exc(), 'w')
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(APP, tr('启动失败，缺少依赖或文件损坏。\n详情见：') + ERR_LOG)
    sys.exit(1)

IMG_TYPES = [(tr('图片'), '*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff'), (tr('所有文件'), '*.*')]


def nb(text):
    """会自动换行的中文说明：空格换成不换行空格。Tk 只在空格处换行，“提示词 A。多出几张……”会在 A 前面断开，留下很短的一行。
    英文界面不换（英文要在空格处换行）。"""
    return (text or '') if i18n.is_en() else (text or '').replace(' ', '\u00a0')

NAV = (('1', tr('生成提示词'), tr('交给 GPT 之前')), ('2', tr('还原'), tr('GPT 出图之后')), ('3', tr('标定'), tr('越用越准，一般自动')),
       ('4', tr('只还原风格'), tr('构图不同时')), ('5', tr('角色设定图'), tr('正面头像 → 四视图')))

HELP = (
    tr('1. 左边放 MJ 原图（MJ 网页下载的 PNG；2×2 宫格图先点「宫格图？切成四格」，再选要修的那一格）。\n2. 右边选这次要做什么：'
       '只修错 / 修错 + 换头 / 修错 + 换整个角色；换头、换角色时再放一张角色参考图（= @图片2）。\n3. 点「测量并生成提示词」：提示词 '
       '= 所选版本的通用提示词 + 末尾从 MJ 原图测出的 MEASURED LOOK，自动复制到剪贴板。\n4. 按下方「下一步」去 GPT 出图，'
       '下载 PNG 后到「2 还原」。'),
    tr('1. MJ 原图（「1 生成提示词」测量过会自动带过来）+ GPT 输出（下载的 PNG，别用截图）；蒙版一般不用。\n2. 「GPT 这次」按 '
       '1 页的记录自动选好。换了头 / 整个角色时：长相、服装按 GPT，发色、肤色、唇色和柔度按 MJ 原来的人还原，结果不加入标定。\n3. 「脸部明暗跟随 '
       'MJ」：0 = 保持 GPT 新脸自己的明暗，100 = 和 MJ 原来那个人的脸一样亮；脸上原有的受光 / 背光起伏都保留。\n4. 还原方式：'
       'GPT 改动少时选「只替换改过的地方」（MJ 原像素最多，GPT 外扩的边也保留）；改动多时选「整图迁移风格」（清晰度最高）。'),
    tr('工具把每一组「交给 GPT 的图 + GPT 的输出」记下来，统计 GPT 每次固定会怎么偏，比如中间调总往蓝偏、颗粒总变少、清晰度总变高。'
       '只有 ≥80% 的组方向一致、幅度够大的偏差，才会用来写提示词里的防漂移语句和生成预补偿图。\n组数越多越准，建议本机攒到 5 组以上。在「2 '
       '还原」里打开「自动加入标定」，每还原一组就会自动加进来，不用来这里手动操作。'),
    tr('GPT 图和 MJ 图构图、长宽、内容不同时用（例如按 MJ 照片做的四视图、白底设定图、同一场景重画、不同取景）。\n「图片类型」默认自动判断，'
       '判断结果写在运行记录第一行。\n背景（白底或纯色 / 渐变底）默认不动（同一场景重画时整幅一起调）；打开「背景也跟随 MJ」才改背景色。\n结果保存在「Output\\style_onl'
       'y」，文件名加「_style_restored」，尺寸和 GPT 图一样，同名时自动加 _2、_3。'),
    tr('全身图上脸还有五官时，把 B 里的 “smooth, blank, featureless surface” 换成 “completely '
       'blank face, no facial features at all”。\n用无脸四视图去生成视频时，要说明脸以左侧头像为准。'),
)


class FitView:
    """预览图：按框的实际大小缩放，窗口变大 / 变小时自动重画，图片总是完整显示（不会被裁掉）。
    用 Canvas 画，图片大小不影响布局（ttk.Label 放大图会把自己撑大，挤掉别的控件或被裁掉）。"""

    def __init__(self, parent, text, k=1.0, min_h=120, retile3=False):
        self.canvas = tk.Canvas(parent, bg=ui.SUNKEN, highlightthickness=0, height=int(min_h * k), width=int(200 * k))
        self.text, self.path, self.ph, self._size, self._after = text, None, None, None, None
        self.retile3, self._src = retile3, (None, None)
        self.mode, self.msg, self._t0, self._frame, self._anim = 'empty', '', 0.0, 0, None
        self.canvas.bind('<Configure>', lambda e: self._schedule())

    def _image(self, w, h):
        """retile3：②页的对比图（横图时 MJ / GPT / 结果上下排成三行）在又宽又矮的显示区里改成左右并排显示，
        能放大不少；只影响显示，对比图文件本身不变。"""
        key = (self.path, os.path.getmtime(self.path))
        if self._src[0] != key:
            with Image.open(self.path) as src:
                im = ImageOps.exif_transpose(src)
                im.load()
            self._src = (key, im)
        im = self._src[1]
        W, H = im.size
        t = (H - 12) / 3
        if self.retile3 and H > W and t > 0 and abs(t - round(t)) < 1e-6:
            t = int(round(t))
            if min(w / (3 * W + 12), h / t) > min(w / W, h / H):
                row = Image.new(im.mode, (3 * W + 12, t), 'white')
                for i in range(3):
                    row.paste(im.crop((0, i * (t + 6), W, i * (t + 6) + t)), (i * (W + 6), 0))
                im = row
        im = im.copy()
        im.thumbnail((w, h))
        return im

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    # 状态：empty（还没有结果）/ image（显示结果图）/ busy（处理中：转圈 + 说明 + 已用秒数）/ msg（没完成时的说明）
    def set(self, path):
        self._stop()
        self.path = path
        self.mode = 'image' if path else 'empty'
        self._size = None
        self._schedule(1)

    def busy(self, text):
        """开始处理：结果框里显示“正在……”和已用时间，直到 set() 放上新结果或 message() 说明没完成。"""
        self._stop()
        self.mode, self.msg, self._t0, self._frame = 'busy', text, time.time(), 0
        self._size = None
        self._draw()
        self._anim = self.canvas.after(80, self._tick)

    def message(self, text):
        self._stop()
        self.mode, self.msg = 'msg', text
        self._size = None
        self._schedule(1)

    @property
    def is_busy(self):
        return self.mode == 'busy'

    def _stop(self):
        if self._anim:
            try:
                self.canvas.after_cancel(self._anim)
            except tk.TclError:
                pass
            self._anim = None

    def _tick(self):
        self._anim = None
        if self.mode != 'busy':
            return
        self._frame = (self._frame + 1) % ui.SPIN_N
        c = self.canvas
        c.itemconfigure('spin', image=ui.spinner(ui.px(34), self._frame, ui.SUNKEN))
        c.itemconfigure('elapsed', text=tr('已用 {v} 秒', v=int(time.time() - self._t0)))
        self._anim = c.after(80, self._tick)

    def _schedule(self, delay=60):
        if self._after:
            self.canvas.after_cancel(self._after)
        self._after = self.canvas.after(delay, self._draw)

    def _draw(self):
        self._after = None
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10 or h < 10 or self._size == (w, h):
            return
        self._size = (w, h)
        c.delete('all')
        if self.mode == 'busy':
            D = ui.px(34)
            cy = h // 2 - ui.px(26)
            c.create_image(w // 2, cy, image=ui.spinner(D, self._frame, ui.SUNKEN), tags=('spin',))
            c.create_text(w // 2, cy + D // 2 + ui.px(14), text=self.msg, fill=ui.FG, font=ui.F(13.5, 'bold'),
                          anchor='n', justify='center', width=max(ui.px(120), w - ui.px(60)))
            c.create_text(w // 2, cy + D // 2 + ui.px(44), text=tr('已用 {v} 秒', v=int(time.time() - self._t0)), fill=ui.MUTED,
                          font=ui.F(12), anchor='n', tags=('elapsed',))
            return
        if self.mode == 'msg':
            c.create_text(w // 2, h // 2, text=self.msg, fill=ui.REQ, font=ui.F(13), justify='center',
                          width=max(ui.px(120), w - ui.px(60)))
            return
        if not self.path:
            c.create_text(w // 2, h // 2, text=self.text, fill=ui.MUTED, font=ui.F(12.5))
            return
        m = ui.px(10)
        try:
            self.ph = ImageTk.PhotoImage(self._image(max(1, w - 2 * m), max(1, h - 2 * m)))
            c.create_image(w // 2, h // 2, image=self.ph)
        except Exception as e:
            c.create_text(w // 2, h // 2, text=tr('（预览失败：{e}）', e=e), fill=ui.MUTED, font=ui.F(12.5), width=w - 20)


def open_preview(path, box):
    """PIL thumbnail in display orientation (EXIF rotation applied, like OpenCV does when processing)."""
    with Image.open(path) as src:          # 关闭文件句柄，否则 Windows 上同名文件下次无法覆盖
        im = ImageOps.exif_transpose(src)
        im.thumbnail(box)
    return im


class Pages:
    """兼容旧代码 / 测试脚本里的 self.nb.select(页面或序号)（V4.7 起页签换成了左侧导航）。"""

    def __init__(self, app):
        self.app = app

    def select(self, x=None):
        if x is None:
            return str(self.app.pages[self.app.cur])
        self.app.show_page(x if isinstance(x, int) else self.app.pages.index(x))

    def index(self, what='current'):
        return self.app.cur


class App:
    TASK_HINTS = dict(fix=tr('找出并修好图里的错误，其余保持 MJ 原样。'),
                      head=tr('把主角的头换成 @图片2 里的头，其余照常修错。'),
                      person=tr('头、身体、服装、鞋都换成 @图片2 里的角色，姿势、光线、构图不变。'))
    CHAR_HINTS = dict(fix='', head=tr('最好用 5 页做的正面头像或四视图'), person=tr('三视图 / 四视图，最好带全身和鞋'))
    KIND_HINTS = dict(auto=tr('判断结果写在运行记录第一行。'), scene=tr('按远近分层调色（要估远近，约半分钟）。'),
                      region=tr('按区域对应：MJ 里对应区域的颜色和质感给到 GPT 图。'), character=tr('按区域对应 + 嘴唇单独配色。'))
    PROMPT_PH = tr('测量后，完整提示词显示在这里（同时自动复制到剪贴板）。')
    OUTFIT_PH = tr('例如：黑色高领毛衣，深灰阔腿西裤，白色运动鞋……（中英文都可以）')

    def __init__(self, root):
        self.root = root
        self.k = root.winfo_fpixels('1i') / 96.0
        root.title(tr('Image F —— 用 GPT 修错，再把 MJ 的色彩、虚化、颗粒拉回来\u3000·\u3000{AUTHOR} 设计', AUTHOR=AUTHOR))
        try:                                   # 窗口和任务栏图标（default= 让弹出的小窗口也用它）
            root.iconbitmap(default=os.path.join(HERE, ICON))
        except tk.TclError:
            pass
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = min(int(1440 * self.k), sw - int(40 * self.k))          # 默认开大一些（焦点图、对比图能完整显示）；
        h = min(int(1080 * self.k), sh - int(90 * self.k))          # 屏幕小时留出任务栏和标题栏
        root.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h - int(50 * self.k)) // 2)}')
        root.minsize(min(int(1280 * self.k), w), min(int(780 * self.k), h))
        ui.apply(root, self.k)
        self.zones = []

        self.q = queue.Queue()
        self.busy = False
        self._view = None
        self.action_buttons = []
        self.needs = []                                # (按钮, 缺什么(), 按钮下方的提示, 平时的提示)
        self.mj = tk.StringVar()
        self.precomp = tk.BooleanVar(value=False)
        self.pver = tk.StringVar(value=core.PROMPT_DEFAULT)
        self.task = tk.StringVar(value='fix')          # 1 页：fix = 只修错，head = 修错 + 换头，person = 修错 + 换整个角色
        self.charref = tk.StringVar()                  # 换头 / 换角色用的角色参考图（= @图片2）
        self.swap2 = tk.StringVar(value='none')        # 2 页：GPT 这次做了什么（none / head / person）
        self._pver_fix = core.PROMPT_DEFAULT
        self._swap_auto = False                        # 2 页「GPT 这次」是不是按 1 页的记录自动选的
        self.ref = tk.StringVar()
        self.gpt = tk.StringVar()
        self.mask = tk.StringVar()
        self.mode = tk.StringVar(value='composite')
        self.size = tk.StringVar(value='gpt')
        self.addcal = tk.BooleanVar(value=True)
        self.upload = None
        self.prompt = ''
        self.prompt_swap = None                        # 当前显示的提示词按哪种模式生成（None / head / person）
        self.prompt_file = None
        self.focus = None
        self.result = None
        self.cur = 0

        self._build_shell()
        self.build1()
        self.build2()
        self.build3()
        self.build4()
        self.build5()
        self.show_page(0)
        for v in (self.mj, self.ref, self.gpt, self.cal_a, self.cal_b, self.st_mj, self.st_gpt):
            v.trace_add('write', lambda *a: self._refresh_actions())
        self._refresh_actions()
        self.dnd_ok = ui.enable_file_drop(root, self.on_files_dropped)

        root.report_callback_exception = self.on_error
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        root.after(100, self.poll)

    # ------------------------------------------------------------ 骨架：导航 / 页面 / 运行记录 / 状态栏
    def px(self, v):
        return int(v * self.k)

    def _build_shell(self):
        r, P = self.root, ui.PANEL
        r.grid_rowconfigure(0, weight=1)
        r.grid_columnconfigure(0, weight=1)
        body = tk.Frame(r, bg=ui.PAGE)
        body.grid(row=0, column=0, sticky='nsew')
        navw = ui.px(212)
        nav = tk.Frame(body, bg=P, width=navw)
        nav.pack(side='left', fill='y')
        nav.pack_propagate(False)
        tk.Frame(body, bg=ui.LINE, width=1).pack(side='left', fill='y')
        brand = tk.Frame(nav, bg=P)
        brand.pack(fill='x', padx=(ui.px(20), ui.px(12)), pady=(ui.px(18), ui.px(4)))
        try:
            with Image.open(os.path.join(HERE, ICON)) as im:
                s = ui.px(34)
                self._brand_img = ImageTk.PhotoImage(ui._flat(im.convert('RGBA').resize((s, s), Image.LANCZOS), P))
            tk.Label(brand, image=self._brand_img, bg=P, bd=0).pack(side='left')
        except Exception:
            pass
        tb = tk.Frame(brand, bg=P)
        tb.pack(side='left', padx=(ui.px(10), 0))
        tk.Label(tb, text='Image F', font=ui.F(16, 'bold'), fg=ui.FG, bg=P, bd=0).pack(anchor='w')
        # 版本号放在署名后面（V4.9 起底部多了语言链接，再放版本号就挤不下了）
        tk.Label(tb, text=tr('{AUTHOR} 设计', AUTHOR=AUTHOR) + ' · V' + VERSION, font=ui.F(11.5), fg=ui.MUTED, bg=P,
                 bd=0).pack(anchor='w')
        self.nav_items = []
        for grp, items in ((tr('修错流程'), NAV[:3]), (tr('其他工具'), NAV[3:])):
            tk.Label(nav, text=grp, font=ui.F(11.5), fg=ui.MUTED, bg=P).pack(anchor='w', padx=ui.px(22),
                                                                             pady=(ui.px(14), ui.px(4)))
            for num, t, s in items:
                it = ui.NavItem(nav, num, t, s, lambda i=int(num) - 1: self.show_page(i), navw)
                it.c.pack(fill='x')
                self.nav_items.append(it)
        foot = tk.Frame(nav, bg=P)
        foot.pack(side='bottom', fill='x', padx=ui.px(20), pady=(0, ui.px(12)))
        tk.Frame(nav, bg=ui.LINE, height=1).pack(side='bottom', fill='x', padx=ui.px(12), pady=(0, ui.px(10)))
        other = 'English' if not i18n.is_en() else '中文'          # 切换语言的链接：用目标语言写，看不懂当前语言也认得出
        for t, cmd in ((tr('使用说明'), self.open_manual), (tr('关于'), self.show_about), (other, self.switch_lang)):
            lk = tk.Label(foot, text=t, font=ui.F(12), fg=ui.ACCENT_FG, bg=P, cursor='hand2', bd=0)
            lk.pack(side='left', padx=(0, ui.px(14)))
            lk.bind('<Button-1>', lambda e, c=cmd: c())
            if cmd == self.switch_lang:
                self.lang_link = lk
        tk.Label(nav, text=tr('免费使用 · 禁止商用'), font=ui.F(11), fg=ui.MUTED, bg=P, bd=0
                 ).pack(side='bottom', anchor='w', padx=ui.px(20), pady=(0, ui.px(8)))

        main = tk.Frame(body, bg=ui.PAGE)
        main.pack(side='left', fill='both', expand=True)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)
        pad = (ui.px(28), ui.px(20), ui.px(28), ui.px(16))
        self.pages = [ttk.Frame(main, style='Page.TFrame', padding=pad) for _ in range(5)]
        self.t1, self.t2, self.t3, self.t4, self.t5 = self.pages
        for p in self.pages:
            p.columnconfigure(0, weight=1)
            p.rowconfigure(2, weight=1)
        self.nb = Pages(self)

        # 运行记录（默认收起；出错时自动展开）
        self.drawer = tk.Frame(r, bg=P)
        tk.Frame(self.drawer, bg=ui.LINE, height=1).pack(fill='x')
        dh = tk.Frame(self.drawer, bg=P)
        dh.pack(fill='x', padx=ui.px(16), pady=(ui.px(8), ui.px(4)))
        ttk.Label(dh, text=tr('运行记录'), style='Drawer.TLabel').pack(side='left')
        for t, cmd, pad_ in ((tr('收起 ▾'), lambda: self.show_log(False), 0), (tr('清空'), lambda: self.log.delete('1.0', 'end'), 16)):
            b = ttk.Label(dh, text=t, style='Hint.TLabel', cursor='hand2')
            b.pack(side='right', padx=(0, ui.px(pad_)))
            b.bind('<Button-1>', lambda e, c=cmd: c())
        lf = tk.Frame(self.drawer, bg=P)
        lf.pack(fill='both', expand=True, padx=ui.px(16), pady=(0, ui.px(10)))
        self.log = tk.Text(lf, height=8, wrap='word', width=1)
        ui.style_text(self.log, 'log')
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)
        self.drawer.grid(row=1, column=0, sticky='ew')
        self.drawer.grid_remove()
        # 状态栏
        sbar = tk.Frame(r, bg=P)
        sbar.grid(row=2, column=0, sticky='ew')
        tk.Frame(sbar, bg=ui.LINE, height=1).pack(fill='x')
        inner = tk.Frame(sbar, bg=P, height=ui.px(34))
        inner.pack(fill='x')
        inner.pack_propagate(False)
        self.dot = ui.dot(inner, ui.OK)
        self.dot.pack(side='left', padx=(ui.px(16), ui.px(10)))
        self.log_btn = ttk.Label(inner, text=tr('运行记录 ▴'), style='StatusLink.TLabel', cursor='hand2')
        self.log_btn.pack(side='right', padx=ui.px(16))
        self.log_btn.bind('<Button-1>', lambda e: self.show_log())
        self.status = ttk.Label(inner, text=tr('就绪。从左侧「1 生成提示词」开始。'), style='Status.TLabel', width=1)
        self.status.pack(side='left', fill='x', expand=True)

    def show_page(self, i):
        for j, p in enumerate(self.pages):
            if j != i:
                p.grid_remove()
        self.pages[i].grid(row=0, column=0, sticky='nsew')
        self.cur = i
        for j, it in enumerate(self.nav_items):
            it.set(j == i)

    def show_log(self, on=None):
        if on is None:
            on = not self.drawer.winfo_ismapped()
        if on:
            self.drawer.grid()
            self.log.see('end')
        else:
            self.drawer.grid_remove()
        self.log_btn.configure(text=tr('运行记录 ▾') if on else tr('运行记录 ▴'))

    def show_about(self):
        """关于：作者署名、许可、第三方组件。"""
        P = ui.PANEL
        top = tk.Toplevel(self.root)
        top.title(tr('关于 Image F'))
        top.transient(self.root)
        top.resizable(False, False)
        top.configure(bg=P)
        fr = tk.Frame(top, bg=P, padx=ui.px(28), pady=ui.px(24))
        fr.pack()
        hd = tk.Frame(fr, bg=P)
        hd.pack(anchor='w')
        if getattr(self, '_brand_img', None):
            try:
                with Image.open(os.path.join(HERE, ICON)) as im:
                    s = ui.px(56)
                    self._about_img = ImageTk.PhotoImage(ui._flat(im.convert('RGBA').resize((s, s), Image.LANCZOS), P))
                tk.Label(hd, image=self._about_img, bg=P, bd=0).pack(side='left', padx=(0, ui.px(14)))
            except Exception:
                pass
        tb = tk.Frame(hd, bg=P)
        tb.pack(side='left')
        tk.Label(tb, text='Image F', font=ui.F(22, 'bold'), fg=ui.FG, bg=P, bd=0).pack(anchor='w')
        tk.Label(tb, text='V' + VERSION + tr('\u3000用 GPT 修错，再把 MJ 的色彩、虚化、颗粒拉回来'), font=ui.F(12.5), fg=ui.MUTED, bg=P,
                 bd=0).pack(anchor='w')
        rows = ((tr('构思与设计'), AUTHOR), (tr('许可'), tr('{LICENSE_NAME}（免费使用，禁止商用）', LICENSE_NAME=LICENSE_NAME)),
                (tr('转发 / 修改'), tr('可以免费转发和修改，但必须附上许可并保留「{AUTHOR} 设计」的署名', AUTHOR=AUTHOR)),
                (tr('第三方组件'), tr('YuNet 人脸模型（MIT）、Depth Anything V2 Small（Apache-2.0）、Python、numpy、OpenCV、Pillow')))
        gr = tk.Frame(fr, bg=P)
        gr.pack(anchor='w', pady=(ui.px(18), ui.px(6)))
        for i, (k, v) in enumerate(rows):
            tk.Label(gr, text=k, font=ui.F(12.5, 'bold'), fg=ui.FG2, bg=P, bd=0).grid(row=i, column=0, sticky='nw',
                                                                                   pady=ui.px(4), padx=(0, ui.px(16)))
            tk.Label(gr, text=v, font=ui.F(13, 'bold' if i == 0 else 'normal'), fg=ui.ACCENT_FG if i == 0 else ui.FG, bg=P,
                     bd=0, justify='left', wraplength=ui.px(440)).grid(row=i, column=1, sticky='w', pady=ui.px(4))
        bf = tk.Frame(fr, bg=P)
        bf.pack(anchor='e', pady=(ui.px(14), 0))
        for t, path in ((tr('查看许可'), LICENSE), (tr('第三方组件说明'), THIRD_PARTY)):
            ttk.Button(bf, text=t, command=lambda p=path: core.open_path(p) if os.path.isfile(p)
                       else self.status.configure(text=tr('找不到文件：') + p)).pack(side='left', padx=(0, ui.px(8)))
        ttk.Button(bf, text=tr('关闭'), style='Small.TButton', command=top.destroy).pack(side='left')
        top.bind('<Escape>', lambda e: top.destroy())
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry(f'+{max(0, x)}+{max(0, y)}')
        top.grab_set()
        self._about = top

    def switch_lang(self, restart=True):
        """中文 ⇄ English：写 lang.json，然后重新打开工具（界面文字是打开时定下来的）。处理中不切换。"""
        if self.busy:
            self.status.configure(text=tr('还有任务在处理，处理完再切换语言。'))
            return
        new = 'zh' if i18n.is_en() else 'en'
        try:
            i18n.set_lang(new)
        except OSError as e:
            messagebox.showerror(APP, tr('没能保存语言设置：{e}', e=e))
            return
        if not restart:
            return new
        exe = sys.executable
        w = os.path.join(os.path.dirname(exe), 'pythonw.exe')
        if os.path.basename(exe).lower() == 'python.exe' and os.path.isfile(w):
            exe = w                                      # 不弹黑色命令行窗口
        env = dict(os.environ)
        env.pop('IMAGEF_LANG', None)
        try:
            import subprocess
            subprocess.Popen([exe, os.path.join(HERE, 'mj_gui.pyw')], cwd=HERE, env=env, close_fds=True)
        except OSError as e:
            messagebox.showinfo(APP, tr('语言已切换，请重新打开 Image F。') + f'\n({e})')
        self.root.destroy()
        return new

    def open_manual(self):
        if os.path.isfile(MANUAL):
            core.open_path(MANUAL)
        else:
            self.status.configure(text=tr('找不到使用说明：') + MANUAL)

    # ------------------------------------------------------------ 每页通用的小块
    def header(self, pg, title, lead, tip, help_label=tr('这一页怎么用')):
        h = ttk.Frame(pg, style='Page.TFrame')
        h.grid(row=0, column=0, sticky='ew', pady=(0, ui.px(16)))
        ui.help_link(h, help_label, tip + tr('\n\n点击打开完整使用说明。'), self.open_manual).pack(side='right', anchor='s',
                                                                                          pady=(0, ui.px(2)))
        left = ttk.Frame(h, style='Page.TFrame')
        left.pack(side='left', fill='x', expand=True)
        ttk.Label(left, text=title, style='Title.TLabel').pack(anchor='w')
        # 英文导语更长、右边的「这一页怎么用」也更宽：折行宽度收窄一些，窗口窄时页头不会把整页撑宽
        ttk.Label(left, text=nb(lead), style='Lead.TLabel', wraplength=ui.px(700 if i18n.is_en() else 860),
                  justify='left').pack(anchor='w', pady=(ui.px(4), 0))

    def card(self, parent):
        return ttk.Frame(parent, style='Card.TFrame', padding=ui.px(16))

    def top_row(self, pg):
        """左边图片卡 + 右边设置面板（固定 372 宽）。"""
        top = ttk.Frame(pg, style='Page.TFrame')
        top.grid(row=1, column=0, sticky='ew', pady=(0, ui.px(16)))
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, minsize=ui.px(372))
        top.rowconfigure(0, weight=1)
        lc, pn = self.card(top), self.card(top)
        lc.grid(row=0, column=0, sticky='nsew', padx=(0, ui.px(16)))
        pn.grid(row=0, column=1, sticky='nsew')
        return lc, pn

    def card_head(self, card, num=None, title='', sub=None, tag=None, mb=12):
        h = ttk.Frame(card)
        h.pack(fill='x', pady=(0, ui.px(mb)))
        act = ttk.Frame(h)                         # 右侧操作先排：标题栏窄时被截的是副标题，不是按钮
        act.pack(side='right')
        if tag:
            ui.Pill(act, *tag).pack(side='right')
        tk.Frame(h, bg=ui.PANEL, width=1, height=ui.px(30)).pack(side='left')
        if num:
            ui.badge(h, num).pack(side='left', padx=(0, ui.px(8)))
        ttk.Label(h, text=title, style='CardTitle.TLabel').pack(side='left')
        sl = None
        if sub is not None:
            sl = ttk.Label(h, text=sub, style='CardSub.TLabel', width=1)
            sl.pack(side='left', padx=(ui.px(8), ui.px(8)), fill='x', expand=True)
        return act, sl

    def field(self, parent, label, tag=None, tip=None):
        fr = ttk.Frame(parent)
        fr.pack(fill='x', pady=(0, ui.px(12)))
        lr = ttk.Frame(fr)
        lr.pack(fill='x', pady=(0, ui.px(6)))
        lbl = ttk.Label(lr, text=label, style='Field.TLabel')
        lbl.pack(side='left')
        if tip:
            ui.info_icon(lr, tip).pack(side='left', padx=(ui.px(6), 0))
        t = ui.Pill(lr, *tag).pack(side='right') if tag else None
        return fr, lr, lbl, t

    def fhint(self, parent, text):
        lb = ttk.Label(parent, text=nb(text), style='Hint.TLabel', wraplength=ui.px(340), justify='left')
        lb.pack(fill='x', pady=(ui.px(6), 0))
        return lb

    def switch_row(self, parent, text, var, tip=None, tag=None):
        fr = ttk.Frame(parent)
        fr.pack(fill='x', pady=(0, ui.px(12)))
        cb = ttk.Checkbutton(fr, variable=var)
        cb.pack(side='right')
        lbl = ttk.Label(fr, text=text, style='Body2.TLabel')
        lbl.pack(side='left')
        if tag:
            ui.Pill(fr, *tag).pack(side='left', padx=(ui.px(6), 0))
        if tip:
            ui.info_icon(fr, tip).pack(side='left', padx=(ui.px(6), 0))
        note = ttk.Label(fr, text='', style='Hint.TLabel')
        note.pack(side='left', padx=(ui.px(8), 0))
        return dict(frame=fr, check=cb, label=lbl, note=note)

    def bottom_action(self, pn, text, cmd, need=None, idle=''):
        """面板最底部的主按钮；缺图时变灰，下方写“还差：……”。"""
        hint = ttk.Label(pn, text=idle, style='Hint.TLabel', anchor='center')
        hint.pack(side='bottom', fill='x', pady=(ui.px(6), 0))
        b = ttk.Button(pn, text=text, style='Big.TButton', command=cmd)
        b.pack(side='bottom', fill='x')
        self.needs.append((b, need, hint, idle))
        return b, hint

    def legend(self, parent, items, right=None, view=None):
        """结果下方一行图例。view = 上面的预览：图例排在它前面（窗口矮时先缩预览，图例不会被挤掉）。"""
        fr = ttk.Frame(parent)
        fr.pack(fill='x', pady=(ui.px(10), 0), side='bottom', **({'before': view.canvas} if view else {}))
        for text, color in items:
            if color:
                tk.Label(fr, image=ui.swatch(color), text=' ' + text, compound='left', bg=ui.PANEL, fg=ui.FG2,
                         font=ui.F(12), bd=0).pack(side='left', padx=(0, ui.px(16)))
            else:
                ttk.Label(fr, text=text, style='Body2.TLabel').pack(side='left', padx=(0, ui.px(8)))
        if right:
            ttk.Label(fr, text=right, style='Hint.TLabel').pack(side='right')

    def text_box(self, parent, kind='code', height=6):
        fr = tk.Frame(parent, bg=ui.PANEL)
        fr.pack(fill='both', expand=True)
        t = tk.Text(fr, wrap='word', height=height, width=1)
        ui.style_text(t, kind)
        t.tag_configure('ph', foreground=ui.MUTED, font=ui.F(12.5))
        sb = ttk.Scrollbar(fr, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        t.pack(side='left', fill='both', expand=True)
        return t

    @staticmethod
    def set_text(t, text, hl=None, ph=False):
        """写入文本框；hl = 要高亮的那一行开头的文字（例如 MEASURED LOOK OF @图片1）。"""
        st = t.cget('state')
        t.configure(state='normal')
        t.delete('1.0', 'end')
        t.insert('1.0', text, ('ph',) if ph else ())
        if hl:
            i = t.search(hl, '1.0', 'end')
            if i:
                t.tag_add('hl', i, f'{i} lineend')
        t.configure(state=st)

    # ------------------------------------------------------------ helpers
    def zone(self, parent, var, title, pick, height=150, **kw):
        z = ui.DropZone(parent, var, title, pick, self.k, height, **kw)
        self.zones.append(z)
        return z

    def on_files_dropped(self, files, x, y):
        """从资源管理器拖进来的文件：放到鼠标所在的上传框；多张图时依次填到同一页后面的空框
        （可选的蒙版框、当前模式用不到的框除外——蒙版只能直接拖到它上面）。"""
        imgs = [f for f in files if f.lower().endswith(ui.IMG_EXT) and os.path.isfile(f)]
        if not imgs:
            self.status.configure(text=tr('拖进来的不是图片（支持 png / jpg / webp / bmp / tif）。'))
            return
        vis = [z for z in self.zones if z.canvas.winfo_viewable()]
        hit = next((z for z in vis if z.contains(x, y)), None)
        if hit is None:
            self.status.configure(text=tr('请把图片拖到虚线框里。'))
            return
        if not hit.enabled:
            self.status.configure(text=tr('这个框在当前模式用不到（「只修错」时不需要角色参考图）。'))
            return
        targets = [hit] + [z for z in vis[vis.index(hit) + 1:] if z.enabled and not z.var.get().strip() and not z.optional]
        for z, f in zip(targets, imgs):
            z.accept(f)
        used = imgs[:len(targets)]
        msg = tr('已载入：') + tr('，').join(os.path.basename(f) for f in used)
        if len(imgs) > len(used):
            msg += tr('（另外 {v} 张没有空框可放，已忽略）', v=len(imgs) - len(used))
        self.status.configure(text=msg)

    def pick(self, var, title):
        cur = var.get()
        p = filedialog.askopenfilename(title=title, filetypes=IMG_TYPES,
                                       initialdir=os.path.dirname(cur) if cur else os.path.expanduser('~/Downloads'))
        if p:
            var.set(os.path.normpath(p))
        return p

    def say(self, t):
        self.log.insert('end', t + '\n')
        self.log.see('end')

    def copy(self, text, ok_msg):
        """复制到剪贴板；失败时如实提示（剪贴板被别的程序占用很常见），不会误报“已复制”。"""
        try:
            core.copy_to_clipboard(text)
        except Exception as e:
            self.status.configure(text=tr('复制失败：{e}。稍后点「复制」按钮再试一次。', e=e))
            return False
        if ok_msg:
            self.status.configure(text=ok_msg)
        return True

    def on_error(self, *exc):
        txt = ''.join(traceback.format_exception(*exc))
        _write_err(txt)
        self.say(tr('[出错]\n') + txt)
        self.show_log(True)
        messagebox.showerror(tr('出错了'), str(exc[1]) + tr('\n\n详情已记录到运行记录。'))

    def on_close(self):
        if self.busy and not messagebox.askyesno(APP, tr('还有任务在处理，现在关闭会中断它（已经保存好的文件不受影响）。\n确定关闭吗？')):
            return
        self.root.destroy()

    def _refresh_actions(self):
        for b in self.action_buttons:
            b.state(['disabled'] if self.busy else ['!disabled'])
        for b, need, hint, idle in self.needs:
            miss = need() if need else []
            b.state(['disabled'] if (self.busy or miss) else ['!disabled'])
            if hint is not None:
                hint.configure(text=(tr('还差：') + tr('、').join(miss)) if miss else idle)

    def _set_busy(self, busy, msg=None):
        self.busy = busy
        self._refresh_actions()
        self.dot.set(ui.ACCENT if busy else ui.OK)
        self.root.configure(cursor='watch' if busy else '')
        if msg:
            self.status.configure(text=msg)

    FAIL_TEXT = tr('没有完成，原因见下方运行记录（已自动展开）。')

    def run(self, fn, done, msg, view=None):
        """在后台线程里执行 fn(log)，结束后在界面线程里调用 done(结果)；出错时结果为 None，原因写进运行记录（并自动展开）。
        view = 这一页的结果框：处理时框里显示 msg（“正在……”）和已用时间；左下角状态栏逐行显示正在写的运行记录。"""
        if self.busy:
            return
        self._set_busy(True, msg)
        self._view = view
        if view is not None:
            view.busy(msg)

        def log(t):
            self.q.put(('log', str(t) + '\n'))
        # 每次处理在运行记录里先写一行标题（几次处理的记录分得开；状态栏第一行显示它，不和结果框里的字重复）
        log(tr('\n—— {v}\u3000{v2} ——', v=time.strftime("%H:%M:%S"), v2=msg.split("，")[0].split(" — ")[0].rstrip("…")))

        def work():
            try:
                res = fn(log)
            except InputError as e:
                res = None
                log(tr('\n[出错] ') + str(e))
            except Exception:
                res = None
                log(tr('\n[出错]\n') + traceback.format_exc())
            self.q.put(('done', (done, res)))
        threading.Thread(target=work, daemon=True).start()

    def fail_text(self, res):
        if isinstance(res, dict) and res.get('error') == 'mismatch':
            return tr('两张图对不上，多半不是同一张图：已停止，没有生成结果，也没有加入标定。\n详情见下方运行记录。')
        if isinstance(res, dict) and res.get('message'):
            return tr('没有完成：') + str(res['message']) + tr('\n详情见下方运行记录。')
        return self.FAIL_TEXT

    def _status_line(self, text):
        """状态栏放不下时在末尾加省略号（不让一行长记录把状态栏撑开）。"""
        w = self.status.winfo_width()
        self.status.configure(text=ui.ellipsize(text, ui.F(12), w - ui.px(8)) if w > ui.px(80) else text)

    def poll(self):
        """处理后台线程的消息。结束回调就算出错，也只报告错误，轮询照常继续（否则之后的结果和日志都不会再显示）。"""
        try:
            last = None
            while True:
                try:
                    kind, v = self.q.get_nowait()
                except queue.Empty:
                    break
                if kind == 'log':
                    self.log.insert('end', v)
                    self.log.see('end')
                    if self.busy:
                        last = next((ln.strip() for ln in reversed(v.splitlines()) if ln.strip()), last)
                    continue
                if last:
                    self._status_line(last)
                    last = None
                self._set_busy(False)
                done, res = v
                view, self._view = getattr(self, '_view', None), None
                failed = res is None or (isinstance(res, dict) and 'error' in res)
                if failed:
                    self.show_log(True)
                    if view is not None:
                        view.message(self.fail_text(res))
                try:
                    done(res)
                except Exception:
                    self.on_error(*sys.exc_info())
                if view is not None and view.is_busy:      # 结束回调没放上新结果
                    view.message(self.FAIL_TEXT)
            if last and self.busy:
                self._status_line(last)
        finally:
            self.root.after(100, self.poll)

    @staticmethod
    def _isfile(v):
        return os.path.isfile(v.get().strip())

    # ------------------------------------------------------------ 1 生成提示词
    def build1(self):
        pg = self.t1
        self.header(pg, tr('生成提示词'), tr('测量 MJ 原图的色彩、焦点和颗粒，生成可直接粘贴给 GPT 的完整提示词。'), HELP[0])
        lc, pn = self.top_row(pg)
        self.card_head(lc, '1', tr('图片'), tr('拖进框里，或点框选择文件'))
        zs = ttk.Frame(lc)
        zs.pack(fill='both', expand=True)
        for c in (0, 1):
            zs.columnconfigure(c, weight=1, uniform='z')
        zs.rowconfigure(0, weight=1)
        self.mj_zone = self.zone(zs, self.mj, tr('MJ 原图'), self.pick_mj, ref='@图片1', tag=(tr('必选'), 'req'),
                                 hint=tr('用 MJ 网页下载的 PNG'), link=(tr('宫格图？切成四格'), self.do_split),
                                 on_set=lambda p: (self.mj.set(p), self.ref.set(p)), expand=True)
        self.mj_zone.frame.grid(row=0, column=0, sticky='nsew', padx=(0, ui.px(14)))
        self.char_zone = self.zone(zs, self.charref, tr('角色参考图'), lambda: self.pick(self.charref, tr('选择角色参考图')),
                                   ref='@图片2', tag=(tr('换头 / 换角色时'), 'plain'), hint='', expand=True,
                                   disabled_text=tr('换头 / 换整个角色时才需要'))
        self.char_zone.frame.grid(row=0, column=1, sticky='nsew')
        self.char_zone.set_enabled(False)

        self.card_head(pn, '2', tr('设置'), mb=14)
        f = self.field(pn, tr('这次要做'))[0]
        self.task_seg = ui.Seg(f, self.task, [('fix', tr('只修错')), ('head', tr('修错 + 换头')), ('person', tr('换整个角色'))],
               command=self.on_task).pack(fill='x')
        self.task_hint = self.fhint(f, self.TASK_HINTS['fix'])
        f = self.field(pn, tr('提示词版本'))[0]
        # 下拉框显示翻译后的名字；self.pver 里始终是内部名字（core.PROMPT_VERSIONS 等的键）
        self.pver_show = tk.StringVar(value=tr(self.pver.get()))
        self.pver_cb = ttk.Combobox(f, textvariable=self.pver_show, state='readonly', width=1)
        self._pver_values(core.PROMPT_VERSIONS)
        self.pver_cb.bind('<<ComboboxSelected>>',
                          lambda e: self.pver.set(self._pver_map.get(self.pver_show.get(), self.pver.get())))
        self.pver.trace_add('write', lambda *a: self.pver_show.set(tr(self.pver.get())))
        self.pver_cb.pack(fill='x')
        self.switch_row(pn, tr('预补偿图'), self.precomp, tag=(tr('实验'), 'plain'),
                        tip=tr('同时生成一张“预补偿图”：先把 GPT 固定会加上的品红 / 蓝色偏反向抵消，上传给 GPT 时用它代替 MJ 原图。还在实验，默认关闭。'))
        self.bottom_action(pn, tr('测量并生成提示词'), self.do_measure,
                           lambda: [] if self._isfile(self.mj) else [tr('MJ 原图')], tr('完成后自动复制到剪贴板'))

        res = ttk.Frame(pg, style='Page.TFrame')
        res.grid(row=2, column=0, sticky='nsew', pady=(0, ui.px(16)))
        res.columnconfigure(0, weight=3, uniform='r')
        res.columnconfigure(1, weight=2, uniform='r')
        res.rowconfigure(0, weight=1)
        pc = self.card(res)
        pc.grid(row=0, column=0, sticky='nsew', padx=(0, ui.px(16)))
        act, self.prompt_sub = self.card_head(pc, None, tr('提示词'), tr('所选版本 + 从 MJ 原图测出的 MEASURED LOOK'))
        self.copied = ui.Pill(act, tr('✓ 已复制'), 'ok')
        self.copy_btn = ttk.Button(act, text=tr('复制'), command=self.copy_prompt)
        self.copy_btn.pack(side='left', padx=(ui.px(8), 0))
        ttk.Button(act, text=tr('打开文件'), command=lambda: core.open_path(self.prompt_file)).pack(side='left', padx=(ui.px(8), 0))
        self.ptext = self.text_box(pc)
        self.set_text(self.ptext, self.PROMPT_PH, ph=True)
        fc = self.card(res)
        fc.grid(row=0, column=1, sticky='nsew')
        act, _ = self.card_head(fc, None, tr('焦点图'), tr('检查分区是否合理'))
        ttk.Button(act, text=tr('打开大图'), command=lambda: core.open_path(self.focus)).pack(side='left')
        self.focus_lbl = FitView(fc, tr('测量后在这里显示'), self.k).pack(fill='both', expand=True)
        self.legend(fc, [(tr('清晰'), '#3CC83C'), (tr('柔'), '#FFC800'), (tr('强虚化'), '#E62828'), (tr('无细节'), '#E6E8EC')],
                    right=tr('白线 = 九宫格'), view=self.focus_lbl)

        # 下一步条：左边步骤、右边两个按钮。放不下时（英文、换头 / 换角色多一个标签、窗口窄）按钮挪到第二行靠右
        bar = ttk.Frame(pg, style='Next.TFrame', padding=(ui.px(16), ui.px(12)))
        bar.grid(row=3, column=0, sticky='ew')
        bar.columnconfigure(1, weight=1)
        steps = ttk.Frame(bar, style='Next.In.TFrame')
        steps.grid(row=0, column=0, sticky='w')
        btns = ttk.Frame(bar, style='Next.In.TFrame')
        btns.grid(row=0, column=2, sticky='e')
        self._next_bar = (bar, steps, btns)
        bar.bind('<Configure>', lambda e: self._fit_next_bar())
        ttk.Button(btns, text=tr('去 ② 还原 →'), style='Next.Small.TButton', command=lambda: self.show_page(1)).pack(side='right')
        ttk.Button(btns, text=tr('打开文件夹'), style='Next.TButton',
                   command=lambda: core.reveal(self.upload or self.mj.get().strip())).pack(side='right', padx=(0, ui.px(8)))
        bar = steps
        ttk.Label(bar, text=tr('下一步：去 GPT 出图'), style='Next.TLabel').pack(side='left', padx=(0, ui.px(18)))

        def step(n, text):
            ui.step_circle(bar, n).pack(side='left', padx=(0, ui.px(8)))
            ttk.Label(bar, text=text, style='NextStep.TLabel').pack(side='left')

        def arrow():
            a = ttk.Label(bar, text='›', style='NextArrow.TLabel')
            a.pack(side='left', padx=ui.px(12))
            return a
        step('1', tr('按顺序上传'))
        self.chip1 = ui.Chip(bar, tr('图片1'), tr('MJ 原图')).pack(side='left', padx=(ui.px(8), 0))
        self.chip2 = ui.Chip(bar, tr('图片2'), tr('角色参考图'))
        self.arrow1 = arrow()
        step('2', tr('Ctrl+V 粘贴提示词'))
        arrow()
        step('3', tr('下载 PNG'))
        for v in (self.mj, self.charref):
            v.trace_add('write', lambda *a: self._update_chips())
        self._update_chips()

    def _pver_values(self, keys):
        """提示词版本下拉框：显示翻译后的名字，记住“显示名 -> 内部名字”。"""
        self._pver_map = {tr(k): k for k in keys}
        self.pver_cb.configure(values=list(self._pver_map))

    def _pver_short(self):
        """提示词版本的短名字（去掉括号里的说明），例如 v4、换头 v1 / Head swap v1。"""
        return tr(self.pver.get()).split('（')[0].split(' (')[0].strip()

    def _update_chips(self):
        swap = None if self.task.get() == 'fix' else self.task.get()
        up = self.upload if (self.prompt and self.upload) else self.mj.get().strip()
        pre = bool(self.prompt and self.upload and os.path.normcase(self.upload) != os.path.normcase(self.mj.get().strip()))
        self.chip1.set(tr('图片1'), tr('预补偿图') if pre else tr('MJ 原图'), tip=up or tr('还没选 MJ 原图'))
        if swap:
            self.chip2.set(tr('图片2'), tr('角色参考图'), tip=self.charref.get().strip() or tr('还没选角色参考图'))
            self.chip2.pack(side='left', padx=(ui.px(6), 0), before=self.arrow1)
        else:
            self.chip2.pack_forget()
        self.root.after_idle(self._fit_next_bar)

    def _fit_next_bar(self):
        """①页下一步条：一行放得下就一行（和以前一样），放不下时两个按钮换到第二行靠右。"""
        bar, steps, btns = self._next_bar
        try:
            avail = bar.winfo_width() - 2 * ui.px(16)
            if avail < 50:
                return
            two = steps.winfo_reqwidth() + ui.px(16) + btns.winfo_reqwidth() > avail
            if two != (str(btns.grid_info().get('row')) == '1'):
                if two:
                    btns.grid(row=1, column=0, columnspan=3, sticky='e', pady=(ui.px(10), 0))
                else:
                    btns.grid(row=0, column=2, columnspan=1, sticky='e', pady=0)
        except tk.TclError:
            pass

    def _clear_prompt(self):
        self.prompt, self.prompt_file = '', None
        self.set_text(self.ptext, self.PROMPT_PH, ph=True)
        self.copied.pack_forget()
        self.prompt_sub.configure(text=tr('所选版本 + 从 MJ 原图测出的 MEASURED LOOK'))

    def on_task(self):
        """切换“只修错 / 修错 + 换头 / 修错 + 换整个角色”：后两种才用角色参考图框，提示词版本换成对应版本。"""
        swap = None if self.task.get() == 'fix' else self.task.get()
        if swap:
            if self.pver.get() in core.PROMPT_VERSIONS:
                self._pver_fix = self.pver.get()
            vers, dflt = core.SWAP_KINDS[swap][:2]
            self.char_zone.set_enabled(True)
            self._pver_values(vers)
            self.pver.set(dflt)
        else:
            self.char_zone.set_enabled(False)
            self._pver_values(core.PROMPT_VERSIONS)
            self.pver.set(self._pver_fix)
        self.char_zone.set_hint(self.CHAR_HINTS[self.task.get()])
        self.task_hint.configure(text=nb(self.TASK_HINTS[self.task.get()]))
        self._update_chips()
        if self.prompt and self.prompt_swap != swap:   # 显示的提示词是另一种模式生成的：清掉，免得复制错
            self._clear_prompt()
            self.status.configure(text=tr('已切换到「{v}」：之前生成的提示词是另一种模式的，已清空，请重新点「测量并生成提示词」。', v=core.SWAP_KINDS[swap][4] if swap else tr('只修错')))
            return
        self.status.configure(text=tr('已切换到「{v}」：再放一张角色参考图，测量后按下方提示上传两张图。', v=core.SWAP_KINDS[swap][4])
                              if swap else tr('已切换到「只修错」。'))

    def pick_mj(self):
        if self.pick(self.mj, tr('选择 MJ 原图（PNG）')):
            self.ref.set(self.mj.get())

    def do_split(self):
        p = self.mj.get().strip()
        if not os.path.isfile(p):
            messagebox.showwarning(APP, tr('先在左边放一张 MJ 原图。'))
            return
        self.run(lambda log: core.split_grid(p), self.split_done, tr('正在切分宫格图……'))

    def split_done(self, r):
        if not r:
            self.status.configure(text=tr('切分没有完成，原因见下方运行记录。'))
            return
        cells, (x, y) = r
        self.say(tr('已切成四格（分界 x={x}, y={y}），保存在：{OUT}', x=x, y=y, OUT=core.OUT))
        self.status.configure(text=tr('已切成四格，在弹出的窗口里点要修的那一格。'))
        top = tk.Toplevel(self.root)
        top.title(tr('点选要修的那一格'))
        top.transient(self.root)
        top.configure(bg=ui.PANEL)
        ttk.Label(top, text=tr('点一下要交给 GPT 修的那一格：'), padding=ui.px(10)).grid(row=0, column=0, columnspan=2, sticky='w')
        for i, c in enumerate(cells):
            ph = ImageTk.PhotoImage(open_preview(c, (self.px(320), self.px(320))))
            b = ttk.Button(top, image=ph, text=[tr('左上'), tr('右上'), tr('左下'), tr('右下')][i], compound='top',
                           command=lambda c=c: self.pick_cell(c, top))
            b.image = ph
            b.grid(row=1 + i // 2, column=i % 2, padx=ui.px(8), pady=ui.px(8))

    def pick_cell(self, c, top):
        self.mj.set(os.path.normpath(c))
        self.ref.set(os.path.normpath(c))
        top.destroy()
        self.say(tr('已选：') + c)
        self.status.configure(text=tr('已选好一格。下一步：点「测量并生成提示词」。'))

    def do_measure(self):
        p = self.mj.get().strip()
        if not os.path.isfile(p):
            messagebox.showwarning(APP, tr('先放一张 MJ 原图。'))
            return
        swap = None if self.task.get() == 'fix' else self.task.get()
        cr = self.charref.get().strip()
        if swap and cr and not os.path.isfile(cr):
            messagebox.showwarning(APP, tr('角色参考图不存在，请重新选择。'))
            return
        self.ref.set(p)
        self.copied.pack_forget()
        pc, ver = self.precomp.get(), self.pver.get()
        self.run(lambda log: dict(core.measure(p, pc, log, ver, swap=swap), swap=swap, charref=cr),
                 self.measure_done, tr('正在测量……'), view=self.focus_lbl)

    def measure_done(self, r):
        if not r:
            self.status.configure(text=tr('测量失败，原因见下方运行记录。'))
            return
        self.prompt, self.prompt_file, self.focus, self.upload = r['prompt'], r['prompt_file'], r['focus'], r['upload']
        self.set_text(self.ptext, self.prompt, hl='MEASURED LOOK OF @图片1')
        self.focus_lbl.set(self.focus)
        self.prompt_sub.configure(text=tr('{v} + 从 MJ 原图测出的 MEASURED LOOK', v=self._pver_short()))
        self.swap2.set(r['swap'] or 'none')
        self._swap_auto = True
        self._update_swap_tag()
        self.prompt_swap = r['swap']
        self._update_chips()
        copied = self.copy(self.prompt, '')
        if copied:
            self.copied.pack(side='left', before=self.copy_btn)
            msg = tr('提示词已生成并复制到剪贴板（{v}）。按下方「下一步」去 GPT 出图', v=self._pver_short())
        else:
            msg = self.status.cget('text') + tr(' 然后按下方「下一步」去 GPT 出图')
        if r['swap']:
            what = tr('换了头') if r['swap'] == 'head' else tr('换了整个角色')
            msg += (tr('：先传图片1、再传图片2（顺序不能反）；出图后到「2 还原」会自动选好“{what}”，这种结果不加入标定。', what=what)
                    + ('' if r['charref'] else tr('还没选角色参考图。')))
        else:
            msg += tr('，出图后到「2 还原」。')
        if self.upload and os.path.normcase(self.upload) != os.path.normcase(self.mj.get().strip()):
            msg += tr(' 图片1 要传预补偿图（点「打开文件夹」可找到）。')
        self.status.configure(text=msg)

    def copy_prompt(self):
        if self.prompt and self.copy(self.prompt, tr('已复制。')):
            self.copied.pack(side='left', before=self.copy_btn)

    # ------------------------------------------------------------ 2 还原
    def build2(self):
        pg = self.t2
        self.header(pg, tr('还原'), tr('把 MJ 原图的颜色、明暗、虚化和颗粒找回到 GPT 修好的图上。'), HELP[1])
        lc, pn = self.top_row(pg)
        self.card_head(lc, '1', tr('图片'), tr('拖进框里，或点框选择文件'))
        zs = ttk.Frame(lc)
        zs.pack(fill='both', expand=True)
        for c, wt in enumerate((100, 100, 62)):
            zs.columnconfigure(c, weight=wt, uniform='z')
        zs.rowconfigure(0, weight=1)
        self.ref_zone = self.zone(zs, self.ref, tr('MJ 原图'), lambda: self.pick(self.ref, tr('选择 MJ 原图（参考）')), ref=tr('参考'),
                                  tag=(tr('必选'), 'req'), hint=tr('交给 GPT 的那张，不要选预补偿图'), expand=True)
        self.ref_zone.frame.grid(row=0, column=0, sticky='nsew', padx=(0, ui.px(14)))
        self.zone(zs, self.gpt, tr('GPT 输出'), lambda: self.pick(self.gpt, tr('选择 GPT 生成的图')), tag=(tr('必选'), 'req'),
                  hint=tr('GPT 下载的原图，别用截图'), expand=True).frame.grid(row=0, column=1, sticky='nsew', padx=(0, ui.px(14)))
        self.zone(zs, self.mask, tr('蒙版'), lambda: self.pick(self.mask, tr('选择蒙版（白=用 GPT，黑=用 MJ）')), tag=(tr('可选'), 'plain'),
                  optional=True, hint=tr('白 = 用 GPT'), empty=tr('一般不用'), expand=True,
                  tip=tr('一般不用选，工具会自动找 GPT 改过的地方。\n按 GPT 图画的黑白图：白 = 用 GPT，黑 = 保留 MJ。')
                  ).frame.grid(row=0, column=2, sticky='nsew')
        for v in (self.ref, self.mj):
            v.trace_add('write', lambda *a: self._ref_tag())

        self.card_head(pn, '2', tr('设置'), mb=14)
        f, lr, _, self.swap_tag = self.field(pn, tr('GPT 这次'), tag=(tr('按 ① 自动选好'), 'auto'))
        self.swap_tag.pack_forget()
        self.swap_seg = ui.Seg(f, self.swap2, [('none', tr('只修错')), ('head', tr('换了头')), ('person', tr('换了整个角色'))],
               command=self._swap_user).pack(fill='x')
        # 脸部明暗跟随 MJ（只在换了头 / 整个角色时有用）：0% = 保持 GPT 的脸部明暗，100% = 和 MJ 原来的人一样
        f, lr, self.face_lbl, _ = self.field(pn, tr('脸部明暗跟随 MJ'),
                                             tip=tr('只改整张脸的整体明暗和轻微反差：0% = 保持 GPT 新脸自己的明暗，100% = 和 MJ 原来那个人的脸一样亮。脸上原有的受光面、背光面、'
                                                    '五官阴影都保留，不会出现明暗交界线。冷暖（偏黄 / 偏粉）始终按 MJ。工具会记住上次用的数值。'))
        self.face_pct = tk.IntVar(value=core.get_face_light())
        ttk.Label(lr, text='%', style='Body2.TLabel').pack(side='right')
        self.face_spin = ttk.Spinbox(lr, from_=0, to=100, increment=5, width=4, textvariable=self.face_pct,
                                     command=self._face_from_spin, justify='right')
        self.face_spin.pack(side='right', padx=(0, ui.px(4)))
        self.face_spin.bind('<Return>', lambda e: self._face_from_spin())
        self.face_spin.bind('<FocusOut>', lambda e: self._face_from_spin())
        sr = ttk.Frame(f)                    # 滑块两端写明方向：左 = 保持 GPT，右 = 跟 MJ
        sr.pack(fill='x')
        self.face_ends = [ttk.Label(sr, text='GPT', style='Hint.TLabel'), ttk.Label(sr, text='MJ', style='Hint.TLabel')]
        self.face_ends[0].pack(side='left', padx=(0, ui.px(8)))
        self.face_ends[1].pack(side='right', padx=(ui.px(8), 0))
        self.face_scale = ttk.Scale(sr, from_=0, to=100, command=self._face_from_scale)
        self.face_scale.set(self.face_pct.get())
        self.face_scale.pack(side='left', fill='x', expand=True)
        self.face_tip = ui.Tip(self.face_scale, '')
        f = self.field(pn, tr('还原方式'), tip=tr('只替换改过的地方：GPT 改动少时用，最贴近 MJ（MJ 原像素最多，GPT 外扩的边也会保留）。\n整图迁移风格：GPT 改动多时用，整图用 '
                                          'GPT，把 MJ 的颜色、明暗、雾气、虚化、颗粒按区域迁移过去，清晰度最高。'))[0]
        self.mode_seg = ui.Seg(f, self.mode, [('composite', tr('只替换改过的地方')), ('transfer', tr('整图迁移风格'))]).pack(fill='x')
        f = self.field(pn, tr('输出尺寸'))[0]
        self.size_seg = ui.Seg(f, self.size, [('gpt', tr('和 GPT 一样大')), ('mj', tr('缩到 MJ 大小'))]).pack(fill='x')
        self.addcal_row = self.switch_row(pn, tr('自动加入标定'), self.addcal,
                                          tip=tr('还原完成后，自动把这一组加入「3 标定」，让测量和预补偿越用越准。换了头 / 整个角色的结果不加入（人物整块换了，会干扰 GPT 偏色的统计）。'))
        self.bottom_action(pn, tr('开始还原'), self.do_restore,
                           lambda: [n for v, n in ((self.ref, tr('MJ 原图')), (self.gpt, tr('GPT 输出'))) if not self._isfile(v)])
        self.swap2.trace_add('write', lambda *a: self._face_state())
        self._face_state()
        self.ref.trace_add('write', lambda *a: self._sync_swap())

        rc = self.card(pg)
        rc.grid(row=2, column=0, sticky='nsew')
        act, _ = self.card_head(rc, None, tr('结果对比'), tr('MJ 原图 ｜ GPT 输出 ｜ 还原结果'))
        ttk.Button(act, text=tr('打开还原结果'), style='Small.TButton',
                   command=lambda: core.open_path((self.result or {}).get('out'))).pack(side='left')
        for t, k in ((tr('对比图'), 'compare'), (tr('改动区域图'), 'mask')):
            ttk.Button(act, text=t, command=lambda k=k: core.open_path((self.result or {}).get(k))
                       ).pack(side='left', padx=(ui.px(8), 0))
        ttk.Button(act, text=tr('在文件夹中显示'), command=lambda: core.reveal((self.result or {}).get('out'))
                   ).pack(side='left', padx=(ui.px(8), 0))
        self.cmp_lbl = FitView(rc, tr('还原后在这里显示'), self.k, retile3=True).pack(fill='both', expand=True)
        self.legend(rc, [(tr('改动区域图：'), None), (tr('GPT 改过的地方'), '#E24A4A'), (tr('GPT 外扩、MJ 里没有的区域'), '#4A7BE2')],
                    right=tr('再次还原同一张图会另存为 _2、_3，不覆盖'), view=self.cmp_lbl)

    def _ref_tag(self):
        r, m = self.ref.get().strip(), self.mj.get().strip()
        auto = bool(r) and os.path.normcase(r) == os.path.normcase(m)
        self.ref_zone.set_tag(*((tr('来自 ①'), 'auto') if auto else (tr('必选'), 'req')))

    def _swap_user(self):
        self._swap_auto = False
        self._update_swap_tag()

    def _update_swap_tag(self):
        if self._swap_auto:
            self.swap_tag.pack(side='right')
        else:
            self.swap_tag.pack_forget()

    def _face_pct(self):
        try:
            v = int(round(float(self.face_spin.get())))
        except (ValueError, tk.TclError):
            v = int(round(float(self.face_scale.get())))   # 输错字：回到滑块上一次的值
        return min(100, max(0, v))                          # 超出范围：夹到 0 / 100

    def _face_from_scale(self, v):
        v = int(round(float(v)))
        try:
            same = self.face_pct.get() == v
        except tk.TclError:
            same = False
        if not same:
            self.face_pct.set(v)

    def _face_from_spin(self):
        v = self._face_pct()
        self.face_pct.set(v)
        self.face_scale.set(v)

    def _face_state(self):
        """「脸部明暗跟随 MJ」只在换了头 / 整个角色时可用；这时「自动加入标定」变灰并写明原因。"""
        on = self.swap2.get() in core.SWAP_KINDS
        for w in (self.face_scale, self.face_spin):
            w.state(['!disabled'] if on else ['disabled'])
        self.face_lbl.configure(style='Field.TLabel' if on else 'FieldDis.TLabel')
        self.face_tip.set(tr('左 0 = 保持 GPT 新脸自己的明暗，右 100 = 和 MJ 原来那个人的脸一样亮') if on
                          else tr('换了头 / 换了整个角色时才用得上'))
        self.addcal_row['check'].state(['disabled'] if on else ['!disabled'])
        self.addcal_row['label'].configure(style='Body2.TLabel')
        self.addcal_row['note'].configure(text=tr('换头 / 换角色时不加入') if on else '')

    def _sync_swap(self):
        """2 页换了 MJ 原图时，按 1 页的记录自动选“GPT 这次做了什么”。"""
        p = self.ref.get().strip()
        if os.path.isfile(p):
            try:
                k = core.swap_kind(p)
            except Exception:
                return
            self.swap2.set(k or 'none')
            self._swap_auto = bool(k) or (bool(self.prompt) and os.path.normcase(p) == os.path.normcase(self.mj.get().strip()))
            self._update_swap_tag()

    def do_restore(self):
        ref, gpt, mask = self.ref.get().strip(), self.gpt.get().strip(), self.mask.get().strip() or None
        for p, n in ((ref, tr('MJ 原图')), (gpt, tr('GPT 输出'))):
            if not os.path.isfile(p):
                messagebox.showwarning(APP, tr('请先选「{n}」。', n=n))
                return
        if mask and not os.path.isfile(mask):
            messagebox.showwarning(APP, tr('蒙版文件不存在。'))
            return
        orig = core.original_of_precomp(ref)
        if orig:
            self.say(tr('参考图选的是预补偿图，已自动换回对应的 MJ 原图：') + orig)
            ref = orig
            self.ref.set(orig)
        mis = core.aspect_mismatch(ref, gpt)
        if mis > 0.08 and not messagebox.askyesno(
                APP, tr('两张图的长宽比相差 {v:.1f}%，差得太多（工具能自动对齐小幅裁边/外扩/平移，但这么大的差别多半不是同一张图）。\n确认选的是同一张图吗？仍然继续？', v=mis * 100)):
            return
        mode, add, size = self.mode.get(), self.addcal.get(), self.size.get()
        swap = self.swap2.get() if self.swap2.get() in core.SWAP_KINDS else False
        self._face_from_spin()
        pct = self._face_pct()
        if swap:
            try:
                core.save_face_light(pct)
            except OSError:
                pass

        def job(log):
            r = core.restore(ref, gpt, mode, mask, log, size, swap=swap, face_light=pct / 100)
            if 'error' not in r and add and swap:
                log(tr('\n「{v}」的结果不加入标定（人物整块换了，会干扰 GPT 偏色的统计）。', v=core.SWAP_KINDS[swap][4]))
            elif 'error' not in r and add:
                log(tr('\n—— 加入标定 ——'))
                try:
                    r['calib'] = core.calib_add(ref, gpt, log, note=os.path.basename(gpt), F=r['F'])
                except Exception:     # 标定出错不影响已经保存好的还原结果
                    log(tr('[加入标定时出错，还原结果不受影响]\n') + traceback.format_exc())
                    r['calib_error'] = True
            return r
        self.run(job, self.restore_done, tr('正在还原，大图需要十几秒……'), view=self.cmp_lbl)

    def restore_done(self, r):
        if not r or 'error' in r:
            self.status.configure(text=tr('还原没有完成，原因见下方运行记录。'))
            if r and r['error'] == 'mismatch':
                messagebox.showwarning(APP, tr('「MJ 原图（参考）」和「GPT 输出」对不上，多半不是同一张图。\n\n工具已主动停止，不会生成错位拼贴，也不会加入标定。详情写在下方「运行记录」里。'))
            elif r:
                messagebox.showwarning(APP, r['message'])
            else:
                messagebox.showwarning(APP, tr('还原时出错了，详情写在下方「运行记录」里。'))
            return
        self.result = r
        self.cmp_lbl.set(r['compare'])
        self.refresh_calib()
        if r.get('calib_error'):
            self.show_log(True)
        self.status.configure(text=tr('还原完成：') + os.path.basename(r['out'])
                              + (tr('（加入标定时出错，见运行记录；还原结果已保存）') if r.get('calib_error') else ''))

    # ------------------------------------------------------------ 3 标定
    def build3(self):
        pg = self.t3
        self.cal_a, self.cal_b = tk.StringVar(), tk.StringVar()
        self.cal_view = tk.StringVar(value='list')
        self._cal_done = False
        self.header(pg, tr('标定'), tr('统计 GPT 每次固定会怎么偏（偏蓝、颗粒变少、变清晰），用来写防漂移语句和预补偿图。「2 还原」时会自动加入，一般不用来这里。'), HELP[2], tr('标定是什么'))
        lc, pn = self.top_row(pg)
        self.card_head(lc, '1', tr('手动加入一组'), tr('平时不用；只有想补录以前的图时才用'))
        zs = ttk.Frame(lc)
        zs.pack(fill='both', expand=True)
        for c in (0, 1):
            zs.columnconfigure(c, weight=1, uniform='z')
        zs.rowconfigure(0, weight=1)
        t1 = tr('第 1 张：当时交给 GPT 的图')
        self.zone(zs, self.cal_a, t1, lambda: self.pick(self.cal_a, t1), tag=(tr('必选'), 'req'), hint=tr('MJ 原图或预补偿图'),
                  expand=True).frame.grid(row=0, column=0, sticky='nsew', padx=(0, ui.px(14)))
        self.zone(zs, self.cal_b, tr('第 2 张：GPT 的输出'), lambda: self.pick(self.cal_b, tr('第 2 张：GPT 的输出')),
                  tag=(tr('必选'), 'req'), hint=tr('GPT 下载的原图'), expand=True).frame.grid(row=0, column=1, sticky='nsew')

        self.card_head(pn, '2', tr('概况'), mb=14)
        sr = ttk.Frame(pn)
        sr.pack(fill='x', pady=(0, ui.px(12)))
        for c in (0, 1):
            sr.columnconfigure(c, weight=1, uniform='s')
        self.stat_n = []
        for c, name in enumerate((core.BASE_NOTE, tr('本机加入'))):
            fr = ttk.Frame(sr, style='Stat.TFrame', padding=(ui.px(12), ui.px(10)))
            fr.grid(row=0, column=c, sticky='ew', padx=(0, ui.px(10)) if c == 0 else 0)
            n = ttk.Label(fr, text='0', style='Stat.TLabel')
            n.pack(anchor='w')
            ttk.Label(fr, text=name, style='StatSub.TLabel').pack(anchor='w')
            self.stat_n.append(n)
        self.cal_hint = ttk.Label(pn, text='', style='Hint.TLabel', wraplength=ui.px(340), justify='left')
        self.cal_hint.pack(fill='x')
        self.bottom_action(pn, tr('加入这一组标定'), self.calib_add_zones,
                           lambda: [n for v, n in ((self.cal_a, tr('第 1 张')), (self.cal_b, tr('第 2 张'))) if not self._isfile(v)])

        rc = self.card(pg)
        rc.grid(row=2, column=0, sticky='nsew')
        hd = ttk.Frame(rc)
        hd.pack(fill='x', pady=(0, ui.px(12)))
        self.cal_seg = ui.Seg(hd, self.cal_view, [('list', tr('组列表')), ('result', tr('标定结果'))], command=self._cal_show_view)
        self.cal_seg.canvas.configure(width=ui.px(240))
        self.cal_seg.pack(side='left')
        act = ttk.Frame(hd)
        act.pack(side='right')
        for t, c in ((tr('重新计算'), self.calib_show), (tr('移除最后一组'), self.calib_remove)):
            b = ttk.Button(act, text=t, command=c)
            b.pack(side='left', padx=(0, ui.px(8)))
            self.action_buttons.append(b)
        ttk.Button(act, text=tr('打开标定文件夹'), command=lambda: core.open_path(core.CALIB)).pack(side='left')
        body = tk.Frame(rc, bg=ui.PANEL)
        body.pack(fill='both', expand=True)
        self.cal_list = tk.Frame(body, bg=ui.PANEL)
        cols = ('id', 'src', 'note', 'pc')
        self.tree = ttk.Treeview(self.cal_list, columns=cols, show='headings', height=5)
        for c, t, w in zip(cols, (tr('组'), tr('来源'), tr('GPT 输出文件'), tr('用了预补偿')), (64, 96, 600, 110)):
            self.tree.heading(c, text=t, anchor='w')
            self.tree.column(c, width=ui.px(w), anchor='w', stretch=c == 'note')
        self.tree.tag_configure('base', foreground=ui.FG2)
        self.tree.tag_configure('local', foreground=ui.FG)
        tsb = ttk.Scrollbar(self.cal_list, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.cal_res = tk.Frame(body, bg=ui.PANEL)
        self.cal_res_hint = ttk.Label(self.cal_res, text=tr('点「重新计算」查看标定结果。'), style='Hint.TLabel')
        self.cal_res_hint.pack(fill='x', pady=(0, ui.px(8)))
        # 结果说明一行放不下时折行（英文更长；中文在默认窗口里本来就是一行，不受影响）
        self.cal_res.bind('<Configure>', lambda e: self.cal_res_hint.configure(wraplength=max(ui.px(200), e.width - ui.px(4))))
        rf = tk.Frame(self.cal_res, bg=ui.PANEL)
        rf.pack(fill='both', expand=True)
        cols = ('item', 'median', 'same', 'use', 'out')
        self.bias_tree = ttk.Treeview(rf, columns=cols, show='headings', height=5)
        for c, t, w in zip(cols, (tr('偏差项'), tr('中位数'), tr('方向一致'), tr('采用'), tr('离群的组')), (200, 110, 110, 110, 400)):
            self.bias_tree.heading(c, text=t, anchor='w')
            self.bias_tree.column(c, width=ui.px(w), anchor='w', stretch=c == 'out')
        self.bias_tree.tag_configure('use', foreground=ui.ACCENT_FG)
        self.bias_tree.tag_configure('no', foreground=ui.FG2)
        bsb = ttk.Scrollbar(rf, command=self.bias_tree.yview)
        self.bias_tree.configure(yscrollcommand=bsb.set)
        bsb.pack(side='right', fill='y')
        self.bias_tree.pack(side='left', fill='both', expand=True)
        self._cal_show_view()
        self.refresh_calib()

    def _cal_show_view(self):
        if self.cal_view.get() == 'result':
            self.cal_list.pack_forget()
            self.cal_res.pack(fill='both', expand=True)
            if not self._cal_done and not self.busy:
                self.calib_show()
        else:
            self.cal_res.pack_forget()
            self.cal_list.pack(fill='both', expand=True)

    def refresh_calib(self):
        self.tree.delete(*self.tree.get_children())
        pairs = core.calib_pairs(self.say)
        n_base = 0
        for p in pairs:
            base = bool(p.get('base'))
            n_base += base
            note = tr('（内置基础数据，不含图片）') if base else (p.get('note') or os.path.basename(p.get('source_gpt', '')))
            self.tree.insert('', 'end', values=(p.get('id', ''), tr('内置') if base else tr('本机'), note,
                                                tr('是') if p.get('precomp') else tr('否')), tags=('base' if base else 'local',))
        nl = len(pairs) - n_base
        self.stat_n[0].configure(text=str(n_base))
        self.stat_n[1].configure(text=str(nl))
        self.cal_seg.set_text('list', tr('组列表（{n}）', n=len(pairs)))
        more = max(0, 5 - nl)
        self.cal_hint.configure(text=nb((tr('本机再攒 {more} 组（≥ 5 组）更准。', more=more) if more else tr('本机已有 {nl} 组。', nl=nl))
                                   + tr('工具自己的还原图、换头 / 换角色的结果、配不上的图会被自动拒收。')))

    def _calib_add(self, a, b, done):
        self.run(lambda log: core.calib_add(a, b, log, note=os.path.basename(b)), done, tr('正在标定……'))

    def calib_add_zones(self):
        a, b = self.cal_a.get().strip(), self.cal_b.get().strip()
        for p, n in ((a, tr('第 1 张')), (b, tr('第 2 张'))):
            if not os.path.isfile(p):
                messagebox.showwarning(APP, tr('请先放入「{n}」。', n=n))
                return

        def done(r):
            self.refresh_calib()
            if r:
                self.cal_a.set('')
                self.cal_b.set('')
                self.status.configure(text=tr('已加入标定并重新汇总。'))
            elif r is not None:
                self.show_log(True)
                self.status.configure(text=tr('这一组没有加入标定，原因见下方运行记录。'))
        self._calib_add(a, b, done)

    def calib_remove(self):
        if core.calib_local() and messagebox.askyesno(APP, tr('移除最后一组（本机加的）标定数据？')):
            self.run(core.calib_remove_last, lambda r: (self.refresh_calib(), self.status.configure(text=tr('已移除最后一组。'))),
                     tr('正在重新计算……'))
        elif not core.calib_local():
            self.status.configure(text=tr('没有本机加的组可移除；「{BASE_NOTE}」是随工具带的，不能单独移除。', BASE_NOTE=core.BASE_NOTE))

    BIAS_ROWS = ([(z, k, f'{zh} {lab}') for z, zh in (('shadows', tr('暗部')), ('midtones', tr('中间调')), ('highlights', tr('高光')))
                  for k, lab in (('dL', tr('亮度')), ('da', tr('a 品红+')), ('db', tr('b 黄+')), ('chroma_ratio', tr('饱和度 ×')))]
                 + [(None, k, lab) for k, lab in (('grain_ratio', tr('颗粒 ×')), ('edge_ratio', tr('边缘能量 ×')),
                                                  ('blur_ratio_soft', tr('虚化区模糊 ×')))])

    def calib_show(self):
        """重新汇总标定（完整报告写进运行记录），「标定结果」里按偏差项列成表：中位数、方向一致的比例、是否采用。"""
        def done(r):
            self._cal_done = True
            t = self.bias_tree
            t.delete(*t.get_children())
            res = core.read_json(core.BIAS_JSON, None) if r else None
            if not isinstance(res, dict) or 'zones' not in res:
                self.cal_res_hint.configure(text=tr('还没有标定数据。'))
            else:
                n_use = 0
                for z, k, lab in self.BIAS_ROWS:
                    s = (res['zones'].get(z, {}) if z else res.get('global', {})).get(k)
                    if not isinstance(s, dict):
                        continue
                    use = bool(s.get('consistent'))
                    n_use += use
                    v = s.get('median', s.get('mean', 0.0))
                    val = f'× {v:.2f}' if k.endswith('ratio') or k.endswith('_soft') else f'{v:+.2f}'
                    outl = s.get('outliers') or []
                    t.insert('', 'end', values=(lab, val, f'{s.get("same_sign", 0) * 100:.0f}%', tr('✓ 采用') if use else '—',
                                                (tr('第 ') + tr('、').join(str(i) for i in outl) + tr(' 组')) if outl else tr('无')),
                             tags=('use' if use else 'no',))
                self.cal_res_hint.configure(text=nb(tr('共 {v} 组。采用 {n_use} 项：≥ 80% 的组方向一致、幅度够大的偏差，会写进提示词的防漂移语句和预补偿图。每组的明细在运行记录里。', v=res.get("n_pairs", len(res.get("pairs", []))), n_use=n_use)))
            self.cal_view.set('result')
            self._cal_show_view()
            self.status.configure(text=tr('标定结果已更新（每组明细见运行记录）。') if r else tr('还没有标定数据。'))
        self.run(core.calib_recompute, done, tr('正在计算……'))

    # ------------------------------------------------------------ 4 只还原风格
    def build4(self):
        pg = self.t4
        self.st_mj, self.st_gpt = tk.StringVar(), tk.StringVar()
        self.st_strength = tk.DoubleVar(value=1.0)
        self.st_black = tk.BooleanVar(value=False)
        self.st_bg = tk.BooleanVar(value=False)
        self.st_kind = tk.StringVar(value='auto')
        self.st_result = None
        self.header(pg, tr('只还原风格'), tr('两张图构图、长宽或内容不同时（四视图、白底设定图、同一场景重画），把 MJ 的颜色、风格和质感迁移到 GPT 图上。'), HELP[3])
        lc, pn = self.top_row(pg)
        self.card_head(lc, '1', tr('图片'), tr('拖进框里，或点框选择文件'))
        zs = ttk.Frame(lc)
        zs.pack(fill='both', expand=True)
        for c in (0, 1):
            zs.columnconfigure(c, weight=1, uniform='z')
        zs.rowconfigure(0, weight=1)
        self.zone(zs, self.st_mj, tr('MJ 风格图'), lambda: self.pick(self.st_mj, tr('选择 MJ 风格参考图')), tag=(tr('必选'), 'req'),
                  hint=tr('提供风格的 MJ 图，宫格整张或其中一格都行'), expand=True
                  ).frame.grid(row=0, column=0, sticky='nsew', padx=(0, ui.px(14)))
        self.zone(zs, self.st_gpt, tr('GPT 图'), lambda: self.pick(self.st_gpt, tr('选择要上风格的 GPT 图')), tag=(tr('必选'), 'req'),
                  hint=tr('结果和它一样大，存在「Output\\style_only」'), expand=True).frame.grid(row=0, column=1, sticky='nsew')

        self.card_head(pn, '2', tr('设置'), mb=14)
        f = self.field(pn, tr('图片类型'))[0]
        self.kind_seg = ui.Seg(f, self.st_kind, [('auto', tr('自动判断（推荐）')), ('scene', tr('同一场景重画')), ('region', tr('构图 / 内容不同')),
                                 ('character', tr('角色为主'))], cols=2,
               command=lambda: self.kind_hint.configure(text=nb(self.KIND_HINTS[self.st_kind.get()]))).pack(fill='x')
        self.kind_hint = self.fhint(f, self.KIND_HINTS['auto'])
        f, lr, _, _ = self.field(pn, tr('风格强度'))
        val = ttk.Label(lr, text='1.00', style='Value.TLabel')
        val.pack(side='right')
        ttk.Scale(f, from_=0.0, to=1.0, variable=self.st_strength,
                  command=lambda v: val.configure(text=f'{float(v):.2f}')).pack(fill='x')
        self.switch_row(pn, tr('保留纯黑'), self.st_black, tip=tr('黑色衣服、鞋子不被提亮、不偏青。'))
        self.switch_row(pn, tr('背景也跟随 MJ'), self.st_bg,
                        tip=tr('背景（白底或纯色 / 渐变底）默认不动，只给主体上风格；打开后背景色也按 MJ 改。\n“同一场景重画”时整幅一起调，不受这个开关影响。'))
        need = lambda: [n for v, n in ((self.st_mj, tr('MJ 风格图')), (self.st_gpt, tr('GPT 图'))) if not self._isfile(v)]
        hint = ttk.Label(pn, text='', style='Hint.TLabel', anchor='center')
        hint.pack(side='bottom', fill='x', pady=(ui.px(6), 0))
        row = ttk.Frame(pn)
        row.pack(side='bottom', fill='x')
        b2 = ttk.Button(row, text=tr('区域 / 远近预览'), style='Lg.TButton', command=self.do_regions)
        b2.pack(side='left')
        b = ttk.Button(row, text=tr('开始只还原风格'), style='Big.TButton', command=self.do_style)
        b.pack(side='left', fill='x', expand=True, padx=(ui.px(10), 0))
        self.needs += [(b, need, hint, ''), (b2, need, None, '')]

        rc = self.card(pg)
        rc.grid(row=2, column=0, sticky='nsew')
        act, _ = self.card_head(rc, None, tr('结果对比'), tr('MJ 风格图 ｜ GPT 图 ｜ 风格还原结果 ｜ 区域对应'))
        ttk.Button(act, text=tr('打开结果'), style='Small.TButton',
                   command=lambda: core.open_path((self.st_result or {}).get('out'))).pack(side='left')
        ttk.Button(act, text=tr('对比图'), command=lambda: core.open_path((self.st_result or {}).get('compare'))
                   ).pack(side='left', padx=(ui.px(8), 0))
        ttk.Button(act, text=tr('在文件夹中显示'), command=lambda: core.reveal((self.st_result or {}).get('out'))
                   ).pack(side='left', padx=(ui.px(8), 0))
        self.st_lbl = FitView(rc, tr('完成后在这里显示'), self.k).pack(fill='both', expand=True)
        self.legend(rc, [(tr('区域对应：同一颜色 = 互相对应'), None), (tr('背景'), '#C8C8C8'), (tr('嘴唇'), '#E04848'),
                         (tr('远近分层：'), None), (tr('远'), '#4A7BE2'), (tr('中'), '#3CB371'), (tr('近'), '#E04848')],
                    right=tr('这一页的结果不加入标定'), view=self.st_lbl)

    def _style_inputs(self):
        mj, gpt = self.st_mj.get().strip(), self.st_gpt.get().strip()
        for p, n in ((mj, tr('MJ 风格图')), (gpt, tr('GPT 图'))):
            if not os.path.isfile(p):
                messagebox.showwarning(APP, tr('请先选「{n}」。', n=n))
                return None
        return mj, gpt

    def do_style(self):
        inp = self._style_inputs()
        if not inp:
            return
        strength, black, bgf = float(self.st_strength.get()), bool(self.st_black.get()), bool(self.st_bg.get())
        kind = self.st_kind.get()
        self.run(lambda log: core.style_only(*inp, strength, black, bgf, log, kind), self.style_done,
                 tr('正在只还原风格，大图需要十几秒（同一场景重画要估远近，约半分钟）……'), view=self.st_lbl)

    def do_regions(self):
        inp = self._style_inputs()
        if not inp:
            return

        def done(path):
            if not path:
                self.status.configure(text=tr('预览没有完成，原因见下方运行记录。'))
                return
            self.st_result = dict(out=path, compare=path)
            self.st_lbl.set(path)
            if os.path.splitext(os.path.basename(path))[0].rstrip('_0123456789').endswith(('_depth_layers', '_远近分层')):
                self.status.configure(text=tr('远近分层预览：蓝 = 远景，绿 = 中景，红 = 近景；每一层单独对齐 MJ 同一层的明暗、颜色和清晰度。'))
            else:
                self.status.configure(text=tr('区域对应预览：同一颜色 = 互相对应；灰 = 背景；暗斜纹 = MJ 里没有对应（用整体风格）；红 = 嘴唇（角色为主时）'))
        kind = self.st_kind.get()
        self.run(lambda log: core.preview_regions(*inp, log, kind), done, tr('正在判断类型、划分区域 / 远近……'), view=self.st_lbl)

    def style_done(self, r):
        if not r:
            self.status.configure(text=tr('只还原风格没有完成，原因见下方运行记录。'))
            return
        self.st_result = r
        self.st_lbl.set(r['compare'])
        self.status.configure(text=tr('只还原风格完成：') + os.path.basename(r['out']))

    # ------------------------------------------------------------ 5 角色设定图
    CS_PROMPTS = (('A', tr('正面头像'), 'prompt_charsheet_front.txt'), ('B', tr('横版四视图'), 'prompt_charsheet_4view.txt'))
    CS_ROLE_BASE = 'outfit, accessories'
    CS_ROLE_OUT = 'outfit (unless described in OUTFIT), accessories'
    CS_HL = 'OUTFIT (overrides @图片2'

    @staticmethod
    def cs_text(fn):
        with open(os.path.join(HERE, fn), encoding='utf-8') as fh:
            return fh.read()

    def build5(self):
        pg = self.t5
        self.header(pg, tr('角色设定图'), tr('按 MJ 参考图做角色设定图：先出正面头像，再出横版四视图，最后（可选）把 MJ 的色调还原回来。'),
                    HELP[4], tr('小技巧'))
        lc, pn = self.top_row(pg)
        self.card_head(lc, '1', tr('三步'), tr('每一步在 GPT 里新开一条消息'))
        st = ttk.Frame(lc)
        st.pack(fill='both', expand=True)
        for c in (0, 2, 4):
            st.columnconfigure(c, weight=1, uniform='st')
        for c in (1, 3):                      # 英文标题更长：箭头那一列窄一点，窗口最窄时三张卡也放得下
            st.columnconfigure(c, minsize=ui.px(16 if i18n.is_en() else 24))
            ttk.Label(st, text='›', style='StepArrow.TLabel').grid(row=0, column=c)
        st.rowconfigure(0, weight=1)

        def stepcard(col, key, title, chips, text, kind='accent', tag=None, button=None):
            fr = ttk.Frame(st, style='Step.TFrame', padding=(ui.px(14), ui.px(12)))
            fr.grid(row=0, column=col, sticky='nsew')
            hd = ttk.Frame(fr, style='Step.In.TFrame')
            hd.pack(fill='x', pady=(0, ui.px(8)))
            ui.Pill(hd, key, kind, bg=ui.STEP_BG, size=12, h=22, radius=6, square=True).pack(side='left', padx=(0, ui.px(8)))
            ttk.Label(hd, text=title, style='StepTitle.TLabel').pack(side='left')
            if tag:
                ui.Pill(hd, *tag, bg=ui.STEP_BG).pack(side='right')
            if chips:
                fl = ui.Flow(fr, ui.STEP_BG)
                fl.pack(fill='x')
                for k, t, kd in chips:
                    fl.add(ui.Chip(fl, k, t, bg=ui.STEP_BG, kind=kd).c)
            lb = ttk.Label(fr, text=nb(text), style='StepText.TLabel', justify='left', wraplength=ui.px(200))
            lb.pack(fill='x', pady=(ui.px(6), 0))
            fr.bind('<Configure>', lambda e, lb=lb: lb.configure(wraplength=max(ui.px(80), e.width - ui.px(30))))
            if button:
                ttk.Button(fr, text=button[0], style='Step.TButton', command=button[1]).pack(anchor='w', pady=(ui.px(10), 0))
        stepcard(0, 'A', tr('正面头像'), [(tr('图片1'), tr('MJ 原图'), 'fc'), ('', tr('比例 3:4'), 'plain')],
                 tr('粘贴提示词 A。多出几张，挑最像、最正的一张'))
        stepcard(2, 'B', tr('横版四视图'), [(tr('图片1'), tr('挑好的正面图'), 'fc'), (tr('图片2'), tr('MJ 原图'), 'fc'), ('', tr('比例 21:9'), 'plain')],
                 tr('粘贴提示词 B（要改服装，先在右边写好）'))
        stepcard(4, 'C', tr('还原色调'), None, tr('到「4 只还原风格」：MJ 风格图选 MJ 原图，GPT 图选四视图，白底自动保护'),
                 kind='grey', tag=(tr('可选'), 'plain'), button=(tr('去 ④ →'), lambda: self.show_page(3)))

        self.card_head(pn, '2', tr('自定义服装'), tag=(tr('可选'), 'plain'), mb=14)
        ttk.Button(pn, text=tr('生成完整提示词 B'), style='Big.TButton', command=self.cs_build).pack(side='bottom', fill='x')
        ttk.Label(pn, text=nb(tr('会写进提示词 B 并自动复制；描述会被记住，下次打开还在。')), style='Hint.TLabel',
                  wraplength=ui.px(340), justify='left').pack(side='bottom', fill='x', pady=(ui.px(8), ui.px(14)))
        self.cs_outfit = tk.Text(pn, wrap='word', height=4, width=1)
        ui.style_text(self.cs_outfit, 'plain')
        self.cs_outfit.tag_configure('ph', foreground=ui.MUTED)
        self.cs_outfit.pack(fill='both', expand=True)
        self._outfit_ph = False
        saved = core.load_state(self.say).get('cs_outfit', '')
        if saved:
            self.cs_outfit.insert('1.0', saved)
        else:
            self._ph_show()
        self.cs_outfit.bind('<FocusIn>', lambda e: self._ph_hide())
        self.cs_outfit.bind('<FocusOut>', lambda e: self._ph_show())

        res = ttk.Frame(pg, style='Page.TFrame')
        res.grid(row=2, column=0, sticky='nsew')
        res.columnconfigure(0, weight=1, uniform='r')
        res.columnconfigure(1, weight=1, uniform='r')
        res.rowconfigure(0, weight=1)
        self.cs_boxes = {}
        for col, (k, name, fn) in enumerate(self.CS_PROMPTS):
            c = self.card(res)
            c.grid(row=0, column=col, sticky='nsew', padx=(0, ui.px(16)) if col == 0 else 0)
            act, _ = self.card_head(c, None, tr('提示词 {k}', k=k), name)
            if k == 'B':
                self.outfit_pill = ui.Pill(act, tr('已加入服装'), 'ok')
            b = ttk.Button(act, text=tr('复制'), style='Small.TButton', command=lambda k=k: self.cs_copy(k))
            b.pack(side='left', padx=(ui.px(8), 0))
            if k == 'B':
                self.cs_copy_b = b
            t = self.text_box(c, height=8)
            try:
                self.set_text(t, self.cs_text(fn))
            except OSError as e:
                self.set_text(t, tr('（读不到 {fn}：{e}）', fn=fn, e=e))
            t.configure(state='disabled')
            self.cs_boxes[k] = t

    def _ph_show(self):
        if not self.cs_outfit.get('1.0', 'end-1c').strip():
            self.cs_outfit.delete('1.0', 'end')
            self.cs_outfit.insert('1.0', self.OUTFIT_PH, ('ph',))
            self._outfit_ph = True

    def _ph_hide(self):
        if self._outfit_ph:
            self.cs_outfit.delete('1.0', 'end')
            self._outfit_ph = False

    def outfit_text(self):
        return '' if self._outfit_ph else self.cs_outfit.get('1.0', 'end-1c').strip()

    def cs_compose(self, outfit):
        base = self.cs_text('prompt_charsheet_4view.txt')
        outfit = outfit.strip()
        if not outfit:
            return base
        p = base.replace(self.CS_ROLE_BASE, self.CS_ROLE_OUT, 1)
        para = 'OUTFIT (overrides @图片2 where they differ): ' + outfit + '\n\n'
        i = p.find('IDENTITY AND DESIGN LOCK')
        return p[:i] + para + p[i:] if i >= 0 else p.rstrip('\n') + '\n\n' + para

    def cs_set_preview(self, k, text):
        self.set_text(self.cs_boxes[k], text, hl=self.CS_HL if k == 'B' else None)

    def cs_build(self):
        outfit = self.outfit_text()
        try:
            core.save_outfit(outfit)
        except OSError:
            pass
        try:
            text = self.cs_compose(outfit)
        except OSError as e:
            messagebox.showerror(APP, tr('读不到提示词 B：{e}', e=e))
            return
        self.cs_set_preview('B', text)
        if not outfit:
            self.outfit_pill.pack_forget()
            self.status.configure(text=tr('服装描述为空：提示词 B 已恢复为基础版（服装按 @图片2）。'))
            return
        self.outfit_pill.pack(side='left', before=self.cs_copy_b)
        self.copy(text, tr('已加入服装描述，完整提示词 B 已复制到剪贴板，去 GPT 里按 Ctrl+V 粘贴。'))

    def cs_copy(self, k):
        self.copy(self.cs_boxes[k].get('1.0', 'end-1c'), tr('提示词 {k} 已复制到剪贴板，去 GPT 里按 Ctrl+V 粘贴。', k=k))


def selftest(root, app, out):
    """测试用：依次截下五个页面后自动关闭（launcher 的 MJ_LAUNCHER_SELFTEST / 命令行 --selftest 图片路径）。"""
    from PIL import ImageGrab
    try:                                  # 截的是屏幕上这块区域：先把窗口放到最前面，免得截到后面别的窗口
        root.attributes('-topmost', True)
        root.lift()
    except tk.TclError:
        pass

    def shot(i=0):
        if i < 5:
            app.nb.select(i)
            root.update()
            root.after(700, lambda: grab(i))
        else:
            root.destroy()

    def grab(i):
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(
            out.replace('.png', f'_{i + 1}.png'))
        shot(i + 1)
    root.after(1200, shot)


def main():
    root = tk.Tk()
    try:
        app = App(root)
    except Exception:
        _write_err(traceback.format_exc(), 'w')
        root.withdraw()
        messagebox.showerror(APP, tr('面板打开失败。\n详情见：') + ERR_LOG)
        sys.exit(1)
    if len(sys.argv) > 2 and sys.argv[1] == '--selftest':
        selftest(root, app, sys.argv[2])
    root.mainloop()


if __name__ == '__main__':
    main()
