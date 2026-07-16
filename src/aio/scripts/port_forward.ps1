# Port-Forward Helper for AIOps Smoke Testing
# =============================================================================
# Opens all required port-forwards in background jobs.
# Run this script, then run the smoke tests in another terminal.
#
# Usage:  powershell -File scripts/port_forward.ps1
# Stop:   Get-Job | Stop-Job; Get-Job | Remove-Job
# =============================================================================

$NS = "techx-corp-prod"

Write-Host "=== AIOps Port-Forward Helper ===" -ForegroundColor Cyan
Write-Host "Namespace: $NS" -ForegroundColor Gray
Write-Host ""

# Define port-forward mappings: [local_port, service_name, remote_port]
$forwards = @(
    @(9090,  "prometheus",  9090),
    @(16686, "jaeger",      16686),
    @(9200,  "opensearch",  9200),
    @(3000,  "grafana",     80)
)

# Start kubectl proxy for Kubernetes API (no token needed)
Write-Host "[K8s API] Starting kubectl proxy on :8001 ..." -ForegroundColor Yellow
$proxyJob = Start-Job -ScriptBlock {
    kubectl proxy --port=8001 2>&1
}
Write-Host "[K8s API] kubectl proxy -> localhost:8001  (job $($proxyJob.Id))" -ForegroundColor Green

# Start each port-forward as a background job
foreach ($fwd in $forwards) {
    $localPort  = $fwd[0]
    $svcName    = $fwd[1]
    $remotePort = $fwd[2]

    Write-Host "[$svcName] Starting port-forward :${localPort} -> svc/${svcName}:${remotePort} ..." -ForegroundColor Yellow

    $job = Start-Job -ScriptBlock {
        param($ns, $svc, $lp, $rp)
        kubectl -n $ns port-forward "svc/$svc" "${lp}:${rp}" 2>&1
    } -ArgumentList $NS, $svcName, $localPort, $remotePort

    Write-Host "[$svcName] localhost:$localPort -> svc/${svcName}:${remotePort}  (job $($job.Id))" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== All port-forwards started ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Endpoints ready:" -ForegroundColor White
Write-Host "  Prometheus   : http://localhost:9090"
Write-Host "  Jaeger       : http://localhost:16686"
Write-Host "  OpenSearch   : http://localhost:9200"
Write-Host "  Grafana      : http://localhost:3000"
Write-Host "  K8s API Proxy: http://localhost:8001"
Write-Host ""
Write-Host "To stop all: Get-Job | Stop-Job; Get-Job | Remove-Job" -ForegroundColor Gray
Write-Host "Press Ctrl+C to exit (port-forwards keep running as jobs)" -ForegroundColor Gray
Write-Host ""

# Keep script alive and show job status
try {
    while ($true) {
        Start-Sleep -Seconds 30
        $failed = Get-Job | Where-Object { $_.State -eq "Failed" }
        if ($failed) {
            Write-Host "[WARN] Some port-forwards failed:" -ForegroundColor Red
            foreach ($f in $failed) {
                Write-Host "  Job $($f.Id): $($f.ChildJobs[0].JobStateInfo.Reason)" -ForegroundColor Red
            }
        }
    }
} finally {
    Write-Host "Cleaning up port-forward jobs..." -ForegroundColor Yellow
    Get-Job | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Remove-Job -ErrorAction SilentlyContinue
}
