<#
一键启动 Go 文章社区助手（本地 Ollama 模式）：
  检查 .env / 虚拟环境 / 依赖 / Ollama 模型 -> 启动 uvicorn -> 等待健康检查 -> 打开控制台
用法：powershell -ExecutionPolicy Bypass -File .\start.ps1   （或直接双击 start.bat）
参数：-NoBrowser  不自动打开浏览器（远程/CI 场景）
#>
param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$port = 8000
$url  = "http://localhost:$port"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Go 文章社区助手一键启动（本地 Ollama 模式）" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1) 配置
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[1/6] 已生成 .env（请按需检查密钥/模型）" -ForegroundColor Yellow
} else {
    Write-Host "[1/6] .env 已存在" -ForegroundColor Green
}

# 2) 虚拟环境
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "[2/6] 创建虚拟环境 .venv ..." -ForegroundColor Yellow
    python -m venv .venv
    if (-not (Test-Path $py)) { Write-Error "创建 .venv 失败，请先安装 Python 3.10+" }
}
Write-Host "[2/6] 虚拟环境就绪" -ForegroundColor Green

# 3) 依赖（幂等，缺失自动安装）
Write-Host "[3/6] 检查核心依赖 ..." -ForegroundColor Yellow
& $py -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "依赖安装失败，请检查网络后重试" }
Write-Host "[3/6] 依赖就绪" -ForegroundColor Green

# 4) Ollama 与模型检查
function Get-EnvValue($key) {
    $line = Select-String -Path ".env" -Pattern ("^" + $key + "=") | Select-Object -First 1
    if ($line) { return $line.Line.Substring($key.Length + 1).Trim() }
    return $null
}
$llmModel = Get-EnvValue "AIROBOT_LLM_MODEL"
$embModel = Get-EnvValue "AIROBOT_EMBEDDING_MODEL"
try {
    $tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    $local = @()
    foreach ($m in @($tags.models)) { $local += ($m.name -replace ":latest$", "") }
    $missing = @()
    if ($llmModel -and $local -notcontains ($llmModel -replace ":latest$", "")) { $missing += $llmModel }
    if ($embModel -and $local -notcontains ($embModel -replace ":latest$", "")) { $missing += $embModel }
    Write-Host "[4/6] Ollama 在线；本地模型: $($local -join ', ')" -ForegroundColor Green
    if ($missing.Count -gt 0) {
        Write-Host "  缺少模型，请先拉取：" -ForegroundColor Yellow
        foreach ($m in $missing) { Write-Host "    ollama pull $m" -ForegroundColor Yellow }
    }
} catch {
    Write-Warning "[4/6] Ollama 未运行！请启动 Ollama 并拉取模型：ollama pull $llmModel; ollama pull $embModel"
}

# 5) 端口检查（已在运行则直接打开控制台）
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "[5/6] 端口 $port 已有服务在运行，直接打开控制台" -ForegroundColor Yellow
    if (-not $NoBrowser) { Start-Process "$url/dashboard" }
    exit 0
}
Write-Host "[5/6] 端口 $port 空闲" -ForegroundColor Green

# 6) 启动服务并等待健康检查
$logDir = Join-Path $root ".logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$outLog = Join-Path $logDir "uvicorn.out.log"
$errLog = Join-Path $logDir "uvicorn.err.log"
Write-Host "[6/6] 启动 uvicorn（日志: .logs\uvicorn.*.log）..." -ForegroundColor Yellow
Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$port" `
    -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog | Out-Null

$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
        $h = Invoke-RestMethod "$url/health" -TimeoutSec 2
        $ok = $true
        break
    } catch {}
}
if (-not $ok) {
    Write-Error "服务启动超时，请查看 $errLog"
}
Write-Host "服务已启动: LLM=$($h.llm_model) / Embedding=$($h.embedding_model)" -ForegroundColor Green
Write-Host "控制台: $url/dashboard" -ForegroundColor Cyan
Write-Host "指标:   $url/api/v1/stats" -ForegroundColor DarkGray
Write-Host "停止:   运行 .\stop.ps1" -ForegroundColor DarkGray
if (-not $NoBrowser) { Start-Process "$url/dashboard" }
