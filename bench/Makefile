# ChatDBG ablation pipeline
#
# End-to-end:
#
#   make bench    MODELS="openrouter/moonshotai/kimi-k2.5 openrouter/openai/gpt-5"
#                 CONFIGS="all_tools debug_only no_tools" TRIALS=3
#   make judge    RUN=bench/results/run-20260417-120000
#   make report   RUN=bench/results/run-20260417-120000
#
# You can also chain them:
#
#   make all MODELS="..." CONFIGS="..." TRIALS=3

SHELL := /bin/bash

PY ?= python3
BENCH_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
REPO_DIR := $(abspath $(BENCH_DIR)/..)

# Resolve chatdbg from the source tree, not pip.
export PYTHONPATH := $(REPO_DIR)/src:$(PYTHONPATH)

MODELS ?= openrouter/moonshotai/kimi-k2.5
CONFIGS ?= all_tools debug_only no_tools
TRIALS ?= 1
CONTEXT ?= 10
CASES ?=
JUDGE_MODEL ?= openrouter/openai/gpt-5

# Newest results dir under bench/results — used by judge/report when
# RUN is not set explicitly.
LATEST := $(shell ls -1dt $(BENCH_DIR)/results/*/ 2>/dev/null | head -n1)
RUN ?= $(LATEST)

.PHONY: help bench judge report all clean-results lint-cases

help:
	@echo "Targets:"
	@echo "  bench         run the (case x model x config) matrix"
	@echo "  judge         score a completed run with the judge LLM"
	@echo "  report        aggregate scores into CSVs + report.md"
	@echo "  all           bench then judge then report"
	@echo "  lint-cases    quick compile-only sanity check on cases"
	@echo ""
	@echo "Variables:"
	@echo "  MODELS        models to sweep (space-separated, LiteLLM paths)"
	@echo "  CONFIGS       tool_config names under bench/configs/ (no .json)"
	@echo "  TRIALS        trials per cell (default: 1)"
	@echo "  CONTEXT       stack-trace context line count(s) (default: 10)"
	@echo "  CASES         optional case ids to restrict to"
	@echo "  JUDGE_MODEL   judge model (default: $(JUDGE_MODEL))"
	@echo "  RUN           results/<run_name> (default: newest)"

bench:
	$(PY) $(BENCH_DIR)/orchestrator.py \
	  --models $(MODELS) \
	  --tool-configs $(CONFIGS) \
	  --trials $(TRIALS) \
	  --context-lines $(CONTEXT) \
	  $(if $(CASES),--cases $(CASES),)

judge:
	@test -n "$(RUN)" || (echo "No RUN. Pass RUN=..."; exit 2)
	$(PY) $(BENCH_DIR)/judge.py "$(RUN)" --judge-model $(JUDGE_MODEL)

report:
	@test -n "$(RUN)" || (echo "No RUN. Pass RUN=..."; exit 2)
	$(PY) $(BENCH_DIR)/analyze.py "$(RUN)"
	@echo "Report: $(RUN)/analysis/report.md"

all: bench
	$(MAKE) judge RUN="$$(ls -1dt $(BENCH_DIR)/results/*/ | head -n1)"
	$(MAKE) report RUN="$$(ls -1dt $(BENCH_DIR)/results/*/ | head -n1)"

lint-cases:
	$(PY) $(BENCH_DIR)/orchestrator.py \
	  --dry-run --models _unused_ --tool-configs all_tools \
	  $(if $(CASES),--cases $(CASES),)

clean-results:
	rm -rf $(BENCH_DIR)/results/*
