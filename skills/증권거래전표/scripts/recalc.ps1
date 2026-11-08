# 엑셀로 워크북을 열어 전부 다시 계산하고 저장한다(수식 결과값을 파일에 남기려고).
# 쓰기: powershell -NoProfile -ExecutionPolicy Bypass -File recalc.ps1 <xlsx 절대경로>
param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
    $wb = $xl.Workbooks.Open($Path)
    $xl.CalculateFull()
    $wb.Save()
    $wb.Close($false)
    Write-Output "recalc ok"
} finally {
    $xl.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
}
