[CmdletBinding()]
param(
    [string]$Namespace = $env:AIOPS_SMOKE_NAMESPACE,
    [int]$StartupTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Namespace)) {
    $Namespace = "techx-corp-prod"
}

$forwards = @(
    [pscustomobject]@{ Name = "prometheus"; LocalPort = 9090; RemotePort = 9090; Scheme = "http" },
    [pscustomobject]@{ Name = "jaeger"; LocalPort = 16686; RemotePort = 16686; Scheme = "http" },
    [pscustomobject]@{ Name = "opensearch"; LocalPort = 9200; RemotePort = 9200; Scheme = "https" },
    [pscustomobject]@{ Name = "grafana"; LocalPort = 3000; RemotePort = 80; Scheme = "http" }
)
$proxyPort = 8001
$jobs = @()

function Test-LocalPort {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(250) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Assert-KubectlSucceeded {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl failed while checking $Description"
    }
}

try {
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        throw "kubectl is not installed or is not available on PATH"
    }

    $context = kubectl config current-context
    Assert-KubectlSucceeded "the current context"
    Write-Host "AIOps live port-forward" -ForegroundColor Cyan
    Write-Host "Context: $context" -ForegroundColor Gray
    Write-Host "Namespace: $Namespace" -ForegroundColor Gray

    kubectl get namespace $Namespace -o name | Out-Null
    Assert-KubectlSucceeded "namespace/$Namespace"

    foreach ($forward in $forwards) {
        kubectl -n $Namespace get service $forward.Name -o name | Out-Null
        Assert-KubectlSucceeded "service/$($forward.Name)"
    }

    foreach ($port in @($forwards.LocalPort) + $proxyPort) {
        if (Test-LocalPort -Port $port) {
            throw "Local port $port is already in use. Stop the old forward or choose a free port."
        }
    }

    foreach ($forward in $forwards) {
        $job = Start-Job -ScriptBlock {
            param($Ns, $Service, $LocalPort, $RemotePort)
            kubectl -n $Ns port-forward "service/$Service" "${LocalPort}:${RemotePort}" 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "kubectl port-forward exited with code $LASTEXITCODE"
            }
        } -ArgumentList $Namespace, $forward.Name, $forward.LocalPort, $forward.RemotePort
        $jobs += $job
    }

    $jobs += Start-Job -ScriptBlock {
        param($Port)
        kubectl proxy --port=$Port 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "kubectl proxy exited with code $LASTEXITCODE"
        }
    } -ArgumentList $proxyPort

    $requiredPorts = @($forwards.LocalPort) + $proxyPort
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        $readyPorts = @($requiredPorts | Where-Object { Test-LocalPort -Port $_ })
        if ($readyPorts.Count -eq $requiredPorts.Count) {
            break
        }
        $failedJobs = @($jobs | Where-Object { $_.State -ne "Running" })
        if ($failedJobs) {
            $details = $failedJobs | Receive-Job -Keep | Out-String
            throw "A port-forward stopped during startup.`n$details"
        }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)

    if ($readyPorts.Count -ne $requiredPorts.Count) {
        $missing = @($requiredPorts | Where-Object { $_ -notin $readyPorts }) -join ", "
        $details = $jobs | Receive-Job -Keep | Out-String
        throw "Timed out waiting for local port(s): $missing`n$details"
    }

    Write-Host "`nEndpoints ready:" -ForegroundColor Green
    foreach ($forward in $forwards) {
        Write-Host ("  {0,-12} {1}://localhost:{2}" -f $forward.Name, $forward.Scheme, $forward.LocalPort)
    }
    Write-Host ("  {0,-12} http://localhost:{1}" -f "kubernetes", $proxyPort)
    Write-Host "  aiops       http://localhost:8000 (start separately for Grafana inbound test)"

    Write-Host "`nCredential requirements:" -ForegroundColor Yellow
    Write-Host "  Prometheus, Jaeger, Kubernetes proxy, Grafana health: no service credential"
    Write-Host "  OpenSearch: Basic Auth username/password is required"
    Write-Host "  Grafana inbound webhook: shared secret must match the AIOps process"
    Write-Host "  Notification: external webhook URL; it cannot be port-forwarded"
    Write-Host "`nPress Ctrl+C to stop only the jobs created by this script." -ForegroundColor Gray

    while ($true) {
        Wait-Job -Job $jobs -Any -Timeout 5 | Out-Null
        $stoppedJobs = @($jobs | Where-Object { $_.State -ne "Running" })
        if ($stoppedJobs) {
            $details = $stoppedJobs | Receive-Job -Keep | Out-String
            throw "A port-forward stopped unexpectedly.`n$details"
        }
    }
}
finally {
    if ($jobs) {
        $jobs | Stop-Job -ErrorAction SilentlyContinue
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    }
}
