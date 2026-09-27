PYTHON ?= python3
PORT ?= 8501

.PHONY: setup pipeline dashboard test clean

setup:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

pipeline:
	$(PYTHON) load_data.py
	$(PYTHON) analysis.py
	$(PYTHON) build_dashboard.py

dashboard:
	PORT=$(PORT) $(PYTHON) dashboard.py

test:
	$(PYTHON) -m unittest discover -s tests -v
	@if command -v node >/dev/null 2>&1; then node tests/check_dashboard.cjs; else echo "node not found; skipping dashboard check"; fi

clean:
	rm -f immune_cells.db
