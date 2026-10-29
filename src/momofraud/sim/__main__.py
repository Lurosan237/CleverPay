"""Generate a simulated dataset.

    python -m momofraud.sim                          # 20,000 people, 90 days, half adaptive fraud
    python -m momofraud.sim --adaptive-share 0 --name naive
    python -m momofraud.sim --users 2000 --days 30 --name small
    python -m momofraud.sim --adaptive-share 0.5 --promo-start-day 78 --promo-share 0.25 --name promo

Writes data/simulated/<name>/{transactions,account_events,accounts}.parquet
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace

from momofraud.paths import ROOT
from momofraud.sim.config import FraudConfig, SimConfig
from momofraud.sim.engine import simulate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--users", type=int, default=SimConfig.n_users)
    parser.add_argument("--days", type=int, default=SimConfig.days)
    parser.add_argument("--seed", type=int, default=SimConfig.seed)
    parser.add_argument("--adaptive-share", type=float, default=FraudConfig.adaptive_share,
                        help="fraction of attacks using the adaptive strategy (0 to 1)")
    parser.add_argument("--rented-share", type=float, default=0.0,
                        help="share of takeovers and wrong transfers using rented accounts (0 to 1)")
    parser.add_argument("--promo-start-day", type=int, default=None,
                        help="drift experiment: day a phone promotion starts")
    parser.add_argument("--promo-share", type=float, default=0.0,
                        help="drift experiment: share of customers who get a new phone that week")
    parser.add_argument("--name", default="default", help="output folder name under data/simulated/")
    args = parser.parse_args(argv)

    cfg = SimConfig(n_users=args.users, days=args.days, seed=args.seed,
                    promo_start_day=args.promo_start_day, promo_new_phone_share=args.promo_share,
                    fraud=replace(FraudConfig(), adaptive_share=args.adaptive_share,
                                  rented_share=args.rented_share))
    started = time.perf_counter()
    frames = simulate(cfg)
    out = ROOT / "data" / "simulated" / args.name
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in frames.items():
        frame.to_parquet(out / f"{name}.parquet", index=False)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2))

    tx = frames["transactions"]
    ok = tx[tx["status"] == "SUCCESS"]
    print(f"{len(tx):,} transactions ({ok['is_fraud'].mean():.3%} of successful ones fraudulent) "
          f"in {time.perf_counter() - started:.0f}s -> {out}")


if __name__ == "__main__":
    main()
