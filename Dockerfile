FROM python:3.11.9-slim

# 1. Set timezone to Asia/Seoul
ENV TZ=Asia/Seoul
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tzdata \
      curl \
      gnupg \
      build-essential \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# 2. Install Node.js 20.x and Supabase MCP Server globally
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @supabase/mcp-server-supabase@latest \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# 3. Python 앱 설치
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 4. 애플리케이션 코드 복사 및 실행
COPY . .
EXPOSE 8000
CMD ["python", "crewai_action_server.py"]
