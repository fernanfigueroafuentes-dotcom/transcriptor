<#
.SYNOPSIS
  Sube al servidor la app del visor y las canciones (solo lo que el visor necesita).

.DESCRIPTION
  - App:       Dockerfile, docker-compose.yml, requirements-web.txt, .env.example y web/
  - Canciones: songs/ SIN la carpeta stems/ (pistas separadas, pesadas y no usadas por el visor)
  Usa ssh/scp del sistema. Este script NO contiene ni guarda credenciales: ssh te pedirá la
  contraseña en tu terminal, o usará tu clave SSH si ya la configuraste.

.EXAMPLE
  .\deploy\push.ps1 -Server root@203.0.113.10 -DryRun        # solo muestra qué subiría
  .\deploy\push.ps1 -Server root@203.0.113.10                # sube app y canciones
  .\deploy\push.ps1 -Server root@203.0.113.10 -SkipApp       # solo canciones nuevas
#>
param(
    [Parameter(Mandatory)][string]$Server,
    [string]$Dest = "/opt/transcriptor",
    [switch]$SkipApp,
    [switch]$SkipSongs,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Tmp = Join-Path ([IO.Path]::GetTempPath()) ("transcriptor-push-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Tmp | Out-Null

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe terminó con código $LASTEXITCODE" }
}

function Send-Tar {
    param([string]$Name, [string]$TarFile, [string]$RemoteDir)
    $size = "{0:n1} MB" -f ((Get-Item $TarFile).Length / 1MB)
    Write-Host "`n== $Name ($size)"
    Invoke-Native "tar" @("-tf", $TarFile) | Select-Object -First 40
    if ($DryRun) { return }
    $remoteTar = "/tmp/transcriptor-$Name.tar"
    Invoke-Native "scp" @($TarFile, "${Server}:${remoteTar}")
    # a+rX: el contenedor corre como usuario sin privilegios y solo necesita leer
    $cmd = "mkdir -p '$RemoteDir' && tar -xf '$remoteTar' -C '$RemoteDir' && chmod -R a+rX '$RemoteDir' && rm -f '$remoteTar'"
    Invoke-Native "ssh" @($Server, $cmd)
    Write-Host "Subido a ${Server}:${RemoteDir}"
}

try {
    if (-not $SkipApp) {
        $appTar = Join-Path $Tmp "app.tar"
        Invoke-Native "tar" @("-C", $Root, "--exclude=__pycache__", "-cf", $appTar,
            "Dockerfile", "docker-compose.yml", "requirements-web.txt", ".dockerignore", ".env.example", "web")
        Send-Tar -Name "app" -TarFile $appTar -RemoteDir "$Dest/app"
    }
    if (-not $SkipSongs) {
        $songsDir = Join-Path $Root "songs"
        if (-not (Test-Path $songsDir)) { throw "No existe $songsDir" }
        $songsTar = Join-Path $Tmp "songs.tar"
        Invoke-Native "tar" @("-C", $songsDir, "--exclude=stems", "-cf", $songsTar, ".")
        Send-Tar -Name "songs" -TarFile $songsTar -RemoteDir "$Dest/songs"
    }
    if ($DryRun) { Write-Host "`n(DryRun: no se subió nada)" }
}
finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}
