FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.pyw"]
