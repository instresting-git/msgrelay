# ChatFlow — test image
# Builds the product in a clean Linux environment and runs the full test suite.
#
#   docker build -t chatflow-test .
#   docker run --rm chatflow-test

FROM python:3.11-slim

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Product code + tests
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY README.md LICENSE ./

# Smoke test the installer script syntax (bash available in slim? ensure)
RUN bash -n scripts/setup.sh && echo "setup.sh syntax OK"

# Run the test suite
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
