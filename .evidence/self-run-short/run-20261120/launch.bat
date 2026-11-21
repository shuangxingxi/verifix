@echo off
cd /d E:\shuangxingxi\ICT_agent
python -u scripts\self_run_short_observe.py --duration-seconds 7200 --interval-seconds 60 --sample-path .evidence\self-run-short\run-20261120\samples.jsonl --summary-path .evidence\self-run-short\run-20261120\summary.md > .evidence\self-run-short\run-20261120\stdout.log 2>&1
echo exit=%ERRORLEVEL% >> .evidence\self-run-short\run-20261120\stdout.log