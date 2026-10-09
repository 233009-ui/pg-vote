FROM python:3.11-slim

RUN pip install --no-cache-dir curl_cffi boto3

WORKDIR /app
COPY src/voter.py .

ENV PG_WORKERS=10
ENV PG_NONCE=3e04eea04c
ENV PG_POST_ID=24454
ENV PG_NTFY_TOPIC=pg-autopilot-sh3rd1l
ENV PG_ENABLE_CLOUDWATCH=1
ENV PG_ENABLE_SOLVER=0

CMD ["python3", "-u", "voter.py"]
