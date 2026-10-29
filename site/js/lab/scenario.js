// Model Lab scenarios: build a situation in a private copy of the network, then score one
// transaction with every model. Nothing here is faked: the setup is real history (events,
// accounts, transfers) applied to the network, and the score comes from the real feature engine.
import { Network, process } from "../engine/network.js";
import { reasons } from "../engine/reasons.js";

const MIN = 60, HOUR = 3600, DAY = 86400;

export const PRESETS = {
  everyday: { type: "transfer", recipient: "contact", amount: 5000, event: "none", delay: 120, phone: "own", hour: 14,
    strangers: 0, cashedOut: false, flood: 0 },
  rushed: { type: "transfer", recipient: "new", amount: "all", event: "SIM_SWAP", delay: 10, phone: "new", hour: 23,
    strangers: 0, cashedOut: false, flood: 0 },
  careful: { type: "transfer", recipient: "rented", amount: 5000, event: "PIN_RESET", delay: 2880, phone: "warmed", hour: 10,
    strangers: 0, cashedOut: false, flood: 0 },
  rogue: { type: "agent_request", recipient: "far_agent", amount: 25000, event: "none", delay: 120, phone: "own", hour: 11,
    strangers: 0, cashedOut: false, flood: 40 },
  mistake: { type: "transfer", recipient: "stranger", amount: 5000, event: "none", delay: 120, phone: "own", hour: 11,
    strangers: 8, cashedOut: true, flood: 0 },
};

// The cast: picked once from the world, deterministically
export function cast(world) {
  const net = Network.fromSnapshot(world);
  const contactsOf = new Map();
  for (const [key, n] of net.state.pairCount) {
    const [s, r] = key.split("|");
    if (n >= 2 && net.kind.get(s) === "customer" && net.kind.get(r) === "customer") {
      if (!contactsOf.has(s)) contactsOf.set(s, []);
      contactsOf.get(s).push([r, n]);
    }
  }
  const customers = net.customers().sort();
  const sender = customers.find((a) => {
    const b = net.balance.get(a) ?? 0;
    return b > 120000 && b < 600000 && (contactsOf.get(a)?.length ?? 0) >= 3 && net.device.has(a)
      && (net.state.amountN.get(a) ?? 0) >= 8;
  });
  const region = net.region.get(sender);
  const contact = contactsOf.get(sender).sort((a, b) => b[1] - a[1])[0][0];
  const paid = new Set([...net.state.pairCount.keys()].filter((k) => k.startsWith(sender + "|")).map((k) => k.split("|")[1]));
  const neverPaid = (a) => a !== sender && !paid.has(a) && net.state.pairCountOf(a, sender) === 0;
  const stranger = customers.find((a) => neverPaid(a) && net.region.get(a) !== region && (net.balance.get(a) ?? 0) < 50000
    && (net.state.activity.get(a) ?? 0) > 20);
  const now = net.now;
  const rented = customers.find((a) => neverPaid(a) && a !== stranger && (now - (net.state.openedT.get(a) ?? now)) / DAY > 365
    && (net.state.activity.get(a) ?? 0) > 60 && !(net.state.in7d.get(a)?.length > 2));
  const agents = net.agents().sort();
  const usual = agents.find((a) => net.state.pairCountOf(sender, a) > 0) ?? agents.find((a) => net.region.get(a) === region);
  const far = agents.find((a) => net.region.get(a) !== region && net.state.pairCountOf(sender, a) === 0);
  const crowd = customers.filter((a) => a !== sender && a !== stranger && a !== rented && (net.balance.get(a) ?? 0) > 20000).slice(0, 40);
  return { sender, contact, stranger, rented, usual, far, crowd, region, balance: net.balance.get(sender) };
}

// Next time >= t whose hour of day is `hour`
const atHour = (t, hour) => {
  const h = Math.floor(t / HOUR) % 24;
  return t + ((hour - h + 24) % 24) * HOUR;
};

export function run(world, models, actors, knobs, lang = "en") {
  const started = performance.now();
  const net = Network.fromSnapshot(world);
  const base = net.now + 60;
  const k = knobs;
  const ownPhone = net.device.get(actors.sender);
  const thief = "D-lab-thief";
  // The transaction happens at the chosen hour; the account event `delay` minutes before it
  const t = atHour(base + (k.event === "none" ? HOUR : k.delay * MIN), k.hour);
  const eventT = t - k.delay * MIN;
  const steps = [];
  if (k.event !== "none") {
    net.accountEvent(actors.sender, k.event, k.phone === "own" ? null : thief, eventT);
    steps.push("event");
  }
  // receiver
  let receiver;
  let type = "TRANSFER", channel = "USSD";
  if (k.type === "transfer") {
    if (k.recipient === "new") {
      receiver = net.newNumber(() => 0.4242);
      net.openAccount(receiver, "customer", "Douala", Math.min(eventT, t - 2 * HOUR));
    } else receiver = actors[k.recipient] ?? actors.contact;
  } else {
    type = "CASH_OUT";
    channel = k.type === "agent_request" ? "AGENT_REQUEST" : "AGENT";
    receiver = k.recipient === "far_agent" ? actors.far : actors.usual;
  }
  // other people's money flowing into the receiver earlier today (mule or scammer hub)
  if (k.type === "transfer" && k.strangers > 0) {
    for (let i = 0; i < k.strangers; i++) {
      const who = actors.crowd[i];
      const when = t - 6 * HOUR + i * Math.floor((5 * HOUR) / k.strangers);
      process(net, models.expert, { type: "TRANSFER", channel: "USSD", sender: who, receiver, amount: 2000 + 500 * (i % 5),
        device: net.device.get(who), t: when }, { overrideReview: true });
    }
    if (k.cashedOut && net.balance.has(receiver)) {
      const amount = Math.floor((net.balance.get(receiver) * 0.9) / 1.002 / 500) * 500;
      if (amount >= 500) {
        process(net, models.expert, { type: "CASH_OUT", channel: "AGENT", sender: receiver, receiver: actors.usual, amount,
          device: net.device.get(receiver), t: t - 30 * MIN }, { overrideReview: true });
      }
    }
  }
  // a rogue agent's flood of declined requests in the last hour
  if (channel === "AGENT_REQUEST" && k.flood > 0) {
    for (let i = 0; i < k.flood; i++) {
      const who = actors.crowd[i % actors.crowd.length];
      process(net, models.expert, { type: "CASH_OUT", channel: "AGENT_REQUEST", sender: who, receiver, amount: 25000,
        device: net.device.get(who), t: t - 55 * MIN + i * Math.floor((50 * MIN) / k.flood) }, { customerDeclined: true });
    }
  }
  // a warm-up purchase from the new phone
  const device = k.phone === "own" ? ownPhone : thief;
  if (k.phone === "warmed") {
    const merchant = [...net.kind].find(([, kind]) => kind === "merchant")[0];
    process(net, models.expert, { type: "AIRTIME", channel: "USSD", sender: actors.sender, receiver: merchant, amount: 500,
      device, t: t - 30 * MIN });
  }
  const balance = net.balance.get(actors.sender);
  const amount = k.amount === "all" ? Math.floor(balance / 1.002) : Math.min(Number(k.amount), Math.floor(balance / 1.002));
  const tx = { type, channel, sender: actors.sender, receiver, amount, device, t };
  const results = {};
  let features = null;
  for (const [key, model] of Object.entries(models)) {
    const tick = performance.now();
    const out = process(net, model, tx, { commit: false, explain: true, lang });
    features = out.features;
    results[key] = { score: out.score, decision: out.decision, contributions: out.contributions, reasons: out.reasons,
      ms: performance.now() - tick, bias: model.bias };
  }
  return { tx, features, results, balance, timestamp: net.timestamp(t), totalMs: performance.now() - started, receiver };
}

export function reasonsFor(result, features, lang) { return reasons(result.contributions, features, lang); }
