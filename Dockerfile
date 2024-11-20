FROM python:3.9-slim

WORKDIR /app

COPY ./requirements.txt .

RUN pip install --no-cache-dir requests aiogram aiomysql

CMD ["python", "./bot.py"]