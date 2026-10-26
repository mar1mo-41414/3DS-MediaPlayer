# Windows 用: 生成ツールが使う外部ツールを配布済みの exe から tools\bin\ に用意する (setup-tools.sh の Windows 版)。
#   makerom / bannertool / 3dstool は動作確認した版の Release を取得する。
#   ffmpeg / ffprobe (libx264 と aac 付き) は PATH 上に無ければ gyan.dev の essentials ビルドを取得する。
# 使い方:  powershell -ExecutionPolicy Bypass -File scripts\setup-tools.ps1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest の進捗表示は極端に遅いので切る
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $repo 'tools\bin'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("mkcia-setup-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $bin, $tmp | Out-Null

# 動作確認した版
$Tools = @(
    @{ Exe = 'makerom.exe';     Url = 'https://github.com/3DSGuy/Project_CTR/releases/download/makerom-v0.19.0/makerom-v0.19.0-win_x86_64.zip' },
    @{ Exe = 'bannertool.exe';  Url = 'https://github.com/Epicpkmn11/bannertool/releases/download/v1.2.2/bannertool.zip' },
    @{ Exe = '3dstool.exe';     Url = 'https://github.com/dnasdw/3dstool/releases/download/v1.2.6/3dstool.zip' }
)
$FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

function Get-Archive([string]$url, [string]$name) {
    $zip = Join-Path $tmp "$name.zip"
    $dir = Join-Path $tmp $name
    Write-Host "取得: $url"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $dir -Force
    return $dir
}

function Copy-Exe([string]$dir, [string]$exe) {
    # zip の中の階層 (windows-x86_64\ など) は版によって違うので探す。64bit 版があればそちらを優先する
    $found = @(Get-ChildItem -Recurse -Filter $exe -Path $dir -File)
    if ($found.Count -eq 0) { throw "$exe が取得したアーカイブに見つかりません" }
    $pick = $found | Where-Object { $_.FullName -match 'x86_64|x64|win64' } | Select-Object -First 1
    if (-not $pick) { $pick = $found[0] }
    Copy-Item -Force $pick.FullName (Join-Path $bin $exe)
    Write-Host "配置: tools\bin\$exe"
}

try {
    foreach ($t in $Tools) {
        $exe = $t.Exe
        if ((Test-Path (Join-Path $bin $exe)) -or (Get-Command $exe -ErrorAction SilentlyContinue)) {
            Write-Host "あるのでスキップ: $exe"
            continue
        }
        Copy-Exe (Get-Archive $t.Url ([IO.Path]::GetFileNameWithoutExtension($exe))) $exe
    }
    $haveFfmpeg = $true
    foreach ($exe in 'ffmpeg.exe', 'ffprobe.exe') {
        if (-not ((Test-Path (Join-Path $bin $exe)) -or (Get-Command $exe -ErrorAction SilentlyContinue))) { $haveFfmpeg = $false }
    }
    if ($haveFfmpeg) {
        Write-Host "あるのでスキップ: ffmpeg.exe / ffprobe.exe"
    } else {
        $dir = Get-Archive $FfmpegUrl 'ffmpeg'
        Copy-Exe $dir 'ffmpeg.exe'
        Copy-Exe $dir 'ffprobe.exe'
    }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
Write-Host "完了: $bin"
