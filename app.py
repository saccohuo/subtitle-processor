from flask import Flask, request, render_template_string, jsonify
import os
from datetime import datetime
import uuid
import codecs
import logging
import sys
import binascii
import chardet
import json

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Store uploaded files and their corresponding URLs
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 存储文件信息的JSON文件
FILES_INFO = 'uploads/files_info.json'
if not os.path.exists(FILES_INFO):
    with open(FILES_INFO, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False)

def load_files_info():
    try:
        with open(FILES_INFO, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_files_info(files_info):
    with open(FILES_INFO, 'w', encoding='utf-8') as f:
        json.dump(files_info, f, ensure_ascii=False, indent=2)

# HTML template for subtitle display
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <title>{{ filename }}</title>
    <style>
        @font-face {
            font-family: "CustomFont";
            src: local("Microsoft YaHei"), local("微软雅黑"), local("SimHei"), local("SimSun");
        }
        body {
            font-family: "CustomFont", sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f4f4f4;
            line-height: 1.6;
        }
        #subtitles {
            padding: 10px;
            background-color: white;
            border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .subtitle {
            display: inline;
        }
        .time {
            display: none;
        }
        .text {
            font-size: 1.1em;
            display: inline;
        }
        .text::after {
            content: " ";
        }
        .show-time .subtitle {
            display: block;
            margin-bottom: 15px;
        }
        .show-time .time {
            display: block;
            color: #666;
            font-size: 0.9em;
            margin: 10px 0;
        }
        .show-time .text {
            display: block;
        }
        .show-time .text::after {
            content: "";
        }
    </style>
</head>
<body>
    {% if show_timeline %}
    <div id="subtitles" class="show-time">
    {% else %}
    <div id="subtitles">
    {% endif %}
        {% for sub in subtitles %}
        <div class="subtitle">
            {% if show_timeline %}
            <div class="time">{{ sub.time }}</div>
            {% endif %}
            <div class="text">{{ sub.text }}</div>
        </div>
        {% endfor %}
    </div>
</body>
</html>
'''

# HTML template for file list
FILES_LIST_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>已上传的字幕文件</title>
    <style>
        @font-face {
            font-family: "CustomFont";
            src: local("Microsoft YaHei"), local("微软雅黑"), local("SimHei"), local("SimSun");
        }
        body {
            font-family: "CustomFont", sans-serif;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f4f4f4;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        h1 {
            color: #2c3e50;
            font-size: 2em;
            margin-bottom: 10px;
        }
        .subtitle {
            color: #7f8c8d;
            font-size: 1em;
        }
        .file-list {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 20px;
            margin-top: 20px;
        }
        .file-item {
            padding: 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            align-items: center;
            transition: background-color 0.2s;
        }
        .file-item:hover {
            background-color: #f8f9fa;
        }
        .file-item:last-child {
            border-bottom: none;
        }
        .file-info {
            flex-grow: 1;
        }
        .file-name {
            font-size: 1.2em;
            color: #2c3e50;
            text-decoration: none;
            margin-bottom: 8px;
            display: block;
            font-weight: bold;
        }
        .file-name:hover {
            color: #3498db;
        }
        .file-meta {
            display: flex;
            gap: 20px;
            color: #7f8c8d;
            font-size: 0.9em;
            margin-top: 5px;
        }
        .meta-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .meta-item i {
            font-size: 1.1em;
        }
        .empty-message {
            text-align: center;
            padding: 40px;
            color: #7f8c8d;
            font-size: 1.1em;
        }
        .refresh-button {
            display: inline-block;
            padding: 8px 20px;
            background-color: #3498db;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            transition: background-color 0.2s;
            margin-top: 10px;
        }
        .refresh-button:hover {
            background-color: #2980b9;
        }
        @media (max-width: 768px) {
            .file-meta {
                flex-direction: column;
                gap: 5px;
            }
            .file-item {
                flex-direction: column;
                align-items: flex-start;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>已上传的字幕文件</h1>
        <div class="subtitle">点击文件名查看字幕内容</div>
        <a href="/view/" class="refresh-button">刷新列表</a>
    </div>
    <div class="file-list">
        {% if files %}
            {% for file in files %}
            <div class="file-item">
                <div class="file-info">
                    <a href="{{ file.url }}" class="file-name" target="_blank">{{ file.filename }}</a>
                    <div class="file-meta">
                        <div class="meta-item">
                            <i>📅</i>上传时间：{{ file.upload_time }}
                        </div>
                        <div class="meta-item">
                            <i>⚙️</i>时间轴：{{ "显示" if file.show_timeline else "隐藏" }}
                        </div>
                        <div class="meta-item">
                            <i>📝</i>字幕条数：{{ file.subtitles|length }}
                        </div>
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty-message">
                暂无上传的字幕文件
            </div>
        {% endif %}
    </div>
</body>
</html>
'''

def detect_file_encoding(raw_bytes):
    """使用多种方法检测文件编码"""
    logger.debug("开始检测文件编码")
    
    # 首先使用chardet检测
    chardet_result = chardet.detect(raw_bytes)
    logger.debug(f"chardet检测结果: {chardet_result}")
    
    # 检查BOM
    encoding_info = {'chardet': chardet_result}
    if raw_bytes.startswith(codecs.BOM_UTF8):
        encoding_info['bom'] = 'UTF-8 with BOM'
        encoding_info['encoding'] = 'utf-8-sig'
    elif raw_bytes.startswith(codecs.BOM_UTF16_LE):
        encoding_info['bom'] = 'UTF-16 LE with BOM'
        encoding_info['encoding'] = 'utf-16-le'
    elif raw_bytes.startswith(codecs.BOM_UTF16_BE):
        encoding_info['bom'] = 'UTF-16 BE with BOM'
        encoding_info['encoding'] = 'utf-16-be'
    else:
        encoding_info['bom'] = 'No BOM detected'
        # 如果chardet的置信度较高，使用chardet的结果
        if chardet_result['confidence'] > 0.8:
            encoding_info['encoding'] = chardet_result['encoding']
        else:
            # 否则尝试常见的中文编码
            encodings_to_try = ['gb18030', 'gbk', 'gb2312', 'utf-8']
            for enc in encodings_to_try:
                try:
                    raw_bytes.decode(enc)
                    encoding_info['encoding'] = enc
                    break
                except UnicodeDecodeError:
                    continue
    
    if 'encoding' not in encoding_info:
        encoding_info['encoding'] = 'utf-8'  # 默认使用UTF-8
        
    logger.debug(f"最终编码检测结果: {encoding_info}")
    return encoding_info

def parse_srt(content):
    logger.debug("开始解析SRT内容")
    logger.debug(f"内容前100个字符的十六进制: {binascii.hexlify(content[:100].encode('utf-8'))}")
    
    subtitles = []
    current = {}
    subtitle_details = []
    
    # 将内容按行分割，处理不同的换行符
    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    logger.debug(f"总行数: {len(lines)}")
    logger.debug(f"前5行内容: {lines[:5]}")
    logger.debug(f"前5行十六进制: {[binascii.hexlify(line.encode('utf-8')) for line in lines[:5]]}")
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        logger.debug(f"处理第{i}行: {line}")
        
        # Skip empty lines
        if not line:
            i += 1
            continue
            
        # Parse subtitle number
        if line.isdigit():
            if current:
                subtitles.append(current)
                logger.debug(f"添加字幕: {current}")
            current = {'number': int(line), 'time': '', 'text': ''}
            i += 1
            continue
            
        # Parse timestamp
        if '-->' in line:
            current['time'] = line
            i += 1
            # Collect all text lines until empty line or end
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            current['text'] = ' '.join(text_lines)
            
            # 记录字幕详细信息
            subtitle_details.append({
                'number': current['number'],
                'time': current['time'],
                'text': current['text'],
                'text_hex': binascii.hexlify(current['text'].encode('utf-8')).decode('ascii')
            })
            
            logger.debug(f"解析字幕文本: {current['text']}")
            logger.debug(f"字幕文本十六进制: {binascii.hexlify(current['text'].encode('utf-8'))}")
            continue
            
        i += 1
    
    if current:
        subtitles.append(current)
        logger.debug(f"添加最后一条字幕: {current}")
    
    logger.debug(f"解析完成，共{len(subtitles)}条字幕")
    return subtitles, subtitle_details

@app.route('/upload', methods=['POST'])
def upload_file():
    logger.info("收到上传请求")
    
    # 从请求头获取时间轴显示设置
    show_timeline = request.headers.get('X-Show-Timeline', 'false').lower() == 'true'
    logger.info(f"显示时间轴: {show_timeline}")
    
    if 'file' not in request.files:
        logger.error("请求中没有文件")
        return jsonify({'error': 'No file provided'}), 400
        
    file = request.files['file']
    filename = file.filename
    logger.info(f"文件名: {filename}")
    
    # 读取原始字节并记录
    raw_bytes = file.stream.read()
    
    # 检测编码
    encoding_info = detect_file_encoding(raw_bytes)
    logger.info(f"文件编码信息: {encoding_info}")
    
    try:
        # 尝试解码内容
        content = raw_bytes.decode(encoding_info['encoding'])
        logger.debug(f"成功解码文件内容，前100个字符: {content[:100]}")
        
        # 解析字幕
        subtitles, subtitle_details = parse_srt(content)
        
        # 生成唯一的文件名
        unique_id = str(uuid.uuid4())
        url_path = f'/view/{unique_id}'
        
        # 保存文件信息
        files_info = load_files_info()
        files_info.append({
            'id': unique_id,
            'filename': filename,
            'url': url_path,
            'upload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'show_timeline': show_timeline,
            'subtitles': subtitles
        })
        save_files_info(files_info)
        
        return jsonify({
            'url': url_path,
            'message': 'File processed successfully'
        })
        
    except Exception as e:
        logger.error(f"处理文件时发生错误: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/view/<file_id>')
def view_file(file_id):
    files_info = load_files_info()
    for file_info in files_info:
        if file_info['id'] == file_id:
            return render_template_string(
                HTML_TEMPLATE,
                filename=file_info['filename'],
                subtitles=file_info['subtitles'],
                show_timeline=file_info['show_timeline']
            )
    return "File not found", 404

@app.route('/view/')
def view_files():
    files_info = load_files_info()
    files_info.sort(key=lambda x: x['upload_time'], reverse=True)  # 按上传时间降序排序
    return render_template_string(FILES_LIST_TEMPLATE, files=files_info)

if __name__ == '__main__':
    logger.info("启动Flask服务器")
    app.run(host='0.0.0.0', port=5000)
