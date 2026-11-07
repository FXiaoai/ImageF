# Image F (MJ restore tool) - bootstrap (Windows PowerShell 5.1+). ASCII only; UI text comes from runtime\manifest.json.
# 1. Find a usable 64-bit Python 3.10 with tkinter.
# 2. If none: show a progress window, verify the bundled installer (SHA256 + Authenticode signature),
#    install Python 3.10 for the current user only (silent, no admin rights, no PATH or file-association changes).
# 3. Start tools\launcher.pyw, which checks / installs numpy, OpenCV and Pillow and then opens the panel.
# Exit codes: 0 = ok, 3 = failed and the error was shown in the window (the .bat reports any other code itself).
# Test switches (not used in normal operation): -SimulateMissing -DryRun -ForceDownload -ShotDir <dir> -NoLaunch
param(
    [switch]$SimulateMissing,
    [switch]$DryRun,
    [switch]$ForceDownload,
    [switch]$NoLaunch,
    [string]$ShotDir = ''
)
$ErrorActionPreference = 'Stop'
$script:downloaded = $null
$Tools = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Tools 'runtime'
$LogFile = Join-Path $Tools 'setup.log'

function Write-Log([string]$m) {
    try { Add-Content -LiteralPath $LogFile -Value ('[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] bootstrap: ' + $m) -Encoding UTF8 } catch {}
}

$M = Get-Content -LiteralPath (Join-Path $Runtime 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
# UI language: lang.json in the install folder (written by the installer / the in-app switch);
# without it, follow the Windows display language (Chinese -> zh, anything else -> en).
$Lang = ''
$LangFile = Join-Path (Split-Path -Parent $Tools) 'lang.json'
try { if (Test-Path -LiteralPath $LangFile) { $Lang = [string]((Get-Content -LiteralPath $LangFile -Raw -Encoding UTF8 | ConvertFrom-Json).lang) } } catch {}
if (-not $Lang) {
    try { if ([System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName -eq 'zh') { $Lang = 'zh' } else { $Lang = 'en' } } catch { $Lang = 'zh' }
}
if ($Lang -eq 'en' -and $M.ui_en) { $U = $M.ui_en } else { $U = $M.ui }

function Test-Python([string]$exe) {
    if (-not $exe) { return $false }
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    try {
        $p = Start-Process -FilePath $exe -ArgumentList '-c "import sys, tkinter; sys.exit(0 if sys.version_info[:2] == (3, 10) and sys.maxsize > 2**32 else 3)"' -WindowStyle Hidden -PassThru -Wait
        return ($p.ExitCode -eq 0)
    } catch { return $false }
}

function Find-Python {
    $cands = New-Object System.Collections.Generic.List[string]
    try {
        $out = & py -3.10 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { $cands.Add(([string]$out).Trim()) }
    } catch {}
    foreach ($root in @('HKCU:\Software\Python\PythonCore\3.10', 'HKLM:\Software\Python\PythonCore\3.10', 'HKLM:\Software\WOW6432Node\Python\PythonCore\3.10')) {
        try {
            $ip = Get-ItemProperty -LiteralPath ($root + '\InstallPath') -ErrorAction Stop
            if ($ip.ExecutablePath) { $cands.Add([string]$ip.ExecutablePath) }
            if ($ip.'(default)') { $cands.Add((Join-Path ([string]$ip.'(default)') 'python.exe')) }
        } catch {}
    }
    if ($env:LOCALAPPDATA) { $cands.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe')) }
    if ($env:ProgramFiles) { $cands.Add((Join-Path $env:ProgramFiles 'Python310\python.exe')) }
    foreach ($c in $cands) {
        if (Test-Python $c) { Write-Log ('found Python 3.10: ' + $c); return $c }
    }
    return $null
}

function Start-Launcher([string]$python) {
    $dir = Split-Path -Parent $python
    $pyw = Join-Path $dir 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pyw)) { $pyw = $python }
    $launcher = Join-Path $Tools 'launcher.pyw'
    Write-Log ('start launcher with ' + $pyw)
    if ($NoLaunch) { return }
    Start-Process -FilePath $pyw -ArgumentList ('"' + $launcher + '"') -WorkingDirectory $Tools | Out-Null
}

# ------------------------------------------------------------------ fast path
Write-Log ('bootstrap start; PowerShell ' + $PSVersionTable.PSVersion.ToString() + '; folder ' + $Tools)
$py = $null
if (-not $SimulateMissing) { $py = Find-Python }
if ($py) { Start-Launcher $py; exit 0 }

# ------------------------------------------------------------------ progress window
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try {
    Add-Type -Namespace MjBoot -Name Dpi -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
    [void][MjBoot.Dpi]::SetProcessDPIAware()
} catch {}
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$g = $form.CreateGraphics(); $k = $g.DpiX / 96.0; $g.Dispose()
function S([double]$v) { return [int]($v * $k) }
$font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10)
$bold = New-Object System.Drawing.Font('Microsoft YaHei UI', 12, [System.Drawing.FontStyle]::Bold)
$form.Text = $U.title
$form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false; $form.MinimizeBox = $true
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size((S 560), (S 190))
$title = New-Object System.Windows.Forms.Label
$title.Font = $bold; $title.AutoSize = $false; $title.Location = New-Object System.Drawing.Point((S 18), (S 16)); $title.Size = New-Object System.Drawing.Size((S 524), (S 28))
$title.Text = $U.py_prepare
$status = New-Object System.Windows.Forms.Label
$status.Font = $font; $status.AutoSize = $false; $status.Location = New-Object System.Drawing.Point((S 18), (S 52)); $status.Size = New-Object System.Drawing.Size((S 524), (S 44))
$status.Text = $U.py_verify
$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Location = New-Object System.Drawing.Point((S 18), (S 100)); $bar.Size = New-Object System.Drawing.Size((S 470), (S 22)); $bar.Minimum = 0; $bar.Maximum = 1000
$pct = New-Object System.Windows.Forms.Label
$pct.Font = $font; $pct.AutoSize = $false; $pct.TextAlign = 'MiddleRight'; $pct.Location = New-Object System.Drawing.Point((S 490), (S 100)); $pct.Size = New-Object System.Drawing.Size((S 52), (S 22))
$detail = New-Object System.Windows.Forms.Label
$detail.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9); $detail.ForeColor = [System.Drawing.Color]::Gray
$detail.AutoSize = $false; $detail.Location = New-Object System.Drawing.Point((S 18), (S 128)); $detail.Size = New-Object System.Drawing.Size((S 524), (S 40))
$btnLog = New-Object System.Windows.Forms.Button
$btnLog.Font = $font; $btnLog.Text = $U.btn_log; $btnLog.Size = New-Object System.Drawing.Size((S 100), (S 30)); $btnLog.Location = New-Object System.Drawing.Point((S 330), (S 150)); $btnLog.Visible = $false
$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Font = $font; $btnClose.Text = $U.btn_close; $btnClose.Size = New-Object System.Drawing.Size((S 100), (S 30)); $btnClose.Location = New-Object System.Drawing.Point((S 442), (S 150)); $btnClose.Visible = $false
$form.Controls.AddRange(@($title, $status, $bar, $pct, $detail, $btnLog, $btnClose))
$script:closed = $false
$form.Add_FormClosed({ $script:closed = $true })
$btnClose.Add_Click({ $form.Close() })
$btnLog.Add_Click({ if (Test-Path -LiteralPath $LogFile) { Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $LogFile + '"') } })
$form.Show()
$form.Activate()

function Pump { [System.Windows.Forms.Application]::DoEvents() }
function Set-Progress([double]$v) {
    if ($v -lt 0) { $v = 0 }; if ($v -gt 100) { $v = 100 }
    $bar.Value = [int]($v * 10); $pct.Text = ('{0}%' -f [int]$v); Pump
}
$shotN = 0
function Shot([string]$tag) {
    if (-not $ShotDir) { return }
    Pump; Start-Sleep -Milliseconds 150; Pump
    $script:shotN++
    $r = $form.Bounds
    $bmp = New-Object System.Drawing.Bitmap($r.Width, $r.Height)
    $gr = [System.Drawing.Graphics]::FromImage($bmp)
    $gr.CopyFromScreen($r.Location, [System.Drawing.Point]::Empty, $r.Size)
    $bmp.Save((Join-Path $ShotDir ('boot_{0}_{1}.png' -f $script:shotN, $tag)), [System.Drawing.Imaging.ImageFormat]::Png)
    $gr.Dispose(); $bmp.Dispose()
}
function Fail([string]$msg) {
    Write-Log ('FAILED: ' + $msg)
    $title.Text = $U.err_prefix.TrimEnd([char]0xFF1A, ':')
    $title.ForeColor = [System.Drawing.Color]::FromArgb(176, 0, 32)
    $status.Text = $msg
    $detail.Text = $U.err_tail + ' ' + $LogFile
    $detail.Size = New-Object System.Drawing.Size((S 524), (S 58))
    $form.ClientSize = New-Object System.Drawing.Size((S 560), (S 236))
    $btnLog.Location = New-Object System.Drawing.Point((S 330), (S 194))
    $btnClose.Location = New-Object System.Drawing.Point((S 442), (S 194))
    $btnLog.Visible = $true; $btnClose.Visible = $true
    Shot 'error'
    if ($ShotDir) { $form.Close(); exit 3 }          # test mode: do not wait for the user
    while (-not $script:closed) { Pump; Start-Sleep -Milliseconds 50 }
    exit 3
}
function Wait-Ms([int]$ms) { $t = [DateTime]::Now; while (([DateTime]::Now - $t).TotalMilliseconds -lt $ms) { Pump; Start-Sleep -Milliseconds 30 } }

# ------------------------------------------------------------------ 1. installer file
try {
    Set-Progress 2
    $inst = Join-Path $Runtime $M.python.file
    $ok = $false
    if ((-not $ForceDownload) -and (Test-Path -LiteralPath $inst)) {
        $status.Text = $U.py_verify; Pump
        $ok = ((Get-FileHash -LiteralPath $inst -Algorithm SHA256).Hash.ToLower() -eq $M.python.sha256)
        if (-not $ok) { Write-Log 'bundled installer hash mismatch' }
    }
    Set-Progress 6
    if (-not $ok) {
        $inst = Join-Path $env:TEMP ('mj_' + $M.python.file)
        $script:downloaded = $inst
        $status.Text = $U.py_download
        foreach ($url in $M.python.urls) {
            try {
                Write-Log ('download ' + $url)
                $detail.Text = $url; Pump
                [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
                $req = [System.Net.HttpWebRequest]::Create($url); $req.Timeout = 20000; $req.ReadWriteTimeout = 30000
                $resp = $req.GetResponse(); $total = $resp.ContentLength
                $in = $resp.GetResponseStream(); $out = [System.IO.File]::Create($inst)
                $buf = New-Object byte[] 262144; $done = 0; $last = [DateTime]::Now
                while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
                    $out.Write($buf, 0, $n); $done += $n
                    if (([DateTime]::Now - $last).TotalMilliseconds -gt 120) {
                        $last = [DateTime]::Now
                        if ($total -gt 0) { Set-Progress (6 + 30 * $done / $total); $detail.Text = ('{0:N1} / {1:N1} MB   {2}' -f ($done / 1MB), ($total / 1MB), $url) } else { Pump }
                    }
                }
                $out.Close(); $in.Close(); $resp.Close()
                if ((Get-FileHash -LiteralPath $inst -Algorithm SHA256).Hash.ToLower() -eq $M.python.sha256) { $ok = $true; break }
                Write-Log ('downloaded file hash mismatch from ' + $url)
            } catch {
                Write-Log ('download failed: ' + $url + ' ' + $_.Exception.Message)
                foreach ($h in @($out, $in, $resp)) { try { if ($h) { $h.Close() } } catch {} }
            }
            $out = $null; $in = $null; $resp = $null
        }
        if (-not $ok) { Remove-Item -LiteralPath $inst -Force -ErrorAction SilentlyContinue; Fail ($U.err_download) }
    }
    $sig = Get-AuthenticodeSignature -LiteralPath $inst
    if ($sig.Status -ne 'Valid' -or ([string]$sig.SignerCertificate.Subject) -notlike ('*' + $M.python.signer + '*')) {
        Fail ($U.err_hash + ' (' + $sig.Status + ')')
    }
    Write-Log ('installer verified: ' + $inst)
    Set-Progress 36
    Shot 'verified'
} catch { Fail ($U.err_hash + ' ' + $_.Exception.Message) }

# ------------------------------------------------------------------ 2. silent per-user install
$title.Text = $U.py_prepare
$status.Text = $U.py_install
$ilog = Join-Path $env:TEMP 'mj_python_install.log'
$instArgs = '/quiet InstallAllUsers=0 Include_launcher=0 InstallLauncherAllUsers=0 PrependPath=0 AssociateFiles=0 Shortcuts=0 ' +
        'Include_doc=0 Include_test=0 Include_dev=0 Include_debug=0 Include_symbols=0 Include_tcltk=1 Include_pip=1 CompileAll=0 ' +
        '/log "' + $ilog + '"'
Write-Log ('run installer: ' + $instArgs)
$t0 = [DateTime]::Now
$proc = $null
if (-not $DryRun) {
    try { $proc = Start-Process -FilePath $inst -ArgumentList $instArgs -PassThru } catch { Fail ($U.err_install -f $_.Exception.Message) }
}
$expected = 75.0
while ($true) {
    $sec = ([DateTime]::Now - $t0).TotalSeconds
    if ($DryRun) { if ($sec -gt 4) { break } } elseif ($proc.HasExited) { break }
    if ($sec -gt 900) { try { $proc.Kill() } catch {}; Fail ($U.err_install -f 'timeout') }
    $frac = 1 - [Math]::Exp(-2.2 * $sec / $expected)
    $logFrac = 0
    try {
        if (Test-Path -LiteralPath $ilog) {
            $txt = Get-Content -LiteralPath $ilog -Raw -ErrorAction Stop
            $planned = ([regex]::Matches($txt, 'Planned package: [^,]+, state: Absent[^\r\n]*execute: Install')).Count
            $applied = ([regex]::Matches($txt, 'Applied execute package: ')).Count
            if ($planned -gt 0) { $logFrac = [Math]::Min(1.0, $applied / $planned) }
        }
    } catch {}
    Set-Progress (36 + 60 * [Math]::Max($frac * 0.95, $logFrac * 0.97))
    $detail.Text = ($U.py_elapsed -f [int]$sec)
    if ($ShotDir -and $sec -gt 2 -and $shotN -lt 2) { Shot 'installing' }
    Start-Sleep -Milliseconds 120
}
if (-not $DryRun) {
    $code = $proc.ExitCode
    Write-Log ('installer exit code ' + $code)
    if ($script:downloaded) {                                 # downloaded copy in %TEMP% is no longer needed
        Remove-Item -LiteralPath $script:downloaded -Force -ErrorAction SilentlyContinue
    }
    if ($code -ne 0 -and $code -ne 3010) { Fail ($U.err_install -f $code) }
}

# ------------------------------------------------------------------ 3. hand over to the Python launcher
$py = Find-Python
if (-not $py) { Fail ($U.err_notfound) }
Set-Progress 100
$title.Text = $U.py_done
$status.Text = $U.py_done
$detail.Text = $py
Shot 'done'
Start-Launcher $py
Wait-Ms 1200
$form.Close()
exit 0
