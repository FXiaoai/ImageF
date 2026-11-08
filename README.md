# Image F

**Fix Midjourney images with GPT — then bring MJ's colour, blur and grain back.**

Designed by **老F** · Free for noncommercial use · Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE.txt)

English · [简体中文](README.zh-CN.md)

---

Midjourney images often have one or two small mistakes — an extra finger, a broken seam, a twisted hand. GPT can fix them, but it also changes the colour grade, the depth-of-field blur and the grain. Image F does two things:

1. **Before GPT** — it measures the MJ original (colour, focus, grain) and writes a complete prompt you can paste straight into GPT. Besides plain error fixing it also supports **Fix + head swap** and **Fix + full character swap**.
2. **After GPT** — it aligns the two images pixel by pixel, finds what GPT really changed, and restores everything else (colour, light, haze, blur, grain) to how it looked in the MJ original.

| Page | What it is for |
|---|---|
| ① Generate prompt | Measure the MJ original and build the GPT prompt (fix only / fix + head swap / fix + full character swap; 2×2 grids can be split first) |
| ② Restore | Align the GPT output with the MJ original and bring MJ's look back outside the fixed areas |
| ③ Calibration | Learn GPT's stable colour / grain / sharpness bias from your own MJ + GPT pairs; mostly automatic, improves with use |
| ④ Style only | For a different composition (4-view sheets, character sheets, the same scene redrawn): transfer MJ's style by matching regions and depth layers instead of pixels |
| ⑤ Character sheet | Prompts for a front portrait and a 4-view sheet, to use as the character reference for head / character swaps |

The interface and the manual are available in **English and Chinese**. The installer asks which one to use; you can switch any time with the language link at the bottom of the sidebar (Image F restarts once). Full instructions with example images: [Manual_en.html](Manual_en.html) · [Manual_zh-CN.html](Manual_zh-CN.html).

## Download and install (Windows 10 / 11, 64-bit)

- **Installer (recommended)** — download `ImageF_V<version>_Setup.exe` from the [Releases](../../releases) page and double-click it. Everything is included offline (Python 3.10, numpy, OpenCV, Pillow); it installs for the current user only and does not need administrator rights. The core modules in the installer are compiled; they behave exactly like the source in this repository.
- **From source** — download the repository, unzip the whole folder, and double-click `ImageF.bat`. If Python 3.10 is missing it is installed for the current user (no admin rights), then numpy / OpenCV / Pillow are installed if needed, and the tool opens. The source does not include the offline installers (`tools\runtime` only holds a manifest), so the first run downloads Python 3.10.11 and three packages (about 70 MB).

Results are saved in the `Output` folder inside the install folder (you can choose another folder in the tool). Results from versions before 4.9 stay in the old `输出` folder and are not moved.

### Updates

Image F does not check for updates and does not connect to the internet while you use it (the only exception is the first run of the source version, which downloads Python and three packages). To be notified of a new version, open the repository page and choose **Watch → Custom → Releases**; GitHub then emails you whenever a new version is published. To update, download the new installer and run it (it upgrades in place and keeps your settings), or, if you use the source version, download the repository again or run `git pull`.

## Repository layout

| Path | Contents |
|---|---|
| `ImageF.pyw`, `ImageF.bat` | Entry points (double-click `ImageF.bat`) |
| `tools\mj_app.py`, `ui_lumen.py`, `mj_gui.pyw` | Interface |
| `tools\i18n.py`, `tools\lang\en.json` | Language switching: Chinese source strings, English table keyed by the Chinese text; the chosen language is stored in `lang.json` in the install folder |
| `tools\mj_measure.py`, `mj_tool_core.py` | Measuring, prompt generation, workflow |
| `tools\mj_restore.py` | ② Restore: alignment, change detection, 3-D colour mapping, low-frequency compensation, band-wise texture |
| `tools\mj_head.py`, `mj_face.py` | Head / character swaps: face, hair / skin regions, like-for-like region restore |
| `tools\mj_style_only.py`, `mj_region.py`, `mj_scene.py`, `mj_depth.py` | ④ Style only: region matching, depth layers |
| `tools\gpt_bias.py`, `calib_base.json` | ③ Calibration |
| `tools\prompt_*.txt` | Prompt templates |
| `tools\launcher.pyw`, `bootstrap.ps1`, `runtime\manifest.json` | First-run setup (Python 3.10 and packages) |
| `tools\selftest.py` | Self-test — run `python tools\selftest.py` after changing code (`set IMAGEF_LANG=en` first to test the English interface) |
| `build_tools\` | Installer build: `build.bat`, `compile_modules.py` (Nuitka), `build_installer.py` + `installer_template.nsi` (NSIS), `make_icon.py`, `make_welcome.py` |

### Building the installer

You need Python 3.10 (64-bit), `pip install nuitka ordered-set zstandard` (the first compile downloads the MinGW compiler automatically), NSIS 3.11 unpacked to `build_tools\nsis-3.11`, and the offline installers in `tools\runtime` (file names and SHA-256 values are listed in `tools\runtime\manifest.json`). Then double-click `build_tools\build.bat`.

## License

Image F was conceived, designed and developed by 老F. It is **source-available** under the **PolyForm Noncommercial License 1.0.0** — free to use and modify, but not for commercial purposes. (Because commercial use is not allowed, this is not an "open source" license in the OSI sense.)

- **You may**: use it for free; use it for personal study, research, creative work and hobby projects; use it in schools, charities, research institutions and government bodies; modify the source; share the original or a modified version free of charge.
- **You must**: include `LICENSE.txt` when you share or publish it (including modified versions), and keep every line starting with `Required Notice:` unchanged.
- **You may not**: use it for any commercial purpose (selling it, paid downloads, paid memberships or groups, paid courses, paid services, use in for-profit business operations, etc.), or remove or change 老F's credit.

For commercial use, please contact 老F for written permission first. The English license text in [LICENSE.txt](LICENSE.txt) is the binding version; a Chinese summary is in [LICENSE.zh-CN.txt](LICENSE.zh-CN.txt).

Bundled third-party components — the YuNet face model (MIT), Depth Anything V2 Small (Apache-2.0), Python and numpy / OpenCV / Pillow — are distributed under their own licenses; see [tools/THIRD_PARTY_NOTICES.txt](tools/THIRD_PARTY_NOTICES.txt).
