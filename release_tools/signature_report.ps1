param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$signature = Get-AuthenticodeSignature -LiteralPath $Path
$cert = $signature.SignerCertificate
$report = [ordered]@{
    status = [string]$signature.Status
    signature_type = [string]$signature.SignatureType
    subject = if ($cert) { $cert.Subject } else { $null }
    thumbprint = if ($cert) { $cert.Thumbprint } else { $null }
    algorithm = if ($cert) { $cert.PublicKey.Oid.Value } else { $null }
    timestamp = ($null -ne $signature.TimeStamperCertificate)
}
$report | ConvertTo-Json -Compress
