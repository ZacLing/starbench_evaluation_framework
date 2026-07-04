.PHONY: install test docker-build gui-build gui-dev

install:
	python3 -m pip install --upgrade pip setuptools wheel
	python3 -m pip install -e .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

docker-build:
	docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .

# Rebuild the console frontend into src/starbench/gui/static (output is committed;
# only needed when gui-frontend/ sources change).
gui-build:
	cd gui-frontend && npm install && npm run build

gui-dev:
	cd gui-frontend && npm install && npm run dev
