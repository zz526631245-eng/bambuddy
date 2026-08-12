[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,

    [Parameter(Mandatory = $true)]
    [string]$DataRoot,

    [switch]$StopOnly,

    [switch]$Interactive
)

# Bambuddy's Windows installer uses this script to make automatic slicing work
# on a clean machine.  Docker Desktop and the two HTTP slicer sidecars remain
# third-party components; the installer only installs the official Docker
# Desktop package and pulls the compose images when it has Internet
# access.  Failures are recorded and never abort the main Bambuddy install.

$ErrorActionPreference = "Stop"
$script:DockerExe = $null
$script:ComposeMode = $null
$SlicerDir = Join-Path $DataRoot "slicer"
$ComposePath = Join-Path $SlicerDir "docker-compose.yml"
$ComposeSource = Join-Path $InstallDir "slicer-api\docker-compose.yml"
$StatusPath = Join-Path $SlicerDir "setup-status.txt"
$RunOncePath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"
$RunOnceName = "BambuddySlicerSetup"

function Write-Status {
    param(
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$Detail
    )

    try {
        New-Item -ItemType Directory -Force -Path $SlicerDir | Out-Null
        @(
            "state=$State"
            "updated_utc=$([DateTime]::UtcNow.ToString('o'))"
            "detail=$Detail"
        ) | Set-Content -LiteralPath $StatusPath -Encoding UTF8
    }
    catch {
        Write-Output "[slicer] unable to write status file: $($_.Exception.Message)"
    }
    Write-Output "[slicer] $State - $Detail"
}

function Register-ResumeAfterRestart {
    $command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' +
        $PSCommandPath + '" -InstallDir "' + $InstallDir +
        '" -DataRoot "' + $DataRoot + '"'
    try {
        New-Item -Path $RunOncePath -Force | Out-Null
        New-ItemProperty -Path $RunOncePath -Name $RunOnceName -PropertyType String -Value $command -Force | Out-Null
        Write-Output "[slicer] Docker requested a restart; setup will resume at next login."
    }
    catch {
        Write-Output "[slicer] could not register restart continuation: $($_.Exception.Message)"
    }
}

function Clear-ResumeAfterSuccess {
    try {
        Remove-ItemProperty -Path $RunOncePath -Name $RunOnceName -ErrorAction SilentlyContinue
    }
    catch {
        # The RunOnce value is only a convenience; setup is already complete.
    }
}

function Resolve-Docker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $script:DockerExe @Arguments
    return $LASTEXITCODE
}

function Resolve-Compose {
    if ($script:DockerExe) {
        $code = Invoke-Docker -Arguments @("compose", "version")
        if ($code -eq 0) {
            $script:ComposeMode = "docker"
            return
        }
    }

    $legacy = Get-Command docker-compose -ErrorAction SilentlyContinue
    if ($legacy) {
        $script:ComposeMode = "legacy"
        return
    }
    throw "Docker Compose is not available."
}

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    if ($script:ComposeMode -eq "docker") {
        return Invoke-Docker -Arguments (@("compose") + $Arguments)
    }
    & docker-compose @Arguments
    return $LASTEXITCODE
}

function Install-DockerDesktop {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Status "installing-docker" "Installing Docker Desktop through winget."
        & $winget.Source install --id Docker.DockerDesktop --exact --silent --disable-interactivity --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Write-Output ("[slicer] winget install returned {0}; trying the official installer." -f $LASTEXITCODE)
    }

    $installer = Join-Path $env:TEMP "Docker Desktop Installer.exe"
    Write-Status "downloading-docker" "Downloading the official Docker Desktop installer."
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 900 -Uri "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" -OutFile $installer
    Write-Status "installing-docker" "Installing Docker Desktop silently."
    $process = Start-Process -FilePath $installer -ArgumentList @("install", "--quiet", "--accept-license") -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
        throw "Docker Desktop installer returned exit code $($process.ExitCode)."
    }
}

function Start-DockerDesktop {
    $desktopCandidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )
    foreach ($desktop in $desktopCandidates) {
        if ($desktop -and (Test-Path -LiteralPath $desktop)) {
            Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
            return
        }
    }
}

function Wait-DockerDaemon {
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $code = Invoke-Docker -Arguments @("info", "--format", "{{.ServerVersion}}") 2>$null
            if ($code -eq 0) {
                return $true
            }
        }
        catch {
            # Docker Desktop is often still booting its WSL2 backend.
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-SidecarHealth {
    param([Parameter(Mandatory = $true)][int]$Port)
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:$Port/health"
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        }
        catch {
            # The image may still be downloading or starting.
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

try {
    New-Item -ItemType Directory -Force -Path $SlicerDir | Out-Null

    if ($StopOnly) {
        $script:DockerExe = Resolve-Docker
        if ($script:DockerExe) {
            Resolve-Compose
            Push-Location $SlicerDir
            try {
                [void](Invoke-Compose -Arguments @("down"))
            }
            finally {
                Pop-Location
            }
        }
        Write-Status "stopped" "Slicer sidecars stopped; Docker images and data were kept."
        exit 0
    }

    if (-not (Test-Path -LiteralPath $ComposeSource)) {
        throw "Bundled slicer compose file not found: $ComposeSource"
    }
    Copy-Item -LiteralPath $ComposeSource -Destination $ComposePath -Force

    $script:DockerExe = Resolve-Docker
    if (-not $script:DockerExe) {
        Install-DockerDesktop
        $script:DockerExe = Resolve-Docker
    }
    if (-not $script:DockerExe) {
        Register-ResumeAfterRestart
        Write-Status "restart-required" "Docker Desktop needs a Windows restart; setup will resume after login."
        exit 0
    }

    Start-DockerDesktop
    if (-not (Wait-DockerDaemon)) {
        Register-ResumeAfterRestart
        Write-Status "restart-required" "Docker Desktop is not ready; restart Windows or finish WSL2 setup, then setup will resume."
        exit 0
    }

    Resolve-Compose
    Push-Location $SlicerDir
    try {
        Write-Status "pulling-slicer" "Starting automatic slicing services (the first run downloads the images)."
        $composeCode = Invoke-Compose -Arguments @("--profile", "bambu", "up", "-d")
    }
    finally {
        Pop-Location
    }
    if ($composeCode -ne 0) {
        throw "docker compose up failed with exit code $composeCode."
    }

    $orcaReady = Wait-SidecarHealth -Port 3003
    $bambuReady = Wait-SidecarHealth -Port 3001
    if (-not ($orcaReady -and $bambuReady)) {
        throw ("Slicer sidecar health check timed out (Orca={0}, Bambu={1})." -f $orcaReady, $bambuReady)
    }

    Clear-ResumeAfterSuccess
    Write-Status "ready" "Automatic slicing is ready: OrcaSlicer=http://127.0.0.1:3003, BambuStudio=http://127.0.0.1:3001."
    exit 0
}
catch {
    Write-Status "needs-attention" $_.Exception.Message
    Write-Output "[slicer] setup did not complete; Bambuddy itself will still be installed."
    if ($Interactive) {
        exit 1
    }
    exit 0
}
