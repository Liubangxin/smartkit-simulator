function Use-7zaWrapper {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ElectronDir
    )

    $sevenZipDir = Join-Path $ElectronDir "node_modules\7zip-bin\win\x64"
    $orig = Join-Path $sevenZipDir "7za_orig.exe"
    $wrapper = Join-Path $sevenZipDir "7za.exe"
    $wrapperSrc = Join-Path $ElectronDir "7za_wrapper.cs"

    if (Test-Path -LiteralPath $orig) {
        Write-Host "[*] 7za wrapper already in place" -ForegroundColor Yellow
        return
    }

    Write-Host "[*] Setting up 7za wrapper..." -ForegroundColor Yellow

    $wrapperExe = Join-Path $sevenZipDir "7za_wrapper.exe"
    if (-not (Test-Path -LiteralPath $wrapperExe) -or
        (Get-Item -LiteralPath $wrapperSrc).LastWriteTime -gt (Get-Item -LiteralPath $wrapperExe).LastWriteTime) {
        $csc = "C:\WINDOWS\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
        if (-not (Test-Path -LiteralPath $csc)) {
            throw "C# compiler not found at $csc. Install .NET Framework 4.x SDK."
        }
        Write-Host "  Compiling wrapper..." -ForegroundColor Gray
        & $csc /target:exe /out:$wrapperExe /reference:System.dll $wrapperSrc
        if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
    }

    Rename-Item -LiteralPath $wrapper -NewName "7za_orig.exe"
    Copy-Item -LiteralPath $wrapperExe -Destination $wrapper
    Write-Host "[+] 7za wrapper installed" -ForegroundColor Green
}

function Restore-7zaOriginal {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ElectronDir,

        [ValidateRange(1, 100)]
        [int]$RetryCount = 20,

        [ValidateRange(0, 5000)]
        [int]$RetryDelayMilliseconds = 100
    )

    $sevenZipDir = Join-Path $ElectronDir "node_modules\7zip-bin\win\x64"
    $orig = Join-Path $sevenZipDir "7za_orig.exe"
    $wrapper = Join-Path $sevenZipDir "7za.exe"

    if (Test-Path -LiteralPath $orig) {
        if (Test-Path -LiteralPath $wrapper) {
            for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
                try {
                    Remove-Item -LiteralPath $wrapper -Force -ErrorAction Stop
                    break
                } catch {
                    if ($attempt -eq $RetryCount) {
                        throw "Unable to restore the original 7za.exe after $RetryCount attempts. " +
                            "Close processes using '$wrapper' and retry the build. $($_.Exception.Message)"
                    }
                    Start-Sleep -Milliseconds $RetryDelayMilliseconds
                }
            }
        }

        Move-Item -LiteralPath $orig -Destination $wrapper
        Write-Host "[*] 7za original restored" -ForegroundColor Yellow
    }
}
