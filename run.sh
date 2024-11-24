#!/bin/bash

# 设置环境变量
export MODELSCOPE_CACHE=/workspace/models
export HF_ENDPOINT=https://hf-mirror.com
export PYTHONPATH=/workspace/FunASR:${PYTHONPATH}

# 启动FunASR服务
cd /workspace

echo "Starting FunASR service..."
echo "Python version: $(python3 --version)"
echo "Current directory: $(pwd)"
echo "PYTHONPATH: ${PYTHONPATH}"
echo "MODELSCOPE_CACHE: ${MODELSCOPE_CACHE}"

python3 -c '
import os
import sys
from funasr import AutoModel
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import tempfile
import cgi
import io
import logging

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

logger.info("Starting model initialization...")

try:
    # 配置模型参数
    model = AutoModel(
        model="paraformer-zh",
        model_hub="huggingface",
        vad_model="fsmn-vad",
        vad_hub="huggingface",
        vad_kwargs={"max_single_segment_time": 60000},
        punc_model="ct-punc",
        punc_hub="huggingface",
        model_cache_dir=os.getenv("MODELSCOPE_CACHE"),
        device="cpu",
        online_mode=True,
        use_vad=True,
        use_punc=True,
        use_itn=True,
        disable_progress_bar=True,
        disable_update=True
    )
    logger.info("Model loaded successfully")
except Exception as e:
    logger.error(f"Error loading model: {str(e)}", exc_info=True)
    sys.exit(1)

class ASRHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(format%args)
        
    def do_POST(self):
        if self.path == "/v1/asr":
            try:
                logger.info("Received ASR request")
                # 解析 multipart/form-data
                content_type = self.headers.get("Content-Type", "")
                if "multipart/form-data" in content_type:
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={
                            "REQUEST_METHOD": "POST",
                            "CONTENT_TYPE": self.headers["Content-Type"],
                        }
                    )
                    
                    # 获取音频文件
                    audio_field = form["audio"]
                    audio_data = audio_field.file.read()
                    logger.info(f"Received audio data: {len(audio_data)} bytes")
                    
                    # 保存到临时文件
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp:
                        temp.write(audio_data)
                        temp_path = temp.name
                    
                    try:
                        # 使用模型进行推理
                        logger.info(f"Starting inference on file: {temp_path}")
                        result = model.inference(temp_path)
                        logger.info(f"Inference result: {result}")
                        
                        # 确保结果是字符串
                        if isinstance(result, list):
                            # 如果是列表，取第一个元素的文本
                            text = result[0]["text"] if result else ""
                        elif isinstance(result, dict):
                            # 如果是字典，取text字段
                            text = result.get("text", "")
                        else:
                            # 如果是其他类型，转换为字符串
                            text = str(result)
                        
                        logger.info(f"Processed text: {text}")
                        
                        # 返回结果
                        self.send_response(200)
                        self.send_header("Content-type", "application/json")
                        self.end_headers()
                        response = {"result": text}
                        self.wfile.write(json.dumps(response).encode())
                    finally:
                        # 清理临时文件
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                else:
                    logger.error(f"Invalid content type: {content_type}")
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    error_response = {"error": "Invalid content type"}
                    self.wfile.write(json.dumps(error_response).encode())
            except Exception as e:
                logger.error(f"Error processing request: {str(e)}", exc_info=True)
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                error_response = {"error": str(e)}
                self.wfile.write(json.dumps(error_response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"FunASR service is running")

logger.info("Starting HTTP server on port 10095...")
server = HTTPServer(("0.0.0.0", 10095), ASRHandler)
logger.info("Server started, waiting for requests...")
server.serve_forever()
'
