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
import requests
from yt_dlp import YoutubeDL
import subprocess

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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit
app.config['UPLOAD_FOLDER'] = '/app/uploads'  # 上传文件存储路径
app.config['OUTPUT_FOLDER'] = '/app/outputs'  # 输出文件存储路径

# 确保目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Store uploaded files and their corresponding URLs
UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
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

def download_youtube_subtitles(url):
    """
    从YouTube下载字幕文件，优先下载中文字幕，其次是英文字幕
    返回字幕内容和语言代码
    """
    logger.info(f"开始处理YouTube URL: {url}")
    
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['zh-Hans', 'zh-CN', 'zh-TW', 'en'],
        'quiet': False,  # 启用详细输出
        'verbose': True
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            logger.info("正在获取视频信息...")
            info = ydl.extract_info(url, download=False)
            
            logger.info("检查可用字幕...")
            if 'subtitles' in info:
                logger.info(f"找到手动字幕: {list(info['subtitles'].keys())}")
            if 'automatic_captions' in info:
                logger.info(f"找到自动字幕: {list(info['automatic_captions'].keys())}")
            
            # 检查是否有字幕
            if 'subtitles' in info and info['subtitles']:
                # 优先查找中文字幕
                for lang in ['zh-Hans', 'zh-CN', 'zh-TW']:
                    if lang in info['subtitles']:
                        logger.info(f"找到{lang}手动字幕")
                        return True, info['subtitles'][lang][0]['data'], lang
                
                # 如果没有中文字幕，查找英文字幕
                if 'en' in info['subtitles']:
                    logger.info("找到英文手动字幕")
                    return True, info['subtitles']['en'][0]['data'], 'en'
            
            # 检查自动生成的字幕
            if 'automatic_captions' in info and info['automatic_captions']:
                for lang in ['zh-Hans', 'zh-CN', 'zh-TW']:
                    if lang in info['automatic_captions']:
                        logger.info(f"找到{lang}自动字幕")
                        return True, info['automatic_captions'][lang][0]['data'], lang
                
                if 'en' in info['automatic_captions']:
                    logger.info("找到英文自动字幕")
                    return True, info['automatic_captions']['en'][0]['data'], 'en'
            
            logger.warning("未找到任何可用字幕")
            return False, None, None
            
    except Exception as e:
        logger.error(f"下载YouTube字幕时出错: {str(e)}", exc_info=True)
        return False, None, None

def download_video(url):
    """
    下载视频并提取音频
    """
    logger.info(f"下载视频: {url}")
    
    if not os.path.exists('videos'):
        os.makedirs('videos')
    
    audio_path = os.path.join('videos', f'video_audio_{uuid.uuid4().hex}.mp3')
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': audio_path,
        'keepvideo': False,
        'postprocessor_args': [
            '-ar', '16000'
        ],
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            logger.info("开始下载...")
            ydl.download([url])
        
        if not os.path.exists(audio_path):
            possible_name = audio_path + '.mp3'
            if os.path.exists(possible_name):
                os.rename(possible_name, audio_path)
                logger.info(f"重命名 {possible_name} 为 {audio_path}")
        
        logger.info(f"音频文件大小: {os.path.getsize(audio_path)} bytes")
        return os.path.abspath(audio_path)
        
    except Exception as e:
        logger.error(f"下载视频时出错: {str(e)}", exc_info=True)
        raise

def transcribe_audio(audio_path):
    """
    使用FunASR转录音频
    """
    logger.info(f"开始转录音频: {audio_path}")
    
    try:
        # 准备音频文件
        with open(audio_path, 'rb') as f:
            audio_data = f.read()
        
        # 调用FunASR服务
        response = requests.post(
            'http://funasronline:10095/v1/asr',
            files={
                'audio': ('audio.mp3', audio_data, 'audio/mpeg')
            },
            data={
                'audio_format': 'mp3',
                'sample_rate': 16000,
                'mode': 'online',
                'use_punc': 'true',  # 明确启用标点符号
                'use_itn': 'true'    # 启用数字转换
            }
        )
        
        if response.status_code != 200:
            logger.error(f"FunASR服务返回错误: {response.status_code} - {response.text}")
            return None
            
        result = response.json()
        logger.info(f"转录完成，结果: {result}")
        
        # 解析结果
        if 'result' in result:
            text = result['result']
            if not isinstance(text, str):
                logger.error(f"非预期的结果格式: {type(text)}")
                return None
                
            # 预处理文本：去除多余的空格，但保留标点
            text = ' '.join(text.split())  # 先标准化空格
            # 移除字符之间的空格，但保留标点
            processed_text = ''
            for i, char in enumerate(text):
                if char != ' ':
                    processed_text += char
            
            logger.info(f"处理后的文本: {processed_text}")
            
            sentences = []
            current_time = 0
            
            try:
                # 使用更多的中文标点符号进行分割
                import re
                # 包含句号、问号、感叹号、分号、冒号等标点
                pattern = r'([。！？；：\n])'
                parts = re.split(pattern, processed_text)
                # 过滤空字符串并组合句子
                processed_parts = []
                temp_sentence = ""
                
                for part in parts:
                    if part:  # 不使用 strip()，保留原始空白
                        if re.match(pattern, part):
                            # 如果是标点符号，添加到临时句子并保存
                            temp_sentence += part
                            if temp_sentence:  # 不使用 strip()
                                processed_parts.append(temp_sentence)
                                temp_sentence = ""
                        else:
                            # 如果不是标点符号，添加到临时句子
                            temp_sentence += part
                
                # 处理最后一个可能没有标点的句子
                if temp_sentence:  # 不使用 strip()
                    processed_parts.append(temp_sentence)
                
                logger.info(f"分割后的句子数量: {len(processed_parts)}")
                logger.info(f"分割后的句子示例: {processed_parts[:3]}")  # 显示前三个句子作为示例
                
                # 根据句子长度估算时间
                total_chars = sum(len(s) for s in processed_parts)
                avg_time_per_char = 0.3  # 假设每个字符平均0.3秒
                
                for part in processed_parts:
                    if part:  # 不使用 strip()
                        # 根据句子长度按比例分配时间
                        duration = len(part) * avg_time_per_char
                        
                        sentences.append({
                            'start': current_time,
                            'duration': duration,
                            'text': part
                        })
                        
                        current_time += duration
                
                logger.info(f"生成的字幕数量: {len(sentences)}")
                return sentences
            except Exception as e:
                logger.error(f"处理文本时出错: {str(e)}", exc_info=True)
                return None
            
        logger.error(f"结果中没有 'result' 字段: {result}")
        return None
        
    except Exception as e:
        logger.error(f"转录音频时出错: {str(e)}", exc_info=True)
        return None
    finally:
        # 清理临时文件
        try:
            os.remove(audio_path)
            logger.info(f"已删除临时文件: {audio_path}")
        except Exception as e:
            logger.warning(f"删除临时文件失败: {str(e)}")

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
            'show_timeline': False,  # 设置为False，不显示时间轴
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

@app.route('/process_youtube', methods=['POST'])
def process_youtube():
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({"error": "未提供URL"}), 400
            
        logger.info(f"收到YouTube处理请求: {url}")
            
        # 1. 尝试下载字幕
        has_subs, subs_content, lang = download_youtube_subtitles(url)
        
        if not has_subs:
            logger.info("未找到字幕，尝试下载视频并转录")
            try:
                # 下载视频
                audio_path = download_video(url)
                logger.info(f"视频已下载到: {audio_path}")
                
                # 转录音频
                segments = transcribe_audio(audio_path)
                if not segments:
                    return jsonify({"error": "音频转录失败"}), 500
                
                # 转换为SRT格式
                subs_content = ""
                for i, segment in enumerate(segments, 1):
                    start_time = segment['start']
                    end_time = start_time + segment['duration']
                    
                    start_str = format_time(start_time)
                    end_str = format_time(end_time)
                    
                    subs_content += f"{i}\n"
                    subs_content += f"{start_str} --> {end_str}\n"
                    subs_content += f"{segment['text']}\n\n"
                
                lang = 'zh'
                
            except Exception as e:
                logger.error(f"处理视频时出错: {str(e)}", exc_info=True)
                return jsonify({"error": "视频处理失败"}), 500
        
        # 3. 处理字幕内容并保存
        file_id = str(uuid.uuid4())
        filename = f"youtube_{file_id}.srt"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(subs_content)
        
        logger.info(f"字幕已保存到: {file_path}")
        
        # 4. 更新files_info.json
        files_info = load_files_info()
        files_info.append({
            'id': file_id,
            'filename': filename,
            'url': f'/view/{file_id}',
            'upload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'show_timeline': False,  # 设置为False，不显示时间轴
            'subtitles': parse_srt(subs_content)[0]
        })
        save_files_info(files_info)
        
        # 5. 保存到Readwise
        if create_readwise_document(
            f"YouTube字幕 - {url}",
            subs_content,
            f"https://youtu.be/{url.split('v=')[1]}"
        ):
            logger.info("成功保存到Readwise")
        else:
            logger.warning("保存到Readwise失败")
        
        # 返回查看URL
        view_url = f"/view/{file_id}"
        return jsonify({
            "success": True,
            "url": view_url,
            "language": lang
        })
        
    except Exception as e:
        logger.error(f"处理YouTube URL时出错: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def create_readwise_document(title, content, url):
    """
    将字幕内容保存到Readwise Reader
    """
    api_token = os.getenv('READWISE_API_TOKEN')
    if not api_token:
        logger.error("未设置Readwise API Token")
        return False
        
    try:
        headers = {
            'Authorization': f'Token {api_token}',
            'Content-Type': 'application/json'
        }
        
        # 处理字幕内容，移除时间信息，只保留文本
        lines = content.split('\n')
        text_only = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line and not line.isdigit() and '-->' not in line:
                text_only.append(line)
            i += 1
        
        processed_content = '\n'.join(text_only)
        
        data = {
            'title': title,
            'text': processed_content,
            'url': url,
            'source_type': 'youtube',  # 使用有效的source_type
            'content_type': 'text',    # 使用有效的content_type
            'should_clean_html': False
        }
        
        response = requests.post(
            'https://readwise.io/api/v3/save/',
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code in [200, 201, 202]:
            logger.info("成功保存到Readwise")
            return True
        else:
            logger.error(f"保存到Readwise失败: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"保存到Readwise时出错: {str(e)}")
        return False

def format_time(seconds):
    """
    将秒数转换为SRT时间格式 (HH:MM:SS,mmm)
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    milliseconds = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

if __name__ == '__main__':
    logger.info("启动Flask服务器")
    app.run(host='0.0.0.0', port=5000)
