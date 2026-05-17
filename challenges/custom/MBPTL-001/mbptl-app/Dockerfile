# Build stage
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories \
    && apk add --no-cache build-base

WORKDIR /usr/src/app

# Final stage
FROM python:3.11-alpine

RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories

# Copy Python runtime environment from builder
COPY --from=builder /usr/local /usr/local

# Set working directory
WORKDIR /usr/src/app

# Copy application files
COPY app.py .
COPY flag.txt /flag.txt

# Install dependencies without cache
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com flask

# Use non-root user for security
USER nobody

# Expose Flask default port (optional)
EXPOSE 5000

# Set entrypoint
ENTRYPOINT ["python", "app.py"]
