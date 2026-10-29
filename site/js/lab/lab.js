import { chrome, lang, onLang, loadModels, loadWorld, loadMetrics, esc, fcfa, pct, logPos, REPO, TIERS } from "../common.js";
import { FEATURES } from "../engine/features.js";
import { LABELS } from "../engine/reasons.js";
import { cast, run, PRESETS } from "./scenario.js";
import { formatValue } from "./format.js";

const T = {
  en: {
    title: "Model Lab",
    lead: "Build a mobile-money transaction, then watch four fraud models score it live, in your browser. Each model is a real LightGBM model trained on the simulator, and every explanation is an exact SHAP value.",
    lead2: "The four models are the difficulty levels of the game. They differ only in what they are allowed to know.",
    presets: { everyday: ["Everyday payment", "5,000 to her sister"], rushed: ["Rushed takeover", "SIM swap, then everything"],
      careful: ["Careful takeover", "PIN leak, 2 days, rented account"], rogue: ["Rogue agent", "40 declined requests first"],
      mistake: ["\"Sent by mistake\"", "Refund to a scam hub"] },
    type: "Transaction", types: { transfer: "Transfer", cashout: "Cash-out at agent", agent_request: "Agent's request" },
    recipient: "Who receives it", recipients: { contact: "Her sister (paid often)", stranger: "A stranger", new: "A number opened today",
      rented: "A rented old account", usual: "Her usual agent", far_agent: "An agent in another town" },
    amount: "Amount", all: "Whole balance", event: "Account event", events: { none: "None", SIM_SWAP: "SIM swap", PIN_RESET: "PIN reset" },
    delay: "Time since the event", delays: { 10: "10 min", 120: "2 hours", 1440: "1 day", 2880: "2 days", 7200: "5 days", 14400: "10 days" },
    phone: "Phone used", phones: { own: "Her own phone", new: "A new phone", warmed: "New phone, warmed up" },
    hour: "Time of day", strangers: "People who sent the receiver money today", cashed: "…and the receiver withdrew it",
    flood: "Declined requests this agent sent in the last hour",
    story: (a) => `<b>Amina</b> (${a.sender}) lives in ${a.region} and has <b>${fcfa(a.balance)} FCFA</b>. Every scenario starts from her real history in a simulated network of 2,000 people.`,
    scale: ["0.01%", "0.1%", "1%", "10%", "100%"], fraud: "fraud score",
    why: "Why this score", whyFor: (m) => `Exact SHAP values for ${m}: how each fact pushed the score up (red) or down (green), in log-odds.`,
    base: "Average transaction", final: "This transaction", reasonsTitle: "What a support agent would read",
    noReasons: "Nothing worth flagging.", timing: (n, ms) => `Scored by ${n} models with exact SHAP explanations in ${ms} ms, in your browser.`,
    unused: "not used by this model",
    tiersTitle: "How well trained is each model?",
    tiersLead: "Same data, same algorithm, different knowledge. Tested on days the models never saw (days 75-89 of the simulator). Recall is the share of fraud caught at the review threshold; thresholds were set for 50% and 90% precision on earlier validation days.",
    tiersHead: ["Model", "Knows", "PR-AUC", "Fraud caught", "Takeovers", "Agent spam", "Refund scams", "Rented-account attacks", "False alarms / 10k"],
    driftTitle: "Watching for drift",
    driftLead: "A model tuned on last quarter's traffic gets worse when traffic changes. In this experiment, a phone promotion from day 78 gives a quarter of customers a new phone. The monitor flags it on the first day; the cost is false alarms on honest people.",
    driftLegend: ["False alarms per 10k, no promotion", "False alarms per 10k, phone promotion", "Days flagged as drift"],
    howTitle: "How it works",
    how: [["Simulator", "20,000 people, 90 days, three scams documented in Cameroon, naive and adaptive versions."],
      ["Point-in-time features", "33 behavioural features computed only from what was known before each transaction."],
      ["LightGBM", "Gradient-boosted trees, thresholds chosen on validation days for 90% and 50% precision."],
      ["SHAP", "Exact TreeSHAP values turned into sentences in English and French."],
      ["Same code everywhere", "Python trains and serves; this page runs a JavaScript port proven identical by parity tests."]],
    repo: "Read the code and the reports on GitHub",
  },
  fr: {
    title: "Labo du modèle",
    lead: "Composez une transaction mobile money, puis regardez quatre modèles anti-fraude l'évaluer en direct, dans votre navigateur. Chaque modèle est un vrai modèle LightGBM entraîné sur le simulateur, et chaque explication est une valeur SHAP exacte.",
    lead2: "Les quatre modèles sont les niveaux de difficulté du jeu. Ils ne diffèrent que par ce qu'ils ont le droit de savoir.",
    presets: { everyday: ["Paiement ordinaire", "5 000 à sa sœur"], rushed: ["Piratage pressé", "Changement de SIM, puis tout"],
      careful: ["Piratage prudent", "Fuite du PIN, 2 jours, compte loué"], rogue: ["Agent véreux", "40 demandes refusées avant"],
      mistake: ["« Envoyé par erreur »", "Remboursement vers un arnaqueur"] },
    type: "Transaction", types: { transfer: "Transfert", cashout: "Retrait chez l'agent", agent_request: "Demande de l'agent" },
    recipient: "Destinataire", recipients: { contact: "Sa sœur (souvent payée)", stranger: "Un inconnu", new: "Un numéro ouvert aujourd'hui",
      rented: "Un vieux compte loué", usual: "Son agent habituel", far_agent: "Un agent d'une autre ville" },
    amount: "Montant", all: "Tout le solde", event: "Événement sur le compte", events: { none: "Aucun", SIM_SWAP: "Changement de SIM", PIN_RESET: "PIN réinitialisé" },
    delay: "Temps depuis l'événement", delays: { 10: "10 min", 120: "2 heures", 1440: "1 jour", 2880: "2 jours", 7200: "5 jours", 14400: "10 jours" },
    phone: "Téléphone utilisé", phones: { own: "Son téléphone", new: "Un nouveau téléphone", warmed: "Nouveau, « réchauffé »" },
    hour: "Heure", strangers: "Personnes qui ont envoyé de l'argent au destinataire aujourd'hui", cashed: "…et le destinataire l'a retiré",
    flood: "Demandes refusées envoyées par cet agent dans la dernière heure",
    story: (a) => `<b>Amina</b> (${a.sender}) vit à ${a.region} et a <b>${fcfa(a.balance)} FCFA</b>. Chaque scénario part de son vrai historique dans un réseau simulé de 2 000 personnes.`,
    scale: ["0,01 %", "0,1 %", "1 %", "10 %", "100 %"], fraud: "score de fraude",
    why: "Pourquoi ce score", whyFor: (m) => `Valeurs SHAP exactes pour ${m} : comment chaque fait a poussé le score vers le haut (rouge) ou le bas (vert), en log-odds.`,
    base: "Transaction moyenne", final: "Cette transaction", reasonsTitle: "Ce que lirait un agent du service client",
    noReasons: "Rien à signaler.", timing: (n, ms) => `Évaluée par ${n} modèles avec explications SHAP exactes en ${ms} ms, dans votre navigateur.`,
    unused: "non utilisé par ce modèle",
    tiersTitle: "À quel point chaque modèle est-il entraîné ?",
    tiersLead: "Mêmes données, même algorithme, connaissances différentes. Testés sur des jours jamais vus (jours 75 à 89 du simulateur). Le rappel est la part de fraude détectée au seuil de vérification ; les seuils visent 50 % et 90 % de précision sur des jours de validation antérieurs.",
    tiersHead: ["Modèle", "Sait", "PR-AUC", "Fraude détectée", "Piratages", "Spam d'agent", "Remboursements", "Comptes loués", "Fausses alertes / 10k"],
    driftTitle: "Surveiller la dérive",
    driftLead: "Un modèle réglé sur le trimestre dernier se dégrade quand le trafic change. Dans cette expérience, une promotion de téléphones à partir du jour 78 donne un nouveau téléphone à un quart des clients. Le moniteur le signale dès le premier jour ; le prix, ce sont des fausses alertes sur des gens honnêtes.",
    driftLegend: ["Fausses alertes pour 10k, sans promotion", "Fausses alertes pour 10k, promotion", "Jours signalés en dérive"],
    howTitle: "Comment ça marche",
    how: [["Simulateur", "20 000 personnes, 90 jours, trois arnaques documentées au Cameroun, en versions naïve et adaptative."],
      ["Variables à l'instant t", "33 variables de comportement calculées uniquement avec ce qui était connu avant chaque transaction."],
      ["LightGBM", "Arbres de gradient boosting, seuils choisis sur des jours de validation pour 90 % et 50 % de précision."],
      ["SHAP", "Valeurs TreeSHAP exactes transformées en phrases en anglais et en français."],
      ["Le même code partout", "Python entraîne et sert ; cette page exécute un portage JavaScript prouvé identique par des tests de parité."]],
    repo: "Lire le code et les rapports sur GitHub",
  },
};
const L = () => T[lang];

let world, models, actors, metrics;
let knobs = { ...PRESETS.everyday }, preset = "everyday", selected = "expert", last = null;
const app = document.getElementById("app");
chrome("lab");

async function init() {
  try {
    [world, models, metrics] = await Promise.all([loadWorld(), loadModels(), loadMetrics()]);
  } catch (e) {
    app.innerHTML = `<p class="loading">Could not load the model files (${esc(e.message)}).</p>`;
    return;
  }
  actors = cast(world);
  render();
  onLang(render);
}

function seg(name, options, value) {
  return `<div class="seg" data-knob="${name}">${Object.entries(options).map(([k, label]) =>
    `<button data-v="${k}" class="${String(value) === k ? "on" : ""}">${esc(label)}</button>`).join("")}</div>`;
}
function sel(name, options, value) {
  return `<select class="in" data-knob="${name}">${Object.entries(options).map(([k, label]) =>
    `<option value="${k}" ${String(value) === k ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
}
const amountToSlider = (a) => Math.log(Math.max(a, 500) / 500) / Math.log(Math.max(actors.balance, 1000) / 500);
const sliderToAmount = (x) => Math.round((500 * Math.pow(Math.max(actors.balance, 1000) / 500, x)) / 500) * 500;

function controls() {
  const t = L(), k = knobs;
  const recips = k.type === "transfer" ? ["contact", "stranger", "new", "rented"] : ["usual", "far_agent"];
  if (!recips.includes(k.recipient)) k.recipient = recips[0];
  const amount = k.amount === "all" ? actors.balance : Number(k.amount);
  return `
    <div><span class="lbl">${t.type}</span>${seg("type", t.types, k.type)}</div>
    <div><span class="lbl">${t.recipient}</span>${sel("recipient", Object.fromEntries(recips.map((r) => [r, t.recipients[r]])), k.recipient)}</div>
    <div><label for="amt">${t.amount} <span class="val">${k.amount === "all" ? t.all : fcfa(amount) + " FCFA"}</span></label>
      <input id="amt" type="range" min="0" max="1" step="0.01" value="${k.amount === "all" ? 1 : amountToSlider(amount).toFixed(2)}" data-knob="amount"></div>
    <div><span class="lbl">${t.event}</span>${seg("event", t.events, k.event)}</div>
    ${k.event !== "none" ? `<div><span class="lbl">${t.delay}</span>${sel("delay", t.delays, k.delay)}</div>` : ""}
    <div><span class="lbl">${t.phone}</span>${seg("phone", t.phones, k.phone)}</div>
    <div><label for="hr">${t.hour} <span class="val">${String(k.hour).padStart(2, "0")}:00</span></label>
      <input id="hr" type="range" min="0" max="23" step="1" value="${k.hour}" data-knob="hour"></div>
    ${k.type === "transfer" ? `<div><span class="lbl">${t.strangers}</span>${seg("strangers", { 0: "0", 3: "3", 8: "8" }, k.strangers)}
      ${k.strangers > 0 ? `<label style="margin-top:6px;display:flex;gap:6px;align-items:center"><input type="checkbox" data-knob="cashedOut" ${k.cashedOut ? "checked" : ""}> ${t.cashed}</label>` : ""}</div>` : ""}
    ${k.type === "agent_request" ? `<div><span class="lbl">${t.flood}</span>${seg("flood", { 0: "0", 10: "10", 40: "40" }, k.flood)}</div>` : ""}`;
}

function render() {
  const t = L();
  app.innerHTML = `
    <section class="hero"><h1>${t.title}</h1><p>${t.lead}</p><p class="muted">${t.lead2}</p></section>
    <div class="presets">${Object.entries(t.presets).map(([k, [a, b]]) =>
      `<button class="preset ${k === preset ? "on" : ""}" data-preset="${k}">${esc(a)}<small>${esc(b)}</small></button>`).join("")}</div>
    <div class="lab">
      <div class="panel ctl" id="controls">${controls()}</div>
      <div>
        <div class="story">${t.story(actors)}</div>
        <div class="panel" style="margin-top:12px">
          <div class="models" id="models"></div>
          <div class="scale">${t.scale.map((s) => `<span>${s}</span>`).join("")}</div>
          <div class="why" id="why"></div>
          <div class="timing" id="timing"></div>
        </div>
      </div>
    </div>
    ${tiersSection()}
    ${driftSection()}
    <section class="block"><h2>${t.howTitle}</h2>
      <div class="pipeline">${t.how.map(([a, b]) => `<div class="step"><b>${a}</b>${b}</div>`).join("")}</div>
      <p style="margin-top:14px"><a href="${REPO}" target="_blank" rel="noopener">${t.repo} ↗</a></p></section>`;
  bind();
  score();
}

function bind() {
  app.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
    preset = b.dataset.preset; knobs = { ...PRESETS[preset] }; render();
  }));
  const ctl = app.querySelector("#controls");
  ctl.addEventListener("click", (e) => {
    const b = e.target.closest(".seg button");
    if (!b) return;
    const name = b.parentElement.dataset.knob;
    const v = b.dataset.v;
    knobs[name] = ["strangers", "flood"].includes(name) ? Number(v) : v;
    changed();
  });
  ctl.addEventListener("input", (e) => {
    const el = e.target, name = el.dataset.knob;
    if (!name) return;
    if (name === "amount") knobs.amount = Number(el.value) >= 0.995 ? "all" : sliderToAmount(Number(el.value));
    else if (name === "hour") knobs.hour = Number(el.value);
    else if (name === "delay") knobs.delay = Number(el.value);
    else if (name === "cashedOut") knobs.cashedOut = el.checked;
    else knobs[name] = el.value;
    changed(name === "amount" || name === "hour");
  });
}

let pending = null;
function changed(light = false) {
  preset = null;
  app.querySelectorAll("[data-preset]").forEach((b) => b.classList.remove("on"));
  if (!light) {
    const ctl = app.querySelector("#controls");
    ctl.innerHTML = controls();
  } else {
    const t = L();
    const amtVal = app.querySelector('label[for="amt"] .val');
    if (amtVal) amtVal.textContent = knobs.amount === "all" ? t.all : `${fcfa(knobs.amount)} FCFA`;
    const hrVal = app.querySelector('label[for="hr"] .val');
    if (hrVal) hrVal.textContent = `${String(knobs.hour).padStart(2, "0")}:00`;
  }
  cancelAnimationFrame(pending);
  pending = requestAnimationFrame(score);
}

function score() {
  last = run(world, models, actors, knobs, lang);
  const t = L();
  const box = app.querySelector("#models");
  box.innerHTML = TIERS.map((k) => {
    const m = models[k], r = last.results[k];
    return `<div class="mrow ${k === selected ? "sel" : ""}" data-model="${k}" title="${esc(m.knows)}">
      <div class="nm">${m.name}<small>${esc(knowsShort(k))}</small></div>
      <div class="gauge" style="--r:${(logPos(m.review) * 100).toFixed(1)}%;--b:${(logPos(m.block) * 100).toFixed(1)}%">
        <span class="sc" style="left:${(logPos(r.score) * 100).toFixed(1)}%">${pct(r.score)}</span>
        <span class="needle" style="left:calc(${(logPos(r.score) * 100).toFixed(1)}% - 2px)"></span></div>
      <div><span class="chip ${r.decision}">${decisionWord(r.decision)}</span></div></div>`;
  }).join("");
  box.querySelectorAll("[data-model]").forEach((row) => row.addEventListener("click", () => { selected = row.dataset.model; score(); }));
  renderWhy();
  const ms = Object.values(last.results).reduce((a, r) => a + r.ms, 0);
  app.querySelector("#timing").textContent = t.timing(TIERS.length, ms.toFixed(1));
}

const knowsShort = (k) => ({
  en: { rookie: "transaction only", analyst: "+ sender's habits", expert: "all 33 signals", elite: "patched v2" },
  fr: { rookie: "transaction seule", analyst: "+ habitudes", expert: "les 33 signaux", elite: "corrigé v2" },
})[lang][k];
const decisionWord = (d) => ({ en: { approve: "approve", review: "review", block: "block" },
  fr: { approve: "accepté", review: "vérif.", block: "bloqué" } })[lang][d] ?? d;

function renderWhy() {
  const t = L(), m = models[selected], r = last.results[selected], f = last.features;
  const used = new Set(m.features);
  const order = FEATURES.map((name, i) => ({ name, i, c: r.contributions[i] }))
    .filter((x) => used.has(x.name)).sort((a, b) => Math.abs(b.c) - Math.abs(a.c)).slice(0, 10);
  const max = Math.max(0.5, ...order.map((x) => Math.abs(x.c)));
  const rows = order.map((x) => {
    const w = (Math.abs(x.c) / max) * 50;
    const bar = x.c >= 0 ? `<span class="up" style="left:50%;width:${w}%"></span>` : `<span class="down" style="left:${50 - w}%;width:${w}%"></span>`;
    return `<div class="r"><div class="f">${esc(LABELS[lang][x.name])} <small>= ${esc(formatValue(x.name, f[x.i], lang))}</small></div>
      <div class="bar">${bar}</div><div class="num">${x.c >= 0 ? "+" : ""}${x.c.toFixed(2)}</div></div>`;
  }).join("");
  const sig = (z) => 1 / (1 + Math.exp(-z));
  const reasons = r.reasons;
  app.querySelector("#why").innerHTML = `<h3 style="margin-top:6px">${t.why} · ${m.name}</h3>
    <p class="muted" style="margin:0 0 6px;font-size:13.5px">${t.whyFor(m.name)}</p>
    <div class="wf"><div class="r"><div class="f muted">${t.base}</div><div></div><div class="num muted">${pct(sig(m.bias))}</div></div>
    ${rows}
    <div class="r"><div class="f"><b>${t.final}</b></div><div></div><div class="num"><b>${pct(r.score)}</b></div></div></div>
    <h3 style="margin-top:16px">${t.reasonsTitle}</h3>
    ${reasons.length ? `<ul class="reasons">${reasons.map((x) => `<li>${esc(x.text)}</li>`).join("")}</ul>` : `<p class="muted">${t.noReasons}</p>`}`;
}

function tiersSection() {
  const t = L();
  const rented = (lvl) => {
    const by = lvl.recall_by_strategy; const v = Object.entries(by).filter(([k]) => k.endsWith("/rented")).map(([, x]) => x);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0;
  };
  const cell = (v) => `<td class="n"><span class="minibar" style="width:${Math.round(v * 60)}px"></span>${Math.round(v * 100)}%</td>`;
  const rows = TIERS.map((k) => {
    const m = models[k], a = m.test.adaptive, p = m.test.patched, s = a.review.recall_by_scenario;
    return `<tr><td><b>${m.name}</b></td><td class="muted" style="min-width:220px">${esc(knowsLong(k))}</td>
      <td class="n">${a.pr_auc.toFixed(3)}</td>${cell(a.review.recall)}${cell(s.account_takeover ?? 0)}${cell(s.withdrawal_request ?? 0)}
      ${cell(s.wrong_transfer ?? 0)}${cell(rented(p.review))}<td class="n">${a.review.false_alarms_per_10k.toFixed(1)}</td></tr>`;
  }).join("");
  return `<section class="block"><h2>${t.tiersTitle}</h2><p>${t.tiersLead}</p>
    <div class="panel tablewrap"><table class="t"><thead><tr>${t.tiersHead.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows}</tbody></table></div></section>`;
}
const knowsLong = (k) => ({
  en: { rookie: "Only the transaction: amount, balance, time of day.", analyst: "Also the sender's habits and whether they have paid this person before.",
    expert: "All 33 signals: phones, SIM swaps, receiving accounts, agents. The production model.",
    elite: "The same signals, retrained on rented-account attacks after the game exposed that blind spot." },
  fr: { rookie: "Seulement la transaction : montant, solde, heure.", analyst: "Aussi les habitudes de l'expéditeur et s'il a déjà payé cette personne.",
    expert: "Les 33 signaux : téléphones, changements de SIM, comptes destinataires, agents. Le modèle de production.",
    elite: "Les mêmes signaux, réentraîné sur les attaques par comptes loués après que le jeu a révélé cet angle mort." },
})[lang][k];

function driftSection() {
  const t = L(), d = metrics.drift;
  if (!d) return "";
  const days = d.mixed.filter((x) => x.day >= 70).map((x) => x.day);
  const series = (w) => d[w].filter((x) => x.day >= 70).map((x) => x.false_alarms_per_10k);
  const a = series("mixed"), b = series("promo");
  const flagged = d.promo.filter((x) => x.day >= 70 && x.status === "drift").map((x) => x.day);
  const W = 760, H = 240, P = { l: 40, r: 12, t: 12, b: 28 };
  const maxY = Math.ceil(Math.max(...a, ...b) / 10) * 10;
  const x = (i) => P.l + (i / (days.length - 1)) * (W - P.l - P.r);
  const y = (v) => H - P.b - (v / maxY) * (H - P.t - P.b);
  const path = (s) => s.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const band = flagged.map((day) => {
    const i = days.indexOf(day);
    return `<rect x="${(x(i) - (W - P.l - P.r) / (days.length - 1) / 2).toFixed(1)}" y="${P.t}" width="${((W - P.l - P.r) / (days.length - 1)).toFixed(1)}" height="${H - P.t - P.b}" fill="#f2a33a" opacity=".12"/>`;
  }).join("");
  const ticks = [0, maxY / 2, maxY].map((v) => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" stroke="#2a3631"/><text x="${P.l - 6}" y="${y(v) + 4}" text-anchor="end" fill="#8fa199" font-size="11" font-family="JetBrains Mono, monospace">${v}</text>`).join("");
  const xt = days.filter((_, i) => i % 2 === 0).map((dd) => `<text x="${x(days.indexOf(dd))}" y="${H - 8}" text-anchor="middle" fill="#8fa199" font-size="11" font-family="JetBrains Mono, monospace">${dd}</text>`).join("");
  return `<section class="block"><h2>${t.driftTitle}</h2><p>${t.driftLead}</p>
    <div class="panel"><svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t.driftTitle)}">${band}${ticks}${xt}
      <path d="${path(a)}" fill="none" stroke="#8fa199" stroke-width="2"/>
      <path d="${path(b)}" fill="none" stroke="#f2a33a" stroke-width="2.5"/></svg>
      <div class="legend"><span><i style="background:#8fa199"></i>${t.driftLegend[0]}</span><span><i style="background:#f2a33a"></i>${t.driftLegend[1]}</span>
      <span><i style="background:#f2a33a;opacity:.3;height:10px"></i>${t.driftLegend[2]}</span></div></div></section>`;
}

init();
