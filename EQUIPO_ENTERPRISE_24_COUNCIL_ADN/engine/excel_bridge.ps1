# OrgDNA Excel adapter: Windows + desktop Excel, no macros or VBOM.
# No ExecutionPolicy change or bypass. If local policy blocks this script,
# have the user follow their organization's script-signing/trust process.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('Read','Apply')][string]$Action,
  [Parameter(Mandatory=$true)][string]$WorkbookPath,
  [string]$PayloadPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$resolved = (Resolve-Path -LiteralPath $WorkbookPath).Path
if ([IO.Path]::GetExtension($resolved) -ine '.xlsx') { throw 'Only the designated .xlsx workbook is supported.' }
$contractPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'workbook\sheet_ranges.json'
$contract = Get-Content -Raw -LiteralPath $contractPath -Encoding UTF8 | ConvertFrom-Json
$excel = $null; $book = $null; $createdExcel = $false; $openedBook = $false
$oldSecurity = $null
function Write-SafeValue($sheet, [int]$row, [int]$column, $value) {
  $cell = $sheet.Cells.Item($row,$column)
  try {
    if ($null -eq $value) { $cell.ClearContents() | Out-Null }
    elseif ($value -is [string]) {
      if ($value.Length -gt 32767) { throw 'Cell text exceeds Excel 32767 UTF-16 units; refusing truncation.' }
      # Excel COM may parse =,+,-,@ prefixes as a formula. Text format must be
      # set BEFORE assignment. Never write Formula/Formula2 from external data.
      $cell.NumberFormat = '@'
      $cell.Value2 = [string]$value
      if ($cell.HasFormula) { $cell.ClearContents() | Out-Null; throw 'Unexpected formula blocked.' }
    } elseif ($value -is [bool]) { $cell.Value2 = [bool]$value }
    else { $cell.NumberFormat = 'General'; $cell.Value2 = [double]$value }
  } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell) }
}
function Write-SafeAddress($sheet, [string]$address, $value) {
  $cell = $sheet.Range($address)
  try { $row = $cell.Row; $col = $cell.Column } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell) }
  Write-SafeValue $sheet $row $col $value
}
function Read-Snapshot($workbook) {
  $configSheet = $workbook.Worksheets.Item([string]$contract.configuration.sheet)
  $config = @{}
  foreach ($entry in $contract.configuration.cells.PSObject.Properties) {
    $cell = $configSheet.Range([string]$entry.Value)
    try { $config[$entry.Name] = $cell.Value2 } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell) }
  }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($configSheet)
  $assignmentSheet = $workbook.Worksheets.Item([string]$contract.assignments.sheet)
  $overrides = @{}
  for ($row=6; $row -le 37; $row++) {
    $id = [string]$assignmentSheet.Cells.Item($row,2).Value2
    $providerCell=$assignmentSheet.Cells.Item($row,4);$modelCell=$assignmentSheet.Cells.Item($row,5)
    $manual=@{}
    try {
      $provider=[string]$providerCell.Value2;$model=[string]$modelCell.Value2
      if (-not $providerCell.HasFormula -and $provider.Trim()) { $manual.provider=$provider.Trim().ToLowerInvariant() }
      if (-not $modelCell.HasFormula -and $model.Trim()) { $manual.model=$model.Trim() }
    } finally {
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($providerCell)
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($modelCell)
    }
    if ($id.Trim() -and $manual.Count -gt 0) { $overrides[$id.Trim()]=$manual }
  }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($assignmentSheet)
  $modelSheet=$workbook.Worksheets.Item('Modelos');$preferences=@()
  for ($row=6; $row -le 205; $row++) {
    $provider=[string]$modelSheet.Cells.Item($row,1).Value2;$model=[string]$modelSheet.Cells.Item($row,2).Value2
    if ($provider.Trim() -and $model.Trim()) {
      $preferences+=@{ provider=$provider.Trim();model=$model.Trim();user_rank=$modelSheet.Cells.Item($row,5).Value2;capabilities=$modelSheet.Cells.Item($row,7).Value2 }
    }
  }
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($modelSheet)
  return @{ config=$config; model_overrides=$overrides; model_preferences=$preferences; source='excel_com_live'; saved=$workbook.Saved }
}
try {
  try { $excel = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application') }
  catch { $excel = New-Object -ComObject Excel.Application; $createdExcel=$true; $excel.Visible=$false }
  $oldSecurity=$excel.AutomationSecurity
  $excel.AutomationSecurity=3 # msoAutomationSecurityForceDisable; restore in finally.
  foreach ($candidate in $excel.Workbooks) {
    if ([string]$candidate.FullName -ieq $resolved) { $book=$candidate; break }
  }
  if ($null -eq $book) {
    if ($Action -eq 'Read') { throw 'Open the designated workbook in the active Excel instance before live synchronization. Saved-file reading is a separate panel action.' }
    # UpdateLinks=0 prevents external link refresh; no macros in .xlsx.
    $book=$excel.Workbooks.Open($resolved,0,($Action -eq 'Read'))
    $openedBook=$true
  }
  if ($Action -eq 'Read') {
    $result=Read-Snapshot $book
    $result | ConvertTo-Json -Depth 20 -Compress
  } else {
    if ($book.ReadOnly) { throw 'Workbook is read-only. Open an editable copy before applying.' }
    if (-not $PayloadPath) { throw 'Apply requires the generated data payload.' }
    $payload=Get-Content -Raw -LiteralPath $PayloadPath -Encoding UTF8 | ConvertFrom-Json
    if ($payload.schema_version -ne '1.0') { throw 'Unknown bridge payload version.' }
    # Hardcoded allowlist. Neither repository text nor HTTP request can select
    # arbitrary sheets, ranges, formulas, commands, or workbook names.
    $targets=@{
      profiles=@{ sheet='Perfiles'; rows=32; columns=10; skip=@() };
      cv=@{ sheet='CV'; rows=400; columns=6; skip=@() };
      skills=@{ sheet='Competencias'; rows=400; columns=8; skip=@() };
      council=@{ sheet='Council'; rows=32; columns=9; skip=@(5) };
      subteams=@{ sheet='Subequipos'; rows=32; columns=9; skip=@(4) };
      assignments=@{ sheet='Asignacion_modelos'; rows=32; columns=11; skip=@(6,7,8) };
      models=@{ sheet='Modelos'; rows=200; columns=8; skip=@() }
    }
    # Validate the whole payload before the first write.
    foreach ($entry in $payload.sheets.PSObject.Properties) {
      if (-not $targets.ContainsKey($entry.Name)) { throw 'Unknown output sheet key.' }
      $target=$targets[$entry.Name]; $rows=@($entry.Value.rows)
      if ($rows.Count -gt $target.rows) { throw ('Too many rows for '+$target.sheet+'. Nothing is truncated.') }
      $null=$book.Worksheets.Item($target.sheet)
      foreach ($values in $rows) {
        if (@($values).Count -ne $target.columns) { throw ('Wrong number of columns for '+$target.sheet) }
        foreach ($value in $values) { if ($value -is [string] -and $value.Length -gt 32767) { throw 'Cell text exceeds Excel limit.' } }
      }
    }
    # Save an independent recovery copy before any mutation, including unsaved edits.
    $backupPath=Join-Path ([IO.Path]::GetDirectoryName($resolved)) ([IO.Path]::GetFileNameWithoutExtension($resolved)+'.before-apply.'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')+'.'+[Guid]::NewGuid().ToString('N').Substring(0,6)+'.xlsx')
    $book.SaveCopyAs($backupPath)
    $configSheet=$book.Worksheets.Item([string]$contract.configuration.sheet)
    foreach ($entry in $contract.configuration.cells.PSObject.Properties) {
      $property=$payload.config.PSObject.Properties[$entry.Name]
      if ($null -ne $property) {
        # The council concurrency cell may be a template formula =B8.
        $cell=$configSheet.Range([string]$entry.Value)
        $preserve=($entry.Name -eq 'council_concurrency' -and $cell.HasFormula)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell)
        if (-not $preserve) { Write-SafeAddress $configSheet ([string]$entry.Value) $property.Value }
      }
    }
    foreach ($entry in $payload.sheets.PSObject.Properties) {
      $target=$targets[$entry.Name]; $sheet=$book.Worksheets.Item($target.sheet); $rows=@($entry.Value.rows)
      if ($entry.Name -eq 'assignments') {
        for ($offset=0; $offset -lt $rows.Count; $offset++) {
          $row=$offset+6;$values=$rows[$offset]
          foreach ($col in @(1,2,3,9,10,11)) { Write-SafeValue $sheet $row $col $values[$col-1] }
          foreach ($col in @(4,5)) {
            $manual=$values[$col-1]
            if ($null -ne $manual -and [string]$manual -ne '') { Write-SafeValue $sheet $row $col $manual }
            else {
              # Only fixed, code-owned template formulas are allowed here.
              # All model/provider values themselves live in safe text cells.
              $cell=$sheet.Cells.Item($row,$col);$cell.NumberFormat='General'
              if ($col -eq 4) { $cell.Formula=('=IF(J{0}<>"",J{0},''Configuracion''!$B$11)' -f $row) }
              else { $cell.Formula=('=IF(K{0}<>"",K{0},''Configuracion''!$B$12)' -f $row) }
              [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell)
            }
          }
        }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
        continue
      }
      # Keep inactive profile seeds so changing N in Excel still reveals all
      # 32 template slots. STALE warns that a new generation/apply is required.
      $writeRows=$target.rows
      if ($entry.Name -eq 'profiles') { $writeRows=$rows.Count }
      for ($offset=0; $offset -lt $writeRows; $offset++) {
        for ($col=1; $col -le $target.columns; $col++) {
          if ($target.skip -contains $col) { continue }
          $value=$null
          if ($offset -lt $rows.Count) { $value=$rows[$offset][$col-1] }
          Write-SafeValue $sheet ($offset+6) $col $value
        }
      }
      # Resize an existing Excel Table only; never create a second table over
      # formulas or user data. Template may instead use plain validated ranges.
      if ($sheet.ListObjects.Count -gt 0 -and $target.skip.Count -eq 0) {
        $table=$sheet.ListObjects.Item(1)
        if ($table.Range.Row -eq 5 -and $table.Range.Column -eq 1) {
          $last=[Math]::Max(6,5+$rows.Count)
          $table.Resize($sheet.Range($sheet.Cells.Item(5,1),$sheet.Cells.Item($last,$target.columns)))
        }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($table)
      }
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
    }
    # Existing model dropdowns refer to this stable workbook-scoped name.
    try { $name=$book.Names.Item('CatalogoModelos'); $name.RefersTo="='Modelos'!`$B`$6:`$B`$205" }
    catch { $name=$book.Names.Add('CatalogoModelos',"='Modelos'!`$B`$6:`$B`$205") }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($name)
    foreach ($address in @('Configuracion!B12','Asignacion_modelos!E6:E37')) {
      $parts=$address.Split('!');$sheet=$book.Worksheets.Item($parts[0]);$range=$sheet.Range($parts[1])
      $range.Validation.Delete()
      # xlValidateList=3, xlValidAlertWarning=2, xlBetween=1. Warning allows an
      # explicit manual model override, which remains UNVERIFIED unless found.
      $range.Validation.Add(3,2,1,'=CatalogoModelos')
      $range.Validation.IgnoreBlank=$true;$range.Validation.InCellDropdown=$true
      $range.Validation.ShowError=$true;$range.Validation.ErrorTitle='Modelo manual no verificado'
      $range.Validation.ErrorMessage='Verifica proveedor y disponibilidad antes de ejecutar. Se permite override manual.'
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($range)
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
    }
    # Replace only the nine declared launch/download cells with native links.
    # Targets are fixed loopback paths; provider/repository text cannot supply URLs.
    $linkTargets=@{
      'Inicio!A17'=@('http://127.0.0.1:8765/','ABRIR PANEL LOCAL');
      'Inicio!A19'=@('http://127.0.0.1:8765/download/implementation.json','DESCARGAR RECIPE DSH');
      'Inicio!A21'=@('http://127.0.0.1:8765/download/definitions.json','DESCARGAR BACKUP DE DEFINICIONES');
      'Inicio!A23'=@('http://127.0.0.1:8765/download/package.zip','DESCARGAR ZIP COMPLETO');
      'Exportacion!B6'=@('http://127.0.0.1:8765/download/implementation.json','Descargar recipe DSH');
      'Exportacion!B7'=@('http://127.0.0.1:8765/download/definitions.json','Descargar definitions backup');
      'Exportacion!B8'=@('http://127.0.0.1:8765/download/package.zip','Descargar ZIP completo');
      'Exportacion!B9'=@('http://127.0.0.1:8765/download/council.json','Council recipe opcional');
      'Exportacion!B10'=@('http://127.0.0.1:8765/','Abrir panel local')
    }
    foreach ($address in $linkTargets.Keys) {
      $parts=$address.Split('!'); $sheet=$book.Worksheets.Item($parts[0]); $cell=$sheet.Range($parts[1])
      $cell.Hyperlinks.Delete()
      $target=$linkTargets[$address]
      $null=$sheet.Hyperlinks.Add($cell,[string]$target[0],'','Requiere launch.cmd y motor local',[string]$target[1])
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($cell)
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
    }
    $metadata=$contract.configuration.bridge_metadata
    Write-SafeAddress $configSheet ([string]$metadata.last_applied) ([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))
    Write-SafeAddress $configSheet ([string]$metadata.applied_config) ([string]$payload.fingerprint)
    Write-SafeAddress $configSheet ([string]$metadata.profile_status) 'GENERADO_LOCAL / RUNTIME NO EJECUTADO'
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($configSheet)
    $excel.CalculateFull()
    $book.Save()
    @{ ok=$true; workbook=$resolved; backup=$backupPath; snapshot=(Read-Snapshot $book); saved=$book.Saved; adapter='Windows Excel COM'; formulas_preserved=@('Organigrama','Council!E6:E37','Subequipos!D6:D37','Asignacion_modelos!A:C,F'); updated_at=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Depth 10 -Compress
  }
} catch {
  if ($backupPath) { Write-Error ('Apply did not finish. The workbook may contain partial changes. Recovery copy: '+$backupPath+'; '+$_.Exception.Message) }
  else { Write-Error $_ }
  exit 1
} finally {
  if ($null -ne $book) {
    if ($openedBook) { $book.Close($false) }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book)
  }
  if ($null -ne $excel) {
    if ($null -ne $oldSecurity) { $excel.AutomationSecurity=$oldSecurity }
    if ($createdExcel) { $excel.Quit() }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
  }
  [GC]::Collect();[GC]::WaitForPendingFinalizers()
}
