.PHONY: check lint typecheck test sweep report

check: lint typecheck test

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy .

test:
	uv run pytest -q

sweep:
	uv run python -m cli sweep --all --samples 3

report:
	uv run python -m cli report
