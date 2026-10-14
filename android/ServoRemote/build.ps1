# Build Servo Remote without Gradle: javac -> d8 -> aapt2 -> zipalign -> apksigner.
# Needs the Android SDK (platform 31, build-tools 34.0.0) and a JDK.
#   powershell -File build.ps1            build out\ServoRemote.apk
#   powershell -File build.ps1 -Install   ... and install it on the phone over adb
param([switch]$Install)
# tools write progress to stderr: failures are caught by their exit codes instead
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA\Android\Sdk" }
$bt = "$sdk\build-tools\34.0.0"
$jar = "$sdk\platforms\android-31\android.jar"
$out = "$here\out"
# the signing key lives outside the repo; the same key must sign every update
$ks = "$env:USERPROFILE\.android\servoremote.jks"
$versionCode = 4
$versionName = '1.3'

Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$out\classes", "$out\dex" | Out-Null

$src = Get-ChildItem "$here\src" -Recurse -Filter *.java | ForEach-Object FullName
# --release 8 takes java.* from the JDK (android.jar's stubs lack the lambda bootstrap)
& javac -nowarn -Xlint:-options --release 8 -encoding UTF-8 -classpath $jar -d "$out\classes" $src
if ($LASTEXITCODE) { throw 'javac failed' }

$classes = Get-ChildItem "$out\classes" -Recurse -Filter *.class | ForEach-Object FullName
# d8 from the command-line tools: build-tools 34's d8 (R8 8.2) crashes on JDK 21 class files
& "$sdk\cmdline-tools\latest\bin\d8.bat" --release --min-api 31 --lib $jar --output "$out\dex" $classes
if ($LASTEXITCODE) { throw 'd8 failed' }

# the panel's own font, taken from the panel's assets at build time
New-Item -ItemType Directory -Force "$out\assets" | Out-Null
Copy-Item "$here\..\..\assets\Orbitron-Medium.ttf" "$out\assets\"
& "$bt\aapt2.exe" link -o "$out\base.apk" -I $jar --manifest "$here\AndroidManifest.xml" -A "$out\assets" `
    --min-sdk-version 31 --target-sdk-version 31 --version-code $versionCode --version-name $versionName
if ($LASTEXITCODE) { throw 'aapt2 link failed' }

Push-Location "$out\dex"
& jar uf "$out\base.apk" classes.dex
Pop-Location
if ($LASTEXITCODE) { throw 'adding classes.dex failed' }

& "$bt\zipalign.exe" -f -p 4 "$out\base.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'zipalign failed' }

if (-not (Test-Path $ks)) {
    New-Item -ItemType Directory -Force (Split-Path $ks) | Out-Null
    & keytool -genkeypair -keystore $ks -storepass servoremote -keypass servoremote -alias servoremote `
        -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Servo Remote' 2>$null
}
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:servoremote --key-pass pass:servoremote `
    --out "$out\ServoRemote.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'apksigner failed' }
Write-Output "built $out\ServoRemote.apk ($((Get-Item "$out\ServoRemote.apk").Length) bytes)"

if ($Install) {
    & adb install -r "$out\ServoRemote.apk"
    & adb shell pm grant com.servocom.remote android.permission.BLUETOOTH_SCAN
    & adb shell pm grant com.servocom.remote android.permission.BLUETOOTH_CONNECT
    & adb shell am start -n com.servocom.remote/.MainActivity
}
