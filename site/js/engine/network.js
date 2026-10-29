// The live state transactions are scored against. Port of src/momofraud/serving/network.py
// and service.py: the same decision path as the Python API.
import { FeatureState, FEATURES } from "./features.js";
import { reasons } from "./reasons.js";

export const TRANSFER_TAX = 0.002;
const TAXED = new Set(["TRANSFER", "CASH_OUT"]);
export const SCORED_TYPES = new Set(["TRANSFER", "CASH_OUT"]);
const KINDS = ["customer", "agent", "merchant", "external"];

export class NetworkError extends Error {
  constructor(message, status = 422) { super(message); this.status = status; }
}

export class Network {
  static fromSnapshot(w) {
    const net = new Network();
    net.snapshotSource = w;
    net.start = new Date(w.start + "Z");
    net.state = FeatureState.fromSnapshot(w);
    net.kind = new Map(); net.region = new Map(); net.balance = new Map(); net.device = new Map();
    net.recent = new Map();
    w.accounts.forEach((a, i) => {
      net.kind.set(a, KINDS[w.kind[i]]);
      if (w.region[i] >= 0) net.region.set(a, w.regions[w.region[i]]);
      if (w.balance[i] !== null) net.balance.set(a, w.balance[i]);
      if (w.device[i] !== null) net.device.set(a, w.device[i]);
    });
    for (const [i, items] of Object.entries(w.recent)) net.recent.set(w.accounts[i], items.map((e) => ({ ...e })));
    net.now = w.now; net.nextId = w.next_id;
    net.regions = w.regions;
    return net;
  }

  // a deep copy, so a game never changes the shared world
  clone() { return Network.fromSnapshot(this.snapshotSource); }

  timestamp(t) {
    return new Date(this.start.getTime() + t * 1000).toISOString().slice(0, 19);
  }

  require(account, role) {
    if (!this.kind.has(account)) throw new NetworkError(`unknown ${role} account: ${account}`, 404);
  }

  openAccount(account, kind, region, t) {
    if (this.kind.has(account)) throw new NetworkError(`account ${account} already exists`, 409);
    this.kind.set(account, kind); this.region.set(account, region);
    this.state.openedT.set(account, t); this.state.region.set(account, region);
    if (kind === "customer") this.balance.set(account, 0);
    this.now = Math.max(this.now, t);
  }

  accountEvent(account, event, device, t) {
    this.require(account, "event");
    this.state.observeEvent(t, account, event);
    if (device) this.device.set(account, device);
    this.now = Math.max(this.now, t);
  }

  build(type, channel, sender, receiver, amount, device, t) {
    this.require(sender, "sender"); this.require(receiver, "receiver");
    if (sender === receiver) throw new NetworkError("sender and receiver must be different accounts");
    return {
      t, type, channel, status: "SUCCESS", amount: Number(amount), sender, receiver,
      senderBalanceBefore: this.balance.has(sender) ? this.balance.get(sender) : NaN,
      receiverBalanceBefore: this.balance.has(receiver) ? this.balance.get(receiver) : NaN,
      device: device || null,
    };
  }

  fee(record) { return TAXED.has(record.type) ? Math.ceil(record.amount * TRANSFER_TAX) : 0; }

  apply(record, status) {
    const fee = this.fee(record);
    const tracked = this.balance.has(record.sender);
    if (status === "SUCCESS" && tracked && this.balance.get(record.sender) < record.amount + fee) status = "FAILED_FUNDS";
    record.status = status;
    this.state.observe(record);
    if (status === "SUCCESS") {
      if (tracked) this.balance.set(record.sender, this.balance.get(record.sender) - (record.amount + fee));
      if (this.balance.has(record.receiver)) this.balance.set(record.receiver, this.balance.get(record.receiver) + record.amount);
    }
    if (record.device) this.device.set(record.sender, record.device);
    this.nextId += 1;
    this.now = Math.max(this.now, record.t);
    return status;
  }

  newNumber(rng = Math.random) {
    for (;;) {
      const n = "69" + String(Math.floor(rng() * 1e7)).padStart(7, "0");
      if (!this.kind.has(n)) return n;
    }
  }

  customers() { return [...this.kind].filter(([, k]) => k === "customer").map(([a]) => a); }
  agents() { return [...this.kind].filter(([, k]) => k === "agent").map(([a]) => a); }
}

// Score, decide, explain and apply one transaction: the same path as service.process in Python.
// model: a Model (model.js). options: {customerDeclined, overrideReview, explain, lang, commit, thresholds}
export function process(net, model, tx, options = {}) {
  const { customerDeclined = false, overrideReview = false, explain = false, lang = "en", commit = true } = options;
  const record = net.build(tx.type, tx.channel || "USSD", tx.sender, tx.receiver, tx.amount, tx.device, tx.t);
  const out = { timestamp: net.timestamp(tx.t), score: null, reasons: [], contributions: null, features: null };
  if (customerDeclined) {
    if (!(tx.type === "CASH_OUT" && tx.channel === "AGENT_REQUEST")) {
      throw new NetworkError("customer_declined only applies to CASH_OUT with channel AGENT_REQUEST");
    }
    return { ...out, decision: "declined_by_customer", status: commit ? net.apply(record, "DECLINED") : "NOT_COMMITTED" };
  }
  if (!SCORED_TYPES.has(tx.type)) {
    return { ...out, decision: "not_scored", status: commit ? net.apply(record, "SUCCESS") : "NOT_COMMITTED" };
  }
  const features = net.state.features(record);
  const probability = model.probability(features);
  const block = options.thresholds?.block ?? model.block, review = options.thresholds?.review ?? model.review;
  const decision = probability >= block ? "block" : probability >= review ? "review" : "approve";
  let why = [], contributions = null;
  if (decision !== "approve" || explain) {
    const e = model.explain(features);
    contributions = e.contributions;
    why = reasons(e.contributions, features, lang);
  }
  let status = "NOT_COMMITTED";
  if (commit) {
    status = net.apply(record, decision === "block" ? "BLOCKED"
      : decision === "review" && !overrideReview ? "HELD_FOR_REVIEW" : "SUCCESS");
  }
  return { ...out, decision, status, score: probability, reasons: why, contributions, features,
    senderBalance: net.balance.get(tx.sender) ?? null };
}

export { FEATURES };
