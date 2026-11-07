# -*- coding: utf-8 -*-
# Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
"""Image F 界面主题和通用控件（V4.7 界面改版，照「设计稿/Image F 界面改版_静态布局稿.html」做）：
紫色主色、4 级字号、圆角卡片、分段按钮、标签、ⓘ 提示、开关、5 种状态的上传框；以及 Windows 原生拖放（无第三方依赖）。
字号一律按“设计稿像素 × 系统缩放”给出（Tk 负数字号 = 像素），在 100% / 150% / 200% 缩放下比例都一样。"""
from i18n import tr
import math
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

# ---- 颜色（设计稿「颜色」一节）
PAGE = '#F5F6F8'         # 页面底
PANEL = '#FFFFFF'        # 卡片
SUNKEN = '#F1F2F5'       # 凹陷（分段按钮底、查看区）
LINE = '#E6E8EC'         # 边框
LINE2 = '#D6DAE1'        # 控件描边
FG = '#17191F'           # 文字
FG2 = '#4A5160'          # 次文字
MUTED = '#8A909B'        # 提示
FAINT = '#B4B9C2'        # 不可用文字
ACCENT = '#5B3DF5'       # 主色（和 IF 图标一致）
ACCENT_HOVER = '#4B2EE3'
ACCENT_PRESS = '#3F24C9'
ACCENT_SOFT = '#EFEBFF'
ACCENT_FG = '#4A2ED6'
ACCENT_LINE = '#DDD5FF'
OK = '#15803D'
OK_SOFT = '#E8F6EC'
WARN = '#9A5B00'
WARN_SOFT = '#FFF4E0'
REQ = '#B42318'
REQ_SOFT = '#FDECEC'
FIELD = '#FAFBFC'        # 文本框 / 提示词底
TRACK = '#D3D7DE'        # 开关 / 滑块轨道
DISABLED = '#C9CDD6'     # 不可用的主按钮
STEP_BG = '#FCFCFD'      # ⑤页步骤卡
# 旧名字（别的代码可能还在用）
BTN, WARM_SOFT, WARM_FG = SUNKEN, WARN_SOFT, WARN

FAMILY = 'Microsoft YaHei UI'
MONO = 'Consolas'
K = 1.0                  # 系统缩放（apply() 里设）
_IMGS = []               # 保留 PhotoImage 引用
_FONTS = {}


def px(v):
    return int(round(v * K))


def F(size, weight='normal', family=None):
    """设计稿里的像素字号 → Tk 字体（按系统缩放）。"""
    key = (family or FAMILY, size, weight)
    f = _FONTS.get(key)
    if f is None:
        f = _FONTS[key] = tkfont.Font(family=key[0], size=-max(6, px(size)), weight=weight)
    return f


def _family(root):
    try:
        fams = set(tkfont.families(root))
        for f in ('Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', 'Segoe UI'):
            if f in fams:
                return f
    except Exception:
        pass
    return 'TkDefaultFont'


def _hex(c, a=255):
    c = c.lstrip('#')
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def _rr(w, h, r, fill, outline=None, S=4, width=1):
    """抗锯齿圆角矩形 RGBA 图。大尺寸时只把四个角精细绘制，中间用纯色铺开（外观一样，生成快）。"""
    c = 2 * r + 8
    if w > c or h > c:
        sw, sh = min(w, c), min(h, c)
        sm = _rr(sw, sh, r, fill, outline, S, width)
        big = Image.new('RGBA', (w, h), _hex(fill))
        hw, hh = sw // 2, sh // 2
        big.paste(sm.crop((0, 0, hw, hh)), (0, 0))
        big.paste(sm.crop((sw - hw, 0, sw, hh)), (w - hw, 0))
        big.paste(sm.crop((0, sh - hh, hw, sh)), (0, h - hh))
        big.paste(sm.crop((sw - hw, sh - hh, sw, sh)), (w - hw, h - hh))
        if w > 2 * hw:
            big.paste(sm.crop((hw, 0, hw + 1, hh)).resize((w - 2 * hw, hh)), (hw, 0))
            big.paste(sm.crop((hw, sh - hh, hw + 1, sh)).resize((w - 2 * hw, hh)), (hw, h - hh))
        if h > 2 * hh:
            big.paste(sm.crop((0, hh, hw, hh + 1)).resize((hw, h - 2 * hh)), (0, hh))
            big.paste(sm.crop((sw - hw, hh, sw, hh + 1)).resize((hw, h - 2 * hh)), (w - hw, hh))
            if w > 2 * hw:
                big.paste(sm.crop((hw, hh, hw + 1, hh + 1)).resize((w - 2 * hw, h - 2 * hh)), (hw, hh))
        return big
    im = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w * S - 1, h * S - 1), r * S, fill=_hex(fill),
                        outline=_hex(outline) if outline else None, width=max(1, int(width * S)) if outline else 0)
    return im.resize((w, h), Image.LANCZOS)


def _flat(im, bg):
    """把 RGBA 合成到已知底色上，得到不透明 RGB 图（Windows 上 Tk 逐像素混合半透明图片很慢）。"""
    if bg is None or im.mode != 'RGBA':
        return im
    base = Image.new('RGBA', im.size, _hex(bg))
    base.alpha_composite(im)
    return base.convert('RGB')


def _ph(im, bg=PANEL):
    p = ImageTk.PhotoImage(_flat(im, bg))
    _IMGS.append(p)
    return p


_CACHE = {}


def _cached(key, make):
    p = _CACHE.get(key)
    if p is None:
        if len(_CACHE) > 400:
            _CACHE.clear()
        p = _CACHE[key] = make()
    return p


def _circle(d, fill, outline=None, width=1.0, bg=PANEL):
    def make():
        S = 4
        im = Image.new('RGBA', (d * S, d * S), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        dr.ellipse((0, 0, d * S - 1, d * S - 1), fill=_hex(fill) if fill else None,
                   outline=_hex(outline) if outline else None, width=max(1, int(width * S)) if outline else 0)
        return ImageTk.PhotoImage(_flat(im.resize((d, d), Image.LANCZOS), bg))
    return _cached(('circle', d, fill, outline, width, bg), make)


SPIN_N = 12          # 转圈动画帧数


def spinner(d, i, bg=PANEL):
    """处理中的转圈：浅灰圆环 + 一段紫色弧，第 i 帧转 i×30°（抗锯齿，按尺寸和帧缓存）。"""
    def make():
        S = 4
        im = Image.new('RGBA', (d * S, d * S), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        lw = max(2, int(d * S * 0.11))
        box = (lw // 2, lw // 2, d * S - 1 - lw // 2, d * S - 1 - lw // 2)
        dr.ellipse(box, outline=_hex(ACCENT_LINE), width=lw)
        a0 = -90 + i * 360 / SPIN_N
        dr.arc(box, a0, a0 + 100, fill=_hex(ACCENT), width=lw)
        return ImageTk.PhotoImage(_flat(im.resize((d, d), Image.LANCZOS), bg))
    return _cached(('spin', d, i % SPIN_N, bg), make)


def swatch(color, bg=PANEL):
    """图例里的小色块。"""
    s = px(10)
    return _cached(('sw', s, color, bg), lambda: ImageTk.PhotoImage(_flat(_rr(s, s, px(3), color), bg)))


# ======================================================================= 全局样式
def apply(root, k=1.0):
    global FAMILY, K
    K = k
    FAMILY = _family(root)
    _FONTS.clear()
    body = F(13)
    root.configure(bg=PAGE)
    # 注意：不能用 option_add('*Font', ...)——ttk 控件会把它当成自己的 -font，样式里的字号、粗细就全失效了
    root.option_add('*TCombobox*Listbox.background', PANEL)
    root.option_add('*TCombobox*Listbox.foreground', FG)
    root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_SOFT)
    root.option_add('*TCombobox*Listbox.selectForeground', ACCENT_FG)
    root.option_add('*TCombobox*Listbox.font', body)
    st = ttk.Style(root)
    st.theme_use('clam')
    st.configure('.', background=PANEL, foreground=FG, font=body, bordercolor=LINE, lightcolor=PANEL,
                 darkcolor=PANEL, troughcolor=SUNKEN, focuscolor=ACCENT, selectbackground=ACCENT_SOFT,
                 selectforeground=ACCENT_FG, insertcolor=FG)

    # ---- 底板：页面、卡片、下一步条、步骤卡、数字卡
    st.configure('TFrame', background=PANEL)
    st.configure('Page.TFrame', background=PAGE)
    st.configure('Next.In.TFrame', background=ACCENT_SOFT)
    st.configure('Step.In.TFrame', background=STEP_BG)
    st.configure('Stat.In.TFrame', background=SUNKEN)
    for name, (r, fill, outline, bg) in {'Card': (12, PANEL, LINE, PAGE), 'Next': (12, ACCENT_SOFT, ACCENT_LINE, PAGE),
                                         'Step': (10, STEP_BG, LINE, PANEL), 'Stat': (10, SUNKEN, None, PANEL)}.items():
        el = 'IF.' + name
        st.element_create(el, 'image', _ph(_rr(px(400), px(400), px(r), fill, outline), bg), border=px(r) + 1,
                          padding=0, sticky='nsew', width=px(2 * r + 4), height=px(2 * r + 4))
        st.layout(name + '.TFrame', [(el, {'sticky': 'nsew'})])
        st.configure(name + '.TFrame', background=fill)

    # ---- 文字（设计稿 4 级：页面名 20 粗 → 卡片标题 14 粗 → 正文 13 → 提示 12 灰）
    def lab(name, bg, fg, font):
        st.configure(name, background=bg, foreground=fg, font=font)
    lab('TLabel', PANEL, FG, body)
    lab('Page.TLabel', PAGE, FG, body)
    lab('Title.TLabel', PAGE, FG, F(20, 'bold'))
    lab('Lead.TLabel', PAGE, FG2, F(13))
    lab('Help.TLabel', PAGE, ACCENT_FG, F(12.5))
    lab('CardTitle.TLabel', PANEL, FG, F(14, 'bold'))
    lab('CardSub.TLabel', PANEL, MUTED, F(12))
    lab('Field.TLabel', PANEL, FG2, F(12, 'bold'))
    lab('FieldDis.TLabel', PANEL, FAINT, F(12, 'bold'))
    lab('Zone.TLabel', PANEL, FG, F(13, 'bold'))
    lab('ZoneDis.TLabel', PANEL, FAINT, F(13, 'bold'))
    lab('Ref.TLabel', PANEL, MUTED, F(12))
    lab('Hint.TLabel', PANEL, MUTED, F(12))
    lab('Link.TLabel', PANEL, ACCENT_FG, F(12))
    lab('Body2.TLabel', PANEL, FG2, F(12.5))
    lab('Value.TLabel', PANEL, FG, F(13, 'bold'))
    lab('Status.TLabel', PANEL, FG2, F(12))
    lab('StatusLink.TLabel', PANEL, FG2, F(12))
    lab('Drawer.TLabel', PANEL, FG, F(12, 'bold'))
    lab('Next.TLabel', ACCENT_SOFT, FG, F(13.5, 'bold'))
    lab('NextStep.TLabel', ACCENT_SOFT, FG2, F(12.5))
    lab('NextArrow.TLabel', ACCENT_SOFT, '#B3A6F5', F(16))
    lab('StepTitle.TLabel', STEP_BG, FG, F(13.5, 'bold'))
    lab('StepText.TLabel', STEP_BG, MUTED, F(12))
    lab('StepArrow.TLabel', PANEL, '#B9BEC7', F(18))
    lab('Stat.TLabel', SUNKEN, FG, F(22, 'bold'))
    lab('StatSub.TLabel', SUNKEN, MUTED, F(12))
    # 旧样式名（弹出的小窗口等还在用）
    lab('Step.TLabel', PANEL, FG, F(14, 'bold'))
    lab('Cap.TLabel', PANEL, MUTED, F(12, 'bold'))
    lab('Next.Old.TLabel', WARN_SOFT, WARN, F(13, 'bold'))

    # ---- 按钮：主按钮（紫，42 高）/ 小主按钮（32 高）/ 次按钮（白底描边，30 高）/ 大次按钮（42 高）
    def btn(name, h, r, cols, outline, font, fg, fg_dis, bg_list, padx=14):
        for bg, suffix in bg_list:
            imgs = [_ph(_rr(px(360), px(h), px(r), c, o), bg) for c, o in zip(cols, outline)]
            el = f'IF.{name}{suffix}.bg'
            st.element_create(el, 'image', imgs[0], ('disabled', imgs[3]), ('pressed', imgs[2]), ('active', imgs[1]),
                              border=px(r) + 1, padding=0, sticky='nsew', width=px(2 * r + 8), height=px(h))
            s = f'{suffix.strip(".") + "." if suffix else ""}{name}'
            st.layout(s, [(el, {'sticky': 'nsew', 'children': [('Button.padding', {'sticky': 'nsew', 'children': [
                ('Button.label', {'sticky': 'nsew'})]})]})])
            st.configure(s, foreground=fg, padding=(px(padx), 0), anchor='center', font=font)
            st.map(s, foreground=[('disabled', fg_dis)])
    on_bgs = [(PANEL, ''), (ACCENT_SOFT, '.Next'), (STEP_BG, '.Step')]
    sec = ((PANEL, '#F7F8FA', '#EEF0F3', FIELD), (LINE2, LINE2, LINE2, LINE))
    pri = ((ACCENT, ACCENT_HOVER, ACCENT_PRESS, DISABLED), (None,) * 4)
    btn('TButton', 30, 8, *sec, F(12.5), FG, FAINT, on_bgs, 12)
    btn('Lg.TButton', 42, 10, *sec, F(13), FG, FAINT, on_bgs[:1], 16)
    btn('Big.TButton', 42, 10, *pri, F(14, 'bold'), '#FFFFFF', '#FFFFFF', on_bgs[:1], 18)
    btn('Accent.TButton', 42, 10, *pri, F(14, 'bold'), '#FFFFFF', '#FFFFFF', on_bgs[:1], 18)
    btn('Small.TButton', 32, 8, *pri, F(13, 'bold'), '#FFFFFF', '#FFFFFF', on_bgs[:2], 14)

    # ---- 开关
    sw, sh = px(34), px(20)

    def switch(on, dis=False):
        S = 4
        im = Image.new('RGBA', (sw * S, sh * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        a = 115 if dis else 255
        d.rounded_rectangle((0, 0, sw * S - 1, sh * S - 1), sh * S // 2, fill=_hex(ACCENT if on else TRACK, a))
        m = 2 * S
        kd = sh * S - 2 * m
        x0 = (sw * S - m - kd) if on else m
        d.ellipse((x0, m, x0 + kd, m + kd), fill=_hex('#ffffff', 255))
        return _ph(im.resize((sw, sh), Image.LANCZOS))
    st.element_create('IF.Switch', 'image', switch(False),
                      ('disabled', 'selected', switch(True, True)), ('disabled', switch(False, True)),
                      ('selected', switch(True)), sticky='')
    st.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nsew', 'children': [
        ('IF.Switch', {'side': 'left', 'sticky': ''}), ('Checkbutton.label', {'side': 'left', 'sticky': 'nsew'})]})])
    st.configure('TCheckbutton', background=PANEL, foreground=FG, padding=0)
    st.map('TCheckbutton', background=[('active', PANEL)], foreground=[('disabled', FAINT)])

    # ---- 单选（只有弹出的小窗口可能用到）
    rd = px(16)

    def radio(on):
        S = 4
        im = Image.new('RGBA', ((rd + px(8)) * S, rd * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((0, 0, rd * S - 1, rd * S - 1), fill=_hex(ACCENT if on else TRACK))
        q = rd * S * (0.32 if on else 0.1)
        d.ellipse((q, q, rd * S - q, rd * S - q), fill=_hex('#ffffff'))
        return _ph(im.resize((rd + px(8), rd), Image.LANCZOS))
    st.element_create('IF.Radio', 'image', radio(False), ('selected', radio(True)), sticky='')
    st.layout('TRadiobutton', [('Radiobutton.padding', {'sticky': 'nsew', 'children': [
        ('IF.Radio', {'side': 'left', 'sticky': ''}), ('Radiobutton.label', {'side': 'left', 'sticky': 'nsew'})]})])
    st.configure('TRadiobutton', background=PANEL, foreground=FG, padding=(0, px(2)))
    st.map('TRadiobutton', background=[('active', PANEL)])

    # ---- 滑块：细轨道 + 白底紫圈圆钮
    th, kd = px(20), px(16)

    def trough(fill):
        S = 4
        im = Image.new('RGBA', (px(40) * S, th * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        y = th * S // 2
        d.rounded_rectangle((0, y - 2 * S, px(40) * S - 1, y + 2 * S), 2 * S, fill=_hex(fill))
        return _ph(im.resize((px(40), th), Image.LANCZOS))

    def knob(c):
        S = 4
        im = Image.new('RGBA', (kd * S, kd * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((0, 0, kd * S - 1, kd * S - 1), fill=_hex(c))
        d.ellipse((S * 2.2, S * 2.2, kd * S - 1 - S * 2.2, kd * S - 1 - S * 2.2), fill=_hex('#ffffff'))
        return _ph(im.resize((kd, kd), Image.LANCZOS))
    st.element_create('IF.Horizontal.Scale.trough', 'image', trough(TRACK), border=(px(8), 0), sticky='ew')
    st.element_create('IF.Horizontal.Scale.slider', 'image', knob(ACCENT), ('disabled', knob(DISABLED)),
                      ('active', knob(ACCENT_HOVER)), sticky='')
    st.layout('Horizontal.TScale', [('IF.Horizontal.Scale.trough', {'sticky': 'ew', 'children': [
        ('IF.Horizontal.Scale.slider', {'side': 'left', 'sticky': ''})]})])
    st.configure('Horizontal.TScale', background=PANEL)

    # ---- 输入框 / 下拉 / 数字框
    for s in ('TEntry', 'TCombobox', 'TSpinbox'):
        st.configure(s, fieldbackground=PANEL, background=PANEL, foreground=FG, bordercolor=LINE2,
                     lightcolor=PANEL, darkcolor=PANEL, arrowcolor=MUTED, padding=(px(8), px(4)), insertcolor=FG,
                     arrowsize=px(12))
        st.map(s, bordercolor=[('focus', ACCENT), ('disabled', LINE)], lightcolor=[('focus', PANEL)],
               fieldbackground=[('readonly', PANEL), ('disabled', FIELD)], foreground=[('disabled', FAINT)],
               selectbackground=[('readonly', PANEL)], selectforeground=[('readonly', FG)])

    # ---- 滚动条（细、灰）
    for s in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        st.configure(s, background='#DCDFE4', troughcolor=PANEL, bordercolor=PANEL, lightcolor='#DCDFE4',
                     darkcolor='#DCDFE4', arrowcolor=FAINT, gripcount=0, arrowsize=px(11))
        st.map(s, background=[('active', '#C9CCD2')])

    # ---- 表格
    st.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=px(32), bordercolor=LINE,
                 lightcolor=PANEL, darkcolor=PANEL, font=F(12.5))
    st.map('Treeview', background=[('selected', ACCENT_SOFT)], foreground=[('selected', ACCENT_FG)])
    st.configure('Treeview.Heading', background=SUNKEN, foreground=MUTED, relief='flat', bordercolor=LINE,
                 lightcolor=SUNKEN, darkcolor=SUNKEN, font=F(12, 'bold'), padding=(px(10), px(6)))
    st.map('Treeview.Heading', background=[('active', '#E9EBEF')])
    return st


def style_text(t, kind='plain'):
    """tk.Text（不是 ttk）的统一外观。kind: code=提示词, log=运行记录, plain=输入框。
    提示词和运行记录里中文很多（@图片1、运行记录全是中文），Consolas 没有中文字形，Windows 会退到点阵宋体，
    很难看——所以都用雅黑（略小一号），不用等宽字体。"""
    font = F(12.5) if kind == 'code' else F(12) if kind == 'log' else F(13)
    t.configure(bg=FIELD if kind != 'plain' else PANEL, fg='#30364A' if kind == 'code' else FG2 if kind == 'log' else FG,
                relief='flat', borderwidth=0, highlightthickness=1, highlightbackground=LINE if kind != 'plain' else LINE2,
                highlightcolor=ACCENT, insertbackground=FG, selectbackground='#DCD3FF', selectforeground=FG,
                padx=px(12), pady=px(10), font=font, spacing1=0, spacing3=px(2))
    t.tag_configure('hl', background=ACCENT_SOFT, foreground=ACCENT_FG)


# ======================================================================= 小控件
PILL = dict(req=(REQ_SOFT, REQ), auto=(ACCENT_SOFT, ACCENT_FG), ok=(OK_SOFT, OK), plain=(SUNKEN, FG2),
            warn=(WARN_SOFT, WARN), dark=(FG, '#FFFFFF'), accent=(ACCENT, '#FFFFFF'), grey=(MUTED, '#FFFFFF'),
            white=('#FFFFFF', ACCENT_FG))


class Pill:
    """圆角小标签（必选 / 可选 / 来自 ① / 已复制 …），也用来画编号方块和圆圈。"""

    def __init__(self, parent, text='', kind='plain', bg=PANEL, size=11, bold=True, h=20, padx=7, radius=None,
                 square=False, outline=None):
        self.bg, self.size, self.bold, self.h, self.padx = bg, size, bold, h, padx
        self.radius, self.square, self.outline = radius, square, outline
        self.lbl = tk.Label(parent, bd=0, padx=0, pady=0, highlightthickness=0, bg=bg, compound='center')
        self.text = self.kind = None
        self.set(text, kind)

    def set(self, text, kind=None):
        kind = kind or self.kind or 'plain'
        if (text, kind) == (self.text, self.kind):
            return
        self.text, self.kind = text, kind
        fill, fg = PILL.get(kind, PILL['plain'])
        f = F(self.size, 'bold' if self.bold else 'normal')
        h = px(self.h)
        w = h if self.square else f.measure(text) + 2 * px(self.padx)
        r = px(self.radius) if self.radius is not None else h // 2
        img = _cached(('pill', w, h, r, fill, self.outline, self.bg),
                      lambda: ImageTk.PhotoImage(_flat(_rr(w, h, r, fill, self.outline), self.bg)))
        self.lbl.configure(image=img, text=text, fg=fg, font=f, width=w, height=h)

    def pack(self, **kw):
        self.lbl.pack(**kw)
        return self

    def grid(self, **kw):
        self.lbl.grid(**kw)
        return self

    def pack_forget(self):
        self.lbl.pack_forget()


def badge(parent, text, bg=PANEL, kind='dark'):
    """卡片标题前的编号小方块（深色圆角 20×20）。"""
    return Pill(parent, text, kind, bg=bg, size=11.5, h=20, radius=6, square=True)


def step_circle(parent, text, bg=ACCENT_SOFT):
    """下一步条里的步骤编号：白底紫字圆圈。"""
    return Pill(parent, text, 'white', bg=bg, size=11.5, h=20, square=True, outline='#D3C9FF')


def _info_img(bg, color='#B6BCC6'):
    d = px(15)

    def make():
        S = 4
        im = Image.new('RGBA', (d * S, d * S), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        dr.ellipse((S // 2, S // 2, d * S - 1 - S // 2, d * S - 1 - S // 2), outline=_hex(color), width=S)
        c = d * S / 2
        lw = d * S * 0.12
        dr.ellipse((c - lw * 0.75, d * S * 0.22, c + lw * 0.75, d * S * 0.22 + lw * 1.5), fill=_hex(color))
        dr.rounded_rectangle((c - lw / 2, d * S * 0.42, c + lw / 2, d * S * 0.76), lw / 2, fill=_hex(color))
        return ImageTk.PhotoImage(_flat(im.resize((d, d), Image.LANCZOS), bg))
    return _cached(('info', d, bg, color), make)


def info_icon(parent, text, bg=PANEL):
    """ⓘ：鼠标放上去显示说明。"""
    lb = tk.Label(parent, image=_info_img(bg), bg=bg, bd=0, highlightthickness=0, cursor='question_arrow')
    lb.tip = Tip(lb, text)
    return lb


def help_link(parent, text, tip, command, bg=PAGE):
    """页头右上角「ⓘ 这一页怎么用」：鼠标放上去显示简短说明，点击打开使用说明。"""
    lb = tk.Label(parent, image=_info_img(bg, ACCENT_FG), text=' ' + text, compound='left', bg=bg, fg=ACCENT_FG,
                  font=F(12.5), bd=0, highlightthickness=0, cursor='hand2')
    lb.tip = Tip(lb, tip, wrap=420)
    lb.bind('<Button-1>', lambda e: command())
    return lb


class Tip:
    """鼠标悬停提示（白底细边框，最多 320 像素宽）。"""

    def __init__(self, widget, text, wrap=320):
        self.w, self.text, self.wrap = widget, text, wrap
        self.top, self._after = None, None
        widget.bind('<Enter>', self._enter, add='+')
        widget.bind('<Leave>', self._leave, add='+')
        widget.bind('<ButtonPress>', self._leave, add='+')

    def set(self, text):
        self.text = text

    def _enter(self, e=None):
        self._cancel()
        self._after = self.w.after(350, self._show)

    def _cancel(self):
        if self._after:
            try:
                self.w.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _leave(self, e=None):
        self._cancel()
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None

    def _show(self):
        self._after = None
        if not self.text or self.top is not None:
            return
        try:
            top = tk.Toplevel(self.w)
        except tk.TclError:
            return
        top.wm_overrideredirect(True)
        try:
            top.attributes('-topmost', True)
        except tk.TclError:
            pass
        fr = tk.Frame(top, bg=LINE2, padx=1, pady=1)
        fr.pack()
        tk.Label(fr, text=self.text, bg=PANEL, fg=FG2, font=F(12), justify='left', wraplength=px(self.wrap),
                 padx=px(12), pady=px(8)).pack()
        top.update_idletasks()
        x = self.w.winfo_rootx()
        y = self.w.winfo_rooty() + self.w.winfo_height() + px(6)
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        tw, th = top.winfo_reqwidth(), top.winfo_reqheight()
        x = max(4, min(x, sw - tw - 8))
        if y + th > sh - 40:
            y = self.w.winfo_rooty() - th - px(6)
        top.geometry(f'+{x}+{y}')
        self.top = top


def ellipsize(text, font, maxw):
    if font.measure(text) <= maxw:
        return text
    lo, hi = 1, len(text)
    best = '…'
    while lo <= hi:
        n = (lo + hi) // 2
        a, b = (n + 1) // 2, n // 2
        t = text[:a] + '…' + (text[-b:] if b else '')
        if font.measure(t) <= maxw:
            best, lo = t, n + 1
        else:
            hi = n - 1
    return best


class Seg:
    """分段按钮（多选一）。options = [(值, 文字)]；cols = 每行几个（④页图片类型是 2×2）。
    点击才调用 command；变量被代码改了也会自动重画。"""
    H, PAD, GAP = 30, 3, 2

    def __init__(self, parent, var, options, cols=None, command=None, bg=PANEL):
        self.var, self.options, self.command, self.bg = var, list(options), command, bg
        self.cols = cols or len(self.options)
        self.rows = math.ceil(len(self.options) / self.cols)
        self.enabled, self.hover = True, None
        h = px(self.PAD * 2 + self.H * self.rows + self.GAP * (self.rows - 1))
        self.canvas = tk.Canvas(parent, height=h, width=1, bg=bg, highlightthickness=0, bd=0, cursor='hand2')
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.canvas.bind('<Button-1>', self._click)
        self.canvas.bind('<Motion>', self._motion)
        self.canvas.bind('<Leave>', lambda e: self._set_hover(None))
        var.trace_add('write', lambda *a: self.redraw())

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def grid(self, **kw):
        self.canvas.grid(**kw)
        return self

    def set_text(self, value, text):
        self.options = [(v, text if v == value else t) for v, t in self.options]
        self.redraw()

    def set_enabled(self, on):
        self.enabled = bool(on)
        self.canvas.configure(cursor='hand2' if on else 'arrow')
        self.redraw()

    def _cells(self):
        w = self.canvas.winfo_width()
        P, G, H = px(self.PAD), px(self.GAP), px(self.H)
        cw = (w - 2 * P - G * (self.cols - 1)) / self.cols
        for i, (v, t) in enumerate(self.options):
            r, c = divmod(i, self.cols)
            x0 = P + c * (cw + G)
            y0 = P + r * (H + G)
            yield i, v, t, (int(round(x0)), y0, int(round(x0 + cw)), y0 + H)

    def _hit(self, x, y):
        for i, v, t, (x0, y0, x1, y1) in self._cells():
            if x0 <= x < x1 and y0 <= y < y1:
                return i
        return None

    def _click(self, e):
        i = self._hit(e.x, e.y)
        if i is None or not self.enabled:
            return
        v = self.options[i][0]
        if self.var.get() != v:
            self.var.set(v)
            if self.command:
                self.command()

    def _motion(self, e):
        self._set_hover(self._hit(e.x, e.y))

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.redraw()

    def redraw(self):
        c = self.canvas
        w, h = c.winfo_width(), int(c.cget('height'))
        if w < 20:
            return
        c.delete('all')
        bgimg = _cached(('segbg', w, h, self.bg), lambda: ImageTk.PhotoImage(_flat(_rr(w, h, px(9), SUNKEN), self.bg)))
        c.create_image(0, 0, image=bgimg, anchor='nw')
        cur = self.var.get()
        for i, v, t, (x0, y0, x1, y1) in self._cells():
            on = v == cur
            if on:
                cw, chh = x1 - x0, y1 - y0

                def make(cw=cw, chh=chh):
                    S = 4
                    im = Image.new('RGBA', (cw * S, (chh + 1) * S), (0, 0, 0, 0))
                    d = ImageDraw.Draw(im)
                    d.rounded_rectangle((0, S, cw * S - 1, (chh + 1) * S - 1), px(7) * S, fill=(20, 30, 60, 34))
                    d.rounded_rectangle((0, 0, cw * S - 1, chh * S - 1), px(7) * S, fill=_hex('#FFFFFF'))
                    return ImageTk.PhotoImage(_flat(im.resize((cw, chh + 1), Image.LANCZOS), SUNKEN))
                c.create_image(x0, y0, image=_cached(('segon', cw, chh), make), anchor='nw')
            fg = (FG if on else (FG if self.hover == i else FG2)) if self.enabled else FAINT
            f = F(12.5, 'bold' if on else 'normal')
            c.create_text((x0 + x1) // 2, (y0 + y1) // 2, text=ellipsize(t, f, x1 - x0 - px(8)), fill=fg, font=f)


class Chip:
    """下一步条 / 步骤卡里的“图片1 MJ 原图”标签：白底紫边，键名紫色加粗。kind='plain' = 灰底小标签（比例 3:4）。"""

    def __init__(self, parent, key, text, bg=ACCENT_SOFT, kind='fc'):
        self.bg, self.kind = bg, kind
        self.c = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
        self.tip = Tip(self.c, '')
        self.set(key, text)

    def set(self, key, text, tip=''):
        self.key, self.text = key, text
        self.tip.set(tip)
        c = self.c
        c.delete('all')
        fk, ft = F(12, 'bold'), F(12 if self.kind == 'fc' else 11.5)
        pad, gap = px(8), px(6)
        wk = fk.measure(key) if key else 0
        w = pad * 2 + wk + (gap if key else 0) + ft.measure(text)
        h = px(24 if self.kind == 'fc' else 21)
        if self.kind == 'fc':
            img = _cached(('chip', w, h, self.bg), lambda: ImageTk.PhotoImage(_flat(_rr(w, h, px(7), '#FFFFFF', '#D9D0FF'), self.bg)))
        else:
            img = _cached(('chipr', w, h, self.bg), lambda: ImageTk.PhotoImage(_flat(_rr(w, h, px(6), SUNKEN), self.bg)))
        c.configure(width=w, height=h)
        c.create_image(0, 0, image=img, anchor='nw')
        x = pad
        if key:
            c.create_text(x, h // 2, text=key, anchor='w', fill=ACCENT_FG, font=fk)
            x += wk + gap
        c.create_text(x, h // 2, text=text, anchor='w', fill=FG if self.kind == 'fc' else FG2, font=ft)

    def pack(self, **kw):
        self.c.pack(**kw)
        return self

    def pack_forget(self):
        self.c.pack_forget()


class Flow(tk.Frame):
    """把小标签按宽度自动换行排开（步骤卡里的 chips）。"""

    def __init__(self, parent, bg, gap=6):
        super().__init__(parent, bg=bg, width=1, height=1)
        self.items, self.gap = [], px(gap)
        self.bind('<Configure>', self._lay)

    def add(self, w):
        self.items.append(w)
        self.after_idle(self._lay)
        return w

    def _lay(self, e=None):
        W = max(self.winfo_width(), 40)
        x = y = rowh = 0
        for w in self.items:
            rw, rh = w.winfo_reqwidth(), w.winfo_reqheight()
            if x > 0 and x + rw > W:
                x, y, rowh = 0, y + rowh + self.gap, 0
            w.place(x=x, y=y)
            x += rw + self.gap
            rowh = max(rowh, rh)
        H = max(1, y + rowh)
        if int(self.cget('height')) != H:
            self.configure(height=H)


class NavItem:
    """左侧导航的一项：编号圆圈 + 页面名 + 一句副标题；当前页浅紫底、左侧紫色竖条。"""

    def __init__(self, parent, num, title, sub, command, width):
        self.num, self.title, self.sub, self.command = num, title, sub, command
        self.on = self.hover = False
        self.c = tk.Canvas(parent, height=px(54), width=width, bg=PANEL, highlightthickness=0, bd=0, cursor='hand2')
        self.c.bind('<Configure>', lambda e: self.draw())
        self.c.bind('<Button-1>', lambda e: command())
        self.c.bind('<Enter>', lambda e: self._hover(True))
        self.c.bind('<Leave>', lambda e: self._hover(False))

    def _hover(self, v):
        self.hover = v
        self.draw()

    def set(self, on):
        self.on = on
        self.draw()

    def draw(self):
        c = self.c
        w, h = c.winfo_width(), int(c.cget('height'))
        if w < 40:
            return
        c.delete('all')
        x0, x1 = px(12), w - px(12)
        if self.on or self.hover:
            fill = ACCENT_SOFT if self.on else '#F6F7F9'
            bw = x1 - x0
            c.create_image(x0, 0, anchor='nw', image=_cached(('navbg', bw, h, fill),
                                                             lambda: ImageTk.PhotoImage(_flat(_rr(bw, h, px(10), fill), PANEL))))
        if self.on:
            c.create_image(0, px(10), anchor='nw', image=_cached(('navbar', h), lambda: ImageTk.PhotoImage(
                _flat(_rr(px(6), h - px(20), px(3), ACCENT), PANEL).crop((px(3), 0, px(6), h - px(20))))))
        d = px(22)
        cx, cy = x0 + px(10) + d // 2, px(10) + d // 2
        bg = ACCENT_SOFT if self.on else ('#F6F7F9' if self.hover else PANEL)
        c.create_image(cx, cy, image=_circle(d, ACCENT if self.on else SUNKEN, bg=bg))
        c.create_text(cx, cy, text=self.num, fill='#FFFFFF' if self.on else FG2, font=F(12, 'bold'))
        tx = x0 + px(10) + d + px(10)
        c.create_text(tx, px(9), anchor='nw', text=self.title, fill=ACCENT_FG if self.on else FG, font=F(13.5, 'bold'))
        c.create_text(tx, px(30), anchor='nw', text=self.sub, fill=MUTED, font=F(11.5))


def dot(parent, color, bg=PANEL):
    d = px(8)
    lb = tk.Label(parent, image=_circle(d, color, bg=bg), bg=bg, bd=0, highlightthickness=0)
    lb.set = lambda col: lb.configure(image=_circle(d, col, bg=bg))
    return lb


# ======================================================================= 拖放上传框
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff')


def _dash_rr(w, h, r, fill, border, S=3, dash=(7, 5), width=1.5):
    im = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = int(1.2 * S)
    x0, y0, x1, y1 = pad, pad, w * S - pad, h * S - pad
    R = r * S
    d.rounded_rectangle((x0, y0, x1, y1), R, fill=_hex(fill))
    pts = []

    def line(a, b):
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1])))
        pts.extend((a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n))

    def arc(cx, cy, a0):
        n = max(4, int(R * 1.6))
        angles = (math.radians(a0 + 90 * i / n) for i in range(n))
        pts.extend((cx + R * math.cos(t), cy + R * math.sin(t)) for t in angles)

    for edge, corner in ((((x0 + R, y0), (x1 - R, y0)), (x1 - R, y0 + R, -90)),
                         (((x1, y0 + R), (x1, y1 - R)), (x1 - R, y1 - R, 0)),
                         (((x1 - R, y1), (x0 + R, y1)), (x0 + R, y1 - R, 90)),
                         (((x0, y1 - R), (x0, y0 + R)), (x0 + R, y0 + R, 180))):
        line(*edge)
        arc(*corner)
    pts.append(pts[0])
    on, off = dash[0] * S, dash[1] * S
    acc, col, lw = 0.0, _hex(border), max(1, int(width * S))
    seg = []
    for a, b in zip(pts, pts[1:]):
        if (acc % (on + off)) < on:
            if not seg:
                seg.append(a)
            seg.append(b)
        elif seg:
            d.line(seg, fill=col, width=lw, joint='curve')
            seg = []
        acc += math.hypot(b[0] - a[0], b[1] - a[1])
    if seg:
        d.line(seg, fill=col, width=lw, joint='curve')
    t = r + 6
    if w <= 2 * t + 8 or h <= 2 * t + 8:
        return im.resize((w, h), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), _hex(fill))
    m = 4

    def band(bx0, by0, bx1, by1):
        X0, Y0, X1, Y1 = max(0, bx0 - m), max(0, by0 - m), min(w, bx1 + m), min(h, by1 + m)
        part = im.crop((X0 * S, Y0 * S, X1 * S, Y1 * S)).resize((X1 - X0, Y1 - Y0), Image.LANCZOS)
        out.paste(part.crop((bx0 - X0, by0 - Y0, bx1 - X0, by1 - Y0)), (bx0, by0))
    for box in ((0, 0, w, t), (0, h - t, w, h), (0, t, t, h - t), (w - t, t, w, h - t)):
        band(*box)
    return out


def _filled_bg(w, h, r, bar, bg):
    """已放图的框：浅灰底 + 底部白色文件名条 + 1px 边框，四角圆。"""
    S = 3
    a = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    ImageDraw.Draw(a).rounded_rectangle((0, 0, w * S - 1, h * S - 1), r * S, fill=_hex('#EEF0F3'))
    b = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
    ImageDraw.Draw(b).rounded_rectangle((0, 0, w * S - 1, h * S - 1), r * S, fill=_hex('#FFFFFF'))
    y = (h - bar) * S
    a.paste(b.crop((0, y, w * S, h * S)), (0, y))
    d = ImageDraw.Draw(a)
    d.line((0, y, w * S, y), fill=_hex(LINE), width=S)
    d.rounded_rectangle((0, 0, w * S - 1, h * S - 1), r * S, outline=_hex(LINE), width=S)
    return a.resize((w, h), Image.LANCZOS)


def _plus(D, fill, cross, under):
    """圆形加号，直接合成在上传框的底色（under）上——不再贴一张白底图（旧版四个白角的来源）。"""
    S = 4
    im = Image.new('RGBA', (D * S, D * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, D * S - 1, D * S - 1), fill=_hex(fill))
    c, L, lw = D * S / 2, D * S * 0.19, max(2, int(D * S * 0.055))
    d.rounded_rectangle((c - L, c - lw / 2, c + L, c + lw / 2), lw / 2, fill=_hex(cross))
    d.rounded_rectangle((c - lw / 2, c - L, c + lw / 2, c + L), lw / 2, fill=_hex(cross))
    return _flat(im.resize((D, D), Image.LANCZOS), under)


def _xbtn(D):
    S = 4
    im = Image.new('RGBA', (D * S, D * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, D * S - 1, D * S - 1), fill=(23, 25, 31, 150))
    c, L, lw = D * S / 2, D * S * 0.17, max(2, int(D * S * 0.075))
    d.line((c - L, c - L, c + L, c + L), fill=(255, 255, 255, 255), width=lw)
    d.line((c - L, c + L, c + L, c - L), fill=(255, 255, 255, 255), width=lw)
    return im.resize((D, D), Image.LANCZOS)


class DropZone:
    """上传框（设计稿「上传框的 5 种状态」）：空 / 鼠标移上 / 已放图（整张缩略图 + 文件名条 + 右上角 × 清除，点图片更换）/
    自动带入（标题右侧紫色「来自 ①」）/ 当前模式用不到（灰）。点击 = pick()；拖入 = accept(path)；路径存在 var 里。
    optional=True 的框（蒙版）多张图一起拖进来时不会被顺带填上。"""

    def __init__(self, parent, var, title, pick, k=1.0, height=150, hint=None, on_set=None, optional=False,
                 ref=None, tag=None, link=None, tip=None, expand=False, empty=tr('拖入或点击上传'), disabled_text=tr('当前模式用不到')):
        self.var, self.pick, self.on_set, self.optional = var, pick, on_set, optional
        self.clearable = optional                       # 旧名字
        self.empty, self.disabled_text = empty, disabled_text
        self.enabled, self.hover = True, False
        self._thumb = self._thumb_key = self._dims = None
        self._drawn = self._after = None
        self.frame = ttk.Frame(parent)
        head = ttk.Frame(self.frame)
        head.pack(fill='x', pady=(0, px(6)))
        self.title_lbl = ttk.Label(head, text=title, style='Zone.TLabel')
        self.title_lbl.pack(side='left')
        if ref:
            ttk.Label(head, text=ref, style='Ref.TLabel').pack(side='left', padx=(px(6), 0))
        self.tag = Pill(head, tag[0], tag[1]).pack(side='right') if tag else None
        self.canvas = tk.Canvas(self.frame, height=px(height), width=1, bg=PANEL, highlightthickness=0, bd=0,
                                cursor='hand2')
        self.canvas.pack(fill='both' if expand else 'x', expand=expand)
        hr = ttk.Frame(self.frame)
        hr.pack(fill='x', pady=(px(6), 0))
        self.hint_lbl = ttk.Label(hr, text=hint or '', style='Hint.TLabel', **({} if tip else dict(width=1)))
        self.hint_lbl.pack(side='left', fill='x' if not tip else None, expand=not tip)
        if tip:
            info_icon(hr, tip).pack(side='left', padx=(px(6), 0))
        if link:
            lk = ttk.Label(hr, text=link[0], style='Link.TLabel', cursor='hand2')
            lk.pack(side='right')
            lk.bind('<Button-1>', lambda e: link[1]())
        self.canvas.bind('<Configure>', lambda e: self.schedule())
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<Enter>', lambda e: self._set_hover(True))
        self.canvas.bind('<Leave>', lambda e: self._set_hover(False))
        var.trace_add('write', lambda *a: self.redraw(force=True))

    # ---- 状态
    def set_hint(self, text):
        self.hint_lbl.configure(text=text or '')

    def set_tag(self, text, kind=None):
        if self.tag:
            self.tag.set(text, kind)

    def set_enabled(self, on, text=None):
        self.enabled = bool(on)
        if text:
            self.disabled_text = text
        self.canvas.configure(cursor='hand2' if on else 'arrow')
        self.title_lbl.configure(style='Zone.TLabel' if on else 'ZoneDis.TLabel')
        self.redraw(force=True)

    def schedule(self, delay=80):
        if self._after is not None:
            try:
                self.canvas.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = self.canvas.after(delay, self._run_scheduled)

    def _run_scheduled(self):
        self._after = None
        self.redraw()

    def _set_hover(self, v):
        self.hover = v
        self.redraw()

    def on_click(self, e=None):
        if not self.enabled:
            return
        cur = self.canvas.find_withtag('current')
        if cur and 'clear' in self.canvas.gettags(cur[0]):
            self.var.set('')
            return
        self.pick()

    def accept(self, path):
        """拖入的文件。不是图片或框不可用时返回 False。"""
        if not self.enabled or not (os.path.isfile(path) and path.lower().endswith(IMG_EXT)):
            return False
        p = os.path.normpath(path)
        if self.on_set:
            self.on_set(p)
        else:
            self.var.set(p)
        return True

    def contains(self, x, y):
        c = self.canvas
        try:
            if not c.winfo_viewable():
                return False
            X, Y = c.winfo_rootx(), c.winfo_rooty()
            return X <= x < X + c.winfo_width() and Y <= y < Y + c.winfo_height()
        except tk.TclError:
            return False

    # ---- 绘制
    def redraw(self, force=False):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:
            return
        p = self.var.get().strip()
        has = bool(p) and os.path.isfile(p) and self.enabled
        hov = self.hover and self.enabled
        state = (w, h, hov, has, self.enabled, p)
        if not force and state == self._drawn:
            return
        self._drawn = state
        c.delete('all')
        r = px(10)
        if has:
            bar = px(28)
            c.create_image(0, 0, anchor='nw', image=_cached(('zfill', w, h, r, bar),
                                                             lambda: ImageTk.PhotoImage(_flat(_filled_bg(w, h, r, bar, PANEL), PANEL))))
            try:
                key = (p, os.path.getmtime(p), w, h)
                if key != self._thumb_key:
                    with Image.open(p) as src:
                        im = ImageOps.exif_transpose(src)
                        self._dims = im.size
                        im.thumbnail((max(10, w - px(12)), max(10, h - bar - px(12))))
                        if im.mode not in ('RGB', 'RGBA'):
                            im = im.convert('RGBA')
                        im = _flat(im, '#EEF0F3') if im.mode == 'RGBA' else im
                        self._thumb = ImageTk.PhotoImage(im)
                    self._thumb_key = key
                c.create_image(w // 2, (h - bar) // 2, image=self._thumb)
            except Exception as e:
                c.create_text(w // 2, (h - bar) // 2, text=tr('（预览失败：{e}）', e=e), fill=MUTED, font=F(12), width=w - px(20))
            fb, fs = F(11.5, 'bold'), F(11.5)
            dims = f'{self._dims[0]} × {self._dims[1]}' if self._dims else ''
            dw = fs.measure(dims)
            c.create_text(px(10), h - bar // 2, anchor='w', fill=FG, font=fb,
                          text=ellipsize(os.path.basename(p), fb, w - dw - px(30)))
            c.create_text(w - px(10), h - bar // 2, anchor='e', fill=MUTED, font=fs, text=dims)
            D = px(22)
            c.create_image(w - px(8) - D // 2, px(8) + D // 2, tags=('clear',),
                           image=_cached(('xbtn', D), lambda: ImageTk.PhotoImage(_xbtn(D))))
            return
        if not self.enabled:
            fill, border, pf, pc, tc, text = '#F7F8F9', '#E1E4E9', '#ECEEF1', '#B9BEC7', FAINT, self.disabled_text
        elif hov:
            fill, border, pf, pc, tc, text = '#F7F5FF', ACCENT, ACCENT, '#FFFFFF', ACCENT_FG, tr('点击选择图片，或把图片拖进来')
        else:
            fill, border, pf, pc, tc, text = '#FAFBFC', '#C9CED8', ACCENT_SOFT, ACCENT, FG2, self.empty
        c.create_image(0, 0, anchor='nw', image=_cached(('zdash', w, h, r, fill, border),
                                                         lambda: ImageTk.PhotoImage(_flat(_dash_rr(w, h, r, fill, border), PANEL))))
        D = px(36)
        cy = h // 2 - px(12)
        c.create_image(w // 2, cy, image=_cached(('zplus', D, pf, pc, fill), lambda: ImageTk.PhotoImage(_plus(D, pf, pc, fill))))
        f = F(12.5)
        c.create_text(w // 2, cy + D // 2 + px(14), text=ellipsize(text, f, w - px(16)), fill=tc, font=f)
        if p and self.enabled and not os.path.isfile(p):
            c.create_text(w // 2, h - px(12), text=ellipsize(tr('找不到文件：') + os.path.basename(p), F(11.5), w - px(16)),
                          fill='#D4380D', font=F(11.5))


# ======================================================================= Windows 原生拖放（WM_DROPFILES）
def enable_file_drop(widget, callback):
    """让 widget 所在窗口接受从资源管理器拖进来的文件。callback(paths, screen_x, screen_y) 在 Tk 主循环里调用。
    非 Windows 或失败时返回 False（只能点击上传）。实现方式与 windnd 相同：DragAcceptFiles + 窗口子类化，不需要额外安装包。"""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.restype = LRESULT
        setlp = getattr(user32, 'SetWindowLongPtrW', None) or user32.SetWindowLongW
        setlp.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
        setlp.restype = ctypes.c_void_p
        shell32.DragQueryFileW.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT)
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryPoint.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.POINT))
        shell32.DragFinish.argtypes = (ctypes.c_void_p,)
        shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
        user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        # 允许低权限的资源管理器向本窗口拖放（工具以管理员身份运行时也能拖）
        try:
            f = user32.ChangeWindowMessageFilterEx
            f.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p)
            hwnd0 = widget.winfo_id()
            for m in (0x0233, 0x004A, 0x0049):
                f(hwnd0, m, 1, None)
        except Exception:
            pass
        hwnd = widget.winfo_id()
        pending = []

        def proc(h, msg, wp, lp):
            if msg == 0x0233:   # WM_DROPFILES
                try:
                    n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                    files = []
                    for i in range(n):
                        ln = shell32.DragQueryFileW(wp, i, None, 0)
                        buf = ctypes.create_unicode_buffer(ln + 1)
                        shell32.DragQueryFileW(wp, i, buf, ln + 1)
                        files.append(buf.value)
                    pt = wintypes.POINT()
                    shell32.DragQueryPoint(wp, ctypes.byref(pt))
                    user32.ClientToScreen(h, ctypes.byref(pt))
                    pending.append((files, pt.x, pt.y))
                finally:
                    shell32.DragFinish(wp)
                return 0
            return user32.CallWindowProcW(old, h, msg, wp, lp)

        cb = WNDPROC(proc)
        old = setlp(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))
        if not old:
            return False
        shell32.DragAcceptFiles(hwnd, True)
        widget._lumen_drop = (cb, old)   # 防止被回收

        def pump():
            while pending:
                files, x, y = pending.pop(0)
                try:
                    callback(files, x, y)
                except Exception:
                    widget.report_callback_exception(*sys.exc_info())
            widget.after(60, pump)
        widget.after(60, pump)
        return True
    except Exception:
        return False
