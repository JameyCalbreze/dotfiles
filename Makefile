.PHONY: help linux macos test

OPENROUTER ?= 0

help:
	@printf '%s\n' 'Run make linux or make macos (optionally OPENROUTER=1).'

linux macos:
	@sh ./scripts/install.sh "$(OPENROUTER)"

test:
	python3 -m unittest discover -s tests -v
	bash codex/tests/test-codex-model-picker.sh
	bash codex/tests/test-model-catalog.sh
	python3 codex/tests/test-codex-model-picker-tui.py
