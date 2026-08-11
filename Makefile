.PHONY: install test gen-types sync-schemas docker-build docker-images gui-build gui-dev

install:
	python3 -m pip install --upgrade pip setuptools wheel
	python3 -m pip install -e .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

# Regenerate the TS client's api-types.ts from src/starbench/gui/contracts.py.
# The output is committed; run this whenever a core API shape changes.
gen-types:
	python3 scripts/gen_api_types.py

# schemas/starbench/ is the authoring source; the packaged mirror under
# src/starbench/contracts/schemas/ is derived. Run after editing any schema.
sync-schemas:
	python3 scripts/sync_schemas.py

docker-build:
	docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .

# One image per runtime; each contains exactly its own CLI.
docker-images: docker-build
	docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .
	docker build -t starbench-gemini-cli:latest -f docker/gemini-cli.Dockerfile .
	docker build -t starbench-grok:latest -f docker/grok.Dockerfile .
	docker build -t starbench-opencode:latest -f docker/opencode.Dockerfile .
	docker build -t starbench-pi:latest -f docker/pi.Dockerfile .

# Images for the bundled runtime definitions (Qwen Code, Kimi Code, Trae Agent).
docker-images-custom:
	docker build -t starbench-qwen:latest -f docker/qwen-code.Dockerfile .
	docker build -t starbench-kimi:latest -f docker/kimi-cli.Dockerfile .
	docker build -t starbench-trae-agent:latest -f docker/trae-agent.Dockerfile .

# Rebuild the console frontend into src/starbench/gui/static (output is committed;
# only needed when gui-frontend/ sources change).
gui-build:
	cd gui-frontend && npm install && npm run build

gui-dev:
	cd gui-frontend && npm install && npm run dev
