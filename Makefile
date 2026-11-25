.PHONY: help linux macos openrouter test

OPENROUTER ?= 0

help:
	@printf '%s\n' 'Run make linux, make macos, or make openrouter (installs OpenRouter and refreshes its catalog).'

linux macos:
	@sh ./scripts/install.sh "$(OPENROUTER)"

openrouter:
	@sh ./scripts/install-openrouter.sh

test:
	python3 -m unittest discover -s tests -v
	bash codex/tests/test-codex-model-picker.sh
	bash codex/tests/test-model-catalog.sh
	python3 codex/tests/test-codex-model-picker-tui.py
