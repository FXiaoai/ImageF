# -*- coding: utf-8 -*-
"""工具图标：用用户给的 IF-icon（紫底、白 I + 黄 F + 黄绿点阵椭圆）生成 tools\\ImageF.ico 和安装界面用的 app_icon_512.png。
原图四周留白多（标志只占 2/3），小尺寸图标里会显得很小，所以以标志为中心裁成正方形（标志约占 82%），
紫色铺满，四角做成圆角（半径 18%），其余不改。原图保留在 IF-icon_source.png。"""
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'IF-icon_source.png')
WS = os.path.abspath(os.path.join(HERE, '..'))
FILL = 0.82          # 标志宽度占图标的比例
RADIUS = 0.18        # 圆角半径（图标边长的比例）
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def make():
    im = Image.open(SRC).convert('RGBA')
    a = np.asarray(im).astype(int)
    bg = a[5, 5, :3]
    ys, xs = np.nonzero(np.abs(a[..., :3] - bg).sum(-1) > 60)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    side = max(xs.max() - xs.min(), ys.max() - ys.min()) / FILL
    canvas = Image.new('RGBA', (int(side), int(side)), tuple(bg) + (255,))
    rgb = im.copy()
    rgb.putalpha(255)                                    # 原图四周的半透明边去掉，底色铺满
    canvas.paste(rgb, (int(side / 2 - cx), int(side / 2 - cy)))
    big = canvas.resize((1024, 1024), Image.LANCZOS)
    mask = Image.new('L', (4096, 4096), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 4095, 4095), int(4096 * RADIUS), fill=255)
    big.putalpha(mask.resize((1024, 1024), Image.LANCZOS))
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(HERE, 'app_icon_512.png'))
    ico = os.path.join(WS, 'tools', 'ImageF.ico')   # 不叫 app.ico：换文件名让 Windows 的图标缓存刷新
    big.save(ico, sizes=[(s, s) for s in SIZES])
    preview = Image.new('RGBA', (sum(SIZES) + 12 * len(SIZES), 270), (244, 245, 247, 255))
    x = 6
    for s in SIZES:
        preview.paste(big.resize((s, s), Image.LANCZOS), (x, 260 - s), big.resize((s, s), Image.LANCZOS))
        x += s + 12
    preview.save(os.path.join(HERE, 'app_icon_preview.png'))
    return ico


if __name__ == '__main__':
    print(make())
