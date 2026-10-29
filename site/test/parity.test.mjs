// Replays the operations recorded by `python -m momofraud.web_export` and checks that the
// JavaScript engine computes exactly what the Python code computed: features, scores, SHAP
// values, decisions and balances.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Network, process as processTx } from "../js/engine/network.js";
import { Model } from "../js/engine/model.js";
import { FEATURES } from "../js/engine/features.js";

const load = (p) => JSON.parse(readFileSync(new URL(`../data/${p}`, import.meta.url)));
const world = load("world.json");
const parity = load("parity.json");
const models = Object.fromEntries(["rookie", "analyst", "expert", "elite"].map((k) => [k, new Model(load(`models/${k}.json`))]));

const close = (a, b, tol, what) => {
  const scale = Math.max(1, Math.abs(a), Math.abs(b));
  assert.ok(Math.abs(a - b) <= tol * scale, `${what}: JS ${a} vs Python ${b}`);
};

test("the replay matches Python, operation by operation", () => {
  const net = Network.fromSnapshot(world);
  let scored = 0, explained = 0, reasonsChecked = 0;
  for (const [i, op] of parity.ops.entries()) {
    if (op.op === "event") { net.accountEvent(op.account, op.event, op.device, op.t); continue; }
    if (op.op === "open") { net.openAccount(op.account, op.kind, op.region, op.t); continue; }
    const tx = { type: op.type, channel: op.channel, sender: op.sender, receiver: op.receiver, amount: op.amount,
      device: op.device, t: op.t };
    if (op.expected) {
      const record = net.build(tx.type, tx.channel, tx.sender, tx.receiver, tx.amount, tx.device, tx.t);
      const features = net.state.features(record);
      FEATURES.forEach((f, k) => close(features[k], op.expected.features[k], 1e-12, `op ${i} feature ${f}`));
      for (const [key, exp] of Object.entries(op.expected.models)) {
        const model = models[key];
        close(model.probability(features), exp.score, 1e-10, `op ${i} ${key} score`);
        const e = model.explain(features);
        e.modelPhi.forEach((v, k) => close(v, exp.shap[k], 1e-8, `op ${i} ${key} SHAP ${model.features[k]}`));
        close(e.raw, Math.log(exp.score / (1 - exp.score)), 1e-8, `op ${i} ${key} SHAP additivity`);
        explained++;
      }
      scored++;
    }
    const out = processTx(net, models.expert, tx, { customerDeclined: op.declined, overrideReview: op.override, lang: op.lang, explain: op.explain });
    assert.equal(out.decision, op.decision, `op ${i} decision`);
    assert.deepEqual(out.reasons.map((r) => r.text), op.reasons, `op ${i} reasons (${op.lang})`);
    reasonsChecked += op.reasons.length;
    assert.equal(out.status, op.status, `op ${i} status`);
    if (op.balance_after !== null && op.balance_after !== undefined) close(net.balance.get(op.sender), op.balance_after, 1e-12, `op ${i} balance`);
  }
  for (const [a, b] of Object.entries(parity.final_balances)) close(net.balance.get(a), b, 1e-12, `final balance ${a}`);
  assert.ok(scored > 100, `only ${scored} scored transactions in the script`);
  console.log(`  ${parity.ops.length} operations, ${scored} scored, ${explained} SHAP explanations, ${reasonsChecked} reasons: identical`);
});

test("explanations add up: bias + SHAP = raw score", () => {
  const net = Network.fromSnapshot(world);
  const [s] = net.customers();
  const tx = { type: "TRANSFER", channel: "USSD", sender: s, receiver: net.customers()[5], amount: 5000, device: "D-test", t: net.now + 60 };
  const record = net.build(tx.type, tx.channel, tx.sender, tx.receiver, tx.amount, tx.device, tx.t);
  const f = net.state.features(record);
  for (const model of Object.values(models)) {
    const e = model.explain(f);
    close(e.bias + e.contributions.reduce((a, b) => a + b, 0), model.raw(f), 1e-9, `${model.key} additivity`);
  }
});
