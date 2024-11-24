#!/bin/bash

# 设置环境变量
export MODELSCOPE_CACHE=/workspace/models
export HF_ENDPOINT=https://hf-mirror.com
export PYTHONPATH=/workspace/FunASR:${PYTHONPATH}

# 启动FunASR服务
cd /workspace

echo -e "\n=========================================================="
echo "🚀 Starting FunASR service..."
echo "🔧 Configuration:"
echo "  📍 Python version: $(python3 --version)"
echo "  📍 Current directory: $(pwd)"
echo "  📍 PYTHONPATH: ${PYTHONPATH}"
echo "  📍 MODELSCOPE_CACHE: ${MODELSCOPE_CACHE}"
echo "=========================================================="

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
    )
    logger.info("Model initialized successfully")
    print("\n" + "="*60)
    print("🎉 FunASR Service Initialization Complete! 🎉")
    print("-"*60)
    print("🚀 Service Status: READY")
    print("🌟 Listening Port: 10095")
    print("🔗 Health Check URL: http://localhost:10095/health")
    print("📝 API Endpoint: http://localhost:10095/funasr/v1/transcribe")
    print("="*60 + "\n")

except Exception as e:
    logger.error(f"Error initializing model: {str(e)}")
    sys.exit(1)

class TranscribeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path != "/funasr/v1/transcribe":
                self.send_response(404)
                self.end_headers()
                return

            # 获取Content-Type和boundary
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid Content-Type")
                return

            # 解析multipart/form-data
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers["Content-Type"],
                }
            )

            # 获取音频文件
            if "audio" not in form:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing audio file")
                return

            # 保存音频文件到临时文件
            audio_field = form["audio"]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                temp_file.write(audio_field.file.read())
                temp_path = temp_file.name

            try:
                # 转录音频
                logger.info(f"Processing audio file: {temp_path}")
                result = model.generate(input=temp_path)
                logger.info("Audio processing completed")
                logger.debug(f"Raw result: {result}")

                # 将结果转换为字符串
                if isinstance(result, list):
                    text = " ".join(str(item) for item in result)
                else:
                    text = str(result)

                # 构造响应
                response = {
                    "text": text,
                    "status": "success"
                }

                # 发送响应
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_path)
                except:
                    pass

        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            error_response = {
                "status": "error",
                "message": str(e)
            }
            self.wfile.write(json.dumps(error_response).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            health_response = {
                "status": "healthy",
                "message": "FunASR service is running"
            }
            self.wfile.write(json.dumps(health_response).encode())
        else:
            self.send_response(404)
            self.end_headers()

server = HTTPServer(("0.0.0.0", 10095), TranscribeHandler)
logger.info("Server started at http://0.0.0.0:10095")
server.serve_forever()
'
