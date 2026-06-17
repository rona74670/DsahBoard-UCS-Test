# Stop UCS Dashboard Server
$procs = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    (Get-NetTCPConnection -OwningProcess $_.Id -ErrorAction SilentlyContinue | Where-Object LocalPort -eq 9000)
}
if ($procs) {
    $procs | Stop-Process -Force
    Write-Host "Server stopped." -ForegroundColor Green
} else {
    Write-Host "Server not running on port 8000." -ForegroundColor Yellow
}
