# 添加Windows Forms支持
Add-Type -AssemblyName System.Windows.Forms

# 设置输出编码为UTF8，以正确显示中文
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== SRT字幕转网页查看器 开始执行 ===" -ForegroundColor Green
Write-Host "时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Green
Write-Host ""

# 获取剪贴板内容
$clipboardText = [System.Windows.Forms.Clipboard]::GetText([System.Windows.Forms.TextDataFormat]::Text)
Write-Host "剪贴板内容类型: Text" -ForegroundColor Yellow

# 尝试获取剪贴板中的文件
$clipboardFiles = [System.Windows.Forms.Clipboard]::GetFileDropList()
Write-Host "剪贴板文件数量: $($clipboardFiles.Count)" -ForegroundColor Yellow

# 尝试获取选中的文件路径
$filePath = $env:QUICKER_SELECTED_FILES
Write-Host "QUICKER_SELECTED_FILES: $filePath" -ForegroundColor Yellow

# 收集所有要处理的文件
$filesToProcess = @()

# 处理逻辑：优先使用剪贴板中的文件
if ($clipboardFiles.Count -gt 0) {
    foreach ($file in $clipboardFiles) {
        if ($file.ToLower().EndsWith('.srt')) {
            $filesToProcess += @{
                Path = $file
                Name = [System.IO.Path]::GetFileName($file)
                Content = Get-Content -Path $file -Raw -Encoding UTF8
                Type = "file"
            }
            Write-Host "添加剪贴板中的.srt文件: $file" -ForegroundColor Green
        }
    }
}
# 如果剪贴板中没有.srt文件，检查文本内容是否包含多个文件路径
elseif ($clipboardText) {
    $paths = $clipboardText -split "`n" | ForEach-Object { $_.Trim() }
    foreach ($path in $paths) {
        if ($path -and $path.ToLower().EndsWith('.srt') -and (Test-Path -LiteralPath $path)) {
            $filesToProcess += @{
                Path = $path
                Name = [System.IO.Path]::GetFileName($path)
                Content = Get-Content -Path $path -Raw -Encoding UTF8
                Type = "file"
            }
            Write-Host "添加文本中的.srt文件路径: $path" -ForegroundColor Green
        }
    }
    
    # 如果没有找到有效的文件路径，检查是否为srt内容
    if ($filesToProcess.Count -eq 0 -and $clipboardText -match '^\d+\r?\n\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}') {
        $filesToProcess += @{
            Path = $null
            Name = "clipboard.srt"
            Content = $clipboardText
            Type = "content"
        }
        Write-Host "使用剪贴板中的srt内容" -ForegroundColor Green
    }
}

if ($filesToProcess.Count -eq 0) {
    Write-Host "错误: 未找到有效的srt文件或内容" -ForegroundColor Red
    [System.Windows.Forms.MessageBox]::Show("请复制.srt文件或内容到剪贴板")
    Read-Host "按回车键退出"
    exit
}

Write-Host "`n开始处理文件..." -ForegroundColor Cyan
$processedUrls = @()

# 获取Quicker环境变量中的时间轴显示设置
$showTimeline = $env:QUICKER_PARAM_SHOW_TIMELINE -eq "true"
Write-Host "时间轴显示设置: $showTimeline" -ForegroundColor Yellow

foreach ($file in $filesToProcess) {
    Write-Host "`n处理文件: $($file.Name)" -ForegroundColor Cyan
    
    try {
        # 准备发送文件
        $serverUrl = 'http://localhost:5000/upload'
        Write-Host "服务器地址: $serverUrl" -ForegroundColor Yellow
        
        # 将内容转换为字节
        $contentBytes = [System.Text.Encoding]::UTF8.GetBytes($file.Content)
        
        # 构建multipart form数据
        $boundary = [System.Guid]::NewGuid().ToString()
        
        # 构建请求体
        $bodyLines = @()
        $bodyLines += "--$boundary"
        $bodyLines += "Content-Disposition: form-data; name=`"file`"; filename=`"$($file.Name)`""
        $bodyLines += "Content-Type: application/octet-stream"
        $bodyLines += ""
        
        # 将header转换为字节
        $headerBytes = [System.Text.Encoding]::UTF8.GetBytes(($bodyLines -join "`r`n") + "`r`n")
        
        # 构建footer字节
        $footerBytes = [System.Text.Encoding]::UTF8.GetBytes("`r`n--$boundary--`r`n")
        
        # 合并所有字节
        $bodyBytes = New-Object byte[] ($headerBytes.Length + $contentBytes.Length + $footerBytes.Length)
        [System.Buffer]::BlockCopy($headerBytes, 0, $bodyBytes, 0, $headerBytes.Length)
        [System.Buffer]::BlockCopy($contentBytes, 0, $bodyBytes, $headerBytes.Length, $contentBytes.Length)
        [System.Buffer]::BlockCopy($footerBytes, 0, $bodyBytes, $headerBytes.Length + $contentBytes.Length, $footerBytes.Length)
        
        $contentType = "multipart/form-data; boundary=$boundary"
        
        Write-Host "发送HTTP请求..." -ForegroundColor Yellow
        
        # 使用WebRequest来发送原始字节
        $webRequest = [System.Net.WebRequest]::Create($serverUrl)
        $webRequest.Method = "POST"
        $webRequest.ContentType = $contentType
        
        # 添加show_timeline参数到请求头
        $webRequest.Headers.Add("X-Show-Timeline", $showTimeline.ToString().ToLower())
        
        Write-Host "写入请求体..." -ForegroundColor Yellow
        $requestStream = $webRequest.GetRequestStream()
        $requestStream.Write($bodyBytes, 0, $bodyBytes.Length)
        $requestStream.Close()
        
        Write-Host "获取响应..." -ForegroundColor Yellow
        $response = $webRequest.GetResponse()
        $responseStream = $response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($responseStream)
        $responseContent = $reader.ReadToEnd()
        
        Write-Host "服务器响应成功!" -ForegroundColor Green
        
        # 解析JSON响应
        $responseJson = $responseContent | ConvertFrom-Json
        
        # 保存URL
        if ($responseJson.url) {
            $processedUrls += $responseJson.url
            Write-Host "成功处理文件: $($file.Name)" -ForegroundColor Green
        }
    }
    catch {
        Write-Host "处理文件 $($file.Name) 时发生错误: $_" -ForegroundColor Red
        Write-Host "错误详情: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# 处理完成后，按顺序打开所有URL
if ($processedUrls.Count -gt 0) {
    Write-Host "`n所有文件处理完成，正在打开网页..." -ForegroundColor Green
    foreach ($url in $processedUrls) {
        Start-Process "http://localhost:5000$url"
        Start-Sleep -Milliseconds 500  # 添加小延迟，避免浏览器同时打开太多标签
    }
    
    # 最后打开文件列表页面
    Start-Process "http://localhost:5000/view/"
    
    [System.Windows.Forms.MessageBox]::Show("成功处理 $($processedUrls.Count) 个文件")
}

Write-Host "`n=== 处理完成 ===" -ForegroundColor Green
Write-Host "窗口保持打开，您可以检查以上信息。" -ForegroundColor Yellow
Read-Host "按回车键关闭窗口..."
