.PHONY: install start stop health test secrets doctor smoke acceptance check probe logs restart status open

install:
	chmod +x scripts/*.sh scripts/*.py
	./scripts/install.sh

start:
	./scripts/start_all.sh

stop:
	./scripts/stop_all.sh

restart:
	./scripts/restart.sh

health:
	./scripts/health.sh

doctor:
	./scripts/doctor.sh

smoke:
	./scripts/smoke.sh

acceptance:
	./scripts/acceptance.sh

check:
	./scripts/check_once.sh

probe:
	./scripts/probe_cli.sh
	python3 scripts/probe_token.py

logs:
	./scripts/logs.sh

test:
	PYTHONPATH=. python3 -m pytest tests/ -q --tb=line

secrets:
	PYTHONPATH=. python3 -c "from src.common.config import get_settings; s=get_settings(); s.ensure_secrets(); print('SECRET_PATH=', s.secret_path)"

status:
	./scripts/status.sh

open:
	./scripts/open_url.sh
