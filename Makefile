.PHONY: test build clean

test:
	python3 -m venv .venv >/dev/null 2>&1 || true
	. .venv/bin/activate && \
	  pip install -r requirements.txt && \
	  pip install -r requirements-dev.txt && \
	  python -m pytest -ra -o addopts= \
	    --cov=notion_format --cov=prompt_contract \
	    --cov-report=term-missing --cov-fail-under=80

build:
	./build.sh

clean:
	rm -rf .venv build dist