# Image F

**用 GPT 修错，再把 MJ 的色彩、虚化、颗粒拉回来。**

设计：**老F** · 免费使用，禁止商用 · 源码公开，按 [PolyForm Noncommercial License 1.0.0](LICENSE.txt) 提供

[English](README.md) · 简体中文

---

Midjourney 出的图常有一两处小错（多出来的手指、错开的接缝、变形的手）。交给 GPT 修，错是修好了，但颜色、虚化、颗粒也跟着变了。Image F 做两件事：

1. **交给 GPT 之前**：测量 MJ 原图的色彩、焦点和颗粒，生成可以直接粘贴给 GPT 的完整提示词。除了只修错，还支持「修错 + 换头」「修错 + 换整个角色」。
2. **GPT 出图之后**：把两张图逐像素对齐，找出 GPT 真正改过的地方，其余地方的颜色、明暗、雾气、虚化、颗粒还原回 MJ 原图的样子。

| 页面 | 用途 |
|---|---|
| ① 生成提示词 | 测量 MJ 原图，生成给 GPT 的提示词（只修错 / 修错 + 换头 / 修错 + 换整个角色；2×2 宫格图可以先切成四格） |
| ② 还原 | 把 GPT 出图和 MJ 原图对齐，修过的地方以外还原成 MJ 的样子 |
| ③ 标定 | 用自己的「MJ 原图 + GPT 出图」统计 GPT 固定的偏色、颗粒、清晰度偏差；一般自动，越用越准 |
| ④ 只还原风格 | 构图不同时（四视图、设定图、同一场景重画）：按区域对应和远近分层迁移 MJ 的风格，不按像素位置 |
| ⑤ 角色设定图 | 正面头像、四视图的提示词，做出来给换头 / 换角色当角色参考图 |

界面和使用说明都有**中文、英文**两种。安装时会问用哪种；装好以后随时可以点侧栏底部的语言链接切换（Image F 会自动重新打开一次）。带例子图的完整用法见 [Manual_zh-CN.html](Manual_zh-CN.html) · [Manual_en.html](Manual_en.html)。

## 下载和安装（Windows 10 / 11，64 位）

- **安装包（推荐）**：到 [Releases](../../releases) 页面下载 `ImageF_V版本号_Setup.exe`，双击安装。离线安装文件全都带着（Python 3.10、numpy、OpenCV、Pillow），只装给当前用户，不需要管理员权限。安装包里的核心模块是编译好的，功能和这里的源码完全一样。
- **用源码运行**：下载本仓库（或 Releases 里的 `ImageF_V版本号_Source.zip`），整个文件夹解压后双击 `ImageF.bat`。电脑上没有 Python 3.10 时会自动安装（只装给当前用户，不需要管理员权限），缺 numpy / OpenCV / Pillow 会自动安装，然后打开工具。源码里不带离线安装文件（`tools\runtime` 里只有清单），第一次运行需要联网下载 Python 3.10.11 和三个依赖包（约 70 MB），国内镜像优先。

结果保存在安装文件夹里的 `Output` 文件夹（工具里可以改到别的文件夹）。4.9 以前版本的结果留在原来的「输出」文件夹，不会被挪动。

### 更新

Image F 不会检查更新，使用时也不会联网（唯一的例外是源码版第一次运行时下载 Python 和三个依赖库）。想在有新版时收到通知：打开仓库页面，点 **Watch → Custom → Releases**，发布新版时 GitHub 会给你发邮件。更新方法：下载新的安装包运行即可（原地升级，设置保留）；用源码版的话，重新下载整个仓库，或者运行 `git pull`。

## 目录

| 位置 | 内容 |
|---|---|
| `ImageF.pyw`、`ImageF.bat` | 入口（双击 `ImageF.bat`） |
| `tools\mj_app.py`、`ui_lumen.py`、`mj_gui.pyw` | 界面 |
| `tools\i18n.py`、`tools\lang\en.json` | 语言切换：源码里写中文原文，英文表以中文原文为键；选的语言记在安装文件夹的 `lang.json` |
| `tools\mj_measure.py`、`mj_tool_core.py` | 测量、生成提示词、流程 |
| `tools\mj_restore.py` | ② 还原：对齐、找改动、三维颜色映射、低频补偿、频段质感 |
| `tools\mj_head.py`、`mj_face.py` | 换头 / 换角色：人脸、头发 / 皮肤分区、同类区域还原 |
| `tools\mj_style_only.py`、`mj_region.py`、`mj_scene.py`、`mj_depth.py` | ④ 只还原风格：区域对应、远近分层 |
| `tools\gpt_bias.py`、`calib_base.json` | ③ 标定 |
| `tools\prompt_*.txt` | 提示词模板 |
| `tools\launcher.pyw`、`bootstrap.ps1`、`runtime\manifest.json` | 第一次运行时的环境安装（Python 3.10 和依赖包） |
| `tools\selftest.py` | 自测（改完代码跑一次：`python tools\selftest.py`；先 `set IMAGEF_LANG=en` 可以测英文界面） |
| `build_tools\` | 打安装包：`build.bat`、`compile_modules.py`（Nuitka 编译核心模块）、`build_installer.py` + `installer_template.nsi`（NSIS）、`make_icon.py`、`make_welcome.py` |

### 打安装包

需要：Python 3.10（64 位）、`pip install nuitka ordered-set zstandard`（第一次编译会自动下载 MinGW 编译器）、NSIS 3.11（解压到 `build_tools\nsis-3.11`），以及 `tools\runtime` 里的离线安装文件（文件名和 SHA-256 校验值见 `tools\runtime\manifest.json`）。然后双击 `build_tools\build.bat`。

## 许可

Image F 由老F 构思、设计并主导开发，按 **PolyForm Noncommercial License 1.0.0** 提供：源码公开，可以免费使用、修改，但不能商用。（因为禁止商用，它不属于 OSI 定义的“开源许可”，准确的说法是“源码公开”。）

- **可以**：免费使用；个人学习、研究、创作、业余项目；学校、公益组织、科研机构、政府机构使用；修改源码；把原版或改过的版本免费转发。
- **必须**：转发或发布（包括改过的版本）时附上 `LICENSE.txt`，并原样保留以 `Required Notice:` 开头的署名行。
- **不可以**：任何商业用途（出售、收费下载、付费会员 / 付费群、收费课程、收费服务、营利公司的业务里使用等）；去掉或改掉老F 的署名。

想商用请先联系老F 取得书面授权。完整条款以 [LICENSE.txt](LICENSE.txt) 里的英文原文为准，中文摘要见 [LICENSE.zh-CN.txt](LICENSE.zh-CN.txt)。

随工具带的第三方组件（YuNet 人脸模型 MIT、Depth Anything V2 Small Apache-2.0、Python 和 numpy / OpenCV / Pillow）按各自的许可分发，见 [tools/THIRD_PARTY_NOTICES.txt](tools/THIRD_PARTY_NOTICES.txt)。
