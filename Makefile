.PHONY: install test docker-build

install:
	python3 -m pip install --upgrade pip setuptools wheel
	python3 -m pip install -e .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

docker-build:
	docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .
