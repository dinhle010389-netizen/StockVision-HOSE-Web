.PHONY: test api sync-bars stream

test:
	PYTHONPATH=backend pytest -q

api:
	PYTHONPATH=backend DATABASE_URL=sqlite:///./stockvision_local.db DEMO_MODE=true uvicorn app.main:app --app-dir backend --reload

sync-bars:
	PYTHONPATH=backend python scripts/sync_tcbs_bars.py --count-back 250

stream:
	PYTHONPATH=backend ENABLE_TCBS_STREAM=true python -m app.run_tcbs_stream
