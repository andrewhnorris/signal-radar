.PHONY: demo run test eval seed import fetch clean

# Zero-setup demo: runs the full pipeline on cached model output. No API key needed.
demo:
	PYTHONPATH=src python -m signal_radar.cli run --replay --out out/digest.md
	@echo "\n--> out/digest.md"

# Live run: requires ANTHROPIC_API_KEY and fetched transcripts.
run:
	PYTHONPATH=src python -m signal_radar.cli run --out out/digest.md

import:
	@echo "Usage: python scripts/import_transcript.py <saved.html> --ticker MDGL --quarter \"Q2 2026\""
	@python scripts/import_transcript.py --list

fetch:
	PYTHONPATH=src python -m signal_radar.cli fetch

seed:
	python scripts/ingest_13f.py --xml data/13f/sample_information_table.xml --top 10

test:
	python tests/test_pipeline.py

eval:
	python eval/run_eval.py

clean:
	rm -rf out/ __pycache__/
