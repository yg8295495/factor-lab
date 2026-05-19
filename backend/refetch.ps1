# 数据补采验证脚本 — PowerShell
# 运行: powershell -ExecutionPolicy Bypass -File factor-lab/backend/refetch.ps1

$assets = @(
    # 宽基
    @("index.000001.SH","1.000001"),@("index.000300.SH","1.000300"),
    @("index.000905.SH","1.000905"),@("index.000852.SH","1.000852"),
    @("index.932000.SH","1.932000"),@("index.000688.SH","1.000688"),
    @("index.399006.SZ","0.399006"),@("index.000016.SH","1.000016"),
    @("index.000985.SH","1.000985"),@("index.000510.SH","1.000510"),
    # 申万
    @("sector.801010.SW","0.801010"),@("sector.801030.SW","0.801030"),
    @("sector.801040.SW","0.801040"),@("sector.801050.SW","0.801050"),
    @("sector.801080.SW","0.801080"),@("sector.801110.SW","0.801110"),
    @("sector.801120.SW","0.801120"),@("sector.801130.SW","0.801130"),
    @("sector.801140.SW","0.801140"),@("sector.801150.SW","0.801150"),
    @("sector.801160.SW","0.801160"),@("sector.801170.SW","0.801170"),
    @("sector.801180.SW","0.801180"),@("sector.801200.SW","0.801200"),
    @("sector.801210.SW","0.801210"),@("sector.801710.SW","0.801710"),
    @("sector.801720.SW","0.801720"),@("sector.801730.SW","0.801730"),
    @("sector.801740.SW","0.801740"),@("sector.801750.SW","0.801750"),
    @("sector.801760.SW","0.801760"),@("sector.801770.SW","0.801770"),
    @("sector.801780.SW","0.801780"),@("sector.801790.SW","0.801790"),
    @("sector.801880.SW","0.801880"),@("sector.801890.SW","0.801890"),
    @("sector.801950.SW","0.801950"),@("sector.801960.SW","0.801960"),
    @("sector.801970.SW","0.801970"),@("sector.801980.SW","0.801980"),
    # 中证主题
    @("index.399997.SZ","0.399997"),@("index.399967.SZ","0.399967"),
    @("index.399986.SZ","0.399986"),@("index.H30590.SH","1.H30590"),
    @("index.000941.SH","1.000941"),@("index.399989.SZ","0.399989"),
    @("index.931152.SZ","0.931152"),@("index.399975.SZ","0.399975"),
    @("index.990001.SH","1.990001"),@("index.930713.SH","1.930713"),
    @("index.930651.SH","1.930651"),@("index.399976.SZ","0.399976"),
    @("index.931719.SZ","0.931719"),@("index.931151.SZ","0.931151"),
    @("index.000819.SH","1.000819")
)

$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
$total = $assets.Length
$ok = 0; $fail = 0; $rows = 0

Write-Host "=== 数据补采验证 ===" -ForegroundColor Cyan
Write-Host "总数: $total" -ForegroundColor Cyan

for ($i = 0; $i -lt $total; $i++) {
    $sym = $assets[$i][0]
    $secid = $assets[$i][1]
    # 用单引号防止 & 被解析
    $url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=$secid" +
           "&fields1=f1,f2,f3,f4,f5,f6" +
           "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61" +
           "&klt=101&fqt=1&end=20500101&lmt=5000"
    
    Write-Host "[$($i+1)/$total] $sym " -NoNewline
    
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30 `
            -Headers @{"User-Agent" = $ua}
        
        $json = $r.Content | ConvertFrom-Json
        $klines = $json.data.klines
        
        if ($klines -and $klines.Count -gt 0) {
            $first = $klines[0].Split(",")[0]
            $last = $klines[-1].Split(",")[0]
            Write-Host "OK $($klines.Count)行 $first ~ $last" -ForegroundColor Green
            $ok++; $rows += $klines.Count
        } else {
            Write-Host "EMPTY" -ForegroundColor Yellow
            $fail++
        }
    } catch {
        Write-Host "FAIL: $($_.Exception.Message.Substring(0, [Math]::Min(60, $_.Exception.Message.Length)))" -ForegroundColor Red
        $fail++
    }
    
    if ($i -lt $total - 1) { Start-Sleep -Milliseconds 1500 }
}

Write-Host "`n=== 完成 ===" -ForegroundColor Cyan
Write-Host "成功: $ok / $total" -ForegroundColor $(if ($ok -eq $total) {"Green"} else {"Yellow"})
Write-Host "失败: $fail"
Write-Host "总行数: $rows"
