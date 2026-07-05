FROM node:22-alpine

RUN apk add --no-cache bash python3
RUN npm install -g @qwen-code/qwen-code

WORKDIR /workspace
