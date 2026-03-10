FROM node:22-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV BUN_INSTALL="/usr/local" \
    PATH="/usr/local/bin:$PATH" \
    DEBIAN_FRONTEND=noninteractive


# 1. 合并系统依赖安装与全局工具安装，并清理缓存
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    chromium \
    curl \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    git \
    gosu \
    jq \
    python3 \
    socat \
    tini \
    unzip \
    websockify && \
    # 更新 npm 并安装全局包
    npm install -g npm@latest && \
    npm install -g openclaw@2026.3.2 @anthropic-ai/claude-code playwright playwright-extra puppeteer-extra-plugin-stealth @steipete/bird && \
    # 安装 Playwright 浏览器依赖
    npx playwright install chromium --with-deps && \
    # 清理 apt 缓存
    apt-get purge -y --auto-remove && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.npm /root/.cache

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources
RUN apt-get update && \
    apt-get install -y --no-install-recommends vim


# 2. 插件安装（作为 node 用户以避免后期权限修复带来的镜像膨胀）
RUN mkdir -p /home/node/.openclaw/workspace /home/node/.openclaw/extensions && \
    chown -R node:node /home/node

USER node
ENV HOME=/home/node
WORKDIR /home/node

RUN cd /home/node/.openclaw/extensions && \
  git clone --depth 1 https://github.com/soimy/openclaw-channel-dingtalk.git dingtalk && \
  cd dingtalk && \
  npm install --omit=dev --legacy-peer-deps && \
  timeout 300 openclaw plugins install -l . || true && \
  cd /home/node/.openclaw/extensions && \
  timeout 300 openclaw plugins install @mem0/openclaw-mem0 || true &&\
  find /home/node/.openclaw/extensions -name ".git" -type d -exec rm -rf {} + && \
  rm -rf /tmp/* /home/node/.npm /home/node/.cache

COPY ./index.ts /home/node/.openclaw/extensions/openclaw-mem0
# 复制初始化脚本
COPY ./init1.sh /usr/local/bin/init.sh


  
# 3. 最终配置
USER root
RUN chmod +x /usr/local/bin/init.sh

RUN chmod -R 755 /home/node/.openclaw



# 设置环境变量
ENV HOME=/home/node \
    TERM=xterm-256color \
    NODE_PATH=/usr/local/lib/node_modules

# 暴露端口
EXPOSE 18789 18790

# 设置工作目录为 home
WORKDIR /home/node

# 使用初始化脚本作为入口点
