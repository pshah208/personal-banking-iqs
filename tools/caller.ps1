# Shared helper: claims of the signed-in az CLI identity, read from its ARM
# access token. Gives the caller's object ID (oid) and type (idtyp: user/app)
# without any Microsoft Graph permission - CI service principals often have none.
function Get-CallerClaims {
    $token = az account get-access-token --resource https://management.azure.com/ --query accessToken -o tsv
    if (-not $token) { throw 'Not logged in. Run: az login' }
    $payload = $token.Split('.')[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) { 2 { $payload += '==' } 3 { $payload += '=' } }
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
}
