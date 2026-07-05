.PHONY: install test docker-build docker-images gui-build gui-dev

install:
	python3 -m pip install --upgrade pip setuptools wheel
	python3 -m pip install -e .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

docker-build:
	docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .

# One image per runtime; each contains exactly its own CLI.
docker-images: docker-build
	docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .
	docker build -t starbench-gemini-cli:latest -f docker/gemini-cli.Dockerfile .
	docker build -t starbench-grok:latest -f docker/grok.Dockerfile .
	docker build -t starbench-opencode:latest -f docker/opencode.Dockerfile .

# Images for the custom-runtime templates (Qwen Code, Trae Agent).
docker-images-custom:
	docker build -t starbench-qwen:latest -f docker/qwen-code.Dockerfile .
	docker build -t starbench-trae-agent:latest -f docker/trae-agent.Dockerfile .

# Rebuild the console frontend into src/starbench/gui/static (output is committed;
# only needed when gui-frontend/ sources change).
gui-build:
	cd gui-frontend && npm install && npm run build

gui-dev:
	cd gui-frontend && npm install && npm run dev
