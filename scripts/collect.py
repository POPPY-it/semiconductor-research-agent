"""采集命令入口：python scripts/collect.py --once | --schedule [--hour 8]"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.pipeline import run_collect_once, schedule_daily  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="半导体行业数据采集")
    parser.add_argument("--once", action="store_true", help="立即采集一次")
    parser.add_argument("--schedule", action="store_true", help="每日定时采集（常驻）")
    parser.add_argument("--hour", type=int, default=8, help="定时小时（默认 8 点）")
    args = parser.parse_args()

    if args.schedule:
        schedule_daily(hour=args.hour)
    else:
        results = run_collect_once()
        for r in results:
            print(r)


if __name__ == "__main__":
    main()
