.PHONY: lint test

lint:
	python3 -m compileall -q calc tests

test:
	python3 -m unittest discover -s tests -t . -v
