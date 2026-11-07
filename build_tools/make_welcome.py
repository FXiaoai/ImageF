# -*- coding: utf-8 -*-
"""安装界面左侧的欢迎图（328x628），版本号随 build_installer.VERSION 自动更新。"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))


def make(version, out=os.path.join(HERE, 'welcome.bmp')):
    W, H = 328, 628
    img = Image.new('RGB', (W, H))
    top, bot = (138, 30, 255), (52, 0, 120)          # 跟图标一致的紫色（图标底色 #8003FD）
    for y in range(H):
        t = y / (H - 1)
        img.paste(tuple(int(a + (b - a) * t) for a, b in zip(top, bot)), (0, y, W, y + 1))
    d = ImageDraw.Draw(img)
    for i, (yy, col) in enumerate(((430, (112, 20, 220)), (480, (88, 8, 180)), (540, (66, 0, 140)))):    # 三层远近
        pts = [(0, H)] + [(x, yy + int(28 * math.sin(x / (55 + i * 18) + i))) for x in range(0, W + 1, 8)] + [(W, H)]
        d.polygon(pts, fill=col)
    d.rounded_rectangle(((W - 162) // 2, 184, (W + 162) // 2, 346), 30, fill=(186, 140, 255))   # 浅紫描边，图标和底色分开
    icon = Image.open(os.path.join(HERE, 'app_icon_512.png')).resize((150, 150), Image.LANCZOS)
    img.paste(icon, ((W - 150) // 2, 190), icon)
    f = ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc', 40)
    t = 'Image F'
    l, tp, r, b = d.textbbox((0, 0), t, font=f)
    d.text(((W - (r - l)) / 2 - l, 360), t, font=f, fill=(255, 255, 255))
    f2 = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 22)
    t2 = 'V' + version
    l, tp, r, b = d.textbbox((0, 0), t2, font=f2)
    d.text(((W - (r - l)) / 2 - l, 418), t2, font=f2, fill=(255, 222, 30))
    f3 = ImageFont.truetype(r'C://Windows//Fonts//msyh.ttc', 20)
    t3 = 'Designed by 老F'        # 中英文安装界面共用一张图
    l, tp, r, b = d.textbbox((0, 0), t3, font=f3)
    d.text(((W - (r - l)) / 2 - l, 586), t3, font=f3, fill=(230, 220, 255))
    img.save(out)
    return out


if __name__ == '__main__':
    import build_installer
    print(make(build_installer.VERSION))
