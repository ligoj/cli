# Optional default target
# all: init test

# Install the package in editable mode
init:
	@echo "Installing dependencies..."
	pip install -e .

# Run the test suite
test:
	@echo "Running tests..."
	py.test tests

# Declare phony targets so make knows they are not files
.PHONY: init test