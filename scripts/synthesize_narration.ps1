param([Parameter(Mandatory=$true)][string]$SceneFile, [Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
$scenes = Get-Content -LiteralPath $SceneFile -Raw -Encoding UTF8 | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$voice = New-Object -ComObject SAPI.SpVoice
$chinese = $voice.GetVoices() | Where-Object { $_.GetDescription() -like '*Huihui*' } | Select-Object -First 1
if (-not $chinese) { throw 'A Chinese desktop voice is required.' }
$voice.Voice = $chinese
$voice.Rate = 0
for ($sceneIndex = 0; $sceneIndex -lt $scenes.Count; $sceneIndex++) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Open((Join-Path $OutDir ('voice-{0:D2}.wav' -f $sceneIndex)), 3, $false)
    $voice.AudioOutputStream = $stream
    [void]$voice.Speak($scenes[$sceneIndex].voice)
    $stream.Close()
}
