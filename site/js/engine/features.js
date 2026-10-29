// Behavioural features, computed point-in-time: a line-by-line port of src/momofraud/behaviour.py.
// Every feature uses only what was known before the transaction. features() first, then observe().
// test/parity.test.mjs checks this file against the Python original on hundreds of transactions.

export const HOUR = 3600, DAY = 86400;
export const CAP_HOURS = 24 * 30;
const EWM_ALPHA = 0.1;
const SECURITY_EVENTS = new Set(["SIM_SWAP", "PIN_RESET"]);

export const FEATURE_GROUPS = {
  transaction: ["is_transfer", "is_agent_request", "log_amount", "log_sender_balance_before", "amount_to_balance",
    "empties_account", "log_receiver_balance_before", "receiver_untracked", "amount_is_round", "hour"],
  sender: ["sender_history", "sender_age_days", "hours_since_sender_last_tx", "amount_zscore",
    "sender_out_count_24h", "log_sender_out_amount_24h"],
  device: ["device_new", "device_history", "hours_since_device_first_seen", "hours_since_sim_swap_or_pin_reset",
    "hours_since_device_change"],
  recipient: ["recipient_new", "pair_history"],
  receiver: ["receiver_age_days", "receiver_history", "receiver_in_count_24h", "receiver_distinct_senders_7d",
    "receiver_stranger_share_7d", "receiver_cashout_ratio_7d"],
  agent: ["agent_new_for_sender", "region_mismatch", "agent_requests_1h", "agent_decline_rate_24h"],
};
export const FEATURES = Object.values(FEATURE_GROUPS).flat();

const isNaN_ = (x) => x !== x;
const pk = (a, b) => a + "|" + b;

// A FIFO window with O(1) amortised pops (Python's deque).
class Window {
  constructor(items = []) { this.items = items; this.head = 0; }
  push(item) { this.items.push(item); }
  prune(oldest) {
    while (this.head < this.items.length && this.items[this.head][0] < oldest) this.head++;
    if (this.head > 64 && this.head * 2 > this.items.length) { this.items = this.items.slice(this.head); this.head = 0; }
    return this;
  }
  get length() { return this.items.length - this.head; }
  *[Symbol.iterator]() { for (let i = this.head; i < this.items.length; i++) yield this.items[i]; }
  toJSON() { return this.items.slice(this.head); }
}

function windowOf(map, key) {
  let w = map.get(key);
  if (!w) { w = new Window(); map.set(key, w); }
  return w;
}

const hoursSince = (then, now) => (then === undefined || then === null ? CAP_HOURS : Math.min((now - then) / HOUR, CAP_HOURS));
const ageDays = (opened, account, now) => (opened.has(account) ? Math.max((now - opened.get(account)) / DAY, 0) : 0);
const get0 = (m, k) => m.get(k) ?? 0;

export class FeatureState {
  constructor() {
    this.openedT = new Map(); this.region = new Map();
    this.senderCount = new Map(); this.activity = new Map(); this.lastTxT = new Map();
    this.amountMean = new Map(); this.amountVar = new Map(); this.amountN = new Map();
    this.out24h = new Map(); this.deviceCount = new Map(); this.deviceFirstT = new Map();
    this.pairCount = new Map(); this.lastSecurityT = new Map(); this.lastDeviceChangeT = new Map();
    this.in7d = new Map(); this.cashout7d = new Map(); this.agentRequests24h = new Map();
  }

  observeEvent(t, account, event) {
    if (SECURITY_EVENTS.has(event)) this.lastSecurityT.set(account, t);
    else if (event === "DEVICE_CHANGE") this.lastDeviceChangeT.set(account, t);
  }

  // tx: {t, type, channel, status, amount, sender, receiver, senderBalanceBefore, receiverBalanceBefore, device}
  features(tx) {
    const { t, sender: s, receiver: r, amount } = tx;
    const before = tx.senderBalanceBefore, rBefore = tx.receiverBalanceBefore;
    const isCashOut = tx.type === "CASH_OUT";
    const known = !isNaN_(before);

    const transaction = [
      +(tx.type === "TRANSFER"), +(tx.channel === "AGENT_REQUEST"), Math.log1p(amount),
      known ? Math.log1p(before) : 0, known ? Math.min(amount / Math.max(before, 1), 10) : 0,
      +(known && amount * 1.002 >= before * 0.99),
      isNaN_(rBefore) ? 0 : Math.log1p(rBefore), +isNaN_(rBefore),
      +(amount % 1000 === 0), Math.floor(t / HOUR) % 24,
    ];

    const n = get0(this.amountN, s);
    let zscore = 0;
    if (n >= 3) {
      const sd = Math.sqrt(this.amountVar.get(s)) + 0.25;
      zscore = (Math.log1p(amount) - this.amountMean.get(s)) / sd;
    }
    const out = windowOf(this.out24h, s).prune(t - DAY);
    let outSum = 0;
    for (const [, a] of out) outSum += a;
    const sender = [
      Math.log1p(get0(this.senderCount, s)), ageDays(this.openedT, s, t), hoursSince(this.lastTxT.get(s), t), zscore,
      out.length, Math.log1p(outSum),
    ];

    const dk = pk(s, tx.device);
    const deviceSeen = tx.device ? get0(this.deviceCount, dk) : 1;
    const firstSeen = tx.device ? this.deviceFirstT.get(dk) : undefined;
    const device = [
      +(deviceSeen === 0), Math.log1p(deviceSeen),
      tx.device && firstSeen === undefined ? 0 : hoursSince(firstSeen, t),
      hoursSince(this.lastSecurityT.get(s), t), hoursSince(this.lastDeviceChangeT.get(s), t),
    ];

    const pair = get0(this.pairCount, pk(s, r));
    const recipient = [+(pair === 0), Math.log1p(pair)];

    const incoming = windowOf(this.in7d, r).prune(t - 7 * DAY);
    let received = 0, last24 = 0, strangers = 0;
    const senders = new Set();
    for (const [tt, snd, a, st] of incoming) {
      received += a; senders.add(snd); strangers += st;
      if (tt >= t - DAY) last24++;
    }
    let cashed = 0;
    for (const [, a] of windowOf(this.cashout7d, r).prune(t - 7 * DAY)) cashed += a;
    const receiver = [
      ageDays(this.openedT, r, t), Math.log1p(get0(this.activity, r)), last24, senders.size,
      incoming.length ? strangers / incoming.length : 0, received ? Math.min(cashed / received, 2) : 0,
    ];

    let agent;
    const regionMismatch = +(this.region.get(s) !== this.region.get(r));
    if (isCashOut) {
      const requests = windowOf(this.agentRequests24h, r).prune(t - DAY);
      let lastHour = 0, declined = 0;
      for (const [tt, d] of requests) { if (tt >= t - HOUR) lastHour++; declined += d; }
      agent = [+(pair === 0), regionMismatch, lastHour, declined / (requests.length + 5)];
    } else {
      agent = [0, regionMismatch, 0, 0];
    }
    return [...transaction, ...sender, ...device, ...recipient, ...receiver, ...agent];
  }

  observe(tx) {
    const { t, sender: s, receiver: r, amount } = tx;
    const ok = tx.status === "SUCCESS";
    this.senderCount.set(s, get0(this.senderCount, s) + 1);
    this.activity.set(s, get0(this.activity, s) + 1);
    this.activity.set(r, get0(this.activity, r) + 1);
    this.lastTxT.set(s, t);
    if (tx.device) {
      const dk = pk(s, tx.device);
      this.deviceCount.set(dk, get0(this.deviceCount, dk) + 1);
      if (!this.deviceFirstT.has(dk)) this.deviceFirstT.set(dk, t);
    }
    if (tx.type === "CASH_OUT" && tx.channel === "AGENT_REQUEST") {
      windowOf(this.agentRequests24h, r).push([t, +(tx.status === "DECLINED")]);
    }
    if (!ok) return;
    if (["TRANSFER", "CASH_OUT", "PAYMENT", "BILL"].includes(tx.type)) {
      const x = Math.log1p(amount);
      if (get0(this.amountN, s) === 0) { this.amountMean.set(s, x); this.amountVar.set(s, 0); }
      else {
        const delta = x - this.amountMean.get(s);
        this.amountMean.set(s, this.amountMean.get(s) + EWM_ALPHA * delta);
        this.amountVar.set(s, (1 - EWM_ALPHA) * (this.amountVar.get(s) + EWM_ALPHA * delta * delta));
      }
      this.amountN.set(s, get0(this.amountN, s) + 1);
      windowOf(this.out24h, s).push([t, amount]);
    }
    if (tx.type === "TRANSFER") {
      const stranger = +(get0(this.pairCount, pk(s, r)) === 0 && get0(this.pairCount, pk(r, s)) === 0);
      windowOf(this.in7d, r).push([t, s, amount, stranger]);
    }
    if (tx.type === "CASH_OUT") windowOf(this.cashout7d, s).push([t, amount]);
    this.pairCount.set(pk(s, r), get0(this.pairCount, pk(s, r)) + 1);
  }

  // Load the snapshot written by momofraud.web_export
  static fromSnapshot(w) {
    const st = new FeatureState(), names = w.accounts;
    for (let i = 0; i < w.n; i++) {
      const a = names[i];
      if (w.opened_t[i] !== null) st.openedT.set(a, w.opened_t[i]);
      if (w.region[i] >= 0) st.region.set(a, w.regions[w.region[i]]);
      if (w.sender_count[i]) st.senderCount.set(a, w.sender_count[i]);
      if (w.activity[i]) st.activity.set(a, w.activity[i]);
      if (w.last_tx_t[i] !== null) st.lastTxT.set(a, w.last_tx_t[i]);
      if (w.amount_mean[i] !== null) { st.amountMean.set(a, w.amount_mean[i]); st.amountVar.set(a, w.amount_var[i]); }
      if (w.amount_n[i]) st.amountN.set(a, w.amount_n[i]);
    }
    for (const [i, items] of Object.entries(w.out_24h)) st.out24h.set(names[i], new Window(items.map((e) => e.slice())));
    for (const [i, items] of Object.entries(w.in_7d)) {
      st.in7d.set(names[i], new Window(items.map(([t, snd, a, s]) => [t, names[snd], a, s])));
    }
    for (const [i, items] of Object.entries(w.cashout_7d)) st.cashout7d.set(names[i], new Window(items.map((e) => e.slice())));
    for (const [i, items] of Object.entries(w.agent_requests_24h)) st.agentRequests24h.set(names[i], new Window(items.map((e) => e.slice())));
    for (const [i, d, c, first] of w.devices) {
      st.deviceCount.set(pk(names[i], d), c);
      if (first !== null) st.deviceFirstT.set(pk(names[i], d), first);
    }
    for (let k = 0; k < w.pairs.length; k += 3) st.pairCount.set(pk(names[w.pairs[k]], names[w.pairs[k + 1]]), w.pairs[k + 2]);
    for (const [i, t] of Object.entries(w.last_security_t)) st.lastSecurityT.set(names[i], t);
    for (const [i, t] of Object.entries(w.last_device_change_t)) st.lastDeviceChangeT.set(names[i], t);
    return st;
  }

  pairCountOf(s, r) { return get0(this.pairCount, pk(s, r)); }
}
