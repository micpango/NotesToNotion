.PHONY: test build clean

test:
	./build.sh --help >/dev/null 2>&1 || true
	python3 -m venv .venv >/dev/null 2>&1 || true
	. .venv/bin/activate && pip install -r requirements.txt && pip install -r requirements-dev.txt && pytest

build:
	./build.sh

clean:
	rm -rf .venv build dist