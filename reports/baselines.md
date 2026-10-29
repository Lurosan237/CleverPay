# Baseline results

Time-based split: train on days 0-11, validate on 12-13, **test on 14-16**.
Only TRANSFER and CASH_OUT transactions (the only types with fraud).

| Model | Test PR-AUC | Recall @ 90% precision | Precision @ 80% recall | Sparse-tail PR-AUC |
|---|---|---|---|---|
| Rule: transaction empties the sender's account | 0.996 | 97.7% | 100.0% | 0.996 |
| Logistic regression (honest features) | 0.998 | 100.0% | 100.0% | 0.999 |
| LightGBM (honest features) | 0.997 | 99.9% | 99.8% | 1.000 |
| LightGBM, class-weighted (honest features) | 1.000 | 100.0% | 100.0% | 1.000 |
| LightGBM (leaky features, for comparison) | 0.998 | 100.0% | 99.9% | 1.000 |
| LightGBM without the sender's balance | 0.196 | 0.0% | 0.8% | 0.505 |

## Evasion test

The test set's frauds replayed as if each fraudster took only part of the victim's balance,
scored by the honest LightGBM with its alert threshold fixed on validation (90% precision):

| Share of balance taken | 100% | 95% | 90% | 70% | 50% |
|---|---|---|---|---|---|
| Frauds caught | 99.9% | 4.2% | 3.9% | 6.5% | 3.6% |

## What this shows

- PaySim's simulated fraudsters almost always **take the whole balance**. The one-line rule
  above matches the machine-learning models, so a near-perfect score on PaySim mostly means
  the model found that rule.
- Without the sender's balance the best model drops to the last row's PR-AUC: the remaining
  signal is weak.
- The evasion test makes it concrete: leaving even 5% of the balance behind is enough to
  avoid almost every alert. That gap is what the game in this project is built to expose,
  and what the adversarial training stage has to close.

Test set: 523,527 transactions, 830 fraudulent (0.16%).
