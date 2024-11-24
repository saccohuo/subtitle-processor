FROM python:3.9-slim

# 设置pip镜像源为阿里云
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set install.trusted-host mirrors.aliyun.com

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

RUN pip install chardet

RUN mkdir uploads

EXPOSE 5000

CMD ["python", "app.py"]
