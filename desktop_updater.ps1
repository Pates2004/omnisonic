# Source-update discovery and consent. The transaction engine never depends on Python.

$desktopUpdateOriginalArguments = @($args)
$script:DesktopUpdateRepository = 'Pates2004/omnisonic'
$script:DesktopUpdateBranch = 'master'

function Get-DesktopUpdateMessages {
    param([string]$ProjectRoot)
    $language = [Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName
    $settingsPath = Join-Path $ProjectRoot 'config\settings.json'
    try {
        if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
            $settings = [IO.File]::ReadAllText($settingsPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($settings.language -in @('pl', 'en')) { $language = $settings.language }
        }
    } catch { }
    if ($language -notin @('pl', 'en')) { $language = 'en' }
    try {
        return [IO.File]::ReadAllText((Join-Path $ProjectRoot ('langs\' + $language + '.lng')), [Text.Encoding]::UTF8) | ConvertFrom-Json
    } catch { return [pscustomobject]@{} }
}

function Get-DesktopUpdateText {
    param([object]$Messages, [string]$Key, [string]$Fallback)
    $property = $Messages.PSObject.Properties[$Key]
    if ($property -and $property.Value -is [string]) { return $property.Value }
    return $Fallback
}

function Invoke-DesktopUpdateHttp {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [string]$OutputPath = '',
        [int]$MaximumBytes = 2097152,
        [int]$TimeoutSeconds = 8
    )
    $address = [Uri]$Uri
    if ($address.Scheme -ne 'https' -or -not $address.IsDefaultPort -or $address.UserInfo -or
        $address.DnsSafeHost -notin @('api.github.com', 'raw.githubusercontent.com', 'codeload.github.com')) {
        throw 'An update URL is not an approved HTTPS GitHub endpoint.'
    }
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('OmniSonic-updater/1.1')
    $client.DefaultRequestHeaders.Accept.ParseAdd('application/vnd.github+json')
    $deadline = New-Object Threading.CancellationTokenSource
    $deadline.CancelAfter($TimeoutSeconds * 1000)
    $response = $null
    $inputStream = $null
    $destination = $null
    $createdOutput = $false
    $previousTls = [Net.ServicePointManager]::SecurityProtocol
    try {
        [Net.ServicePointManager]::SecurityProtocol = $previousTls -bor [Net.SecurityProtocolType]::Tls12
        $response = $client.GetAsync($address, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $deadline.Token).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200) { throw ('GitHub HTTP status ' + [int]$response.StatusCode) }
        if ($null -ne $response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -gt $MaximumBytes) {
            throw 'The update response exceeds its size limit.'
        }
        $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        if ($OutputPath) {
            $destination = [IO.File]::Open($OutputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $createdOutput = $true
        } else { $destination = New-Object IO.MemoryStream }
        $buffer = New-Object byte[] 65536
        $total = 0L
        while ($true) {
            $read = $inputStream.ReadAsync($buffer, 0, $buffer.Length, $deadline.Token).GetAwaiter().GetResult()
            if ($read -eq 0) { break }
            $total += $read
            if ($total -gt $MaximumBytes) { throw 'The update response exceeds its streamed size limit.' }
            $destination.Write($buffer, 0, $read)
        }
        if (-not $OutputPath) { return [Text.Encoding]::UTF8.GetString($destination.ToArray()) }
    }
    catch {
        $originalError = $_
        if ($destination) { $destination.Dispose(); $destination = $null }
        if ($createdOutput) {
            try { [IO.File]::Delete($OutputPath) }
            catch { Write-Warning ('Partial update download retained: ' + $OutputPath) }
        }
        throw $originalError
    }
    finally {
        if ($destination) { $destination.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
        $deadline.Dispose()
        $client.Dispose()
        [Net.ServicePointManager]::SecurityProtocol = $previousTls
    }
}

function Get-DesktopUpdateCandidate {
    param([string]$InstalledSha = '')
    $api = 'https://api.github.com/repos/' + $script:DesktopUpdateRepository
    $commits = @(Invoke-DesktopUpdateHttp ($api + '/commits?sha=master&per_page=1') | ConvertFrom-Json)
    # PowerShell5.1 can wrap a JSON array as a single pipeline object.
    $commit = @($commits | ForEach-Object { $_ })[0]
    if ($null -eq $commit -or $commit.sha -notmatch '^[a-f0-9]{40}$') { throw 'GitHub returned an invalid master commit.' }
    if ($commit.sha -eq $InstalledSha) { return $null }
    $runs = Invoke-DesktopUpdateHttp ($api + '/actions/workflows/quality.yml/runs?branch=master&event=push&head_sha=' + $commit.sha + '&per_page=1') | ConvertFrom-Json
    $run = @($runs.workflow_runs)[0]
    if ($null -eq $run -or $run.head_sha -ne $commit.sha -or $run.head_branch -ne 'master' -or
        $run.event -ne 'push' -or $run.path -ne '.github/workflows/quality.yml' -or
        $run.head_repository.full_name -ne $script:DesktopUpdateRepository -or
        $run.status -ne 'completed' -or $run.conclusion -ne 'success') { return $null }
    $remoteManifest = Invoke-DesktopUpdateHttp ('https://raw.githubusercontent.com/' + $script:DesktopUpdateRepository + '/' + $commit.sha + '/update_manifest.json') | ConvertFrom-Json
    if ($remoteManifest.schema -is [bool] -or $remoteManifest.schema -ne 1 -or $remoteManifest.algorithm -cne 'sha256-lf' -or
        $remoteManifest.version -isnot [string] -or $remoteManifest.version -notmatch '^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$') {
        throw 'The approved revision has no supported source-update manifest.'
    }
    return [pscustomobject]@{Sha=$commit.sha;Date=$commit.commit.committer.date;Subject=($commit.commit.message -split '\r?\n')[0];Run=$run.id;Version=$remoteManifest.version;Manifest=$remoteManifest}
}

function Test-DesktopUpdateSameSource {
    param([object]$InstalledManifest, [object]$RemoteManifest)
    if ($InstalledManifest.schema -ne $RemoteManifest.schema -or $InstalledManifest.algorithm -ne $RemoteManifest.algorithm -or
        $InstalledManifest.version -ne $RemoteManifest.version) { return $false }
    $oldFiles = @($InstalledManifest.files | Sort-Object path | ForEach-Object { $_.path + '=' + $_.sha256 })
    $newFiles = @($RemoteManifest.files | Sort-Object path | ForEach-Object { $_.path + '=' + $_.sha256 })
    return ($oldFiles -join "`n") -ceq ($newFiles -join "`n")
}

function Get-DesktopUpdateNotes {
    param([string]$TargetSha, [string]$InstalledSha = '')
    $api = 'https://api.github.com/repos/' + $script:DesktopUpdateRepository
    if ($TargetSha -notmatch '^[a-f0-9]{40}$') { throw 'Invalid target revision.' }
    $commits = @(Invoke-DesktopUpdateHttp ($api + '/commits?sha=' + $TargetSha + '&per_page=10') | ConvertFrom-Json | ForEach-Object { $_ })
    $notes = @()
    foreach ($commit in @($commits | Select-Object -First 10)) {
        if ($commit.sha -eq $InstalledSha) { break }
        $subject = ([string]$commit.commit.message -split '\r?\n')[0]
        $subject = $subject -replace '[\x00-\x1f\x7f]', ' '
        if ($subject.Length -gt 150) { $subject = $subject.Substring(0, 147) + '...' }
        if ($subject.Trim()) { $notes += '- ' + $subject }
    }
    return $notes -join [Environment]::NewLine
}

function Confirm-DesktopUpdate {
    param([string]$Title, [string]$Body)
    Add-Type -AssemblyName System.Windows.Forms
    return [Windows.Forms.MessageBox]::Show($Body, $Title,
        [Windows.Forms.MessageBoxButtons]::YesNo, [Windows.Forms.MessageBoxIcon]::Information,
        [Windows.Forms.MessageBoxDefaultButton]::Button2) -eq [Windows.Forms.DialogResult]::Yes
}

function ConvertTo-DesktopUpdateArgument {
    param([AllowEmptyString()][string]$Value)
    if ($Value -match '[\x00\r\n]') { throw 'Launcher arguments contain unsupported control characters.' }
    $escaped = [regex]::Replace($Value, '(\\*)"', { param($match) $match.Groups[1].Value + $match.Groups[1].Value + '\"' })
    $escaped = [regex]::Replace($escaped, '(\\+)$', { param($match) $match.Value + $match.Value })
    return '"' + $escaped + '"'
}

function Start-DesktopUpdatedLauncher {
    param([string]$ProjectRoot, [string[]]$LauncherArguments = @())
    $powershell = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
    $arguments = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $ProjectRoot 'desktop_launcher.ps1')) + $LauncherArguments
    $commandLine = @($arguments | ForEach-Object { ConvertTo-DesktopUpdateArgument $_ }) -join ' '
    if ($commandLine.Length -gt 30000) { throw 'The restart command exceeds the Windows command-line limit.' }
    $style = 'Normal'
    if ($null -eq $LauncherArguments -or $LauncherArguments.Length -eq 0) {
        try {
            $query = Invoke-DesktopUpdateProcess -FilePath $powershell -WorkingDirectory $ProjectRoot -Arguments @(
                '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $ProjectRoot 'desktop_launcher.ps1'), '-QueryHiddenLaunch'
            ) -TimeoutSeconds 10
            if ($query.ExitCode -eq 0 -and $query.Output.Trim() -ceq 'HIDE') {
                $style = 'Hidden'
                $commandLine += ' "-HiddenLaunch"'
            }
        } catch {
            # A missing/invalid readiness response must leave installation prompts visible.
        }
    }
    # A fresh process uses only the newly installed modules, never the old in-memory launcher.
    Start-Process -FilePath $powershell -ArgumentList $commandLine -WorkingDirectory $ProjectRoot -WindowStyle $style | Out-Null
}

function Invoke-DesktopUpdateProcess {
    param(
        [string]$FilePath, [string]$WorkingDirectory, [string[]]$Arguments,
        [int]$TimeoutSeconds = 90, [int]$MaximumCharacters = 1048576,
        [hashtable]$Environment = @{}
    )
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $FilePath
    $info.WorkingDirectory = $WorkingDirectory
    $info.Arguments = @($Arguments | ForEach-Object { ConvertTo-DesktopUpdateArgument $_ }) -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    foreach ($key in $Environment.Keys) { $info.EnvironmentVariables[$key] = $Environment[$key] }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $started = $false
    $stdout = New-Object Text.StringBuilder
    $stderr = New-Object Text.StringBuilder
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        if (-not $process.Start()) { throw 'Could not start the owned updater helper.' }
        $started = $true
        $outBuffer = New-Object char[] 4096
        $errBuffer = New-Object char[] 4096
        $outTask = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length)
        $errTask = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length)
        while ($outTask -or $errTask -or -not $process.HasExited) {
            if ($timer.Elapsed.TotalSeconds -gt $TimeoutSeconds) { throw 'The owned updater helper exceeded its time limit.' }
            if ($outTask -and $outTask.IsCompleted) {
                $read = $outTask.GetAwaiter().GetResult()
                if ($read) {
                    [void]$stdout.Append($outBuffer, 0, $read)
                    $outTask = $process.StandardOutput.ReadAsync($outBuffer, 0, $outBuffer.Length)
                } else { $outTask = $null }
            }
            if ($errTask -and $errTask.IsCompleted) {
                $read = $errTask.GetAwaiter().GetResult()
                if ($read) {
                    [void]$stderr.Append($errBuffer, 0, $read)
                    $errTask = $process.StandardError.ReadAsync($errBuffer, 0, $errBuffer.Length)
                } else { $errTask = $null }
            }
            if ($stdout.Length + $stderr.Length -gt $MaximumCharacters) { throw 'The owned updater helper exceeded its output limit.' }
            if ($outTask -or $errTask -or -not $process.HasExited) { Start-Sleep -Milliseconds 20 }
        }
        return [pscustomobject]@{ExitCode=$process.ExitCode;Output=$stdout.ToString();Error=$stderr.ToString()}
    }
    finally {
        if ($started -and -not $process.HasExited) {
            # Terminate only the process tree created above, never another launcher/app.
            $stopper = $null
            try {
                $stopInfo = New-Object Diagnostics.ProcessStartInfo
                $stopInfo.FileName = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'
                $stopInfo.Arguments = '/PID ' + $process.Id + ' /T /F'
                $stopInfo.UseShellExecute = $false
                $stopInfo.CreateNoWindow = $true
                $stopInfo.RedirectStandardOutput = $true
                $stopInfo.RedirectStandardError = $true
                $stopper = [Diagnostics.Process]::Start($stopInfo)
                if (-not $stopper.WaitForExit(5000)) { $stopper.Kill() }
                if (-not $process.HasExited) { $process.Kill() }
            } catch { Write-Warning ('Could not stop the owned updater helper PID ' + $process.Id + ': ' + $_.Exception.Message) }
            finally { if ($stopper) { $stopper.Dispose() } }
        }
        $process.Dispose()
    }
}

function Invoke-DesktopUpdateGitFetch {
    param([string]$Git, [string]$ProjectRoot, [string]$TargetSha)
    $result = Invoke-DesktopUpdateProcess -FilePath $Git -WorkingDirectory $ProjectRoot -Arguments @(
        '-C', $ProjectRoot, 'fetch', '--no-tags', 'origin', $TargetSha
    ) -TimeoutSeconds 90 -Environment @{GIT_TERMINAL_PROMPT='0';GCM_INTERACTIVE='Never'}
    if ($result.ExitCode -ne 0) { throw ('Git could not fetch the approved source revision. ' + $result.Error.Trim()) }
}

function Invoke-DesktopUpdateCheck {
    param([string]$ProjectRoot, [string[]]$LauncherArguments = @())
    $ErrorActionPreference = 'Stop'
    if ($env:OMNISONIC_SKIP_UPDATE -eq '1' -or @($LauncherArguments | Where-Object { $_ -in @('-SelfTest', '-QueryHiddenLaunch', '-BootstrapOnly', '-InstallOnly') }).Count) { return 0 }
    $messages = Get-DesktopUpdateMessages $ProjectRoot
    $lock = $null
    $updated = $false
    $session = ''
    try {
        $lock = Enter-DesktopUpdateLock $ProjectRoot
        Assert-DesktopUpdateAppClosed $ProjectRoot
        Repair-DesktopInterruptedUpdate -ProjectRoot $ProjectRoot -LockHeld | Out-Null
        $pending = Join-Path $ProjectRoot '.launcher\update-recovery\pending.json'
        if (Test-Path -LiteralPath $pending) { return 0 }
        Assert-DesktopUpdateRecoveryClear -ProjectRoot $ProjectRoot
        $manifestPath = Join-Path $ProjectRoot 'update_manifest.json'
        $manifest = Read-DesktopUpdateManifest $manifestPath
        $installedSha = ''
        $gitContext = $null
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
            $gitContext = Get-DesktopUpdateGitContext $ProjectRoot
            $installedSha = $gitContext.OldSha
        } else {
            $statePath = Join-Path $ProjectRoot '.launcher\update-state.json'
            if (Test-Path -LiteralPath $statePath -PathType Leaf) {
                $state = [IO.File]::ReadAllText($statePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
                if ($state.sha -match '^[a-f0-9]{40}$') { $installedSha = $state.sha }
            }
        }
        $candidate = Get-DesktopUpdateCandidate $installedSha
        if ($null -eq $candidate) { return 0 }
        if (Test-DesktopUpdateSameSource $manifest $candidate.Manifest) { return 0 }
        $notes = Get-DesktopUpdateNotes $candidate.Sha $installedSha
        $title = Get-DesktopUpdateText $messages 'update_title' 'OmniSonic update'
        $template = Get-DesktopUpdateText $messages 'update_offer' 'A tested OmniSonic update is available: {0} ({1}, {2}). Installed: {5}.{3}{3}Recent changes (up to10):{3}{4}{3}{3}Download and restart? Your settings, presets and Python environments will be preserved. Previous source files are kept only until the new application starts successfully.'
        $body = $template -f $candidate.Version, $candidate.Sha.Substring(0, 7), $candidate.Date, [Environment]::NewLine, $notes, $manifest.version
        if (-not (Confirm-DesktopUpdate $title $body)) { return 0 }
        Assert-DesktopUpdateAppClosed $ProjectRoot
        $checks = Join-Path $ProjectRoot '.launcher\updates'
        if ((Test-Path -LiteralPath $checks) -and ((Get-Item -LiteralPath $checks -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Update staging is redirected.' }
        [IO.Directory]::CreateDirectory($checks) | Out-Null
        $session = Join-Path $checks ([Guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($session) | Out-Null
        $archive = Join-Path $session 'source.zip'
        Write-Host (Get-DesktopUpdateText $messages 'update_downloading' 'Downloading the verified source update...')
        Invoke-DesktopUpdateHttp ('https://codeload.github.com/' + $script:DesktopUpdateRepository + '/zip/' + $candidate.Sha) $archive 33554432 90
        $prepared = Expand-DesktopUpdateArchive $archive (Join-Path $session 'prepared')
        New-DesktopUpdatePlan $ProjectRoot $prepared.Root | Out-Null
        if ($gitContext) {
            # Fetch only after consent; core rechecks provenance, ancestry and exact tree ownership.
            Invoke-DesktopUpdateGitFetch $gitContext.Git $ProjectRoot $candidate.Sha
            Get-DesktopUpdateGitContext $ProjectRoot -TargetSha $candidate.Sha | Out-Null
        }
        Assert-DesktopUpdateAppClosed $ProjectRoot
        Invoke-DesktopSourceUpdate $ProjectRoot $prepared.Root $candidate.Sha -DownloadSession $session | Out-Null
        $updated = $true
    }
    catch {
        $pending = Join-Path $ProjectRoot '.launcher\update-recovery\pending.json'
        if (Test-Path -LiteralPath $pending) {
            $template = Get-DesktopUpdateText $messages 'update_recovery_required' 'Source update recovery must finish before starting. Recovery: {0}. Details: {1}'
            Write-Warning ($template -f (Split-Path -Parent $pending), $_.Exception.Message)
            return 20
        }
        $template = Get-DesktopUpdateText $messages 'update_unavailable' 'Update not applied; using the current installation. Details: {0}'
        Write-Warning ($template -f $_.Exception.Message)
        if ($session) { Write-Warning ('Update staging retained for inspection: ' + $session) }
        return 0
    }
    finally { if ($lock) { $lock.Dispose() } }
    if ($updated) {
        try {
            Start-DesktopUpdatedLauncher $ProjectRoot $LauncherArguments
            return 10
        } catch {
            $template = Get-DesktopUpdateText $messages 'update_restart_failed' 'The updated source is installed, but restart failed. Start OmniSonic again; recovery files were retained. Details: {0}'
            Write-Warning ($template -f $_.Exception.Message)
            return 20
        }
    }
    return 0
}

$desktopUpdateCorePath = Join-Path $PSScriptRoot 'desktop_update_runtime.ps1'
if (Test-Path -LiteralPath $desktopUpdateCorePath -PathType Leaf) { . $desktopUpdateCorePath }
if ($MyInvocation.InvocationName -eq '.') { return }
if (-not (Test-Path -LiteralPath $desktopUpdateCorePath -PathType Leaf)) {
    Write-Warning 'Source updater is incomplete; continuing with the installed launcher.'
    exit 0
}
exit (Invoke-DesktopUpdateCheck -ProjectRoot $PSScriptRoot -LauncherArguments $desktopUpdateOriginalArguments)
