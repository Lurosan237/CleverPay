// Launch Day: the game rules. No DOM here, so the rules can be tested in Node.
//
// Every money movement goes through the real decision path (engine/network.js `process`), scored
// by one of the four real models. The game adds what makes it a game: a campaign of chapters,
// a budget, a security level that reacts to what the model flags, intel you can buy to probe
// the model, random events, and a log of the model's blind spots you discovered.
import { Network, process } from "../engine/network.js";
import { reasons } from "../engine/reasons.js";
import { FEATURES } from "../engine/features.js";

export const MIN = 60, HOUR = 3600, DAY = 86400;
export const TIER_ORDER = ["rookie", "analyst", "expert", "elite"];
export const COSTS = { sim: 500, rent: 6000, rentCut: 0.15, intel: 2000, till: 8000, airtime: 500 };
export const START_CASH = 20000;
export const NAMES = {
  f: ["Mama Ngono", "Tantine Clarisse", "Esther", "Hawa", "Ruth", "Brigitte", "Amina", "Solange", "Mireille", "Aïssatou"],
  m: ["Papa Bello", "Grand-frère Serge", "Jean-Paul", "Moussa", "Didier", "Oumarou", "Emmanuel", "Hamadou", "Thierry", "Achille"],
};
export const PERSONAS = {
  retired: { trust: 0.48, label: "retired" }, trader: { trust: 0.32, label: "trader" }, student: { trust: 0.26, label: "student" },
  teacher: { trust: 0.36, label: "teacher" },
};
export const SCRIPTS = {
  apologetic: { belief: 1.0, report: 0.04, cancel: 0.7, leak: 0.0 },
  urgent: { belief: 1.3, report: 0.09, cancel: 0.55, leak: 0.05 },
  official: { belief: 1.5, report: 0.16, cancel: 0.5, leak: 0.35 },
};
export const HEAT_LEVELS = 4;   // 0..4, three pips each

// -- chapters ---------------------------------------------------------------------------------------
export const CHAPTERS = [
  { id: "refund", kinds: ["refund"], goal: 25000, days: 3, rival: 31000 },
  { id: "requests", kinds: ["requests"], goal: 40000, days: 2, rival: 52000 },
  { id: "takeover", kinds: ["takeover"], goal: 60000, days: 5, rival: 74000, victimBalance: [150000, 400000] },
  { id: "patch", kinds: ["refund", "takeover"], goal: 40000, days: 4, rival: 52000, patch: true, leak: true },
  { id: "finale", kinds: ["refund", "requests", "takeover"], goal: 70000, days: 4, rival: 90000, leak: true, ownerChecks: true },
];

// -- campaign --------------------------------------------------------------------------------------
export class Campaign {
  constructor({ storyline = "redteam", difficulty = "expert", seed = Date.now() % 1e9 } = {}) {
    this.storyline = storyline;
    this.difficulty = difficulty;
    this.seed = seed;
    this.chapterIndex = 0;
    this.cash = START_CASH;
    this.results = [];          // per chapter: {stars, profit, outcome, beatRival}
    this.findings = [];         // blind spots discovered
    this.attempts = [];         // every scored attempt, for retraining
    this.patched = false;
  }

  modelKey(index = this.chapterIndex) {
    const base = TIER_ORDER.indexOf(this.difficulty);
    return CHAPTERS[index].patch || index > 3 ? TIER_ORDER[Math.min(base + 1, 3)] : TIER_ORDER[base];
  }
  // At Elite, "patch v2" can't upgrade the model, so the operators tighten the thresholds instead
  thresholdTighten(index = this.chapterIndex) {
    return (CHAPTERS[index].patch || index > 3) && this.difficulty === "elite" ? 0.8 : 1;
  }

  totalStars() { return this.results.reduce((a, r) => a + (r?.stars ?? 0), 0); }
  get done() { return this.chapterIndex >= CHAPTERS.length; }

  toJSON() {
    const { storyline, difficulty, seed, chapterIndex, cash, results, findings, patched } = this;
    return { storyline, difficulty, seed, chapterIndex, cash, results, findings, patched, attempts: this.attempts.slice(-400) };
  }
  static fromJSON(o) { return Object.assign(new Campaign(o), o); }
}

// -- one chapter ----------------------------------------------------------------------------------
export class Chapter {
  /**
   * @param campaign  Campaign
   * @param world     the snapshot JSON (each chapter plays in a fresh copy)
   * @param models    {rookie, analyst, expert, elite}: Model instances
   * @param rng       () => [0, 1)
   */
  constructor(campaign, world, models, rng) {
    this.campaign = campaign;
    this.spec = CHAPTERS[campaign.chapterIndex];
    this.index = campaign.chapterIndex;
    this.net = Network.fromSnapshot(world);
    this.modelKey = campaign.modelKey();
    this.model = models[this.modelKey];
    this.tighten = campaign.thresholdTighten();
    this.rng = rng;
    this.lang = "en";
    this.startCash = campaign.cash;
    this.stolen = 0; this.spent = 0; this.blocks = 0; this.reviews = 0; this.attempts = 0;
    this.pips = 0; this.lastFlagT = this.net.now; this.cooledUntil = this.net.now;
    this.over = false; this.outcome = null;
    this.log = [];            // {t, kind, key, vars}: rendered by the UI in the player's language
    this.lastCheck = null;    // last scored attempt, for the fraud desk panel
    this.intel = null;        // last intel preview
    this.owned = [];          // {account, rented, burned, cut}
    this.leads = [];
    this.customers = this.net.customers();
    this.agentsList = this.net.agents();
    this.called = new Set();
    // Each chapter starts at 08:00 the next morning: people don't take calls at 1 a.m.
    this.start = Math.ceil((this.net.now + 1) / DAY) * DAY + 8 * HOUR;
    this.net.now = this.start;
    this.deadline = this.start + this.spec.days * DAY;
    this.setup();
  }

  // -- shared helpers -------------------------------------------------------------------------------
  get now() { return this.net.now; }
  get level() { return Math.min(HEAT_LEVELS, Math.floor(this.pips / 3)); }
  get profit() { return this.stolen - this.spent; }
  get cash() { return this.startCash + this.profit; }
  thresholds() {
    const m = this.model, lvl = this.level, k = this.tighten;
    return { review: m.review * k * (lvl >= 1 ? 0.6 : 1), block: m.block * k * (lvl >= 3 ? 0.6 : 1) };
  }
  pick(list) { return list[Math.floor(this.rng() * list.length)]; }
  emit(kind, key, vars = {}) { const e = { t: this.now, kind, key, vars }; this.log.push(e); return e; }

  spend(amount, key) {
    if (this.cash < amount) throw new GameError("no_cash");
    this.spent += amount;
    if (key) this.emit("spend", key, { amount });
  }

  advance(seconds) {
    const target = this.now + Math.max(1, Math.round(seconds));
    // cooling: a pip drops for every 12 h without anything flagged
    while (this.pips > 0 && target - Math.max(this.lastFlagT, this.cooledUntil) >= 12 * HOUR) {
      this.cooledUntil = Math.max(this.lastFlagT, this.cooledUntil) + 12 * HOUR;
      this.pips -= 1;
      this.emit("cool", "cooled", { level: this.level });
    }
    if (target >= this.deadline) {
      this.net.now = Math.max(this.net.now, this.deadline);
      this.finish("time_up");
      return -1;
    }
    this.net.now = target;
    this.randomEvent();
    return this.over ? -1 : target;
  }

  heat(pips, why) {
    const before = this.level;
    this.pips = Math.min(HEAT_LEVELS * 3 + 2, this.pips + pips);
    this.lastFlagT = this.now;
    if (this.level > before) this.emit("heat", `level_${this.level}`, { why });
  }

  requireOpen(kind) {
    if (this.over) throw new GameError("over");
    if (kind && !this.spec.kinds.includes(kind)) throw new GameError("wrong_mission");
    if (kind === "takeover" && !this.victim) throw new GameError("no_victim");
  }

  // Score one transaction with the chapter's model; record what the model saw
  score(tx, { override = false, declined = false, commit = true } = {}) {
    const out = process(this.net, this.model, tx, { customerDeclined: declined, overrideReview: override, explain: true,
      lang: this.lang, commit, thresholds: this.thresholds() });
    if (out.features && commit) {
      this.attempts += 1;
      const top = topContributions(out.contributions, out.features, 6);
      const check = { t: tx.t, amount: tx.amount, decision: out.decision, score: out.score, status: out.status,
        thresholds: this.thresholds(), top, reasons: out.reasons, model: this.modelKey };
      this.lastCheck = check;
      this.campaign.attempts.push({ chapter: this.spec.id, model: this.modelKey, decision: out.decision, score: out.score,
        features: Object.fromEntries(FEATURES.map((f, i) => [f, out.features[i]])) });
    }
    return out;
  }

  // Something risky got through: record it as a blind spot (once per pattern)
  noteFinding(out, how) {
    if (out.decision !== "approve" || !out.features) return;
    const f = Object.fromEntries(FEATURES.map((n, i) => [n, out.features[i]]));
    const signals = [];
    if (f.hours_since_sim_swap_or_pin_reset < 720) signals.push("security_event");
    if (f.device_new >= 0.5 || f.hours_since_device_first_seen < 72) signals.push("new_phone");
    if (f.recipient_new >= 0.5) signals.push("new_recipient");
    if (f.receiver_distinct_senders_7d >= 4) signals.push("busy_receiver");
    if (f.agent_decline_rate_24h >= 0.2) signals.push("declines");
    if (!signals.length) return;
    const key = `${this.modelKey}:${how}:${signals.join("+")}`;
    if (this.campaign.findings.some((x) => x.key === key)) return;
    const finding = { key, chapter: this.spec.id, model: this.modelKey, how, signals, score: out.score,
      review: this.thresholds().review, amount: out.amount };
    this.campaign.findings.push(finding);
    this.emit("finding", "finding", { how, signals, model: this.modelKey });
  }

  finish(outcome) {
    if (this.over) return;
    this.over = true;
    this.outcome = outcome;
    const goal = this.spec.goal;
    const met = outcome !== "caught" && this.profit >= goal;
    let stars = 0;
    if (met) { stars = 1; if (this.blocks <= 1) stars = 2; if (this.blocks === 0 && this.level <= 1) stars = 3; }
    this.result = { stars, profit: this.profit, stolen: this.stolen, spent: this.spent, outcome, met,
      beatRival: met && this.profit > this.spec.rival, blocks: this.blocks, reviews: this.reviews, attempts: this.attempts,
      model: this.modelKey };
    this.emit("end", outcome, { profit: this.profit });
  }

  // Commit the chapter to the campaign (only when the player continues)
  // moveOn: after a failed chapter, continue the campaign anyway with zero stars and no profit
  commit({ moveOn = false } = {}) {
    const c = this.campaign;
    if (!this.over) throw new GameError("not_over");
    if (!this.result.met && moveOn) {
      c.results[this.index] = { ...this.result, stars: 0, profit: 0, conceded: true };
      c.chapterIndex += 1;
      if (this.spec.patch) c.patched = true;
      return true;
    }
    if (this.result.met) {
      c.cash = this.cash;
      c.results[this.index] = this.result;
      c.chapterIndex += 1;
      if (this.spec.patch) c.patched = true;
    }
    return this.result.met;
  }

  // -- random events ---------------------------------------------------------------------------------
  randomEvent() {
    const r = this.rng();
    if (r < 0.025) { this.emit("event", "outage"); this.net.now += 2 * HOUR; }
    else if (r < 0.04 && this.pips >= 2) { this.pips -= 2; this.emit("event", "rival_busted"); }
    else if (r < 0.05 && this.level >= 2) { this.heat(1, "news"); this.emit("event", "news_report"); }
    if (this.spec.ownerChecks && this.victim && this.now >= this.nextOwnerCheck) this.ownerCheck();
  }

  // -- setup per mission -------------------------------------------------------------------------------
  setup() {
    const kinds = this.spec.kinds;
    this.emit("brief", `brief_${this.spec.id}`, { goal: this.spec.goal, days: this.spec.days });
    if (kinds.includes("refund")) { this.makeLeads(); this.openNumber(); }
    if (kinds.includes("requests")) {
      this.agent = this.pick(this.agentsList);
      this.usedAgents = new Set([this.agent]);
      this.emit("info", "your_till", { agent: this.agent, region: this.net.region.get(this.agent) });
    }
    if (this.spec.victimBalance) this.chooseVictim(this.spec.victimBalance);
    this.refreshOffers();
  }

  person(account) {
    const female = this.rng() < 0.5;
    const ageDays = (this.now - (this.net.state.openedT.get(account) ?? this.now)) / DAY;
    const balance = this.net.balance.get(account) ?? 0;
    const persona = ageDays > 1500 && balance > 60000 ? "retired" : balance > 150000 ? "trader" : ageDays < 400 ? "student"
      : this.pick(["teacher", "trader"]);
    return { account, name: this.pick(female ? NAMES.f : NAMES.m), female, persona, region: this.net.region.get(account),
      wealth: balance > 100000 ? "comfortable" : balance > 25000 ? "getting_by" : "tight", seed: Math.floor(this.rng() * 1e9) };
  }

  makeLeads() {
    const owned = new Set(this.owned.map((o) => o.account));
    this.leads = [];
    let guard = 0;
    while (this.leads.length < 3 && guard++ < 500) {
      const a = this.pick(this.customers);
      if (this.called.has(a) || owned.has(a) || (this.net.balance.get(a) ?? 0) < 4000 || this.leads.some((l) => l.account === a)) continue;
      this.leads.push(this.person(a));
    }
  }

  chooseVictim([min, max]) {
    const candidates = this.customers.filter((a) => {
      const b = this.net.balance.get(a) ?? 0;
      return b >= min && b <= max && this.net.device.has(a);
    }).sort((a, b) => (this.net.balance.get(b) ?? 0) - (this.net.balance.get(a) ?? 0));
    const pool = this.spec.id === "bigone" ? candidates.slice(0, 3) : candidates;
    const account = pool.length ? this.pick(pool) : this.customers.reduce((a, b) =>
      ((this.net.balance.get(a) ?? 0) > (this.net.balance.get(b) ?? 0) ? a : b));
    this.victim = this.person(account);
    this.entered = false;
  }

  // Takeover entry: a fake-agent call (5 days before they notice) or a SIM swap (36 h)
  enter(how) {
    this.requireOpen();
    if (!this.victim || this.entered) throw new GameError("wrong_mission");
    this.entered = true;
    this.thief = `D-thief-${Math.floor(this.rng() * 1e6)}`;
    this.net.accountEvent(this.victim.account, how === "sim" ? "SIM_SWAP" : "PIN_RESET", this.thief, this.now);
    const window = (how === "sim" ? 36 : 120) * HOUR;
    this.deadline = Math.min(this.deadline, this.now + window);
    this.endKey = how === "sim" ? "sim_back" : "owner_noticed";
    if (this.spec.ownerChecks) this.nextOwnerCheck = this.now + this.pickRange(8, 14) * HOUR;
    this.emit("story", how === "sim" ? "entered_sim" : "entered_pin", { name: this.victim.name, balance: this.net.balance.get(this.victim.account) });
    if (!this.owned.length) this.openNumber();
  }
  pickRange(a, b) { return a + this.rng() * (b - a); }

  // The owner of a big account checks the app twice a day; the more is missing, the likelier they notice
  ownerCheck() {
    this.nextOwnerCheck = this.now + this.pickRange(10, 14) * HOUR;
    const start = this.victimStart ?? this.net.balance.get(this.victim.account);
    const missing = Math.max(0, start - (this.net.balance.get(this.victim.account) ?? 0)) / Math.max(start, 1);
    this.emit("event", "owner_checks", { name: this.victim.name });
    if (missing > 0 && this.rng() < Math.min(0.9, missing * 2.2)) {
      this.emit("story", "owner_noticed_now", { name: this.victim.name });
      this.finish("noticed");
    }
  }

  // -- accounts ------------------------------------------------------------------------------------
  openNumber() {
    this.requireOpen();
    if (this.owned.filter((o) => !o.burned).length >= 5) throw new GameError("too_many");
    this.spend(COSTS.sim, "bought_sim");
    const account = this.net.newNumber(this.rng);
    const region = this.pick(this.net.regions.filter((r) => r));
    this.net.openAccount(account, "customer", region, this.now);
    this.owned.push({ account, rented: false, burned: false, region });
    return account;
  }

  // The rental market: three old accounts on offer. Older and same-town accounts cost more.
  refreshOffers() {
    const exclude = new Set([this.victim?.account, ...this.owned.map((o) => o.account), ...this.leads.map((l) => l.account)]);
    const pool = this.customers.filter((a) => !exclude.has(a) && (this.now - (this.net.state.openedT.get(a) ?? this.now)) / DAY > 180);
    this.offers = [];
    for (let i = 0; i < 3 && pool.length; i++) {
      const account = pool.splice(Math.floor(this.rng() * pool.length), 1)[0];
      const years = (this.now - this.net.state.openedT.get(account)) / DAY / 365;
      const activity = this.net.state.activity.get(account) ?? 0;
      const price = Math.round((COSTS.rent * (0.6 + Math.min(years, 5) * 0.12 + Math.min(activity, 300) / 1000)) / 100) * 100;
      this.offers.push({ account, region: this.net.region.get(account), years, activity, price });
    }
  }

  rentAccount(account) {
    this.requireOpen();
    if (this.owned.filter((o) => !o.burned).length >= 5) throw new GameError("too_many");
    const offer = this.offers.find((o) => o.account === account) ?? this.offers[0];
    if (!offer) throw new GameError("no_offers");
    const price = Math.round(offer.price * (this.level >= 2 ? 1.5 : 1));
    this.spend(price, "rented");
    this.owned.push({ account: offer.account, rented: true, burned: false, cut: COSTS.rentCut, region: offer.region });
    this.refreshOffers();
    return offer.account;
  }

  usable() { return this.owned.filter((o) => !o.burned); }
  ownedEntry(account) {
    const o = this.owned.find((x) => x.account === account);
    if (!o) throw new GameError("not_yours");
    if (o.burned) throw new GameError("burned");
    return o;
  }

  credit(amount, entry) {
    const cut = entry?.cut ? Math.round(amount * entry.cut) : 0;
    this.stolen += amount - cut;
    return cut;
  }

  flagged(out, entry, how) {
    if (out.decision === "review") {
      this.reviews += 1; this.heat(1, "review");
      if (this.level >= 2 && entry) { entry.burned = true; this.emit("bad", "burned_blacklist", { account: entry.account }); }
      if (this.level >= HEAT_LEVELS) { this.emit("bad", "lockdown_caught"); this.finish("caught"); }
    } else if (out.decision === "block") {
      this.blocks += 1; this.heat(2, "block");
      if (entry) entry.burned = true;
      if (this.level >= HEAT_LEVELS || this.blocks >= 3) { this.emit("bad", this.blocks >= 3 ? "three_blocks" : "lockdown_caught"); this.finish("caught"); }
    } else {
      this.noteFinding(out, how);
    }
  }

  // -- intel: probe the model before acting ------------------------------------------------------------
  // Runs the exact same transaction without committing it, and shows the score band and top reasons.
  buyIntel(plan) {
    this.requireOpen();
    this.spend(COSTS.intel, "bought_intel");
    const tx = this.planTx(plan);
    const out = process(this.net, this.model, tx, { commit: false, explain: true, lang: this.lang, thresholds: this.thresholds() });
    this.intel = { plan, score: out.score, decision: out.decision, reasons: out.reasons,
      top: topContributions(out.contributions, out.features, 4), thresholds: this.thresholds() };
    return this.intel;
  }

  planTx(plan) {
    const t = this.now + (plan.kind === "call" ? 15 * MIN : 2 * MIN);
    if (plan.kind === "steal") {
      return { type: "TRANSFER", channel: "USSD", sender: this.victim.account, receiver: plan.to, amount: plan.amount, device: this.thief, t };
    }
    if (plan.kind === "call") {
      const lead = this.leads.find((l) => l.account === plan.lead) ?? this.leads[0];
      return { type: "TRANSFER", channel: "USSD", sender: lead.account, receiver: plan.to, amount: plan.amount,
        device: this.net.device.get(lead.account), t };
    }
    throw new GameError("bad_plan");
  }

  // -- mission: "sent by mistake" (refund trick) ----------------------------------------------------------
  belief(lead, script, amount) {
    const s = SCRIPTS[script];
    const amt = amount <= 2000 ? 1.2 : amount <= 5000 ? 1 : amount <= 15000 ? 0.75 : 0.5;
    const wealth = lead.wealth === "tight" ? 0.8 : 1;
    const news = this.level >= 3 ? 0.8 : 1;
    return Math.min(0.85, PERSONAS[lead.persona].trust * s.belief * amt * wealth * news);
  }

  call({ lead: account, script, amount, to }) {
    this.requireOpen("refund");
    if (!account && this.leads.length) account = this.leads[0].account;
    const lead = this.leads.find((l) => l.account === account);
    if (!lead) throw new GameError("no_lead");
    const entry = this.ownedEntry(to);
    const balance = this.net.balance.get(lead.account) ?? 0;
    if (amount > balance * 0.9) amount = Math.max(500, Math.floor(balance * 0.9 / 500) * 500);
    const t = this.advance(this.pickRange(10, 25) * MIN);
    if (t < 0) return;
    this.called.add(lead.account);
    this.leads = this.leads.filter((l) => l !== lead);
    const s = SCRIPTS[script];
    const p = this.belief(lead, script, amount);
    this.emit("call", `call_${script}`, { name: lead.name, amount });
    if (this.rng() >= p) {
      if (this.rng() < Math.min(0.4, s.report * 1.5)) {
        entry.burned = true; this.heat(1, "report");
        this.emit("bad", "reported", { name: lead.name, account: entry.account });
      } else this.emit("info", "hung_up", { name: lead.name });
      this.refillLeads();
      return;
    }
    this.emit("info", "believes", { name: lead.name, amount });
    const tx = { type: "TRANSFER", channel: "USSD", sender: lead.account, receiver: entry.account, amount,
      device: this.net.device.get(lead.account), t };
    let out = this.score(tx);
    out.amount = amount;
    if (out.decision === "review") {
      if (this.rng() < s.cancel) {
        this.emit("review", "victim_warned_cancels", { name: lead.name });
        this.flagged(out, entry, "refund");
      } else {
        this.emit("review", "victim_warned_sends", { name: lead.name });
        this.flagged(out, entry, "refund");
        if (!this.over) {
          out = this.score({ ...tx, t: tx.t + 30 }, { override: true });
          if (out.status === "SUCCESS") { const cut = this.credit(amount, entry); this.emit("good", "received", { amount, cut, to: entry.account }); }
        }
      }
    } else if (out.decision === "block") {
      this.emit("bad", "blocked", { amount, to: entry.account });
      this.flagged(out, entry, "refund");
    } else if (out.status === "SUCCESS") {
      const cut = this.credit(amount, entry);
      this.emit("good", "received", { amount, cut, to: entry.account });
      this.flagged(out, entry, entry.rented ? "refund_rented" : "refund_fresh");
    }
    // The "refund code" trick: some believers dial a code that leaks their PIN
    if (this.spec.leak && !this.over && !this.victim && this.rng() < s.leak * (out.status === "SUCCESS" ? 1 : 0.5)) {
      this.victim = lead; this.entered = false; this.leakedFrom = lead.name;
      this.emit("story", "pin_leaked", { name: lead.name, balance: this.net.balance.get(lead.account) });
    }
    this.refillLeads();
  }

  refillLeads() { if (this.leads.length < 3) { const keep = this.leads; this.makeLeads(); this.leads = [...keep, ...this.leads].slice(0, 3); } }

  // -- mission: account takeover ---------------------------------------------------------------------
  warmup() {
    this.requireOpen("takeover");
    if (!this.entered) throw new GameError("not_in");
    this.spend(COSTS.airtime, null);
    const t = this.advance(this.pickRange(2, 6) * MIN);
    if (t < 0) return;
    const merchant = [...this.net.kind].find(([, k]) => k === "merchant")[0];
    const out = process(this.net, this.model, { type: "AIRTIME", channel: "USSD", sender: this.victim.account, receiver: merchant,
      amount: COSTS.airtime, device: this.thief, t });
    this.spent -= COSTS.airtime;   // paid from the victim's account, not yours
    this.emit("info", out.status === "SUCCESS" ? "warmed_up" : "no_funds", { amount: COSTS.airtime });
  }

  steal({ to, amount }) {
    this.requireOpen("takeover");
    if (!this.entered) throw new GameError("not_in");
    const entry = this.ownedEntry(to);
    if (this.victimStart === undefined) this.victimStart = this.net.balance.get(this.victim.account);
    const t = this.advance(this.pickRange(1, 4) * MIN);
    if (t < 0) return;
    const out = this.score({ type: "TRANSFER", channel: "USSD", sender: this.victim.account, receiver: entry.account, amount,
      device: this.thief, t });
    out.amount = amount;
    if (out.decision === "block") {
      this.emit("bad", "blocked", { amount, to: entry.account });
      this.blocks += 1; this.heat(2, "block"); entry.burned = true;
      this.emit("bad", "account_frozen", { name: this.victim.name });
      this.finish("caught");
    } else if (out.decision === "review") {
      this.emit("review", "owner_asked", { name: this.victim.name, amount });
      this.flagged(out, entry, "takeover");
      if (!this.over && this.reviews >= 2) { this.emit("bad", "account_frozen", { name: this.victim.name }); this.finish("caught"); }
    } else if (out.status === "FAILED_FUNDS") {
      this.emit("info", "no_funds", { amount });
    } else {
      const cut = this.credit(amount, entry);
      this.emit("good", "received", { amount, cut, to: entry.account });
      this.flagged(out, entry, entry.rented ? "takeover_rented" : "takeover_fresh");
    }
  }

  // -- mission: rogue agent withdrawal requests --------------------------------------------------------
  requests({ count, amount, targets, spread }) {
    this.requireOpen("requests");
    const region = this.net.region.get(this.agent);
    const span = { "10m": 10 * MIN, "2h": 2 * HOUR, "1d": DAY }[spread];
    const summary = { sent: 0, declined: 0, approved: 0, paid: 0 };
    for (let i = 0; i < count && !this.over; i++) {
      const t = this.advance((span / count) * this.pickRange(0.5, 1.5));
      if (t < 0) break;
      let target, guard = 0;
      do { target = this.pick(this.customers); } while (targets === "local" && this.net.region.get(target) !== region && guard++ < 200);
      const value = amount === "varied" ? Math.round(this.pickRange(2, 40)) * 500 : Number(amount);
      summary.sent += 1;
      const p = (value <= 10000 ? 0.07 : 0.05) * (targets === "local" ? 1.1 : 1);
      const tx = { type: "CASH_OUT", channel: "AGENT_REQUEST", sender: target, receiver: this.agent, amount: value,
        device: this.net.device.get(target), t };
      if (this.rng() >= p) { process(this.net, this.model, tx, { customerDeclined: true }); summary.declined += 1; continue; }
      summary.approved += 1;
      const out = this.score(tx);
      out.amount = value;
      if (out.decision === "approve" && out.status === "SUCCESS") {
        this.stolen += value; summary.paid += value; this.flagged(out, null, "requests");
      } else if (out.decision !== "approve") {
        this.emit(out.decision === "block" ? "bad" : "review", out.decision === "block" ? "request_blocked" : "request_warned", { amount: value });
        this.flagged(out, null, "requests");
      }
    }
    this.emit("info", "batch", summary);
    return summary;
  }

  // Move to another agent's till: a fresh history, at a price
  switchTill() {
    this.requireOpen("requests");
    this.spend(COSTS.till, "switched_till");
    const fresh = this.agentsList.filter((a) => !this.usedAgents.has(a));
    this.agent = fresh.length ? this.pick(fresh) : this.pick(this.agentsList);
    this.usedAgents.add(this.agent);
    this.emit("info", "new_till", { agent: this.agent, region: this.net.region.get(this.agent) });
  }

  // -- shared actions ------------------------------------------------------------------------------
  wait(duration) {
    this.requireOpen();
    this.emit("wait", "waited", { duration });
    this.advance({ "1h": HOUR, "6h": 6 * HOUR, "1d": DAY }[duration] ?? HOUR);
  }

  giveUp() { this.requireOpen(); this.finish("quit"); }
}

export class GameError extends Error {
  constructor(code) { super(code); this.code = code; }
}

export function topContributions(contributions, features, n = 5) {
  if (!contributions) return [];
  return FEATURES.map((f, i) => ({ feature: f, value: features[i], contribution: contributions[i] }))
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, n);
}

export { reasons };
