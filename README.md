# MoMo Fraud Game

*Can you scam the model?* A mobile money fraud detector, served as a game where you play
the fraudster.

> **Try it:** https://lurosan237.github.io/CleverPay/ (Model Lab, the Launch Day game and the
> classic game, all running in your browser).
>
> **Status:** all seven stages are done: PaySim analysis, simulator, behavioural model, scoring API,
> the game, monitoring with Docker and CI, and the public website. See the roadmap below.

> **CleverPay**, the mobile money brand in the game, is fictional. It is not affiliated with any
> real company, and every account, person and amount in this project is simulated.

## Why this project

Most fraud-detection portfolios train a model on a public dataset, report a 0.99 score and stop.
This project starts from that score and asks what it is worth against a fraudster who adapts.

The data is [PaySim](https://www.kaggle.com/datasets/ealaxi/paysim1): 6.4 million mobile money
transactions from a simulator calibrated on real logs from an African mobile money service.
That is the context these models would actually run in: mobile money is how most people in
Cameroon send and receive money.

## Stage 1 findings

Full numbers: [reports/baselines.md](reports/baselines.md).

1. **A near-perfect score is easy, and almost meaningless.** A one-line rule, "flag any transfer
   that empties the sender's account", catches 97.7% of fraud at 99.9% precision. LightGBM and
   logistic regression do no better: PaySim's simulated fraudsters always take everything.
2. **Two kinds of leakage had to be removed first.**
   - *Balances after the transaction*: 90% of legitimate PaySim transactions have balances that
     don't add up and fraudulent ones almost never do, a simulator bookkeeping artifact.
     These values also aren't known when a transaction is approved.
   - *Time of day*: the simulator injects about 11 frauds per hour however quiet the network is,
     so at 4 a.m. over half of all transactions are fraud. A model that learns "night = fraud"
     looks great here and would fail on real traffic.
3. **The model breaks the moment the fraudster adapts.** Replaying the test frauds with the
   fraudster leaving just 5% of the balance behind, the model's catch rate falls from
   **99.9% to 4.2%**.

That last result is the point of the game: put an adaptive human in the fraudster's seat, and
use what they discover to train a model that holds up.

## Stage 2: a simulator with Cameroon-style scams

PaySim can show the problem but not support the fix: 99.85% of its senders appear only once, so
there is no history to learn from. So I built a simulator: 20,000 account holders over 90 days
(about 5 million transactions), with five user profiles, social circles, agents, salaries and
bills, calibrated to published CEMAC figures. Every balance follows on exactly from the previous
transaction, which a test checks for every row.

Three scams reported in Cameroon, each with a naive and an adaptive fraudster:

- **Account takeover:** a fake "operator agent" call or a SIM swap, then the money goes to mules.
- **Withdrawal requests:** a rogue agent sends hundreds of requests; a few people approve by mistake.
- **"Sent by mistake":** a fake SMS, then the victim "refunds" money they never received.

Design, sources and assumptions: [docs/simulator.md](docs/simulator.md).

A model that sees only the transaction itself (like the stage 1 model), trained on a world of naive
fraudsters, then tested on both worlds ([report](reports/behaviour.md)):

| Victim transactions caught | Naive fraudsters | Adaptive fraudsters |
|---|---|---|
| Account takeover | 98% | 0% |
| Withdrawal request | 48% | 2% |
| "Sent by mistake" | 3% | 0% |

## Stage 3: behavioural features

Catching adaptive fraud needs history: has this person ever paid this number, how long has this
phone been on the account, was the PIN just reset, is this agent sending requests that people keep
declining. 33 features in six groups (transaction, sender, device, recipient, receiver, agent),
[defined here](src/momofraud/behaviour.py).

**No peeking at the future.** Every feature is computed point-in-time by a single `FeatureState` that
replays history and computes a transaction's features *before* adding it to its memory. A test cuts
a world off at day 7, recomputes, and checks every earlier transaction gets identical features. The
same class will score live transactions in the API, so training and serving can't drift apart.
It takes about 16 µs per transaction.

Results on days 75-89 of the adaptive world, threshold set for 90% precision on the training world's
validation days ([full report](reports/behaviour.md)):

| | Transaction only, trained on naive | Behavioural, trained on naive | Behavioural, trained on mixed |
|---|---|---|---|
| Account takeover | 0% | 0% | 99% |
| Withdrawal request | 2% | 33% | 76% |
| "Sent by mistake" | 0% | 0% | 5% |
| **All victim transactions** | **0.2%** | **4%** | **76%** |
| Precision of alerts | 7% | 25% | 90% |
| False alarms per 10,000 legitimate | 0.7 | 2.8 | 1.9 |

What I learned:

1. **Better features are not enough on their own.** Trained only on naive fraud, the behavioural
   model still misses adaptive fraud (4%). It needs examples of fraud that tries to blend in, which
   is what the game will supply.
2. **Adversarial training closes one gap and exposes the next.** The mixed-trained model leaned on
   "how new is the phone": a fraudster who used their phone on the account for a month first would
   get through every time. Adding synthetic copies of training takeovers with an established phone
   raised that case from 0% to 99% caught. The weak point then moves to fraudsters who also wait a
   month after the PIN reset (35% caught): possible after a phished PIN, impossible after a SIM swap,
   since the owner gets their SIM back within days, and very costly either way.
3. **"Sent by mistake" stays hard (about 5%).** The victim authorises the payment from their own
   phone, so the only clues are on the receiving side. In real systems this kind of fraud is also the
   hardest to stop; it needs signals the data doesn't have, such as other victims reporting the number.
4. **The simulator had to get more realistic first.** In the first run, only fraudsters ever reset
   PINs or swapped SIMs, which made those events an unrealistically clean signal. Legitimate PIN resets
   (2% of users a month) and SIM replacements were added and everything was regenerated.

The adversarially trained model catches as much as the plain one (76% at 90% precision) and is far
harder to fool with an established phone, so it is the one the API and the game will use.

**PyTorch comparison.** A two-layer neural network on the same features comes close (PR-AUC 0.829 vs
0.866, 73% vs 76% of victim transactions caught) but trains twice as slowly and catches fewer
withdrawal-request scams. On tabular data like this, gradient-boosted trees are usually the stronger
choice, and LightGBM stays the main model ([comparison](reports/mlp.md)).

## Stage 4: a scoring API that explains itself

`uvicorn momofraud.serving.api:app` starts a FastAPI service on a simulated network of 3,000 people
(interactive docs at `/docs`). `POST /v1/transactions` scores a transfer or withdrawal against the
network's history, decides, explains, and applies the outcome:

- **approve**: the money moves.
- **review** (50% precision threshold): the transaction is held. In a real system this is a warning
  and a confirmation step; it catches 37% of "sent by mistake" scams, against 4% for blocking alone,
  at 15 extra checks per 10,000 legitimate transactions.
- **block** (90% precision threshold): the transaction is stopped.

A SIM-swap takeover, as the API sees it:

```json
POST /v1/transactions
{"type": "TRANSFER", "sender": "622767125", "receiver": "690334248", "amount": 72899,
 "device": "D-fraudster", "lang": "en"}

{
  "decision": "block",
  "status": "BLOCKED",
  "score": 0.99841,
  "reasons": [
    {"feature": "hours_since_sim_swap_or_pin_reset", "text": "PIN reset or SIM swap 1 min ago", "contribution": 6.678},
    {"feature": "receiver_age_days", "text": "Recipient account opened 1 min ago", "contribution": 3.416},
    {"feature": "recipient_new", "text": "First payment to this number", "contribution": 1.58}
  ],
  ...
}
```

With `"lang": "fr"`: *« Code PIN réinitialisé ou carte SIM changée il y a 1 min »*.
`python -m momofraud.serving.demo` plays out a normal payment and the three scams.

Design decisions:

- **One feature engine.** The API scores with the same `FeatureState` used for training, so features
  can't drift between training and serving.
- **Exact explanations without extra dependencies.** LightGBM computes TreeSHAP natively
  (`pred_contrib=True`); a test checks the contributions add up exactly to the model's score. Each
  reason is written from the feature's actual value ("1 min ago", "opened 10 min ago").
- **Explain only what needs explaining.** SHAP takes about 4-6 ms on this 482-tree model, against
  under 0.2 ms for the prediction, so it runs for review and block decisions (about 3% of traffic) or on
  request. Approvals stay fast.
- **One process owns the state.** Endpoints run one at a time on the event loop, so two requests can
  never update the same account's history at once. Scaling past one CPU core would need the state in
  a shared store such as Redis.

### Latency: a real number

Measured over HTTP with a realistic mix (90% payments to known contacts, 8% to strangers, 2%
takeovers), one uvicorn worker on one CPU core of a 2.8 GHz Xeon ([full report](reports/latency.md)):

| Concurrent clients | p50 | p95 | p99 | Throughput |
|---|---|---|---|---|
| 1 | 1.0 ms | 2.8 ms | 6.9 ms | 750 req/s |
| 4 | 2.0 ms | 7.4 ms | 10.2 ms | 1,330 req/s |
| 16 | 11.4 ms | 22.5 ms | 31.3 ms | 1,230 req/s |

Approved transactions: p50 1.0 ms, p95 1.8 ms. Flagged and explained: p50 6.1 ms. Inside the server,
features take about 0.09 ms and the model 0.17 ms. One core saturates at about 1,200-1,300
transactions per second; beyond that, extra clients queue.

The first version of this benchmark showed throughput *falling* as concurrency rose (390 down to
120 requests/s), which made no sense for a server that was barely busy. The load generator was the
problem: on a 2-core machine, the Python HTTP client was competing with the server for the CPU.
Pinning the server and the client to separate cores and switching the client to `aiohttp` gave
stable numbers: two runs agree within 10%.

## Stage 5: the game

`uvicorn momofraud.serving.api:app`, then open http://127.0.0.1:8000/game.

You play the scammer against the stage 4 model, on a phone-style screen. A "fraud desk" panel next
to it shows the score of every transaction you attempt, where it falls against the review and block
thresholds, and the reasons in plain English or French. Three missions, one per scam:

| Mission | You... | You lose when |
|---|---|---|
| Account takeover | have a victim's PIN (fake agent call: 5 days before they notice; SIM swap: 36 hours). Move money to numbers you open (500 FCFA) or aged accounts you rent (10,000 FCFA). | one block freezes the account; two reviews (the real owner refuses) do too |
| Rogue agent | send batches of withdrawal requests; about 5% of customers approve by mistake | three blocks |
| "Sent by mistake" | call people claiming you sent them money; 20-40% believe you, depending on the amount. A review shows the victim a warning, and 70% then cancel | three blocks |

The end screen shows what gave you away, how real people protect themselves against that scam,
and a leaderboard ranked by profit (what you stole minus what your numbers cost).

**Design decisions**

- **Same decision path as the API.** Scoring, deciding and applying a transaction live in one
  function (`serving/service.py`) that both the API and the game call. The game cannot be easier or
  harder than production.
- **Each game gets its own copy of the network**, so players don't share a clock, can wait days
  without moving anyone else's time, and never change the API's state. Copying 3,000 people takes
  about a second, done off the event loop.
- **Every scored attempt is logged with its 33 features** (`data/game/attempts.jsonl`). What players
  get past the model is exactly the data a retraining needs.
- **Costs make it a game.** Without them, the best move is always "rent ten accounts".

**What scripted players found** ([full report](reports/game_strategies.md)): eight strategies,
six games each.

| Strategy | Mean profit | Caught | Never flagged |
|---|---|---|---|
| Takeover: whole balance at once | -500 | 100% | 0% |
| Takeover: wait 3 days, small amounts to a new number | -500 | 100% | 0% |
| Takeover: wait 3 days, small amounts to a rented account | 83,667 | 0% | 100% |
| Rogue agent: 100 requests in 10 minutes | 4,167 | 100% | 0% |
| "Sent by mistake": fresh numbers | -1,500 | 100% | 0% |
| "Sent by mistake": rented numbers | 59,500 | 0% | 100% |

The model is very good at what it was trained on (new receiving accounts, request floods) and
blind to one thing: **money going to an account with years of ordinary history that doesn't cash it
out straight away**. In the simulator, even the adaptive fraudsters' "aged" mules received from many
strangers and withdrew quickly, so the model learned to judge the *receiver's behaviour*. A
genuinely rented account has none of that. A real attacker would rent accounts exactly like this,
so the fix is to put them in the simulator (and use the logged game attempts) for the next
training run, not to hard-code a rule.

## Stage 6: drift monitoring, Docker, CI

### Drift monitoring

A model tuned on last quarter's traffic quietly gets worse when the traffic changes. The API keeps
the last 5,000 scored transactions and compares them with the traffic the model was tuned on
(`GET /v1/monitoring`). None of the checks needs fraud labels, so they work the same day:

- **PSI per feature** (Population Stability Index), with the usual 0.1 / 0.25 levels.
- **Rare-event jumps.** PSI is nearly blind to a rare value becoming much more common, and rare
  values (a new phone, a first payment to someone) are what fraud features are made of. Each bin is
  also tested on its own: flagged when it is at least twice as common as in the reference and more
  than 5 standard errors from chance.
- **Score PSI**, because if the score distribution moves, the thresholds stop meaning 90% and 50%
  precision.
- **Alert rates**, reported apart from drift: a jump in blocks is more often an attack than a
  change in customers.

Lifetime counters (an account's number of transactions, its age...) are reported but don't raise
the status: they grow as accounts age, and in a 90-day simulation that starts empty they always
do. The first version of the monitor didn't know that and flagged "drift" on every test day of the
control world.

**Does it work?** Three worlds, identical until day 75, each day compared with the reference
(the validation days) ([full report](reports/drift.md)):

| World | What changes | Days flagged as drift (75-89) |
|---|---|---|
| mixed (control) | nothing | none |
| adaptive | fraudsters switch to adaptive tactics | none |
| promo | from day 78, a phone promotion: a quarter of customers get a new phone within a week | 78-86, from the first day |

In the promo world, transactions from a phone new to the account go from 0.06% to up to 2.3% of
traffic. PSI for that feature never exceeds 0.1, so PSI alone would have missed it; the rare-event
check flags it on day 78. It matters: false alarms on honest customers nearly double on days 81-82
(30 per 10,000 instead of 17), while the overall review rate moves too little to notice.

The adaptive world is the honest limit: when *fraudsters* change tactics, customers don't, and
fraud is 0.1% of traffic, so no input monitor sees it. That needs labels (confirmed fraud, weeks
later) or the game's logged attempts, which is one more reason the game logs them.

The promo world reuses the mixed world's random stream and draws the promotion from a separate
one, so everything before day 78 is identical, transaction for transaction (a test checks this).
The difference after day 78 is the promotion and nothing else.

### Docker

```powershell
docker compose up --build        # then open http://localhost:8000/game
```

The image holds only what serving needs: the code, the model and its drift reference (no data, no
tests). It runs as a non-root user, has a health check, installs dependencies before copying code
so rebuilds are fast, and keeps game attempts in a volume. One uvicorn worker on purpose: the
network state lives in that process.

### CI

GitHub Actions (`.github/workflows/ci.yml`) on every push and pull request: ruff; the tests on
Python 3.10 and 3.12 from a clean checkout (no dataset needed: tests build small simulated worlds);
then the Docker image is built, started, and smoke-tested over HTTP (scoring, the game,
monitoring, and that it doesn't run as root).

## Stage 7: a website anyone can open

Free Python hosting in 2026 means a server that sleeps and takes a minute to wake up. So the
website runs **entirely in the visitor's browser**, as static files on GitHub Pages:

- **The engine is ported to JavaScript**: the point-in-time feature state, LightGBM tree
  evaluation, exact TreeSHAP, the reason sentences (EN/FR) and the decision path.
  `python -m momofraud.web_export` writes the models as flat trees, a snapshot of a simulated
  network, and a script of 400+ operations played through the Python code. `npm test` (in
  `site/`) replays it in JavaScript and checks every feature, score, SHAP value, decision,
  balance and sentence: they match Python to 1e-12 on features and 1e-10 on scores. This is the
  training/serving skew problem, solved by a test instead of by hope; CI runs it, and the site is
  only published if it passes.
- **Model Lab** (`lab.html`): build a transaction (who receives it, amount, SIM swap or PIN reset
  and how long ago, which phone, time of day, mule-like receivers, agent request floods) and watch
  four models score it live, with a SHAP waterfall and the sentences a support agent would read.
- **Launch Day** (`play.html`): the game, redesigned to be fun (below).
- **Classic** (`classic.html`): the stage 5 game, unchanged, its Python engine ported so it runs
  without a server.

### Four models, four difficulty levels

The game's difficulty is not a slider: each level is a separately trained model that knows
more ([report](reports/tiers.md), `python -m momofraud.tiers`).

| Level | Knows | Fraud caught (adaptive world) | Rented-account attacks caught | False alarms / 10k |
|---|---|---|---|---|
| Rookie | the transaction alone | 0% | 0% | 4.4 |
| Analyst | + sender's habits, past payments to this person | 45% | 11% | 12.1 |
| Expert | all 33 features (the production model) | 85% | 27% | 15.1 |
| Elite | the same, retrained on rented-account attacks | 84% | 82% | 20.7 |

Elite closes the loop that stage 5 opened. The scripted players found the production model was
blind to money sent to rented old accounts. That attack was added to the simulator
(`--rented-share`, off by default so earlier worlds don't change), a new world was simulated,
and the model retrained. Elite catches 82% of rented-account attacks instead of 27%, with the
same recall on everything else. The price is 37% more false alarms, which is the kind of
trade-off a fraud team has to choose knowingly.

### Making the game fun

Design notes from heist and stealth games (Invisible Inc.'s alarm system in particular) and
risk/reward design: constant visible pressure, predictable consequences, and losses the player
can explain.

- **Five chapters, two storylines.** Red team (CleverPay hires you to break the model before
  launch; your exploits become findings) or Ghost Network (a fictional crew; it ends with the
  network dismantled by a model that learned its tricks). Same mechanics, both in English and
  French.
- **Security level.** Reviews and blocks raise it; each level changes the rules (reviews come
  sooner, reviewed numbers are blacklisted, blocks come sooner, then lockdown). It cools if you
  lie low for 12 hours: patience against time.
- **Money and choices.** A budget carried across chapters, SIM cards, a rental market of old
  accounts (town, age and price differ, and the owner keeps a cut), call scripts with visible
  odds, an agent's till you can abandon for a fresh one.
- **Inside tips.** Pay to see what the model *would* say about your next move: a probe of the
  real model, shown with its SHAP factors. The fraud desk always explains every flag.
- **Patch Day.** In week 4 the model is upgraded to the next level, retrained on what players
  found. Your best trick may stop working. That is how fraud detection works.
- **Findings.** Anything risky that gets through is logged as a blind spot, with the signals
  the model let pass. The final report lists them, and every scored attempt can be downloaded as
  JSON for retraining.
- Random events, a rival, stars per chapter, sound, portraits drawn in SVG, a mercy rule (move on
  with zero stars after a failed chapter).

Balancing used scripted bots against every chapter and level (the same idea as stage 5's
strategies). They showed, for example, that warming up a stolen phone with an airtime purchase
*raises* the score: the simulator's adaptive fraudsters always do it, so the model learned it as
a signature. And Elite cannot be beaten on a pure account takeover, which is why the finale lets
you use every method.

## Method

- **Time-based split**: train on days 0-11, validate on days 12-13, test once on days 14-16.
  Never a random split: the model is always tested on transactions that come after the ones it
  learned from. Days 17-30 have a very different fraud rate and are kept as a stress test.
- **Metrics for rare events**: PR-AUC, recall at 90% precision, precision at 80% recall.
  Accuracy is useless at a 0.16% fraud rate.
- **Alert thresholds** are chosen on the validation set, never on the test set.

## Roadmap

- [x] Stage 1: data pipeline, leakage analysis, baselines, evasion test
- [x] Stage 2: Cameroon-style simulator with recurring users and three documented scams,
      naive and adaptive
- [x] Stage 3: point-in-time behavioural features, adversarial training, PyTorch baseline
- [x] Stage 4: FastAPI scoring service with SHAP explanations in English and French; HTTP latency benchmark
- [x] Stage 5: the game: three missions against the live model, EN/FR, attempt logging, scripted
      strategies that expose the model's blind spot
- [x] Stage 6: drift monitoring (PSI, rare-event jumps, score and alert rates) tested on a
      controlled population shift; Docker image; GitHub Actions CI
- [x] Stage 7: public website: JavaScript engine with parity tests, Model Lab, Launch Day
      (two storylines, four model levels, Patch Day), classic game; GitHub Pages

## Running it

Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

1. Download the dataset from [Kaggle](https://www.kaggle.com/datasets/ealaxi/paysim1) and put
   the zip in `data/raw/`.
2. Build the parquet file (about 1 minute): `python -m momofraud.data`
3. Reproduce the baselines (about 2 minutes, 8 GB RAM recommended): `python -m momofraud.baselines`

Simulator (no download needed; about 1 minute and 2.5 GB of RAM per world):

```powershell
python -m momofraud.sim --name naive --adaptive-share 0
python -m momofraud.sim --name adaptive --adaptive-share 1
python -m momofraud.simreport
```

Use `--users 2000 --days 30` for a quick small run.

Stage 3 (after simulating the naive, mixed and adaptive worlds):

```powershell
python -m momofraud.sim --name mixed --adaptive-share 0.5
python -m momofraud.featurestore    # about 2 minutes per world
python -m momofraud.experiments     # about 10 minutes
pip install torch
python -m momofraud.mlp             # optional PyTorch comparison
```

Stage 4:

```powershell
python -m momofraud.train                    # exports models/ (already included in the repo)
uvicorn momofraud.serving.api:app            # then open http://127.0.0.1:8000/docs
python -m momofraud.serving.demo --lang fr   # the four scenes, in French
python -m momofraud.serving.bench            # latency benchmark (about 30 s)
```

Stage 5:

```powershell
uvicorn momofraud.serving.api:app            # then open http://127.0.0.1:8000/game
python -m momofraud.serving.strategies       # scripted players (about 2 minutes)
```

Set `MOMO_GAME_LOG=off` to stop logging game attempts.

Stage 6:

```powershell
python -m momofraud.sim --adaptive-share 0.5 --promo-start-day 78 --promo-share 0.25 --name promo
python -m momofraud.featurestore promo
python -m momofraud.monitoring reference     # models/drift_reference.json (already in the repo)
python -m momofraud.monitoring report        # reports/drift.md
docker compose up --build                    # the API and the game in a container
```

Stage 7 (the website):

```powershell
python -m momofraud.sim --adaptive-share 0.5 --rented-share 0.35 --name patched
python -m momofraud.featurestore patched
python -m momofraud.tiers                    # the four difficulty models
python -m momofraud.web_export               # site/data/: models, network snapshot, parity script
cd site; npm test                            # JavaScript engine == Python engine
python -m http.server -d site 8000           # then open http://localhost:8000
```

Tests: `pytest`

## Project layout

```
src/momofraud/
  data.py        PaySim zip -> typed parquet
  features.py    feature definitions and the leakage policy
  split.py       time-based split
  metrics.py     PR-AUC, recall at fixed precision, threshold selection
  baselines.py   experiments, evasion test, report
  sim/           the simulator: config, population, legit traffic, fraud scenarios, engine
  simreport.py   simulator calibration checks
  behaviour.py   point-in-time behavioural features (FeatureState)
  featurestore.py  computes and caches features for each world
  experiments.py stage 3 models, ablation, adversarial training, sensitivity
  mlp.py         PyTorch baseline
  train.py       exports the production model and its thresholds
  monitoring.py  drift checks, the live monitor and the drift report
  tiers.py       the four difficulty models and their metrics
  web_export.py  models, network snapshot and parity script for the website
  serving/       the API: network state, model + SHAP, reasons (EN/FR), FastAPI app, demo, benchmark,
                 and the game (service.py shared decision path, game.py engine, gameapi.py routes,
                 static/game.html page, strategies.py scripted players)
models/          the exported model (1.7 MB), its metadata and drift reference
site/            the website: js/engine (the JavaScript port), lab/, game/ (Launch Day), classic/,
                 test/ (parity and game tests)
.github/         CI and website workflows
Dockerfile, compose.yaml
docs/            design notes
reports/         generated results
tests/
```

## License

MIT
