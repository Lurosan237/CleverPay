"""Everything the static website needs, exported from the real Python code.

    python -m momofraud.web_export     # writes site/data/

The website runs entirely in the visitor's browser: the same feature engine (ported to
JavaScript), the same LightGBM models and the same SHAP explanations. To prove the port is
exact, this script also records a script of operations played through the Python service,
with every feature vector, score and SHAP value it produced. `npm test` in site/ replays the
script in JavaScript and fails if anything differs.

Files:
- models/<tier>.json   trees as flat arrays, thresholds, metrics (from models/tiers/)
- world.json           a simulated network (accounts, balances, history) as of its last day
- parity.json          operations and expected outputs, for the JavaScript tests
- metrics.json         stage 3 results, drift report, latency, game strategies: for the Model Lab
"""

from __future__ import annotations

import copy
import json
import math
import random

import lightgbm as lgb
import numpy as np

from momofraud.behaviour import FEATURES, FeatureState
from momofraud.paths import REPORTS_DIR, ROOT
from momofraud.serving.network import Network
from momofraud.serving.service import new_number
from momofraud.sim.config import REGIONS, FraudConfig, SimConfig
from momofraud.sim.engine import simulate
from momofraud.tiers import TIERS_DIR

SITE_DATA = ROOT / "site" / "data"
WORLD = {"n_users": 2000, "days": 30, "seed": 11}
KINDS = ["customer", "agent", "merchant", "external"]
DAY = 86_400


# -- models --------------------------------------------------------------------------------------

def export_model(booster: lgb.Booster, features: list[str]) -> dict:
    """Trees as flat arrays. Node i < 0 means leaf ~i. Decisions: x <= threshold goes left."""
    dump = booster.dump_model()
    if dump["objective"].split()[0] != "binary":
        raise ValueError("only binary models are supported")
    trees = [_export_tree(info["tree_structure"]) for info in dump["tree_info"]]
    # SHAP's expected value (the last column of pred_contrib) is the same for every row
    bias = float(booster.predict(np.zeros((1, len(features))), pred_contrib=True)[0][-1])
    return {"features": features, "trees": trees, "bias": bias}


def _export_tree(root: dict) -> dict:
    feature, threshold, left, right, cover, leaf_value, leaf_cover = [], [], [], [], [], [], []

    def visit(node) -> int:
        if "split_index" not in node:
            leaf_value.append(node["leaf_value"])
            leaf_cover.append(node.get("leaf_count", 1))
            return ~(len(leaf_value) - 1)
        if node["decision_type"] != "<=" or node.get("missing_type") not in (None, "None"):
            raise ValueError(f"unsupported split: {node['decision_type']}, {node.get('missing_type')}")
        i = len(feature)
        feature.append(node["split_feature"])
        threshold.append(node["threshold"])
        cover.append(node["internal_count"])
        left.append(0)
        right.append(0)
        left[i] = visit(node["left_child"])
        right[i] = visit(node["right_child"])
        return i

    visit(root)
    return {"f": feature, "t": threshold, "l": left, "r": right, "c": cover, "v": leaf_value, "vc": leaf_cover}


def export_models() -> dict:
    meta = json.loads((TIERS_DIR / "tiers.json").read_text())["tiers"]
    out = {}
    for key, tier in meta.items():
        booster = lgb.Booster(model_file=str(TIERS_DIR / f"{key}.txt"))
        model = export_model(booster, tier["features"])
        model |= {"key": key, "name": tier["name"], "knows": tier["knows"], "thresholds": tier["thresholds"],
                  "test": tier["test"]}
        (SITE_DATA / "models").mkdir(parents=True, exist_ok=True)
        (SITE_DATA / "models" / f"{key}.json").write_text(json.dumps(model, separators=(",", ":")))
        out[key] = booster
    return out


# -- the world -----------------------------------------------------------------------------------

def build_world() -> Network:
    cfg = SimConfig(n_users=WORLD["n_users"], days=WORLD["days"], seed=WORLD["seed"],
                    fraud=FraudConfig(adaptive_share=0.5))
    return Network.from_world(simulate(cfg))


def _prune_all(state: FeatureState, now: int) -> None:
    """Drop window entries that can never count again: the export only keeps what matters."""
    for windows, span in ((state.out_24h, DAY), (state.in_7d, 7 * DAY), (state.cashout_7d, 7 * DAY),
                          (state.agent_requests_24h, DAY)):
        for key in list(windows):
            w = windows[key]
            while w and w[0][0] < now - span:
                w.popleft()
            if not w:
                del windows[key]


def snapshot(net: Network) -> dict:
    s = net.state
    _prune_all(s, net.now)
    names = sorted(set(net.kind) | set(s.opened_t) | set(s.activity) | {a for a, _ in s.pair_count}
                   | {r for _, r in s.pair_count})
    idx = {a: i for i, a in enumerate(names)}
    regions = sorted(set(net.region.values()) | set(REGIONS))
    n = len(names)

    def col(d: dict, default=None):
        return [d.get(a, default) for a in names]

    return {
        "start": net.timestamp(0), "now": net.now, "next_id": net.next_id, "regions": regions,
        "accounts": names,
        "kind": [KINDS.index(net.kind[a]) if a in net.kind else 3 for a in names],
        "region": [regions.index(net.region[a]) if a in net.region else -1 for a in names],
        "balance": col(net.balance),
        "device": col(net.device),
        "opened_t": col(s.opened_t),
        "sender_count": [s.sender_count.get(a, 0) for a in names],
        "activity": [s.activity.get(a, 0) for a in names],
        "last_tx_t": col(s.last_tx_t),
        "amount_mean": col(s.amount_mean), "amount_var": col(s.amount_var),
        "amount_n": [s.amount_n.get(a, 0) for a in names],
        "out_24h": {idx[a]: [list(e) for e in w] for a, w in s.out_24h.items()},
        "in_7d": {idx[a]: [[t, idx[snd], amt, st] for t, snd, amt, st in w] for a, w in s.in_7d.items()},
        "cashout_7d": {idx[a]: [list(e) for e in w] for a, w in s.cashout_7d.items()},
        "agent_requests_24h": {idx[a]: [list(e) for e in w] for a, w in s.agent_requests_24h.items()},
        "devices": [[idx[a], d, c, s.device_first_t.get((a, d))] for (a, d), c in s.device_count.items() if c],
        "pairs": [v for (a, b), c in s.pair_count.items() if c for v in (idx[a], idx[b], c)],
        "last_security_t": {idx[a]: t for a, t in s.last_security_t.items()},
        "last_device_change_t": {idx[a]: t for a, t in s.last_device_change_t.items()},
        "recent": {idx[a]: list(r)[-5:] for a, r in net.recent.items() if a in idx and net.kind.get(a) == "customer"},
        "n": n,
    }


# -- parity script -------------------------------------------------------------------------------

def parity_script(net: Network, boosters: dict, seed: int = 5, steps: int = 400) -> dict:
    """Random but realistic operations, applied through the Python code, with expected outputs.

    The production decision path (thresholds of the Expert model) decides what is committed;
    every model's score and SHAP values are recorded for every scored transaction.
    """
    from momofraud.serving.model import FraudModel
    from momofraud.serving.service import process

    rng = random.Random(seed)
    expert = FraudModel(TIERS_DIR / "expert.txt")
    customers = [a for a, k in net.kind.items() if k == "customer"]
    agents = [a for a, k in net.kind.items() if k == "agent"]
    merchants = [a for a, k in net.kind.items() if k == "merchant"]
    pairs = [(s, r) for (s, r), c in net.state.pair_count.items()
             if c >= 2 and net.kind.get(s) == "customer" and net.kind.get(r) == "customer"]
    ops, t = [], net.now
    # A few scripted attacks first, so flagged transactions and their reasons are covered too
    for k in range(6):
        victim = customers[k * 7]
        t += 600
        net.account_event(victim, "SIM_SWAP", f"D-thief{k}", t)
        ops.append({"op": "event", "account": victim, "event": "SIM_SWAP", "device": f"D-thief{k}", "t": t})
        mule = new_number(net, seed=10_000 + k)
        net.open_account(mule, "customer", "Douala", t)
        ops.append({"op": "open", "account": mule, "kind": "customer", "region": "Douala", "t": t})
        pairs.append((victim, mule))
        net.device[victim] = f"D-thief{k}"
    for step in range(steps):
        t += rng.randint(1, 3600)
        roll = rng.random()
        if roll < 0.04:
            account = rng.choice(customers)
            event = rng.choice(["SIM_SWAP", "PIN_RESET", "DEVICE_CHANGE"])
            device = f"D-x{step}" if event != "PIN_RESET" else None
            net.account_event(account, event, device, t)
            ops.append({"op": "event", "account": account, "event": event, "device": device, "t": t})
            continue
        if roll < 0.07:
            account = new_number(net, seed=step)
            region = rng.choice(list(REGIONS))
            net.open_account(account, "customer", region, t)
            customers.append(account)
            ops.append({"op": "open", "account": account, "kind": "customer", "region": region, "t": t})
            continue
        if roll < 0.55 and pairs:
            sender, receiver = rng.choice(pairs)
            type_, channel = "TRANSFER", rng.choice(["USSD", "APP"])
        elif roll < 0.70:
            sender, receiver = rng.choice(customers), rng.choice(customers)
            type_, channel = "TRANSFER", "USSD"
        elif roll < 0.85:
            sender, receiver = rng.choice(customers), rng.choice(agents)
            type_, channel = "CASH_OUT", rng.choice(["AGENT", "AGENT_REQUEST", "USSD"])
        else:
            sender, receiver = rng.choice(customers), rng.choice(merchants)
            type_, channel = rng.choice(["PAYMENT", "AIRTIME"]), "USSD"
        if sender == receiver:
            continue
        balance = net.balance.get(sender, 0.0)
        amount = float(rng.choice([500, 1000, 2000, 5000, 10_000, 25_000, max(500.0, math.floor(balance * 0.97))]))
        device = net.device.get(sender) if rng.random() < 0.9 else f"D-new{step}"
        declined = type_ == "CASH_OUT" and channel == "AGENT_REQUEST" and rng.random() < 0.6
        override = rng.random() < 0.3
        # every model scores the same pre-transaction state
        record = net.build(type_, channel, sender, receiver, amount, device, t)
        expected = None
        if type_ in ("TRANSFER", "CASH_OUT") and not declined:
            features = net.state.features(copy.copy(record))
            expected = {"features": features, "models": {}}
            for key, booster in boosters.items():
                names = json.loads((SITE_DATA / "models" / f"{key}.json").read_text())["features"]
                row = np.asarray([[features[FEATURES.index(f)] for f in names]])
                contrib = booster.predict(row, pred_contrib=True)[0]
                expected["models"][key] = {"score": float(booster.predict(row)[0]),
                                           "shap": [float(v) for v in contrib[:-1]]}
        lang = "fr" if step % 2 else "en"
        explain = rng.random() < 0.5
        outcome = process(net, expert, type_=type_, channel=channel, sender=sender, receiver=receiver,
                          amount=amount, device=device, t=t, customer_declined=declined,
                          override_review=override, lang=lang, explain=explain)
        ops.append({"op": "tx", "type": type_, "channel": channel, "sender": sender, "receiver": receiver,
                    "amount": amount, "device": device, "t": t, "declined": declined, "override": override,
                    "expected": expected, "decision": outcome.decision, "status": outcome.status,
                    "lang": lang, "explain": explain, "reasons": [r["text"] for r in outcome.reasons],
                    "balance_after": net.balance.get(sender)})
    return {"ops": ops, "final_balances": {a: net.balance[a] for a in customers[:200] if a in net.balance}}


def export_metrics() -> dict:
    out = {}
    for name in ("behaviour", "drift", "game_strategies", "latency", "simulator", "baselines"):
        path = REPORTS_DIR / f"{name}.json"
        if path.exists():
            out[name] = json.loads(path.read_text())
    return out


def main() -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    boosters = export_models()
    net = build_world()
    world = snapshot(net)
    (SITE_DATA / "world.json").write_text(json.dumps(world, separators=(",", ":")))
    # The parity script starts from exactly the exported state
    parity = parity_script(net, boosters)
    (SITE_DATA / "parity.json").write_text(json.dumps(parity, separators=(",", ":")))
    (SITE_DATA / "metrics.json").write_text(json.dumps(export_metrics(), separators=(",", ":")))
    for f in sorted(SITE_DATA.rglob("*.json")):
        print(f"{f.relative_to(SITE_DATA)}: {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
