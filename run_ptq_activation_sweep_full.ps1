
$ErrorActionPreference = "Continue"

# Always run from the project root
Set-Location $PSScriptRoot

$Python = "D:\anaconda\envs\kwt_ref\python.exe"
$Launcher = ".\scripts\_kwt_ptq_gpu_launcher.py"
$Validator = ".\scripts\_validate_kwt1_ptq_activations_baseline_gpu.py"

$Groups = @(
    "input",
    "qkv",
    "scores",
    "softmax",
    "context",
    "residual",
    "norm",
    "ffn"
)

# All experiments use the complete validation partition
$MaxSamples = 0
$BatchSize = 128

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RootOut = ".\testdata\ptq_activation_validation\full_sweep_$Timestamp"
New-Item -ItemType Directory -Force -Path $RootOut | Out-Null

if (-not (Test-Path $Launcher)) {
    throw "Launcher not found: $Launcher"
}
if (-not (Test-Path $Validator)) {
    throw "Validator not found: $Validator"
}

$Results = @()

Write-Host ""
Write-Host "============================================"
Write-Host " Full Validation PTQ Activation Sweep"
Write-Host " Groups      : $($Groups -join ', ')"
Write-Host " Max samples : $MaxSamples (full validation)"
Write-Host " Batch size  : $BatchSize"
Write-Host " Output      : $RootOut"
Write-Host "============================================"
Write-Host ""

foreach ($Group in $Groups) {
    $OutDir = Join-Path $RootOut $Group
    $LogFile = Join-Path $RootOut "$Group.log"

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

    Write-Host ""
    Write-Host "========== GROUP: $Group ==========" -ForegroundColor Cyan
    Write-Host "Log: $LogFile"

    # Run each group in its own process and save the complete log
    & $Python $Launcher $Validator `
        --groups $Group `
        --max-samples $MaxSamples `
        --batch-size $BatchSize `
        --output-dir $OutDir 2>&1 |
        Tee-Object -FilePath $LogFile

    $ExitCode = $LASTEXITCODE
    $LogText = Get-Content $LogFile -Raw

    $SampleCheck = $LogText -match '4445\s*/\s*4445|4445\s+of\s+4445'
    $TestPartitionCheck = $LogText -match 'Testing partition accessed:\s*NO'

    if ($ExitCode -eq 0) {
        $Status = "Completed"
    } else {
        $Status = "Failed (exit $ExitCode)"
    }

    $Results += [PSCustomObject]@{
        Group                    = $Group
        Status                   = $Status
        ExitCode                 = $ExitCode
        FullValidationConfirmed  = $SampleCheck
        TestingPartitionNoAccess  = $TestPartitionCheck
        OutputDirectory          = $OutDir
        LogFile                  = $LogFile
    }

    if ($ExitCode -ne 0) {
        Write-Warning "Group '$Group' failed. Continuing with the next group."
    }
    elseif (-not $SampleCheck) {
        Write-Warning "Could not confirm 4445/4445 samples from the log for '$Group'. Check the log."
    }
}

$SummaryFile = Join-Path $RootOut "sweep_summary.csv"
$Results | Export-Csv -Path $SummaryFile -NoTypeInformation -Encoding UTF8

Write-Host ""
Write-Host "============================================"
Write-Host " Sweep finished"
Write-Host "============================================"

$Results | Format-Table Group, Status, FullValidationConfirmed, TestingPartitionNoAccess -AutoSize

Write-Host ""
Write-Host "Summary: $SummaryFile"
Write-Host "Results: $RootOut"

if (@($Results | Where-Object { $_.ExitCode -ne 0 }).Count -gt 0) {
    Write-Warning "Some groups failed. Inspect their individual log files."
    exit 1
}

if (@($Results | Where-Object { -not $_.FullValidationConfirmed }).Count -gt 0) {
    Write-Warning "Some logs did not match the expected sample-count pattern. Verify the actual processed count."
}
