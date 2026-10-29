# The simulator

`python -m momofraud.sim` generates a mobile money network: 20,000 account holders over 90
days (about 5 million transactions, 1 minute, 2.5 GB of RAM). Results and calibration checks:
[reports/simulator.md](../reports/simulator.md).

## Why not just use PaySim

PaySim was enough to show the problem (stage 1) but cannot support the solution:

- **No history.** 99.85% of PaySim's senders appear once, so behavioural signals such as
  "has this person ever paid this number?" cannot be computed.
- **One kind of fraud, always naive.** Fraudsters always take the whole balance, which a one-line
  rule catches.
- **Inconsistent balances.** 90% of legitimate transactions have balances that don't add up.

This simulator fixes all three. Every account's balance follows on exactly from its previous
transaction (a test checks this for every row), and fraud comes in three documented scams,
each with a naive and an adaptive version.

## Legitimate behaviour

- **Five profiles** (students, salaried workers, traders, farmers, retired people) with different
  incomes, habits and transaction sizes, across ten Cameroonian towns.
- **Social circles:** each person mostly sends money to 3-12 regular contacts, 70% in the same
  town; 12% of transfers go to someone new (a one-off payment), so "new recipient" alone is not fraud.
- **Agents:** deposits and withdrawals happen at one of two usual agents, sometimes elsewhere.
  60% of withdrawals are agent-initiated requests the customer approves with their PIN, which is
  what the withdrawal-request scam abuses.
- **Rhythms:** quiet nights and Sundays, salaries in the last three days of the month, monthly bills.
- **Money constraints:** spending is budgeted so that typical balances stay roughly stable. People
  adjust transfers to what they have, deposit cash before a payment they can't afford, and about
  4% of transactions still fail for insufficient funds.
- **Hard negatives:** legitimate phone changes, people withdrawing money soon after receiving it,
  and mistyped withdrawal requests. All of these look a bit like fraud on purpose.
- **Transfer tax:** 0.2% on transfers and withdrawals (the TTA, in force since January 2022).

Calibration anchors: airtime purchases average 570 FCFA and other merchant payments about 4,073 FCFA
in CEMAC in 2024 ([Business in Cameroon][bic-airtime]); the average Cameroonian mobile money
transaction was about 10,000 FCFA in 2023 ([Business in Cameroon][bic-volume]). The simulation has
no businesses or bulk payments, so its overall average (about 5,800 FCFA) is lower.

## Fraud scenarios

| Scenario | How it works | Naive version | Adaptive version |
|---|---|---|---|
| **Account takeover** | A caller posing as an operator agent obtains the PIN, or the victim's SIM is swapped. The fraudster moves the money to mule accounts, which withdraw it at agents. While the SIM is swapped, the real owner can't transact. | Acts within the hour, at any time of day; takes the whole balance in one transfer to a freshly opened mule, who withdraws everything minutes later. | Waits 2-36 hours and acts in business hours; makes a small airtime purchase first so the new phone has history; takes 50-90% in 2-4 round-number transfers to long-standing accounts; mules withdraw part of it hours later. |
| **Withdrawal request** | A rogue agent sends withdrawal requests to many numbers. People who approve by mistake lose the money; most decline. | 300 requests in two hours, random numbers nationwide, fixed amounts (25,000 or 50,000 FCFA). | 60 requests a day over three days, numbers in the agent's own town, varied amounts. |
| **"Sent by mistake"** | A fake SMS announces a credit; a caller says it was a mistake and asks for it back. The victim sends real money. 30% are also talked into dialling a "refund code" that leaks their PIN, which leads to a takeover. | Ten scammer numbers reused for every victim, round amounts. | A different recipient each time, ordinary-looking amounts. |

Sources for the scam mechanics:
- MTN Cameroon on unsolicited withdrawal requests and fraudulent PIN resets
  ([allAfrica, Sept. 2025][allafrica]).
- Orange Cameroon on fake withdrawal alerts, callers posing as Orange agents, and fake
  "wrong transfer" calls ([Osiris][osiris]).
- The fake airtime SMS and "refund code" variant described by Orange and MTN managers
  ([Stop Blablacam][stopblablacam]).

## Assumptions and limitations

These are modelling choices, not measured facts:

- **Fraud rates are inflated** (about 1 fraudulent transaction in 900-2,000) so there is enough fraud to
  train and evaluate on. Real rates are lower; precision at real-world rates would be lower too.
- **Retired people and farmers are targeted somewhat more often** (weights 2.0 and 1.5) and approve
  rogue withdrawal requests twice as often (8% vs 4%). This is plausible but not measured.
- **Profiles, amounts and frequencies** are set by hand to match the published averages above, not
  fitted to real transaction logs, which are not public.
- **Naive fraudsters act at any hour**, so night-time is a real signal for them; adaptive ones don't.
- Merchants and agents have no tracked balances, like PaySim's merchants.
- The simulated phone numbers and the brand in the game are fictional.

## Labels

Every fraudulent row has a `scenario`, a `strategy` (naive or adaptive), an `attack_id` linking the
rows of one attack, and a `role`:

| Role | Meaning |
|---|---|
| `victim_debit` | Money leaving a victim's account: what a fraud system must stop |
| `mule_cashout` | A mule or scammer withdrawing stolen money: a separate detection problem |
| `attempt` | A rogue withdrawal request the target declined: no money moved |
| `warmup` | The fraudster's small purchase to give a new phone some history |

`accounts.parquet` contains the ground truth (`kind`: customer, mule, scammer, agent...). It must
never be used as a model feature.

[bic-airtime]: https://www.businessincameroon.com/public-management/0505-16124-airtime-accounts-for-65-of-mobile-money-payments-in-cemac-in-2024
[bic-volume]: https://www.businessincameroon.com/finance/2110-15212-cameroon-s-mobile-money-transactions-rise-almost-fourfold-in-five-years-despite-new-taxes
[allafrica]: https://fr.allafrica.com/stories/202509300387.html
[osiris]: https://www.osiris.sn/suite-aux-plaintes-d-arnaques-l-operateur-orange-cameroun-renforce-la-securite.html
[stopblablacam]: https://www.stopblablacam.com/economy-and-politics/2305-680-are-cybercriminals-really-trying-to-steal-the-details-of-mobile-money-account-holders

## Population shift for drift experiments

`--promo-start-day D --promo-share S` adds a handset promotion: from day D, over one week, a share
S of customers get a new phone (an ordinary `DEVICE_CHANGE`). The promotion is drawn from its own
random stream (`seed + 1`), so the world is identical to the same world without it until day D,
transaction for transaction. Stage 6 uses `--promo-start-day 78 --promo-share 0.25` on the mixed
world to check that the drift monitor sees the shift, and what it costs in false alarms.

## Rented-account attacks (stage 7)

`--rented-share S` makes a share S of takeovers and "wrong transfer" scams use *rented*
accounts: ordinary customers' accounts with years of normal history, rented out to the fraudster,
who lets the money sit instead of withdrawing it. Takeovers using them also wait one to three
days, warm up the phone and take small round amounts. This is the blind spot the stage 5 game's
scripted players found. The extra random draw only happens when S > 0, so every earlier world is
unchanged. The Elite model (`python -m momofraud.tiers`) is trained on a world with S = 0.35.
