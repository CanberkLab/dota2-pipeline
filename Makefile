# Uses its own virtualenv (.venv), so it works even when `python` / `pip` are not on your PATH
# (e.g. macOS only ships python3).
VENV   := .venv
PY     := $(VENV)/bin/python
PYTHON3 ?= python3

.PHONY: setup sample run test dashboard dbt-docs clean

setup:             ## create .venv and install everything (run this first)
	$(PYTHON3) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,dashboard]"

sample:            ## offline demo: fake OpenDota API, synthetic data (two runs show incremental loading)
	$(PY) -m dota_pipeline.run --mock --mock-size 5000 --pages 60
	$(PY) -m dota_pipeline.run --mock --mock-size 7000 --pages 60

run:               ## real OpenDota API (about 1 request/second)
	$(PY) -m dota_pipeline.run --pages 20

test:
	$(PY) -m pytest -q

dashboard:
	$(PY) -m streamlit run dashboard/app.py

dbt-docs:
	$(PY) -c "from dota_pipeline.run import run_dbt; run_dbt('docs','generate'); run_dbt('docs','serve')"

clean:
	rm -rf data/raw/* data/warehouse/* dbt_project/target dbt_project/logs
