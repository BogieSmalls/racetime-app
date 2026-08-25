Set-StrictMode -Version Latest

function ConvertFrom-IntegrationComposePsJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$InputText
    )

    if ([string]::IsNullOrWhiteSpace($InputText)) {
        throw [FormatException]::new('Compose service status output is empty.')
    }

    $trimmed = $InputText.Trim()
    $records = [Collections.Generic.List[object]]::new()
    if ($trimmed.StartsWith('[', [StringComparison]::Ordinal)) {
        try {
            $parsed = @($trimmed | ConvertFrom-Json -ErrorAction Stop)
        } catch {
            throw [FormatException]::new(
                'Compose service status is not a valid JSON array.',
                $_.Exception
            )
        }
        foreach ($record in $parsed) {
            $records.Add($record)
        }
    } else {
        $reader = [IO.StringReader]::new($InputText)
        $lineNumber = 0
        while ($null -ne ($line = $reader.ReadLine())) {
            $lineNumber++
            if ([string]::IsNullOrWhiteSpace($line)) {
                throw [FormatException]::new(
                    "Compose service status JSONL contains an empty record at line $lineNumber."
                )
            }
            try {
                $record = $line | ConvertFrom-Json -ErrorAction Stop
            } catch {
                throw [FormatException]::new(
                    "Compose service status JSONL is invalid at line $lineNumber.",
                    $_.Exception
                )
            }
            if ($record -is [Array] -or $record -isnot [pscustomobject]) {
                throw [FormatException]::new(
                    "Compose service status JSONL line $lineNumber is not an object."
                )
            }
            $records.Add($record)
        }
    }

    if ($records.Count -eq 0) {
        throw [FormatException]::new('Compose service status contains no records.')
    }
    foreach ($record in $records) {
        if ($record -is [Array] -or $record -isnot [pscustomobject]) {
            throw [FormatException]::new(
                'Compose service status records must all be JSON objects.'
            )
        }
    }

    $records
}

function Test-IntegrationServicesHealthy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [object[]]$Statuses,
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [string[]]$ExpectedServices
    )

    if ($ExpectedServices.Count -eq 0 -or $Statuses.Count -ne $ExpectedServices.Count) {
        return $false
    }

    $expected = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($service in $ExpectedServices) {
        if ([string]::IsNullOrWhiteSpace($service) -or -not $expected.Add($service)) {
            return $false
        }
    }

    $observed = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($status in $Statuses) {
        if ($status -isnot [pscustomobject]) {
            return $false
        }
        $serviceProperty = $status.PSObject.Properties['Service']
        $stateProperty = $status.PSObject.Properties['State']
        $healthProperty = $status.PSObject.Properties['Health']
        if ($null -in @($serviceProperty, $stateProperty, $healthProperty)) {
            return $false
        }

        $service = [string]$serviceProperty.Value
        if (-not $expected.Contains($service) -or -not $observed.Add($service)) {
            return $false
        }
        if (
            [string]$stateProperty.Value -cne 'running' -or
            [string]$healthProperty.Value -cne 'healthy'
        ) {
            return $false
        }
    }

    $observed.Count -eq $expected.Count
}
