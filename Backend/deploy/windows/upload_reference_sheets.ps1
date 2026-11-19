# Store the fixed ("static") sheets in Supabase, schema `reference` (ingestion/reference_sheets.py).
# Run after deploy/supabase_edits.sql has been run in Supabase (it creates the `reference` folder).
#   Set-ExecutionPolicy -Scope Process Bypass; .\upload_reference_sheets.ps1
# Re-running replaces the stored copies. Importers then read them with supabase:<name>, e.g.
#   .venv\Scripts\python.exe manage.py import_asm_tracker supabase:asm_tracker_2026_11 --month 2026-11
$ErrorActionPreference = "Stop"
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$py = Join-Path $backend ".venv\Scripts\python.exe"
$td = Join-Path $env:USERPROFILE "Desktop\TD_Data\DATA"
$imp = Join-Path $backend "data\import"
Set-Location $backend

$sheets = @(
    # name                        file                                                                        columns kept
    @("order_tracking_workbook", (Join-Path $td "Technodirect Order Tracking (2).xlsx"), ""),
    @("asm_tracker_2026_04", (Join-Path $imp "asm_tracker\Technodirect Order Tracking - Apr 26 (Sheet10).csv"), ""),
    @("asm_tracker_2026_10", (Join-Path $imp "asm_tracker\Technodirect Order Tracking - Oct 26 (Sheet10).csv"), ""),
    @("asm_tracker_2026_11", (Join-Path $imp "asm_tracker\Technodirect Order Tracking - Nov 26 (Sheet10 update).csv"), ""),
    @("asm_beat_plan_2026_09", (Join-Path $imp "asm_tracker\ASM Beat Plan - Sept 26.tsv"), ""),
    # HR sheet: only what the sales hierarchy needs - phone numbers, emails and addresses stay out of Supabase
    @("sales_team", (Join-Path $td "Master ASM Tracker - ASM_RSM_FSE complete details.csv"),
      "Emp ID,Name,DOJ,Designation,Reporting Manager,City,Region,Current Status"),
    @("distributor_names", (Join-Path $imp "distributor_names\Distribuot Formatting - Sheet1.csv"), ""),
    @("distributor_network", (Join-Path $imp "distributor_network.csv"), ""),
    # TD P&L - Quarter-on-Quarter (QoQ) Analysis: once with the values, once with every formula (=G4-G5) as written
    @("pnl_qoq", (Join-Path $td "TD_P&L_QoQ_Rev.xlsx"), ""),
    @("pnl_qoq_formulas", (Join-Path $td "TD_P&L_QoQ_Rev.xlsx"), "--formulas"),
    # the two "live" sheets, until their Google Sheet links are set in .env: re-upload when the team updates them
    @("settlement_tracker", (Join-Path $td "Technodirect Order Tracking - Tracker.csv"), ""),
    @("distributor_sync", (Join-Path $td "TechnoDirect Data - TechnoD Distributors (2).csv"), "")
)
foreach ($s in $sheets) {
    $name, $file, $cols = $s
    if (-not (Test-Path $file)) { Write-Host "skipped $name - file not found: $file" -ForegroundColor Yellow; continue }
    Write-Host "== $name" -ForegroundColor Cyan
    if ($cols -eq "--formulas") { & $py manage.py reference_sheet upload $name $file --formulas }
    elseif ($cols) { & $py manage.py reference_sheet upload $name $file --columns $cols }
    else { & $py manage.py reference_sheet upload $name $file }
}
& $py manage.py reference_sheet list
