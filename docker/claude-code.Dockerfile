FROM node:22-alpine

RUN apk add --no-cache bash python3
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
ENTRYPOINT ["claude"]
