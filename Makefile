.PHONY: sample test api benchmark frontend
sample:
	python data/generator/generate.py --cases 500

test:
	pytest -q

api:
	uvicorn backend.app.main:app --reload

benchmark:
	python benchmarks/benchmark.py

frontend:
	cd frontend && npm run build
