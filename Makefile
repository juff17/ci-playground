.PHONY: lint test

lint:
	python3 -m compileall -q calc sandbox tests tools

# sandbox/ holds the code scenario PRs add, each with its own tests.
test:
	python3 -m unittest discover -s tests -t . -v
	python3 -m unittest discover -s sandbox -t . -v
