<# 停止本地 AI Robot 服务（8000 端口） #>
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $ids = @($conn | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($id in $ids) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    Write-Host "已停止端口 8000 服务（PID: $($ids -join ', ')）" -ForegroundColor Green
} else {
    Write-Host "端口 8000 没有服务在运行" -ForegroundColor Yellow
}