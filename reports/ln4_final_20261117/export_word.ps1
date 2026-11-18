$ErrorActionPreference = 'Stop'
$reportBase = $PSScriptRoot
$reportFile = Join-Path $reportBase '30022_uv_KWT1_作品设计报告_SystemBus修正版.docx'
$reportPdf = [IO.Path]::ChangeExtension($reportFile, '.pdf')
$wordTask = New-Object -ComObject Word.Application
$wordTask.Visible = $false
$wordTask.DisplayAlerts = 0
try {
    $wordDoc = $wordTask.Documents.Open($reportFile, $false, $false)
    try {
        $null = $wordDoc.Fields.Update()
        foreach ($reportToc in $wordDoc.TablesOfContents) { $reportToc.Update() }
        $wordDoc.Repaginate()
        $wordDoc.Save()
        $wordDoc.ExportAsFixedFormat($reportPdf, 17)
        Write-Output ('WORD_EXPORT_PAGES ' + $wordDoc.ComputeStatistics(2))
    } finally { $wordDoc.Close(0) }
} finally { $wordTask.Quit() }
