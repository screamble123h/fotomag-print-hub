FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY upload_gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    useradd -u 10001 --create-home --shell /usr/sbin/nologin fotomag
COPY upload_gateway/ /app/upload_gateway/
RUN mkdir -p /data && chown -R fotomag:fotomag /data
USER fotomag
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "upload_gateway.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
