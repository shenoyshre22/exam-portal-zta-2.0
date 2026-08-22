FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --default-timeout=1000 --retries 5 --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
