.PHONY: demo run test eval fetch clean

# Zero-setup demo: runs the full pipeline on cached model output. No API key needed.
demo:
	PYTHONPATH=src python -m signal_radar.cli run --replay --out out/digest.md
	@echo "\n--> out/digest.md"

# Live run: requires ANTHROPIC_API_KEY and fetched transcripts.
run:
	PYTHONPATH=src python -m signal_radar.cli run --out out/digest.md

fetch:
	PYTHONPATH=src python -m signal_radar.cli fetch

test:
	python tests/test_pipeline.py

eval:
	python eval/run_eval.py

clean:
	rm -rf out/ __pycache__/
