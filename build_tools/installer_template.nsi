; Image F —— 设计：老F · 许可：PolyForm Noncommercial 1.0.0（免费使用，禁止商用；见 LICENSE.txt）
; Image F 安装程序模板（build_installer.py 填入 @@...@@ 后生成 installer.nsi，再用 NSIS 3.11 编译）。
; V4.9 起中英双语：开头选语言（默认 = 上次装 / 工具里切换后 lang.json 里的语言，没有就跟 Windows 显示语言），
; 选的语言写进安装文件夹的 lang.json，工具和启动器按它显示；文件名都是英文，升级时清掉旧的中文名文件和快捷方式。
Unicode true
ManifestDPIAware true
RequestExecutionLevel user          ; 只装给当前用户，不需要管理员权限
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define APPNAME "Image F"           ; 新装时默认文件夹名
!define APPTITLE "Image F"          ; 快捷方式、开始菜单、“应用”列表里显示的名字
!define OLDNAME "MJ还原工具"         ; V4.6 及以前的名字：旧文件夹、旧快捷方式、旧文件名，升级时识别 / 清理
!define OLDUNINST "卸载与升级.exe"   ; V4.3.1 及以前的安装器留下的卸载程序
!define VERSION "@@VERSION@@"
!define REGKEY "Software\MJRestoreTool"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MJRestoreTool"
!define UNINSTEXE "Uninstall_ImageF.exe"
!define LAUNCHER "ImageF.bat"
!define ICONFILE "tools\ImageF.ico"
!define OUTDIR "Output"

Name "${APPTITLE} V${VERSION}"
Caption "$(T_CAPTION)"
UninstallCaption "$(T_UNCAPTION)"
OutFile "@@OUTFILE@@"
InstallDir "$PROFILE\${APPNAME}"
InstallDirRegKey HKCU "${REGKEY}" "InstallDir"
BrandingText "${APPTITLE} V${VERSION} · $(T_BRAND)"
ShowInstDetails show
SetFont "Microsoft YaHei UI" 9
ShowUninstDetails show

VIProductVersion "@@VERSION4@@"
VIAddVersionKey /LANG=1033 "ProductName" "${APPTITLE}"
VIAddVersionKey /LANG=1033 "FileDescription" "${APPTITLE} V${VERSION} Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright (c) 2026 老F · PolyForm Noncommercial 1.0.0 (free to use, no commercial use)"
VIAddVersionKey /LANG=1033 "CompanyName" "老F"
VIAddVersionKey /LANG=2052 "ProductName" "${APPTITLE}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APPTITLE} V${VERSION} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Copyright (c) 2026 老F · PolyForm Noncommercial 1.0.0（免费使用，禁止商用）"
VIAddVersionKey /LANG=2052 "CompanyName" "老F"

!define MUI_ICON "@@ICON@@"
!define MUI_WELCOMEFINISHPAGE_BITMAP "@@BITMAP@@"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "@@BITMAP@@"
!define MUI_UNICON "@@ICON@@"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "$(T_ABORT)"
!define MUI_CUSTOMFUNCTION_ABORT CleanEmptyDir
!define MUI_LANGDLL_WINDOWTITLE "Image F"
!define MUI_LANGDLL_INFO "Please choose the language / 请选择语言："
!define MUI_LANGDLL_ALLLANGUAGES

!define MUI_WELCOMEPAGE_TITLE "$(T_WELCOME_TITLE)"
!define MUI_WELCOMEPAGE_TEXT "$(T_WELCOME_TEXT)"
!insertmacro MUI_PAGE_WELCOME
!define MUI_LICENSEPAGE_TEXT_TOP "$(T_LIC_TOP)"
!define MUI_LICENSEPAGE_TEXT_BOTTOM "$(T_LIC_BOTTOM)"
!insertmacro MUI_PAGE_LICENSE "$(L_LICENSE)"

!define MUI_DIRECTORYPAGE_TEXT_TOP "$(T_DIR_TOP)"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "$(T_DIR_DEST)"
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE CheckInstDir
!insertmacro MUI_PAGE_DIRECTORY

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "$(T_FIN_TITLE)"
!define MUI_FINISHPAGE_TEXT_LARGE
!define MUI_FINISHPAGE_TEXT "$(T_FIN_TEXT)"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "$(T_FIN_RUN)"
!define MUI_FINISHPAGE_RUN_FUNCTION RunApp
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(T_FIN_DESKTOP)"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION DesktopShortcut
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

; ------------------------------------------------------------------ 两种语言的文字
LicenseLangString L_LICENSE ${LANG_ENGLISH} "@@LICENSE_EN@@"
LicenseLangString L_LICENSE ${LANG_SIMPCHINESE} "@@LICENSE_ZH@@"
LangString T_CAPTION ${LANG_ENGLISH} "${APPTITLE} V${VERSION} Setup"
LangString T_CAPTION ${LANG_SIMPCHINESE} "${APPTITLE} V${VERSION} 安装"
LangString T_UNCAPTION ${LANG_ENGLISH} "Uninstall ${APPTITLE}"
LangString T_UNCAPTION ${LANG_SIMPCHINESE} "${APPTITLE} 卸载"
LangString T_BRAND ${LANG_ENGLISH} "designed by 老F"
LangString T_BRAND ${LANG_SIMPCHINESE} "设计：老F"
LangString T_ABORT ${LANG_ENGLISH} "Are you sure you want to quit the setup?"
LangString T_ABORT ${LANG_SIMPCHINESE} "确定要退出安装吗？"
LangString T_WELCOME_TITLE ${LANG_ENGLISH} "Welcome to ${APPTITLE} V${VERSION}"
LangString T_WELCOME_TITLE ${LANG_SIMPCHINESE} "欢迎安装 ${APPTITLE} V${VERSION}"
LangString T_WELCOME_TEXT ${LANG_ENGLISH} "After GPT fixes the errors in a Midjourney image, Image F brings back the original's colour, blur and grain.$\r$\nDesigned by 老F. Free to use, no commercial use.$\r$\n$\r$\n· You can choose the install folder on the next pages.$\r$\n· Only copies files: no admin rights needed, no system settings changed.$\r$\n· On first start it prepares its environment (Python 3.10 and image libraries; offline files are included, no internet needed). This takes about 1–2 minutes, with a progress bar.$\r$\n$\r$\nIf it was installed before (including as “MJ还原工具”), the old folder is selected and upgraded in place: your output images and calibration data are kept."
LangString T_WELCOME_TEXT ${LANG_SIMPCHINESE} "用 GPT 修正 MJ 出图的错误后，把 MJ 原图的色彩、虚化、颗粒找回来。$\r$\n由老F 设计，免费使用，禁止商用。$\r$\n$\r$\n· 下一步可以自己选择安装文件夹。$\r$\n· 只复制文件，不需要管理员权限，也不改系统设置。$\r$\n· 第一次打开时会自动准备运行环境（Python 3.10 和图像处理组件，安装包里已带离线文件，不用联网），大约 1～2 分钟，有进度条。$\r$\n$\r$\n以前装过（包括改名前的「MJ还原工具」）会自动选中原来的文件夹，直接覆盖升级：输出的图片和自己加入的标定数据都会保留，旧的快捷方式会换成新名字和新图标。"
LangString T_LIC_TOP ${LANG_ENGLISH} "Image F is designed by 老F and provided free of charge under the license below."
LangString T_LIC_TOP ${LANG_SIMPCHINESE} "Image F 由老F 设计，免费提供；按下面的许可使用（中文摘要在前，英文原文为准）。"
LangString T_LIC_BOTTOM ${LANG_ENGLISH} "Click “I Agree” to accept: noncommercial use only; when sharing or modifying, include this license and keep the credit to 老F."
LangString T_LIC_BOTTOM ${LANG_SIMPCHINESE} "点「我接受」表示同意：只用于非商业用途；转发或修改时附上这份许可，并保留老F 的署名。"
LangString T_DIR_TOP ${LANG_ENGLISH} "Choose the install folder.$\r$\nGenerated images are saved in its “${OUTDIR}” folder, so pick a place that is easy to find and that you can write to, e.g. the default or D:\${APPNAME} (not C:\Program Files)."
LangString T_DIR_TOP ${LANG_SIMPCHINESE} "请选择安装位置。$\r$\n生成的图片会保存在安装文件夹里的「${OUTDIR}」文件夹，所以请选一个方便找到、自己有写入权限的位置，例如默认位置或 D:\${APPNAME}（不要选 C:\Program Files）。"
LangString T_DIR_DEST ${LANG_ENGLISH} "Install to this folder"
LangString T_DIR_DEST ${LANG_SIMPCHINESE} "安装到这个文件夹"
LangString T_NOWRITE ${LANG_ENGLISH} "You can't write to this folder:$\r$\n$INSTDIR$\r$\n$\r$\nPlease choose another one, e.g. the default or D:\${APPNAME}."
LangString T_NOWRITE ${LANG_SIMPCHINESE} "这个位置没有写入权限：$\r$\n$INSTDIR$\r$\n$\r$\n请换一个文件夹，例如默认位置或 D:\${APPNAME}。"
LangString T_FIN_TITLE ${LANG_ENGLISH} "Installation complete"
LangString T_FIN_TITLE ${LANG_SIMPCHINESE} "安装完成"
LangString T_FIN_TEXT ${LANG_ENGLISH} "The first start prepares the environment (1–2 minutes; please wait for the progress bar). Start menu: “${APPTITLE}”, “Manual”, “Uninstall”. Switch the language any time at the bottom left of the tool.$\r$\n$\r$\nInstalled in: $INSTDIR"
LangString T_FIN_TEXT ${LANG_SIMPCHINESE} "第一次打开要先准备运行环境（约 1～2 分钟），请等进度条走完。开始菜单里有「${APPTITLE}」「使用说明」和「卸载」。工具左下角可以随时切换中文 / English。$\r$\n$\r$\n安装位置：$INSTDIR"
LangString T_FIN_RUN ${LANG_ENGLISH} "Open ${APPTITLE} now"
LangString T_FIN_RUN ${LANG_SIMPCHINESE} "现在打开 ${APPTITLE}"
LangString T_FIN_DESKTOP ${LANG_ENGLISH} "Create a desktop shortcut"
LangString T_FIN_DESKTOP ${LANG_SIMPCHINESE} "在桌面创建快捷方式"
LangString T_SC_GUIDE ${LANG_ENGLISH} "Manual"
LangString T_SC_GUIDE ${LANG_SIMPCHINESE} "使用说明"
LangString T_SC_OUT ${LANG_ENGLISH} "Output folder"
LangString T_SC_OUT ${LANG_SIMPCHINESE} "输出文件夹"
LangString T_SC_UNINST ${LANG_ENGLISH} "Uninstall ${APPTITLE}"
LangString T_SC_UNINST ${LANG_SIMPCHINESE} "卸载 ${APPTITLE}"
LangString T_GUIDE_FILE ${LANG_ENGLISH} "Manual_en.html"
LangString T_GUIDE_FILE ${LANG_SIMPCHINESE} "Manual_zh-CN.html"
LangString T_LANG_CODE ${LANG_ENGLISH} "en"
LangString T_LANG_CODE ${LANG_SIMPCHINESE} "zh"
LangString T_UN_ASK ${LANG_ENGLISH} "Also delete the generated images (the “${OUTDIR}” folder and the older “输出” folder) and the calibration data you added?$\r$\n$\r$\nChoose “No” to keep them; installing to the same folder again lets you continue with them."
LangString T_UN_ASK ${LANG_SIMPCHINESE} "要不要同时删除生成的图片（「${OUTDIR}」文件夹和以前的「输出」文件夹），以及你自己加入的标定数据？$\r$\n$\r$\n选「否」会保留它们，以后重新安装到同一个文件夹还能接着用。"

Var CreatedDir

; 读安装文件夹里的 lang.json：{"lang": "en"} → 英文，其余 → 中文；没有这个文件时不改（= 跟 Windows 显示语言）
!macro READ_LANG_JSON DIR
  ${If} ${FileExists} "${DIR}\lang.json"
    ClearErrors
    FileOpen $9 "${DIR}\lang.json" r
    ${IfNot} ${Errors}
      FileRead $9 $8
      FileClose $9
      ${If} $8 == '{"lang": "en"}'
        StrCpy $LANGUAGE ${LANG_ENGLISH}
      ${Else}
        StrCpy $LANGUAGE ${LANG_SIMPCHINESE}
      ${EndIf}
    ${EndIf}
  ${EndIf}
!macroend

; 以前装过：InstallDirRegKey 已经取到本安装器记下的位置（改名前装的也是这个登记，位置照旧，例如 E:\MJ还原工具）。
; 没有登记时找改名前的默认位置：%USERPROFILE%\MJ还原工具，或 V4.3.1 自制安装器的 %LOCALAPPDATA%\MJ还原工具（命令行 /D= 不受影响）
Function .onInit
  ${If} $INSTDIR == "$PROFILE\${APPNAME}"
  ${AndIfNot} ${FileExists} "$INSTDIR\tools\launcher.pyw"
    ${If} ${FileExists} "$PROFILE\${OLDNAME}\tools\launcher.pyw"
      StrCpy $INSTDIR "$PROFILE\${OLDNAME}"
    ${ElseIf} ${FileExists} "$LOCALAPPDATA\${OLDNAME}\tools\launcher.pyw"
      StrCpy $INSTDIR "$LOCALAPPDATA\${OLDNAME}"
    ${EndIf}
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\tools\launcher.pyw"
  ${AndIfNot} ${FileExists} "$INSTDIR\lang.json"
    StrCpy $LANGUAGE ${LANG_SIMPCHINESE}       ; V4.8 及以前装的（只有中文）：升级时默认还是中文
  ${EndIf}
  !insertmacro READ_LANG_JSON "$INSTDIR"
  !insertmacro MUI_LANGDLL_DISPLAY             ; 静默安装（/S）时不弹，用上面定下的语言
FunctionEnd

Function un.onInit
  StrCpy $LANGUAGE ${LANG_SIMPCHINESE}
  !insertmacro READ_LANG_JSON "$INSTDIR"
FunctionEnd

; ------------------------------------------------------------------ 安装位置检查
Function CheckInstDir
  StrCpy $CreatedDir 0
  ${IfNot} ${FileExists} "$INSTDIR\*.*"
    StrCpy $CreatedDir 1
  ${EndIf}
  ClearErrors
  CreateDirectory "$INSTDIR"
  FileOpen $0 "$INSTDIR\.mj_write_test" w
  ${If} ${Errors}
    ${If} $CreatedDir == 1
      RMDir "$INSTDIR"          ; 先删掉刚建出的空文件夹，再提示
      StrCpy $CreatedDir 0
    ${EndIf}
    MessageBox MB_OK|MB_ICONEXCLAMATION "$(T_NOWRITE)"
    Abort
  ${EndIf}
  FileClose $0
  Delete "$INSTDIR\.mj_write_test"
FunctionEnd

Function CleanEmptyDir
  ${If} $CreatedDir == 1
    RMDir "$INSTDIR"            ; 只删空文件夹
  ${EndIf}
FunctionEnd

Function RunApp
  ExecShell "open" "$INSTDIR\${LAUNCHER}" "" SW_SHOWMINIMIZED
FunctionEnd

Function DesktopShortcut
  SetShellVarContext current
  CreateShortcut "$DESKTOP\${APPTITLE}.lnk" "$INSTDIR\${LAUNCHER}" "" "$INSTDIR\${ICONFILE}" 0 SW_SHOWMINIMIZED "" "${APPTITLE} V${VERSION}"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
FunctionEnd

; ------------------------------------------------------------------ 安装
Section "install"
  SetShellVarContext current
  SetOverwrite on
@@INSTALL_FILES@@
  CreateDirectory "$INSTDIR\${OUTDIR}"
  FileOpen $0 "$INSTDIR\lang.json" w          ; 安装时选的语言（工具左下角可以再改）
  FileWrite $0 '{"lang": "$(T_LANG_CODE)"}'
  FileClose $0
  Delete "$INSTDIR\${OLDUNINST}"        ; 旧版卸载程序：留着的话以后点它会把新装的文件删掉
  ; 改名前（MJ还原工具）和 V4.8 及以前（中文文件名）的文件：入口、说明、卸载程序、旧图标、旧说明
  Delete "$INSTDIR\${OLDNAME}.pyw"
  Delete "$INSTDIR\启动 ${OLDNAME}.bat"
  Delete "$INSTDIR\${OLDNAME}_使用说明_当前版.html"
  Delete "$INSTDIR\卸载 ${OLDNAME}.exe"
  Delete "$INSTDIR\tools\app.ico"
  Delete "$INSTDIR\Image F.pyw"
  Delete "$INSTDIR\启动 Image F.bat"
  Delete "$INSTDIR\Image F_使用说明.html"
  Delete "$INSTDIR\卸载 Image F.exe"
  Delete "$INSTDIR\tools\第三方组件说明.txt"
  WriteUninstaller "$INSTDIR\${UNINSTEXE}"

  ; 旧的开始菜单和桌面快捷方式（改名前、中文版、英文版的名字都删掉，再按这次的语言建）；桌面上原来有的，换成新的
  Delete "$SMPROGRAMS\${OLDNAME}\${OLDNAME}.lnk"
  Delete "$SMPROGRAMS\${OLDNAME}\使用说明.lnk"
  Delete "$SMPROGRAMS\${OLDNAME}\输出文件夹.lnk"
  Delete "$SMPROGRAMS\${OLDNAME}\卸载 ${OLDNAME}.lnk"
  RMDir "$SMPROGRAMS\${OLDNAME}"
  Delete "$SMPROGRAMS\${APPTITLE}\使用说明.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\输出文件夹.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\卸载 ${APPTITLE}.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\Manual.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\Output folder.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\Uninstall ${APPTITLE}.lnk"
  ${If} ${FileExists} "$DESKTOP\${OLDNAME}.lnk"
  ${OrIf} ${FileExists} "$DESKTOP\${APPTITLE}.lnk"
    Delete "$DESKTOP\${OLDNAME}.lnk"
    CreateShortcut "$DESKTOP\${APPTITLE}.lnk" "$INSTDIR\${LAUNCHER}" "" "$INSTDIR\${ICONFILE}" 0 SW_SHOWMINIMIZED "" "${APPTITLE} V${VERSION}"
  ${EndIf}

  CreateDirectory "$SMPROGRAMS\${APPTITLE}"
  CreateShortcut "$SMPROGRAMS\${APPTITLE}\${APPTITLE}.lnk" "$INSTDIR\${LAUNCHER}" "" "$INSTDIR\${ICONFILE}" 0 SW_SHOWMINIMIZED "" "${APPTITLE} V${VERSION}"
  CreateShortcut "$SMPROGRAMS\${APPTITLE}\$(T_SC_GUIDE).lnk" "$INSTDIR\$(T_GUIDE_FILE)"
  CreateShortcut "$SMPROGRAMS\${APPTITLE}\$(T_SC_OUT).lnk" "$INSTDIR\${OUTDIR}"
  CreateShortcut "$SMPROGRAMS\${APPTITLE}\$(T_SC_UNINST).lnk" "$INSTDIR\${UNINSTEXE}"

  WriteRegStr HKCU "${REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "Version" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPTITLE}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "老F"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\${ICONFILE}"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\${UNINSTEXE}"'
  WriteRegStr HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\${UNINSTEXE}" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" @@SIZE_KB@@
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'   ; 通知资源管理器刷新图标
SectionEnd

; ------------------------------------------------------------------ 卸载（只删安装过的文件，绝不整目录递归删除安装目录）
Section "Uninstall"
  SetShellVarContext current
  StrCpy $1 0
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/PURGE" $2
  ${IfNot} ${Errors}
    StrCpy $1 1
  ${Else}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "$(T_UN_ASK)" /SD IDNO IDNO keep
    StrCpy $1 1
    keep:
  ${EndIf}

@@UNINSTALL_FILES@@
  ${If} $1 == 1
    RMDir /r "$INSTDIR\${OUTDIR}"
    RMDir /r "$INSTDIR\输出"
    RMDir /r "$INSTDIR\tools\calib"
    Delete "$INSTDIR\tools\gpt_bias.json"
  ${EndIf}
  Delete "$INSTDIR\lang.json"
  Delete "$INSTDIR\${UNINSTEXE}"
@@UNINSTALL_DIRS@@
  RMDir "$INSTDIR\${OUTDIR}"
  RMDir "$INSTDIR\输出"
  RMDir "$INSTDIR"

  Delete "$DESKTOP\${APPTITLE}.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\${APPTITLE}.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\使用说明.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\输出文件夹.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\卸载 ${APPTITLE}.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\Manual.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\Output folder.lnk"
  Delete "$SMPROGRAMS\${APPTITLE}\Uninstall ${APPTITLE}.lnk"
  RMDir "$SMPROGRAMS\${APPTITLE}"
  Delete "$DESKTOP\${OLDNAME}.lnk"
  RMDir "$SMPROGRAMS\${OLDNAME}"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "${REGKEY}"
SectionEnd
