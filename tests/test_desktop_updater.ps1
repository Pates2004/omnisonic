$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\project_materials.ps1')
$testProject = Split-Path -Parent $PSScriptRoot
$modulePath = Join-Path $testProject 'desktop_updater.ps1'
$parseTokens = $null
$parseErrors = $null
$moduleAst = [Management.Automation.Language.Parser]::ParseFile($modulePath, [ref]$parseTokens, [ref]$parseErrors)
if (@($parseErrors).Count) { throw ('Updater parse failed: ' + ($parseErrors -join '; ')) }
. $modulePath

function Assert-Updater {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Desktop updater regression: $Message" }
}

function Assert-UpdaterRejected {
    param([scriptblock]$Body, [string]$Pattern)
    try { & $Body | Out-Null }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        return
    }
    throw "Desktop updater expected rejection: $Pattern"
}

function New-UpdaterTestManifest {
    param([string]$Version = '1.2.3', [string]$Hash = ('a' * 64))
    return [pscustomobject]@{
        schema = 1
        algorithm = 'sha256-lf'
        version = $Version
        files = @(
            [pscustomobject]@{path='start_desktop.bat';sha256=$Hash},
            [pscustomobject]@{path='omnisonic/app.py';sha256=('b' * 64)}
        )
    }
}

function New-UpdaterTestRun {
    return [pscustomobject]@{
        id = 1234
        head_sha = ('c' * 40)
        head_branch = 'master'
        event = 'push'
        path = '.github/workflows/quality.yml'
        head_repository = [pscustomobject]@{full_name='Pates2004/omnisonic'}
        status = 'completed'
        conclusion = 'success'
    }
}

$fixture = Join-ProjectMaterialPath $testProject ('Trash\desktop-updater-tests-' + [Guid]::NewGuid().ToString('N'))
Assert-ProjectTestPath $fixture $testProject | Out-Null
[IO.Directory]::CreateDirectory($fixture) | Out-Null
$originalSkipUpdate = [Environment]::GetEnvironmentVariable('OMNISONIC_SKIP_UPDATE', 'Process')
try {
    [Environment]::SetEnvironmentVariable('OMNISONIC_SKIP_UPDATE', $null, 'Process')

    # No external call is made: rejected endpoints fail before HttpClient creation.
    foreach ($uri in @(
        'http://api.github.com/repos/Pates2004/omnisonic',
        'https://api.github.com:444/repos/Pates2004/omnisonic',
        'https://user@api.github.com/repos/Pates2004/omnisonic',
        'https://api.github.com.attacker.invalid/repos/Pates2004/omnisonic',
        'https://example.invalid/redirect',
        'file:///C:/Windows/win.ini'
    )) {
        Assert-UpdaterRejected { Invoke-DesktopUpdateHttp $uri } 'approved HTTPS GitHub endpoint'
    }

    & {
        $head = 'c' * 40
        $old = 'd' * 40
        $requested = New-Object 'Collections.Generic.List[string]'
        $commit = [pscustomobject]@{
            sha=$head
            commit=[pscustomobject]@{
                committer=[pscustomobject]@{date='2026-10-23T18:00:00Z'}
                message="Verified source changes`n`nLong body is not the subject."
            }
        }
        $run = New-UpdaterTestRun
        $remote = New-UpdaterTestManifest '2.3.4'
        function Invoke-DesktopUpdateHttp {
            param([string]$Uri)
            $requested.Add($Uri)
            if ($Uri -eq 'https://api.github.com/repos/Pates2004/omnisonic/commits?sha=master&per_page=1') {
                return ConvertTo-Json -InputObject @($commit) -Depth 10 -Compress
            }
            if ($Uri -eq ('https://api.github.com/repos/Pates2004/omnisonic/actions/workflows/quality.yml/runs?branch=master&event=push&head_sha=' + $head + '&per_page=1')) {
                return ConvertTo-Json -InputObject @{workflow_runs=@($run)} -Depth 10 -Compress
            }
            if ($Uri -eq ('https://raw.githubusercontent.com/Pates2004/omnisonic/' + $head + '/update_manifest.json')) {
                return ConvertTo-Json -InputObject $remote -Depth 10 -Compress
            }
            throw "Unexpected discovery URL: $Uri"
        }
        $candidate = Get-DesktopUpdateCandidate $old
        Assert-Updater ($candidate.Sha -ceq $head -and $candidate.Run -eq 1234) 'Exact master push CI approves only its own SHA'
        Assert-Updater ($candidate.Version -ceq '2.3.4') 'Offered version is the frozen remote manifest version'
        Assert-Updater ($candidate.Subject -ceq 'Verified source changes') 'Candidate subject omits its message body'
        Assert-Updater ($requested.Count -eq 3) 'Candidate reads head, exact workflow run and exact-SHA manifest'
        $requested.Clear()
        Assert-Updater ($null -eq (Get-DesktopUpdateCandidate $head)) 'Already installed SHA needs no offer'
        Assert-Updater ($requested.Count -eq 1) 'Installed SHA skips workflow and manifest requests'

        foreach ($change in @(
            @{field='status';value='queued'},
            @{field='status';value='in_progress'},
            @{field='conclusion';value='failure'},
            @{field='conclusion';value='cancelled'},
            @{field='head_sha';value=$old},
            @{field='head_branch';value='other'},
            @{field='event';value='pull_request'},
            @{field='path';value='.github/workflows/unrelated.yml'},
            @{field='repository';value='other/omnisonic'}
        )) {
            $run = New-UpdaterTestRun
            if ($change.field -eq 'repository') { $run.head_repository.full_name = $change.value }
            else { $run.($change.field) = $change.value }
            $requested.Clear()
            Assert-Updater ($null -eq (Get-DesktopUpdateCandidate $old)) ('Unapproved CI refused: ' + $change.field + '=' + $change.value)
            Assert-Updater ($requested.Count -eq 2) 'Unapproved CI never fetches manifest'
        }
        $run = $null
        Assert-Updater ($null -eq (Get-DesktopUpdateCandidate $old)) 'Absent workflow cannot approve source'
        $run = New-UpdaterTestRun
        $remote.version = 'invalid version!'
        Assert-UpdaterRejected { Get-DesktopUpdateCandidate $old } 'supported source-update manifest'
        $remote = New-UpdaterTestManifest
        $remote.schema = $true
        Assert-UpdaterRejected { Get-DesktopUpdateCandidate $old } 'supported source-update manifest'
        $remote = New-UpdaterTestManifest
        $remote.algorithm = 'SHA256-LF'
        Assert-UpdaterRejected { Get-DesktopUpdateCandidate $old } 'supported source-update manifest'
        $remote = New-UpdaterTestManifest
        $commit.sha = 'invalid'
        Assert-UpdaterRejected { Get-DesktopUpdateCandidate $old } 'invalid master commit'
    }

    & {
        $installed = New-UpdaterTestManifest
        $remote = New-UpdaterTestManifest
        $remote.files = @($remote.files[1], $remote.files[0])
        Assert-Updater (Test-DesktopUpdateSameSource $installed $remote) 'Fresh ZIP identity ignores manifest entry ordering'
        foreach ($field in @('version', 'algorithm', 'schema', 'hash', 'path')) {
            $remote = New-UpdaterTestManifest
            switch ($field) {
                'version' { $remote.version = '1.2.4' }
                'algorithm' { $remote.algorithm = 'different' }
                'schema' { $remote.schema = 2 }
                'hash' { $remote.files[0].sha256 = 'f' * 64 }
                'path' { $remote.files[0].path = 'different.py' }
            }
            Assert-Updater (-not (Test-DesktopUpdateSameSource $installed $remote)) ('Source identity notices changed ' + $field)
        }
    }

    & {
        $target = 'c' * 40
        $installed = 'd' * 40
        $requested = @()
        $commits = @(
            [pscustomobject]@{sha=$target;commit=@{message="First$([char]27) subject`nHidden body"}},
            [pscustomobject]@{sha=('b' * 40);commit=@{message=('L' * 180)}},
            [pscustomobject]@{sha=$installed;commit=@{message='Already installed'}},
            [pscustomobject]@{sha=('a' * 40);commit=@{message='Older changes'}}
        )
        function Invoke-DesktopUpdateHttp {
            param([string]$Uri)
            Assert-Updater ($Uri -ceq ('https://api.github.com/repos/Pates2004/omnisonic/commits?sha=' + $target + '&per_page=10')) 'Notes are pinned to approved source SHA and request at most ten'
            return ConvertTo-Json -InputObject $commits -Depth 10 -Compress
        }
        $notes = Get-DesktopUpdateNotes $target $installed
        $lines = @($notes -split '\r?\n')
        Assert-Updater ($lines.Count -eq 2) 'Notes stop at installed revision'
        Assert-Updater ($notes -notmatch 'Hidden body|Already installed|Older changes|\x1b') 'Notes omit bodies, older subjects and terminal control bytes'
        Assert-Updater ($lines[1].Length -eq 152 -and $lines[1].EndsWith('...')) 'Notes bound each displayed subject length'
        $commits = @(1..12 | ForEach-Object { [pscustomobject]@{sha=('{0:x40}' -f $_);commit=@{message=('Subject ' + $_)}} })
        $notes = Get-DesktopUpdateNotes $target
        Assert-Updater (@($notes -split '\r?\n').Count -eq 10) 'Notes independently bound a malformed oversized API response to ten entries'
        Assert-UpdaterRejected { Get-DesktopUpdateNotes 'bad revision' } 'Invalid target revision'
    }

    # The native consent window is not displayed. Static contract verifies Yes/No
    # with No as default, while orchestration below verifies decline behavior.
    $confirmation = $moduleAst.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Confirm-DesktopUpdate'}, $true)
    Assert-Updater ($confirmation.Body.Extent.Text -match 'MessageBoxButtons\]::YesNo') 'Consent is an explicit Yes/No dialog'
    Assert-Updater ($confirmation.Body.Extent.Text -match 'MessageBoxDefaultButton\]::Button2') 'Consent defaults to No'

    foreach ($scenario in @(
        'approved', 'git-approved', 'git-fetch-error', 'declined', 'offline', 'download-error', 'no-candidate', 'same-source',
        'initial-live-app', 'consent-live-app', 'transfer-live-app', 'pending',
        'repair-error-pending', 'apply-error', 'apply-error-pending', 'restart-error'
    )) {
        & {
            $program = Join-Path $fixture $scenario
            [IO.Directory]::CreateDirectory($program) | Out-Null
            $launcherArgs = @('-Backend', 'CUDA', '-Mode', 'Portable', '-ProbeTimeoutSeconds', '600')
            $mockState = @{network=0;query=0;confirm=0;guard=0;apply=0;restart=0;repair=0;git=0;context=0;installed='';order=(New-Object 'Collections.Generic.List[string]')}
            $installedManifest = New-UpdaterTestManifest '1.0.0'
            $remoteManifest = New-UpdaterTestManifest '2.0.0' ('e' * 64)
            if ($scenario -eq 'same-source') { $remoteManifest = New-UpdaterTestManifest '1.0.0' }
            $pending = Join-Path $program '.launcher\update-recovery\pending.json'
            $statePath = Join-Path $program '.launcher\update-state.json'
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($statePath)) | Out-Null
            [IO.File]::WriteAllText($statePath, ('{"sha":"' + ('d' * 40) + '"}'))
            if ($scenario -in @('pending', 'repair-error-pending')) {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($pending)) | Out-Null
                [IO.File]::WriteAllText($pending, '{"synthetic":true}')
            }
            if ($scenario -in @('git-approved', 'git-fetch-error')) { [IO.Directory]::CreateDirectory((Join-Path $program '.git')) | Out-Null }
            function Assert-OwnedUpdateLock {
                param([bool]$Held = $true)
                $blocked = $false
                $unexpected = $null
                try { $unexpected = [IO.File]::Open((Join-Path $program '.launcher\runtime.lock'), [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
                catch [IO.IOException] { $blocked = ($_.Exception.HResult -band 0xFFFF) -in @(32, 33) }
                finally { if ($unexpected) { $unexpected.Dispose() } }
                Assert-Updater ($blocked -eq $Held) ('Expected fixture runtime lock held=' + $Held + ' in ' + $scenario)
            }
            function Get-DesktopUpdateMessages { return [pscustomobject]@{} }
            function Repair-DesktopInterruptedUpdate {
                param($ProjectRoot, [switch]$LockHeld)
                $mockState.repair++
                Assert-Updater $LockHeld 'Recovery reuses updater-owned lock'
                Assert-OwnedUpdateLock
                if ($scenario -eq 'repair-error-pending') { throw 'Synthetic pending recovery error' }
            }
            function Assert-DesktopUpdateAppClosed {
                param($ProjectRoot)
                Assert-Updater ($ProjectRoot -ceq $program) 'Live-app guard targets only synthetic root'
                Assert-OwnedUpdateLock
                $mockState.guard++
                if (($scenario -eq 'initial-live-app' -and $mockState.guard -eq 1) -or
                    ($scenario -eq 'consent-live-app' -and $mockState.guard -eq 2) -or
                    ($scenario -eq 'transfer-live-app' -and $mockState.guard -eq 3)) { throw 'Synthetic live application blocks source mutation' }
            }
            function Read-DesktopUpdateManifest {
                param($Path)
                Assert-Updater ($Path -ceq (Join-Path $program 'update_manifest.json')) 'Only synthetic installed manifest is read'
                return $installedManifest
            }
            function Get-DesktopUpdateGitContext {
                param($ProjectRoot, $TargetSha = '')
                Assert-OwnedUpdateLock
                $mockState.context++
                if ($mockState.context -eq 1) { Assert-Updater (-not $TargetSha) 'Installed Git identity is checked before remote query' }
                else { Assert-Updater ($TargetSha -ceq ('c' * 40)) 'Fetched Git revision is revalidated against approved SHA' }
                return [pscustomobject]@{Git='synthetic-git.exe';OldSha=('d' * 40)}
            }
            function Invoke-DesktopUpdateGitFetch {
                param($Git, $ProjectRoot, $TargetSha)
                Assert-OwnedUpdateLock
                $mockState.git++
                Assert-Updater ($Git -ceq 'synthetic-git.exe' -and $ProjectRoot -ceq $program -and $TargetSha -ceq ('c' * 40)) 'Git fetch is exact approved origin SHA, never arbitrary branch/reset'
                if ($scenario -eq 'git-fetch-error') { throw 'Synthetic bounded Git fetch failed' }
            }
            function Get-DesktopUpdateCandidate {
                param($InstalledSha)
                Assert-OwnedUpdateLock
                $mockState.query++
                $mockState.installed = $InstalledSha
                $mockState.order.Add('query')
                if ($scenario -eq 'offline') { throw 'Synthetic network is offline' }
                if ($scenario -eq 'no-candidate') { return $null }
                return [pscustomobject]@{Sha=('c' * 40);Version='2.0.0';Date='2026-10-23';Manifest=$remoteManifest}
            }
            function Get-DesktopUpdateNotes {
                param($TargetSha, $InstalledSha)
                Assert-OwnedUpdateLock
                return '- Synthetic approved change'
            }
            function Confirm-DesktopUpdate {
                param($Title, $Body)
                Assert-OwnedUpdateLock
                $mockState.confirm++
                Assert-Updater ($Body -match '2\.0\.0' -and $Body -match '1\.0\.0' -and $Body -match 'Synthetic approved change') 'Consent includes installed/offered version and change notes'
                return $scenario -ne 'declined'
            }
            function Invoke-DesktopUpdateHttp {
                param($Uri, $OutputPath, $MaximumBytes, $TimeoutSeconds)
                Assert-OwnedUpdateLock
                $mockState.network++
                $mockState.order.Add('download')
                Assert-Updater ($Uri -ceq ('https://codeload.github.com/Pates2004/omnisonic/zip/' + ('c' * 40))) 'Archive is pinned to approved exact SHA'
                Assert-Updater ($OutputPath.StartsWith($program + '\.launcher\updates\', [StringComparison]::OrdinalIgnoreCase)) 'Download stays in synthetic private updater staging'
                Assert-Updater ($MaximumBytes -eq 33554432 -and $TimeoutSeconds -eq 90) 'Archive download has explicit bounded size and time'
                if ($scenario -eq 'download-error') { throw 'Synthetic archive download failed' }
            }
            function Expand-DesktopUpdateArchive {
                param($ArchivePath, $Destination)
                Assert-OwnedUpdateLock
                return [pscustomobject]@{Root=$Destination}
            }
            function New-DesktopUpdatePlan {
                param($ProjectRoot, $PreparedRoot)
                Assert-OwnedUpdateLock
                Assert-Updater ($ProjectRoot -ceq $program) 'Planning cannot touch active checkout'
            }
            function Invoke-DesktopSourceUpdate {
                param($ProjectRoot, $PreparedRoot, $Sha, $DownloadSession)
                Assert-OwnedUpdateLock
                Assert-Updater ($ProjectRoot -ceq $program -and $Sha -ceq ('c' * 40)) 'Only approved fixture source can be applied'
                $mockState.apply++
                $mockState.order.Add('apply')
                if ($scenario -in @('apply-error-pending', 'restart-error')) {
                    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($pending)) | Out-Null
                    [IO.File]::WriteAllText($pending, '{"synthetic":true}')
                }
                if ($scenario -in @('apply-error', 'apply-error-pending')) { throw 'Synthetic source activation failed' }
            }
            function Start-DesktopUpdatedLauncher {
                param($ProjectRoot, $LauncherArguments)
                Assert-OwnedUpdateLock $false
                Assert-Updater ($ProjectRoot -ceq $program) 'Fresh restart targets synthetic installation only'
                Assert-Updater (($LauncherArguments -join '|') -ceq ($launcherArgs -join '|')) 'Fresh restart preserves original launcher arguments'
                $mockState.restart++
                $mockState.order.Add('restart')
                if ($scenario -eq 'restart-error') { throw 'Synthetic fresh process creation failed' }
            }
            $output = @(Invoke-DesktopUpdateCheck $program $launcherArgs 3>&1 6>$null)
            $codes = @($output | Where-Object { $_ -is [int] })
            Assert-Updater ($codes.Count -eq 1) ('Exactly one updater disposition returned: ' + $scenario)
            $expected = if ($scenario -in @('approved', 'git-approved')) { 10 } elseif ($scenario -in @('repair-error-pending', 'apply-error-pending', 'restart-error')) { 20 } else { 0 }
            Assert-Updater ($codes[0] -eq $expected) ('Disposition=' + $expected + ' for ' + $scenario + '; actual output: ' + ($output -join ' | '))
            Assert-OwnedUpdateLock $false
            if ($scenario -in @('approved', 'git-approved', 'restart-error')) {
                Assert-Updater ($mockState.apply -eq 1 -and $mockState.restart -eq 1) 'Only applied source attempts fresh restart'
                Assert-Updater (($mockState.order -join ',') -ceq 'query,download,apply,restart') 'Approval order is query, download, apply, fresh restart'
            } else { Assert-Updater ($mockState.restart -eq 0) 'Decline/error/no update cannot restart application' }
            if ($scenario -notin @('approved', 'git-approved', 'apply-error', 'apply-error-pending', 'restart-error')) {
                Assert-Updater ($mockState.apply -eq 0) 'Skipped/error update cannot mutate source'
            }
            if ($scenario -in @('pending', 'repair-error-pending', 'initial-live-app')) {
                Assert-Updater ($mockState.query -eq 0 -and $mockState.network -eq 0) 'Busy/recovery state cannot query/download newer source'
            }
            if ($scenario -in @('declined', 'offline', 'no-candidate', 'same-source', 'consent-live-app')) {
                Assert-Updater ($mockState.network -eq 0) 'No consent or no verified candidate means no source download'
            }
            if ($mockState.query) { Assert-Updater ($mockState.installed -ceq ('d' * 40)) 'ZIP install persisted SHA participates in candidate selection' }
            if ($scenario -in @('apply-error-pending', 'restart-error', 'repair-error-pending')) { Assert-Updater (Test-Path -LiteralPath $pending) 'Failed update/restart retains recovery metadata' }
            if ($scenario -in @('git-approved', 'git-fetch-error')) {
                Assert-Updater ($mockState.git -eq 1) 'Git checkout fetch happens only after consent and archive validation'
                Assert-Updater ($mockState.context -eq $(if ($scenario -eq 'git-approved') { 2 } else { 1 })) 'Only successful fetch reaches post-fetch provenance check'
            }
            if ($scenario -in @('repair-error-pending', 'apply-error-pending')) {
                Assert-Updater (($output -join ' ') -match 'recovery must finish' -and ($output -join ' ') -notmatch 'using the current installation') 'Unfinished recovery never claims the current source is ready'
            }
        }
    }

    & {
        $program = Join-Path $fixture 'maintenance-skip'
        function Get-DesktopUpdateMessages { throw 'Skipped maintenance must not inspect user settings' }
        function Enter-DesktopUpdateLock { throw 'Skipped maintenance must not lock runtime' }
        function Invoke-DesktopUpdateHttp { throw 'Skipped maintenance must not access network' }
        foreach ($flag in @('-SelfTest', '-QueryHiddenLaunch', '-BootstrapOnly', '-InstallOnly')) {
            Assert-Updater ((Invoke-DesktopUpdateCheck $program @('-Backend', 'CUDA', $flag)) -eq 0) ('Maintenance skips update: ' + $flag)
        }
        [Environment]::SetEnvironmentVariable('OMNISONIC_SKIP_UPDATE', '1', 'Process')
        Assert-Updater ((Invoke-DesktopUpdateCheck $program) -eq 0) 'Explicit environment opt-out skips update entirely'
        [Environment]::SetEnvironmentVariable('OMNISONIC_SKIP_UPDATE', $null, 'Process')
    }

    & {
        $program = Join-Path $fixture 'busy-project-lock'
        [IO.Directory]::CreateDirectory($program) | Out-Null
        $held = Enter-DesktopUpdateLock $program
        function Get-DesktopUpdateMessages { return [pscustomobject]@{} }
        function Get-DesktopUpdateCandidate { throw 'Busy fixture must not query network' }
        try {
            $result = @(Invoke-DesktopUpdateCheck $program 3>&1)
            Assert-Updater (@($result | Where-Object { $_ -is [int] })[0] -eq 0) 'Already locked project continues without update'
        } finally { $held.Dispose() }
    }

    # Real, short owned PowerShell child: no Python, GUI, public network or active
    # project. It serializes only these synthetic arguments and exits naturally.
    & {
        $program = Join-Path $fixture 'argv space & percent% Unicode'
        [IO.Directory]::CreateDirectory($program) | Out-Null
        $childSource = @'
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'argv.json'), (ConvertTo-Json -InputObject @($args) -Compress), (New-Object Text.UTF8Encoding($false)))
exit 0
'@
        [IO.File]::WriteAllText((Join-Path $program 'desktop_launcher.ps1'), $childSource)
        $child = @{process=$null;starts=0}
        function Start-Process {
            param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle)
            Assert-Updater ($WorkingDirectory -ceq $program -and $WindowStyle -eq 'Normal') 'Explicit launcher arguments keep interactive installation visible'
            $child.starts++
            $child.process = Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
            return $child.process
        }
        $syntheticArgs = @('-Backend', 'CUDA', '-Mode', 'Portable', 'space value', '100% & literal', 'quoted"value', 'C:\trailing\', 'C:\two\\"quote', ([string][char]0x17c + [char]0xf3 + [char]0x142 + [char]0x107), '$(throw injected); untouched')
        Start-DesktopUpdatedLauncher $program $syntheticArgs
        try {
            Assert-Updater ($child.process.WaitForExit(10000)) 'Owned argument child exits within ten seconds'
            Assert-Updater ($child.process.ExitCode -eq 0) 'Owned argument child exits successfully'
            $actual = @([IO.File]::ReadAllText((Join-Path $program 'argv.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json | ForEach-Object { $_ })
            Assert-Updater ($actual.Count -eq $syntheticArgs.Count) 'Restart preserves argument count'
            for ($index = 0; $index -lt $syntheticArgs.Count; $index++) {
                Assert-Updater ($actual[$index] -ceq $syntheticArgs[$index]) ('Restart preserves exact synthetic argument ' + $index)
            }
        } finally {
            if ($child.process -and -not $child.process.HasExited) { $child.process.Kill(); $child.process.WaitForExit(5000) | Out-Null }
            if ($child.process) { $child.process.Dispose() }
        }
        foreach ($bad in @("bad`nvalue", "bad`rvalue", ('bad' + [char]0 + 'value'))) {
            Assert-UpdaterRejected { ConvertTo-DesktopUpdateArgument $bad } 'unsupported control characters'
        }
        Assert-Updater ((ConvertTo-DesktopUpdateArgument '') -ceq '""') 'Empty argument has explicit quoted representation'
        Assert-UpdaterRejected { Start-DesktopUpdatedLauncher $program @('x' * 31000) } 'command-line limit'
        Assert-Updater ($child.starts -eq 1) 'Rejected huge arguments never create another process'
    }

    foreach ($readiness in @('ready', 'failed', 'lowercase', 'show', 'error', 'explicit')) {
        & {
            $program = Join-Path $fixture ('restart-readiness-' + $readiness)
            [IO.Directory]::CreateDirectory($program) | Out-Null
            $restartState = @{queries=0;starts=0;style='';line=''}
            function Invoke-DesktopUpdateProcess {
                param($FilePath, $WorkingDirectory, $Arguments, $TimeoutSeconds)
                Assert-Updater ($WorkingDirectory -ceq $program) 'Readiness query targets only fresh synthetic launcher'
                Assert-Updater ($TimeoutSeconds -eq 10) 'Readiness child is bounded to ten seconds'
                Assert-Updater ($Arguments[-1] -ceq '-QueryHiddenLaunch') 'Readiness uses fresh launcher explicit query mode'
                $restartState.queries++
                if ($readiness -eq 'error') { throw 'Synthetic bounded readiness failure' }
                $exitCode = if ($readiness -eq 'failed') { 1 } else { 0 }
                $output = switch ($readiness) { 'ready' { "`r`n HIDE `r`n" }; 'lowercase' { 'hide' }; 'show' { 'SHOW' }; default { 'HIDE' } }
                return [pscustomobject]@{ExitCode=$exitCode;Output=$output}
            }
            function Start-Process {
                param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle)
                $restartState.starts++
                $restartState.style = $WindowStyle
                $restartState.line = $ArgumentList
            }
            $suppliedArgs = if ($readiness -eq 'explicit') { @('-Mode', 'Portable') } else { @() }
            Start-DesktopUpdatedLauncher $program $suppliedArgs
            Assert-Updater ($restartState.starts -eq 1) 'Readiness always leads to exactly one fresh launcher, not duplicate startup'
            if ($readiness -eq 'ready') {
                Assert-Updater ($restartState.style -eq 'Hidden' -and $restartState.line -match '"-HiddenLaunch"$') 'Only affirmative ready response hides console and enables hidden-launch handshake'
            } else {
                Assert-Updater ($restartState.style -eq 'Normal' -and $restartState.line -notmatch '-HiddenLaunch') 'Unready/error/explicit restart keeps installer console visible'
            }
            Assert-Updater ($restartState.queries -eq $(if ($readiness -eq 'explicit') { 0 } else { 1 })) 'Explicit arguments bypass automatic hidden-readiness query'
        }
    }

    & {
        $program = Join-Path $fixture 'git-helper-contract'
        $gitState = @{calls=0;exit=0}
        function Invoke-DesktopUpdateProcess {
            param($FilePath, $WorkingDirectory, $Arguments, $TimeoutSeconds, $Environment)
            $gitState.calls++
            Assert-Updater ($FilePath -ceq 'synthetic-git.exe' -and $WorkingDirectory -ceq $program) 'Bounded Git process receives exact verified executable/root'
            Assert-Updater (($Arguments -join '|') -ceq (@('-C', $program, 'fetch', '--no-tags', 'origin', ('c' * 40)) -join '|')) 'Bounded Git process receives only approved origin revision'
            Assert-Updater ($TimeoutSeconds -eq 90) 'Git fetch has a bounded ninety-second lifetime'
            Assert-Updater ($Environment.GIT_TERMINAL_PROMPT -ceq '0' -and $Environment.GCM_INTERACTIVE -ceq 'Never') 'Git authentication cannot wait on hidden terminal/UI prompts'
            return [pscustomobject]@{ExitCode=$gitState.exit;Output='';Error='Synthetic Git error'}
        }
        Invoke-DesktopUpdateGitFetch 'synthetic-git.exe' $program ('c' * 40)
        $gitState.exit = 1
        Assert-UpdaterRejected { Invoke-DesktopUpdateGitFetch 'synthetic-git.exe' $program ('c' * 40) } 'could not fetch.*Synthetic Git error'
        Assert-Updater ($gitState.calls -eq 2) 'Git nonzero status remains a failure, not successful source activation'
    }

    & {
        $program = Join-Path $fixture 'bounded-process-helper'
        [IO.Directory]::CreateDirectory($program) | Out-Null
        $helper = Join-Path $program 'owned-helper.ps1'
        $helperSource = @'
param([string]$Case)
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
if ($Case -eq 'timeout') {
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'owned-pid.txt'), [string]$PID)
    Start-Sleep -Seconds 30
    exit 0
}
if ($Case -eq 'large') {
    [Console]::Write(('o' * 7000))
    [Console]::Error.Write(('e' * 7000))
    Start-Sleep -Seconds 5
    exit 0
}
[Console]::Write(('UTF8-' + [char]0x17c + [char]0xf3 + [char]0x142 + [char]0x107 + ';env=' + $env:OMNISONIC_UPDATER_CHILD_SCOPE))
[Console]::Error.Write(('ERR-' + [char]0x142))
if ($Case -eq 'nonzero') { exit 7 }
exit 0
'@
        [IO.File]::WriteAllText($helper, $helperSource)
        $hostPath = Join-Path $PSHOME 'powershell.exe'
        $helperArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $helper)
        $priorScopeValue = [Environment]::GetEnvironmentVariable('OMNISONIC_UPDATER_CHILD_SCOPE', 'Process')
        try {
            [Environment]::SetEnvironmentVariable('OMNISONIC_UPDATER_CHILD_SCOPE', 'parent-only', 'Process')
            foreach ($case in @('success', 'nonzero')) {
                $probe = Invoke-DesktopUpdateProcess $hostPath $program ($helperArgs + @('-Case', $case)) -TimeoutSeconds 10 -Environment @{OMNISONIC_UPDATER_CHILD_SCOPE='child-only'}
                Assert-Updater ($probe.ExitCode -eq $(if ($case -eq 'success') { 0 } else { 7 })) 'Bounded helper preserves exact process exit code'
                Assert-Updater ($probe.Output -ceq ('UTF8-' + [char]0x17c + [char]0xf3 + [char]0x142 + [char]0x107 + ';env=child-only')) 'Bounded helper captures UTF-8 stdout and child-scoped environment'
                Assert-Updater ($probe.Error -ceq ('ERR-' + [char]0x142)) 'Bounded helper captures independent UTF-8 stderr'
                Assert-Updater ([Environment]::GetEnvironmentVariable('OMNISONIC_UPDATER_CHILD_SCOPE', 'Process') -ceq 'parent-only') 'Child environment override never changes parent policy'
            }
            Assert-UpdaterRejected { Invoke-DesktopUpdateProcess $hostPath $program ($helperArgs + @('-Case', 'large')) -TimeoutSeconds 10 -MaximumCharacters 10000 } 'output limit'
            $timer = [Diagnostics.Stopwatch]::StartNew()
            Assert-UpdaterRejected { Invoke-DesktopUpdateProcess $hostPath $program ($helperArgs + @('-Case', 'timeout')) -TimeoutSeconds 2 } 'time limit'
            Assert-Updater ($timer.Elapsed.TotalSeconds -lt 12) 'Timed-out owned helper is stopped with bounded cleanup'
            $ownedPid = [int][IO.File]::ReadAllText((Join-Path $program 'owned-pid.txt'))
            $terminated = $false
            try { $ownedProcess = [Diagnostics.Process]::GetProcessById($ownedPid); $terminated = $ownedProcess.HasExited; $ownedProcess.Dispose() }
            catch [ArgumentException] { $terminated = $true }
            Assert-Updater $terminated 'Timeout cleanup stops only the recorded owned helper process'
        } finally {
            [Environment]::SetEnvironmentVariable('OMNISONIC_UPDATER_CHILD_SCOPE', $priorScopeValue, 'Process')
        }
    }

    # Intentional test-only controller copy exercises the real -File entrypoint,
    # including $args scoping when a core with param() is dot-sourced. The tiny
    # core replaces only InvokeCheck with capture+return0; no update operation runs.
    & {
        $program = Join-Path $fixture 'controller-entry-args'
        [IO.Directory]::CreateDirectory($program) | Out-Null
        $controller = Join-Path $program 'desktop_updater.ps1'
        [IO.File]::Copy($modulePath, $controller, $false)
        Assert-Updater ([IO.File]::ReadAllText($controller) -ceq [IO.File]::ReadAllText($modulePath)) 'Controller fixture is an exact current source copy'
        $captureCore = @'
param([switch]$Recover, [string]$RecoveryProjectRoot = '')
function Invoke-DesktopUpdateCheck {
    param([string]$ProjectRoot, [string[]]$LauncherArguments = @())
    $record = @{Root=$ProjectRoot;Arguments=@($LauncherArguments)}
    [IO.File]::WriteAllText((Join-Path $ProjectRoot 'controller-argv.json'), (ConvertTo-Json -InputObject $record -Compress), (New-Object Text.UTF8Encoding($false)))
    return 0
}
'@
        [IO.File]::WriteAllText((Join-Path $program 'desktop_update_runtime.ps1'), $captureCore)
        $expectedArgs = @('-Backend', 'XPU', '-Mode', 'System', 'space value', '100% & literal', 'quoted"value', 'C:\ending\', ([string][char]0x142 + [char]0xf3 + [char]0x17c), '$(throw injected)')
        $hostPath = Join-Path $PSHOME 'powershell.exe'
        $nativeArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $controller) + $expectedArgs
        $line = @($nativeArgs | ForEach-Object { ConvertTo-DesktopUpdateArgument $_ }) -join ' '
        $process = Microsoft.PowerShell.Management\Start-Process -FilePath $hostPath -ArgumentList $line -WorkingDirectory $program -WindowStyle Hidden -PassThru
        try {
            Assert-Updater ($process.WaitForExit(10000)) 'Owned controller capture exits within ten seconds'
            Assert-Updater ($process.ExitCode -eq 0) 'Controller execution exits0 without network/UI/update'
            $captured = [IO.File]::ReadAllText((Join-Path $program 'controller-argv.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
            Assert-Updater ($captured.Root -ceq $program) 'Executed controller targets its own synthetic root'
            Assert-Updater (@($captured.Arguments).Count -eq $expectedArgs.Count) 'Dot-sourced core cannot consume original controller argument count'
            for ($index = 0; $index -lt $expectedArgs.Count; $index++) {
                Assert-Updater ($captured.Arguments[$index] -ceq $expectedArgs[$index]) ('Executed controller preserves original argument ' + $index)
            }
        } finally {
            if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit(5000) | Out-Null }
            $process.Dispose()
        }
    }
} finally {
    [Environment]::SetEnvironmentVariable('OMNISONIC_SKIP_UPDATE', $originalSkipUpdate, 'Process')
}

# A successful negative-case native command cannot leak its exit status into the
# hosted PowerShell wrapper. Real assertion failures throw before this point.
$global:LASTEXITCODE = 0
Write-Host 'Desktop updater tests: OK (exact CI/SHA, consent/offline, lock lifecycle, recovery, restart and Windows argv)'
Write-Host ('Synthetic fixtures: ' + $fixture)
