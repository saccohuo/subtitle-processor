from flask import Flask, request, jsonify
import os
import logging
import sys
import soundfile as sf
import numpy as np
from funasr import AutoModel
import torch
import json
from pydub import AudioSegment
import tempfile
from modelscope import snapshot_download
from pathlib import Path
import shutil
from datetime import datetime

# FunASR 模型列表
FUNASR_MODELS = [
    "SenseVoiceSmall", "paraformer-zh", "paraformer-zh-streaming", "paraformer-en",
    "conformer-en", "ct-punc", "fsmn-vad", "fsmn-kws", "fa-zh", "cam++",
    "Qwen-Audio", "Qwen-Audio-Chat", "emotion2vec+large"
]

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# 创建logger
logger = logging.getLogger("transcribe-audio")
logger.setLevel(logging.WARNING)  # 将日志级别从INFO改为WARNING

# 确保其他库的日志级别不会太详细
logging.getLogger("modelscope").setLevel(logging.ERROR)
logging.getLogger("funasr").setLevel(logging.ERROR)
logging.getLogger("jieba").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("filelock").setLevel(logging.WARNING)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max-limit
app.config['UPLOAD_FOLDER'] = '/app/uploads'


# 全局模型变量
model = None

# 设置请求超时时间（5分钟）
app.config['TIMEOUT'] = 300

def ensure_dir(dir_path):
    """确保目录存在，如果不存在则创建"""
    Path(dir_path).mkdir(parents=True, exist_ok=True)

def download_model(model_id, revision, cache_dir):
    """下载指定的模型"""
    try:
        logger.info(f"开始下载模型 {model_id} 到 {cache_dir}")
        
        # 下载模型
        model_dir = snapshot_download(
            model_id=model_id,
            revision=revision,
            cache_dir=cache_dir
        )
        logger.info(f"模型下载完成: {model_dir}")
        
        # 确保目录有写权限
        for root, dirs, files in os.walk(cache_dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        
        return model_dir
    except Exception as e:
        logger.error(f"下载模型 {model_id} 时出错: {str(e)}")
        raise

def get_model_id(model_type, model_name):
    """获取完整的模型ID"""
    model_mappings = {
        "main": {
            "paraformer-zh": "damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "paraformer-zh-streaming": "damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "paraformer-en": "damo/speech_paraformer-large_asr_nat-en-16k-common-vocab10020",
            "conformer-en": "damo/speech_conformer_asr_nat-en-16k-common-vocab10020",
            "SenseVoiceSmall": "damo/speech_SenseVoiceSmall_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            "fa-zh": "damo/speech_FastConformer_asr_nat-zh-cn-16k-common-vocab8404",
            "Qwen-Audio": "damo/speech_qwen_audio_asr_nat-zh-cn-16k-common-vocab8404",
            "Qwen-Audio-Chat": "damo/speech_qwen_audio_chat_asr_nat-zh-cn-16k-common-vocab8404",
            "emotion2vec+large": "damo/speech_emotion2vec_large_sv_zh-cn_16k-common"
        },
        "vad": {
            "fsmn-vad": "damo/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            "fsmn-kws": "damo/speech_fsmn_kws_zh-cn-16k-common-pytorch"
        },
        "punc": {
            "ct-punc": "damo/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
        },
        "spk": {
            "cam++": "damo/speech_campplus_sv_zh-cn_16k-common"
        }
    }
    
    # 检查是否是完整的模型ID（包含damo/前缀）
    if model_name.startswith("damo/"):
        return model_name
    
    # 检查是否在映射表中
    try:
        return model_mappings[model_type][model_name]
    except KeyError:
        # 如果找不到映射，尝试构建标准格式的模型ID
        if model_type == "main":
            # 主模型ID格式：damo/speech_[model_name]_asr_nat-[lang]-16k-common-[vocab]
            if "zh" in model_name.lower():
                return f"damo/speech_{model_name}_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
            elif "en" in model_name.lower():
                return f"damo/speech_{model_name}_asr_nat-en-16k-common-vocab10020"
            else:
                return f"damo/speech_{model_name}_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        elif model_type == "vad":
            # VAD模型ID格式：damo/speech_[model_name]_zh-cn-16k-common-pytorch
            return f"damo/speech_{model_name}_zh-cn-16k-common-pytorch"
        elif model_type == "punc":
            # 标点模型ID格式：damo/punc_[model_name]_zh-cn-common-vocab272727-pytorch
            return f"damo/punc_{model_name}_zh-cn-common-vocab272727-pytorch"
        elif model_type == "spk":
            # 说话人分离模型ID格式：damo/speech_[model_name]_sv_zh-cn_16k-common
            return f"damo/speech_{model_name}_sv_zh-cn_16k-common"
        else:
            # 如果无法确定格式，直接添加damo/前缀
            logger.warning(f"未知的模型类型: {model_type}，将直接添加damo/前缀")
            return f"damo/{model_name}"

def ensure_models():
    """确保模型文件存在，如果不存在则下载"""
    # 设置模型目录
    model_dir = os.getenv("MODEL_DIR", "/app/models")
    
    # 设置环境变量
    os.environ['MODELSCOPE_CACHE'] = model_dir
    os.environ['HF_HOME'] = model_dir
    os.environ['TORCH_HOME'] = model_dir
    
    # 获取所有模型名称
    model_name = os.getenv("FUNASR_MODEL", "paraformer-zh")
    vad_model = os.getenv("FUNASR_VAD_MODEL", "fsmn-vad")
    punc_model = os.getenv("FUNASR_PUNC_MODEL", "ct-punc")
    spk_model = os.getenv("FUNASR_SPK_MODEL", "cam++")
    
    # 获取完整的模型ID
    model_configs = {
        "main": {"name": model_name, "id": get_model_id("main", model_name)},
        "vad": {"name": vad_model, "id": get_model_id("vad", vad_model)},
        "punc": {"name": punc_model, "id": get_model_id("punc", punc_model)},
        "spk": {"name": spk_model, "id": get_model_id("spk", spk_model)}
    }
    
    logger.info("检查模型配置：")
    for model_type, config in model_configs.items():
        logger.info(f"{model_type}模型: {config['name']} (ID: {config['id']})")
    
    # 检查所有模型文件是否存在
    model_paths = {
        model_type: os.path.join(model_dir, f"hub/{config['id']}")
        for model_type, config in model_configs.items()
    }
    
    logger.info("检查模型文件：")
    for model_type, path in model_paths.items():
        logger.info(f"{model_type}模型路径: {path}")
    
    # 检查是否需要下载模型
    missing_models = [path for path in model_paths.values() if not os.path.exists(path)]
    if missing_models:
        logger.info("部分模型文件不存在，开始下载...")
        ensure_dir(model_dir)
        
        # 下载所有缺失的模型
        success = True
        for model_type, config in model_configs.items():
            model_path = model_paths[model_type]
            if model_path in missing_models:
                try:
                    downloaded_path = download_model(
                        model_id=config["id"],
                        revision=None,  # 使用最新版本
                        cache_dir=model_dir
                    )
                    logger.info(f"模型 {config['id']} 下载成功: {downloaded_path}")
                except Exception as e:
                    logger.error(f"下载模型 {config['id']} 失败: {str(e)}")
                    success = False
                    continue
        
        if not success:
            logger.error("部分模型下载失败，请检查错误信息并重试")
            sys.exit(1)
        else:
            logger.info(f"所有模型下载成功，模型目录: {model_dir}")
    else:
        logger.info("所有模型文件已存在，无需下载")
    
    return model_dir, {k: v["name"] for k, v in model_configs.items()}

# 初始化FunASR模型
def init_model():
    global model  # 声明使用全局变量
    print("="*50)
    print("开始初始化FunASR模型...")
    print("正在检测GPU状态...")
    
    try:
        # 检测GPU是否可用
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print("\n" + "="*20 + " GPU检测信息 " + "="*20)
        print(f"CUDA是否可用: {torch.cuda.is_available()}")
        print(f"PyTorch版本: {torch.__version__}")
        
        if device == "cuda":
            gpu_count = torch.cuda.device_count()
            print(f"可用GPU数量: {gpu_count}")
            for i in range(gpu_count):
                print(f"GPU {i}: {torch.cuda.get_device_name(i)}")
                print(f"GPU {i} 总内存: {torch.cuda.get_device_properties(i).total_memory / 1024**3:.1f} GB")
                print(f"GPU {i} CUDA版本: {torch.version.cuda}")
                if hasattr(torch.backends.cudnn, 'version'):
                    print(f"GPU {i} cuDNN版本: {torch.backends.cudnn.version()}")
        else:
            print("警告: 未检测到可用的GPU，将使用CPU进行推理")
        
        print("\n" + "="*20 + " 模型加载开始 " + "="*20)
        
        # 确保模型存在
        model_dir, model_names = ensure_models()
        
        try:
            # 尝试使用指定的模型
            model = AutoModel(
                model=model_names["main"],
                device=device,  # 使用检测到的设备
                model_dir=model_dir,
                vad_model=model_names["vad"],
                vad_kwargs={"max_single_segment_time": 60000},
                punc_model=model_names["punc"],
                spk_model=model_names["spk"],
                batch_size=1 if device == "cpu" else 4,  # GPU时使用更大的batch_size
                vad_model_dir=model_dir,
                disable_update=True,
                use_local=True,
                punc_model_dir=model_dir,
                spk_model_dir=model_dir
            )
            print(f"FunASR模型加载完成，使用设备: {device}")
            print(f"主模型: {model_names['main']}")
            print(f"VAD模型: {model_names['vad']}")
            print(f"标点模型: {model_names['punc']}")
            print(f"说话人模型: {model_names['spk']}")
            print(f"批处理大小: {1 if device == 'cpu' else 4}")
            
        except Exception as e:
            print(f"警告: 加载指定模型失败: {str(e)}")
            print("尝试使用默认模型配置")
            
            # 使用默认模型
            model = AutoModel(
                model="paraformer-zh",
                device=device,  # 使用检测到的设备
                model_dir=model_dir,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 60000},
                punc_model="ct-punc",
                spk_model="cam++",
                batch_size=1 if device == "cpu" else 4,  # GPU时使用更大的batch_size
                vad_model_dir=model_dir,
                disable_update=True,
                use_local=True,
                punc_model_dir=model_dir,
                spk_model_dir=model_dir
            )
            print(f"FunASR模型加载完成，使用设备: {device}")
            print(f"主模型: paraformer-zh")
            print(f"VAD模型: fsmn-vad")
            print(f"标点模型: ct-punc")
            print(f"说话人模型: cam++")
            print(f"批处理大小: {1 if device == 'cpu' else 4}")
        
        # 验证模型加载
        print("验证模型加载状态...")
        test_audio = np.zeros(16000, dtype=np.float32)  # 1秒的静音用于测试
        test_result = model.generate(input=test_audio, sample_rate=16000)
        print(f"模型验证结果: {test_result}")
        print("FunASR模型加载完成")
        
        return model
        
    except Exception as e:
        print(f"错误: 加载FunASR模型失败: {str(e)}")
        import traceback
        print(traceback.format_exc())  # 打印完整的错误堆栈
        sys.exit(1)

# 初始化模型
model = init_model()

@app.route('/health')
def health_check():
    """健康检查接口"""
    device_info = {
        "status": "healthy",
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu_available": torch.cuda.is_available(),
        "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "gpu_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())] if torch.cuda.is_available() else [],
        "timestamp": datetime.now().isoformat()
    }
    return jsonify(device_info)

@app.route('/device')
def device_info():
    """设备信息接口"""
    device_info = {
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu_available": torch.cuda.is_available(),
        "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "gpu_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())] if torch.cuda.is_available() else [],
        "timestamp": datetime.now().isoformat()
    }
    return jsonify(device_info)

def convert_audio_to_wav(input_path, target_sample_rate=16000):
    """将音频转换为WAV格式并重采样"""
    try:
        # 使用pydub加载音频
        logger.info(f"开始转换音频文件: {input_path}")
        audio = AudioSegment.from_file(input_path)
        
        logger.info(f"原始音频信息: 通道数={audio.channels}, 采样率={audio.frame_rate}Hz, 时长={len(audio)/1000.0}秒")
        
        # 转换为单声道
        if audio.channels > 1:
            audio = audio.set_channels(1)
            logger.info("已转换为单声道")
        
        # 设置采样率
        if audio.frame_rate != target_sample_rate:
            audio = audio.set_frame_rate(target_sample_rate)
            logger.info(f"已调整采样率至 {target_sample_rate}Hz")
        
        # 调整音量
        if audio.dBFS < -30:  # 如果音量太小
            gain_needed = min(-30 - audio.dBFS, 30)  # 最多增益30dB
            audio = audio.apply_gain(gain_needed)
            logger.info(f"音量过小，已增加 {gain_needed}dB")
        
        # 创建临时文件
        temp_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_wav_path = temp_wav.name
        temp_wav.close()
        
        # 导出为WAV格式
        audio.export(temp_wav_path, format='wav', parameters=["-ac", "1", "-ar", str(target_sample_rate)])
        logger.info(f"音频已导出为WAV格式: {temp_wav_path}")
        
        return temp_wav_path
    except Exception as e:
        logger.error(f"音频转换失败: {str(e)}")
        raise

def normalize_audio(audio_data):
    """标准化音频数据"""
    try:
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)
        
        # 计算音频统计信息
        mean_val = np.mean(audio_data)
        std_val = np.std(audio_data)
        max_abs = np.max(np.abs(audio_data))
        
        logger.info(f"音频统计: 均值={mean_val:.6f}, 标准差={std_val:.6f}, 最大绝对值={max_abs:.6f}")
        
        # 如果音频太弱，进行放大
        if max_abs < 0.1:
            scale_factor = 0.5 / max_abs  # 放大到0.5的幅度
            audio_data = audio_data * scale_factor
            logger.info(f"音频信号较弱，已放大 {scale_factor:.2f} 倍")
        
        # 确保音频数据在 [-1, 1] 范围内
        if max_abs > 1.0:
            audio_data = audio_data / max_abs
            logger.info("音频数据已归一化到 [-1, 1] 范围")
        
        # 移除DC偏置
        audio_data = audio_data - np.mean(audio_data)
        
        return audio_data
    except Exception as e:
        logger.error(f"音频标准化失败: {str(e)}")
        raise

def process_recognition_result(result):
    """处理识别结果，支持字符串和列表格式"""
    if isinstance(result, str):
        return result.strip()
    elif isinstance(result, list):
        # 如果是列表，可能包含多个识别结果或时间戳信息
        text_parts = []
        for item in result:
            if isinstance(item, dict):
                # 如果是字典格式，提取文本部分
                text = item.get('text', '') or item.get('result', '')
                if text:
                    text_parts.append(text)
            elif isinstance(item, str):
                text_parts.append(item)
        return ' '.join(filter(None, text_parts)).strip()
    elif result is None:
        return ""
    else:
        logger.warning(f"未知的识别结果格式: {type(result)}")
        return str(result)

def process_audio_chunk(audio_data, sample_rate, chunk_size=30*16000, hotwords=None):
    """分块处理音频数据
    
    Args:
        audio_data: 音频数据
        sample_rate: 采样率
        chunk_size: 每个音频块的大小（默认30秒）
        hotwords: 热词列表，用于提高特定词汇的识别准确率
    """
    try:
        results = []
        total_len = len(audio_data)
        
        # 标准化音频数据
        audio_data = normalize_audio(audio_data)
        
        # 如果音频太短，直接处理整个音频
        if total_len < chunk_size:
            try:
                with torch.no_grad():
                    # print(f"\n处理短音频 (长度: {total_len/sample_rate:.2f}秒)")
                    # 检查 generate 方法的参数
                    if hotwords:
                        # 将热词列表转换为空格分隔的字符串
                        hotword_str = ' '.join(hotwords)
                        logger.warning(f"调用 model.generate 方法，热词：{hotword_str}")
                    else:
                        hotword_str = None
                    
                    result = model.generate(
                        input=audio_data, 
                        sample_rate=sample_rate, 
                        hotword=hotword_str  # 使用空格分隔的热词字符串
                    )
                    processed_result = process_recognition_result(result)
                    if processed_result:
                        results.append(processed_result)
            except Exception as e:
                print(f"处理短音频时出错: {str(e)}")
        else:
            # 分块处理长音频
            overlap = int(0.5 * sample_rate)  # 0.5秒重叠
            total_chunks = (total_len + chunk_size - 1)//chunk_size
            print(f"\n开始处理音频，总共 {total_chunks} 个块")
            
            for i in range(0, total_len, chunk_size - overlap):
                chunk = audio_data[i:min(i+chunk_size, total_len)]
                chunk_num = i//chunk_size + 1
                
                # 检查音频块的有效性
                chunk_max = np.max(np.abs(chunk))
                chunk_energy = np.mean(chunk**2)
                
                # print(f"\n处理音频块 {chunk_num}/{total_chunks}")
                # print(f"块信息: 最大振幅={chunk_max:.6f}, 能量={chunk_energy:.6f}")
                
                # 使用能量和振幅双重判断是否为静音
                if chunk_max < 1e-3 or chunk_energy < 1e-6:
                    # print("跳过静音块")
                    continue
                
                try:
                    with torch.no_grad():
                        # 检查 generate 方法的参数
                        if hotwords:
                            # 将热词列表转换为空格分隔的字符串
                            hotword_str = ' '.join(hotwords)
                            logger.warning(f"调用 model.generate 方法，热词：{hotword_str}")
                        else:
                            hotword_str = None
                        
                        result = model.generate(
                            input=chunk, 
                            sample_rate=sample_rate, 
                            hotword=hotword_str  # 使用空格分隔的热词字符串
                        )
                        processed_result = process_recognition_result(result)
                        if processed_result:
                            results.append(processed_result)
                            # print(f"识别结果: {processed_result}")
                except Exception as e:
                    print(f"处理音频块 {chunk_num} 时出错: {str(e)}")
                    continue
        
        final_result = " ".join(results)
        print("\n音频处理完成！")
        return final_result
        
    except Exception as e:
        print(f"音频处理失败: {str(e)}")
        raise

@app.route('/recognize', methods=['POST'])
def recognize_audio():
    """处理音频文件并返回识别结果"""
    temp_files = []  # 用于跟踪需要清理的临时文件
    
    try:
        if 'audio' not in request.files:
            return jsonify({"error": "没有找到音频文件"}), 400
            
        audio_file = request.files['audio']
        if not audio_file:
            return jsonify({"error": "空的音频文件"}), 400
        
        # 获取原始文件信息
        original_filename = audio_file.filename
        file_size = len(audio_file.read())
        audio_file.seek(0)  # 重置文件指针
        logger.info(f"接收到音频文件: {original_filename}, 大小: {file_size/1024:.2f}KB")
        
        # 获取热词参数
        hotwords = request.form.get('hotwords', '')
        if hotwords:
            hotwords = [word.strip() for word in hotwords.split(',') if word.strip()]
            logger.warning(f"接收到热词参数: {hotwords}")  # 使用 warning 级别确保一定会打印
        
        # 保存上传的音频文件
        orig_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_audio_orig')
        audio_file.save(orig_audio_path)
        temp_files.append(orig_audio_path)
        
        try:
            # 转换音频格式
            wav_path = convert_audio_to_wav(orig_audio_path)
            temp_files.append(wav_path)
            
            # 读取转换后的音频文件
            audio_data, sample_rate = sf.read(wav_path)
            
            # 检查音频数据是否为空或无效
            if len(audio_data) == 0:
                logger.error("音频数据为空")
                return jsonify({"error": "音频数据为空"}), 400
                
            if np.all(np.abs(audio_data) < 1e-6):
                logger.error("音频数据全为静音")
                return jsonify({"error": "音频数据全为静音"}), 400
            
            # 分块处理音频
            logger.info("开始音频识别...")
            result = process_audio_chunk(audio_data, sample_rate, hotwords=hotwords if hotwords else None)
            
            # 放宽对空结果的处理
            if not result or len(result.strip()) == 0:
                logger.warning("识别结果为空，尝试整体识别...")
                # 如果分块识别失败，尝试整体识别
                try:
                    with torch.no_grad():
                        result = model.generate(
                            input=audio_data, 
                            sample_rate=sample_rate,
                            hotwords=hotwords if hotwords else None
                        )
                        result = process_recognition_result(result)
                except Exception as e:
                    logger.error(f"整体识别失败: {str(e)}")
                    result = ""
            
            logger.info("音频识别完成")
            
            response_data = {
                "success": True,
                "text": result if result and len(result.strip()) > 0 else "",
                "audio_info": {
                    "original_filename": original_filename,
                    "file_size_kb": file_size/1024,
                    "duration_seconds": len(audio_data)/sample_rate,
                    "sample_rate": sample_rate
                }
            }
            return jsonify(response_data)
            
        except Exception as e:
            logger.error(f"处理音频文件时出错: {str(e)}")
            return jsonify({"error": f"处理音频文件时出错: {str(e)}"}), 500
            
    except Exception as e:
        logger.error(f"请求处理出错: {str(e)}")
        return jsonify({"error": f"请求处理出错: {str(e)}"}), 500
        
    finally:
        # 清理所有临时文件
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as e:
                logger.error(f"清理临时文件失败: {str(e)}")

if __name__ == '__main__':
    try:
        # 确保上传目录存在
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        print("\n" + "="*20 + " FunASR服务启动 " + "="*20)
        print(f"服务启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"监听地址: 0.0.0.0:{10095}")
        print(f"上传目录: {app.config['UPLOAD_FOLDER']}")
        print(f"模型目录: {os.getenv('MODEL_DIR', '/app/models')}")
        print("="*56 + "\n")
        
        # 启动Flask应用
        app.run(host='0.0.0.0', port=10095, threaded=True)
    except Exception as e:
        print(f"错误: 启动FunASR服务失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
        sys.exit(1)
