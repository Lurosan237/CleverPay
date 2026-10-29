"""A short story told through the API: one normal payment and three scams.

    python -m momofraud.serving.demo            # English
    python -m momofraud.serving.demo --lang fr  # français

Runs the API in-process on a demo network, so no server is needed.
"""

from __future__ import annotations

import argparse
import math

from fastapi.testclient import TestClient

from momofraud.serving.api import create_app

LINE = "-" * 78


def show(title: str, response: dict) -> None:
    score = response["score"]
    score_text = f"score {score:.3f}" if score is not None else "not scored"
    print(f"\n{title}\n  -> {response['decision'].upper()} ({score_text}, status {response['status']}, "
          f"{response['timings_us']['total'] / 1000:.1f} ms)")
    for reason in response["reasons"]:
        print(f"     - {reason['text']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", choices=["en", "fr"], default="en")
    args = parser.parse_args(argv)
    lang = args.lang

    print("Building a demo network of 3,000 people (about 10 seconds)...")
    with TestClient(create_app()) as api:
        net = api.app.state.network
        # A customer with money, a regular contact and a phone (read from the network, like a support tool would)
        amina, sister = next((s, r) for (s, r), n in net.state.pair_count.items()
                             if n >= 3 and net.kind.get(s) == net.kind.get(r) == "customer"
                             and net.balance.get(s, 0) > 30_000)
        phone = net.device[amina]
        agents = [a for a, k in net.kind.items() if k == "agent"]
        print(LINE)

        show(f"1. {amina} sends 5,000 FCFA to {sister}, whom she pays regularly, from her own phone.",
             api.post("/v1/transactions", json={"type": "TRANSFER", "sender": amina, "receiver": sister,
                                                 "amount": 5000, "device": phone, "lang": lang}).json())

        # 2. Account takeover after a SIM swap
        api.post("/v1/events", json={"account": amina, "event": "SIM_SWAP", "device": "D-fraudster"})
        mule = api.post("/v1/accounts", json={"region": "Douala"}).json()["account"]
        balance = api.get(f"/v1/accounts/{amina}").json()["balance"]
        show(f"2. Her SIM is swapped. Ten minutes later, a new phone tries to send her whole balance\n"
             f"   ({balance:,.0f} FCFA) to {mule}, an account opened a few minutes ago.",
             api.post("/v1/transactions", json={
                 "type": "TRANSFER", "sender": amina, "receiver": mule, "amount": math.floor(balance / 1.002),
                 "device": "D-fraudster", "timestamp": net.timestamp(net.now + 600), "lang": lang}).json())

        # 3. Rogue agent: dozens of withdrawal requests, almost all declined
        rogue = agents[0]
        targets = [a for a, k in net.kind.items() if k == "customer" and a not in (amina, sister)][:41]
        for target in targets[:40]:
            api.post("/v1/transactions", json={
                "type": "CASH_OUT", "channel": "AGENT_REQUEST", "sender": target, "receiver": rogue,
                "amount": 25_000, "customer_declined": True})
        victim = targets[40]
        show(f"3. Agent {rogue} sends 40 withdrawal requests of 25,000 FCFA to random numbers in a few\n"
             f"   minutes; everyone declines. Then {victim} approves one by mistake.",
             api.post("/v1/transactions", json={
                 "type": "CASH_OUT", "channel": "AGENT_REQUEST", "sender": victim, "receiver": rogue,
                 "amount": 25_000, "device": net.device.get(victim), "lang": lang}).json())

        # 4. "Sent by mistake": the victim refunds money they never received
        caller = api.post("/v1/accounts", json={"region": "Yaoundé"}).json()["account"]
        for i, other in enumerate(targets[:6]):  # other victims already "refunded" this number
            api.post("/v1/transactions", json={
                "type": "TRANSFER", "sender": other, "receiver": caller, "amount": 2000 + 500 * i,
                "device": net.device.get(other), "override_review": True})
        show(f"4. A caller says they sent {sister} 5,000 FCFA by mistake. {sister} has never paid this\n"
             f"   number; six other people sent it money today.",
             api.post("/v1/transactions", json={
                 "type": "TRANSFER", "sender": sister, "receiver": caller, "amount": 5000,
                 "device": net.device.get(sister), "lang": lang}).json())
        print(LINE)


if __name__ == "__main__":
    main()
