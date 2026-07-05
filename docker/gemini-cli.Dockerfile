FROM node:22-alpine

RUN apk add --no-cache bash python3
RUN npm install -g @google/gemini-cli

WORKDIR /workspace
