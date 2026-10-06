param([ValidateSet('esp32','esp32s3')][string]$Target='esp32')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$env:ARDUINO_DIRECTORIES_DATA=Join-Path $projectRoot 'tools\arduino-data'
$env:ARDUINO_DIRECTORIES_DOWNLOADS=Join-Path $projectRoot 'tools\arduino-downloads'
$env:ARDUINO_DIRECTORIES_USER=Join-Path $projectRoot 'tools\arduino-user'
$cli=Join-Path $projectRoot 'tools\arduino-cli\arduino-cli.exe'
if (-not (Test-Path -LiteralPath $cli)) { throw 'Install the official Arduino CLI and ESP32 core first; see README.md.' }
$build=Join-Path $projectRoot "tools\build-$Target"
$log=Join-Path $projectRoot "reports\firmware-$Target.txt"
# Compile only. This script contains no serial port or upload action.
& $cli compile --fqbn "esp32:esp32:$Target" --jobs 2 --build-path $build (Join-Path $projectRoot 'firmware\halo_esp32') *> $log
$buildExit=$LASTEXITCODE
Get-Content -LiteralPath $log
if ($buildExit -ne 0) { throw "Firmware compilation failed (exit $buildExit)." }
