// The classic stage 5 game, ported line by line from src/momofraud/serving/game.py so it runs in
// the browser. `localApi` answers the same requests as the Python endpoints (/game/api/...), so the
// original page works unchanged on a static site. Scored by the Expert (production) model.
import { Network, process } from "../engine/network.js";
import { TEXT, WAIT_LABEL, NAMES, RENT_COST, SIM_COST } from "./text.js";

const MINUTE = 60, HOUR = 3600, DAY = 86400;
const WAITS = { "10m": 10 * MINUTE, "2h": 2 * HOUR, "1d": DAY };

class ApiError extends Error { constructor(detail, status = 422) { super(detail); this.status = status; } }

function pyRandom(seed) {   // a seedable RNG with Python-like helpers
  let a = seed >>> 0;
  const r = () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  r.choice = (list) => list[Math.floor(r() * list.length)];
  r.randint = (lo, hi) => lo + Math.floor(r() * (hi - lo + 1));
  r.uniform = (lo, hi) => lo + r() * (hi - lo);
  r.randrange = (lo, hi) => lo + Math.floor(r() * (hi - lo));
  return r;
}

export class ClassicGame {
  constructor(world, model, seed = Date.now() % 1e9) {
    this.world = world; this.model = model;
    this.rng = pyRandom(seed);
    this.sessions = new Map();
    let board = {};
    try { board = JSON.parse(localStorage.getItem("classic-board") || "{}"); } catch { /* fine */ }
    this.leaderboard = { takeover: board.takeover || [], rogue_agent: board.rogue_agent || [], wrong_transfer: board.wrong_transfer || [] };
    const net = Network.fromSnapshot(world);
    this.customers = net.customers();
    this.agents = net.agents();
    this.airtime = [...net.kind].find(([, k]) => k === "merchant")[0];
  }

  t(s, key, kw = {}) {
    const sep = s.lang === "en" ? "," : " ";
    return TEXT[s.lang][key].replace(/\{(\w+)\}/g, (_, k) => {
      const v = kw[k];
      return typeof v === "number" ? Math.round(v).toLocaleString("en-US").replace(/,/g, sep) : String(v ?? "");
    });
  }
  event(s, kind, text, extra = {}) { s.log.push({ time: s.net.timestamp(s.net.now), kind, text, ...extra }); }
  advance(s, seconds) {
    const t = s.net.now + Math.max(1, Math.floor(seconds));
    if (t >= s.deadline) { s.net.now = Math.max(s.net.now, s.deadline); this.finish(s, "time_up"); this.event(s, "info", this.t(s, s.endKey)); return -1; }
    s.net.now = t;
    return t;
  }
  finish(s, outcome) {
    if (s.over) return;
    s.over = true; s.outcome = outcome;
    const board = this.leaderboard[s.mission];
    board.push({ player: s.player, profit: Math.round(s.stolen - s.costs), stolen: Math.round(s.stolen), attempts: s.attempts, outcome });
    board.sort((a, b) => b.profit - a.profit); board.splice(10);
    try { localStorage.setItem("classic-board", JSON.stringify(this.leaderboard)); } catch { /* fine */ }
  }
  requireOpen(s, mission) {
    if (s.over) throw new ApiError("this mission is over: start a new one", 409);
    if (mission && s.mission !== mission) throw new ApiError(`this action is not part of the ${s.mission} mission`);
  }
  pickCustomer(s, { minBalance = 0, exclude = new Set(), region = null, needsContacts = false } = {}) {
    for (let i = 0; i < 5000; i++) {
      const a = s.rng.choice(this.customers);
      if (exclude.has(a) || (s.net.balance.get(a) ?? 0) < minBalance) continue;
      if (region && s.net.region.get(a) !== region) continue;
      if (needsContacts) {
        let n = 0;
        for (const [key, c] of s.net.state.pairCount) if (c && key.startsWith(a + "|")) { n++; if (n >= 2) break; }
        if (n < 2) continue;
      }
      return a;
    }
    throw new ApiError("could not find a suitable account in this network", 500);
  }
  open(s, rented) {
    let number;
    if (rented) {
      number = this.pickCustomer(s, { exclude: new Set([s.victim, ...s.owned].filter(Boolean)) });
      s.rented.add(number); s.costs += RENT_COST;
      this.event(s, "info", this.t(s, "rented", { number, cost: RENT_COST }));
    } else {
      number = s.net.newNumber(s.rng);
      s.net.openAccount(number, "customer", "Douala", s.net.now);
      s.costs += SIM_COST;
      this.event(s, "info", this.t(s, "opened", { number }));
    }
    s.owned.push(number);
    return number;
  }
  scored(s, out, amount, to) {
    s.attempts += 1;
    if (out.decision === "review" || out.decision === "block") for (const r of out.reasons) s.caughtBy.set(r.text, (s.caughtBy.get(r.text) ?? 0) + 1);
    if (out.decision === "block") { s.strikes += 1; this.event(s, "block", this.t(s, "block", { amount, to }), { score: out.score, reasons: out.reasons }); }
    else if (out.status === "FAILED_FUNDS") this.event(s, "fail", this.t(s, "no_funds", { amount }), { score: out.score });
    else if (out.status === "SUCCESS") { s.stolen += amount; this.event(s, "approve", this.t(s, "approve", { amount, to }), { score: out.score, reasons: out.reasons }); }
  }
  run(s, tx, options = {}) { return process(s.net, this.model, tx, { lang: s.lang, ...options }); }

  start({ mission, lang = "en", player = "anonymous", entry = "pin" }) {
    if (!this.leaderboard[mission]) throw new ApiError(`unknown mission: ${mission}`);
    const net = Network.fromSnapshot(this.world);
    const now = net.now = net.now + 1;
    const id = Math.floor(this.rng() * 2 ** 48).toString(16);
    const s = { id, net, rng: pyRandom(this.rng.randrange(0, 2 ** 31)), mission, lang, player, started: now, stolen: 0, costs: 0,
      strikes: 0, attempts: 0, over: false, outcome: null, log: [], caughtBy: new Map(), victim: null, victimName: null,
      device: null, agent: null, owned: [], rented: new Set(), burned: new Set(), called: new Set() };
    if (mission === "takeover") {
      Object.assign(s, { deadline: now + (entry === "sim" ? 36 : 120) * HOUR, maxStrikes: 2, endKey: entry === "sim" ? "sim_back" : "owner_noticed" });
      s.victim = this.pickCustomer(s, { minBalance: 60000, needsContacts: true });
      s.victimName = s.rng.choice(NAMES);
      s.device = `D-player-${id}`;
      net.accountEvent(s.victim, entry === "sim" ? "SIM_SWAP" : "PIN_RESET", s.device, now);
      const deadline = net.timestamp(s.deadline).slice(0, 16).replace("T", " ");
      this.event(s, "brief", this.t(s, "takeover_brief", { name: s.victimName, balance: net.balance.get(s.victim), deadline, how: this.t(s, `how_${entry}`) }));
      this.open(s, false);
    } else if (mission === "rogue_agent") {
      Object.assign(s, { deadline: now + 3 * DAY, maxStrikes: 3, endKey: "time_up" });
      s.agent = s.rng.choice(this.agents);
      this.event(s, "brief", this.t(s, "rogue_brief", { agent: s.agent, region: net.region.get(s.agent) }));
    } else {
      Object.assign(s, { deadline: now + 3 * DAY, maxStrikes: 3, endKey: "time_up" });
      this.event(s, "brief", this.t(s, "wrong_brief"));
      this.open(s, false);
    }
    this.sessions.set(id, s);
    return s;
  }
  get(id) { const s = this.sessions.get(id); if (!s) throw new ApiError("unknown game session", 404); return s; }

  act(s, body) {
    switch (body.action) {
      case "wait":
        this.requireOpen(s);
        this.event(s, "info", this.t(s, "wait", { what: WAIT_LABEL[s.lang][body.duration ?? "2h"] }));
        this.advance(s, WAITS[body.duration ?? "2h"]); break;
      case "open": case "rent":
        this.requireOpen(s);
        if (s.mission === "rogue_agent") throw new ApiError("an agent collects at their own till: no receiving accounts in this mission");
        if (s.owned.length >= 6) throw new ApiError("you already control 6 accounts");
        this.open(s, body.action === "rent"); break;
      case "airtime": {
        this.requireOpen(s, "takeover");
        const t = this.advance(s, s.rng.randint(1, 5) * MINUTE);
        if (t < 0) break;
        const out = this.run(s, { type: "AIRTIME", channel: "USSD", sender: s.victim, receiver: this.airtime, amount: body.amount ?? 500, device: s.device, t });
        this.event(s, out.status === "SUCCESS" ? "info" : "fail", this.t(s, out.status === "SUCCESS" ? "airtime" : "no_funds", { amount: body.amount ?? 500 }));
        break;
      }
      case "steal": {
        this.requireOpen(s, "takeover");
        const to = body.to, amount = Number(body.amount);
        if (!s.owned.includes(to)) throw new ApiError("you can only send to accounts you control");
        const t = this.advance(s, s.rng.randint(1, 3) * MINUTE);
        if (t < 0) break;
        const out = this.run(s, { type: "TRANSFER", channel: "USSD", sender: s.victim, receiver: to, amount, device: s.device, t });
        this.scored(s, out, amount, to);
        if (out.decision === "block") { this.event(s, "info", this.t(s, "frozen")); this.finish(s, "caught"); }
        else if (out.decision === "review") {
          s.strikes += 1;
          this.event(s, "review", this.t(s, "review_takeover", { amount }), { score: out.score, reasons: out.reasons });
          if (s.strikes >= s.maxStrikes) { this.event(s, "info", this.t(s, "frozen")); this.finish(s, "caught"); }
        }
        break;
      }
      case "requests": this.requests(s, body); break;
      case "call": this.call(s, Number(body.amount), body.to); break;
      case "quit": this.requireOpen(s); this.finish(s, "quit"); break;
      default: throw new ApiError(`unknown action ${body.action}`);
    }
  }

  requests(s, body) {
    this.requireOpen(s, "rogue_agent");
    const count = Number(body.count ?? 30), amount = body.request_amount ?? "25000", targets = body.targets ?? "national", spread = body.spread ?? "2h";
    const region = targets === "local" ? s.net.region.get(s.agent) : null;
    const gap = WAITS[spread] / count;
    const summary = { sent: 0, declined: 0, approved: 0 };
    for (let i = 0; i < count; i++) {
      const t = this.advance(s, Math.max(1, Math.floor(gap * s.rng.uniform(0.5, 1.5))));
      if (t < 0) break;
      const target = this.pickCustomer(s, { region, exclude: new Set([s.agent]) });
      const value = amount !== "varied" ? Number(amount) : s.rng.randrange(2, 41) * 500;
      summary.sent += 1;
      const tx = { type: "CASH_OUT", channel: "AGENT_REQUEST", sender: target, receiver: s.agent, amount: value, device: s.net.device.get(target), t };
      if (s.rng() >= (value <= 10000 ? 0.07 : 0.05)) { this.run(s, tx, { customerDeclined: true }); summary.declined += 1; continue; }
      summary.approved += 1;
      const out = this.run(s, tx);
      this.scored(s, out, value, s.agent);
      if (out.decision === "review") this.event(s, "review", this.t(s, "review_request"), { score: out.score, reasons: out.reasons });
      if (s.strikes >= s.maxStrikes) { this.event(s, "info", this.t(s, "suspended")); this.finish(s, "caught"); break; }
    }
    this.event(s, "info", this.t(s, "batch", summary));
  }

  call(s, amount, number) {
    this.requireOpen(s, "wrong_transfer");
    if (!s.owned.includes(number)) throw new ApiError("you can only use numbers you control");
    if (s.burned.has(number)) throw new ApiError("this number has been flagged: open or rent another one");
    const t = this.advance(s, s.rng.randint(5, 20) * MINUTE);
    if (t < 0) return;
    const victim = this.pickCustomer(s, { minBalance: amount * 1.01, exclude: new Set([...s.called, ...s.owned]) });
    s.called.add(victim);
    const name = s.rng.choice(NAMES);
    if (s.rng() >= (amount <= 5000 ? 0.4 : amount <= 15000 ? 0.3 : 0.2)) { this.event(s, "info", this.t(s, "hung_up", { name })); return; }
    this.event(s, "info", this.t(s, "believes", { name, amount }));
    const tx = { type: "TRANSFER", channel: "USSD", sender: victim, receiver: number, amount, device: s.net.device.get(victim), t };
    let out = this.run(s, tx);
    if (out.decision === "review") {
      s.attempts += 1;
      for (const r of out.reasons) s.caughtBy.set(r.text, (s.caughtBy.get(r.text) ?? 0) + 1);
      if (s.rng() < 0.7) { this.event(s, "review", this.t(s, "review_victim_cancels"), { score: out.score, reasons: out.reasons }); return; }
      this.event(s, "review", this.t(s, "review_victim_sends"), { score: out.score, reasons: out.reasons });
      out = this.run(s, { ...tx, t: t + 30 }, { overrideReview: true });
      if (out.status === "SUCCESS") { s.stolen += amount; this.event(s, "approve", this.t(s, "approve", { amount, to: number }), { score: out.score }); }
      return;
    }
    this.scored(s, out, amount, number);
    if (out.decision === "block") {
      s.burned.add(number);
      this.event(s, "info", this.t(s, "burned", { number }));
      if (s.strikes >= s.maxStrikes) { this.event(s, "info", this.t(s, "suspended")); this.finish(s, "caught"); }
    }
  }

  view(s) {
    const tips = { takeover: "tips_takeover", rogue_agent: "tips_rogue", wrong_transfer: "tips_wrong" }[s.mission];
    return {
      id: s.id, mission: s.mission, lang: s.lang, player: s.player,
      clock: s.net.timestamp(s.net.now), deadline: s.net.timestamp(s.deadline),
      hours_left: Math.max(0, Math.round(((s.deadline - s.net.now) / HOUR) * 10) / 10),
      stolen: Math.round(s.stolen), costs: Math.round(s.costs), profit: Math.round(s.stolen - s.costs),
      strikes: s.strikes, max_strikes: s.maxStrikes, attempts: s.attempts, over: s.over, outcome: s.outcome,
      victim: s.victim ? { account: s.victim, name: s.victimName, balance: s.net.balance.get(s.victim) } : null,
      agent: s.agent,
      owned: s.owned.map((a) => ({ account: a, balance: s.net.balance.get(a) ?? null, burned: s.burned.has(a), rented: s.rented.has(a) })),
      log: s.log.slice(-40),
      caught_by: [...s.caughtBy].sort((a, b) => b[1] - a[1]).slice(0, 5),
      tips: s.over ? this.t(s, tips) : null,
      leaderboard: this.leaderboard[s.mission],
    };
  }
}

// The same requests the page used to send to the Python server
export function localApi(game) {
  return async (path, body) => {
    try {
      if (path === "/game/api/start") return game.view(game.start(body));
      const m = path.match(/^\/game\/api\/sessions\/([^/]+)$/);
      if (m) { const s = game.get(m[1]); if (body) game.act(s, body); return game.view(s); }
      throw new ApiError("not found", 404);
    } catch (e) {
      if (e instanceof ApiError) throw new Error(e.message);
      throw e;
    }
  };
}
