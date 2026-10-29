import { chrome, lang, onLang, loadModels, loadWorld, esc, fcfa, pct, logPos, rng, store, TIERS, REPO } from "../common.js";
import { LABELS } from "../engine/reasons.js";
import { formatValue } from "../lab/format.js";
import { Campaign, Chapter, CHAPTERS, COSTS, SCRIPTS, GameError, HOUR, DAY } from "./engine.js";
import { STORY, LINES, FINDINGS, TIPS, fill } from "./story.js";
import { portrait, handlerPortrait, heroArt, stars } from "./art.js";
import { play, muted, setMuted } from "./audio.js";

const UI = {
  en: {
    play: "Play", cont: (n, d) => `Continue: chapter ${n}, ${d}`, newGame: "New campaign", story: "Choose your story", difficulty: "Choose the model you play against",
    redteam: ["Red team", "CleverPay hires you to break its fraud model before launch."], underworld: ["Ghost Network", "A fictional crew. The same real model. A different ending."],
    diffNote: { rookie: "Sees only the transaction. Nearly blind.", analyst: "Knows the sender's habits.", expert: "The production model: all 33 signals.", elite: "Retrained on the blind spots players found." },
    caught: "fraud caught", takeovers: "takeovers", rented: "rented-account tricks",
    howto: "How to play", howtoItems: [
      "Each chapter has a profit goal and a deadline. Every move costs time; some cost money.",
      "Every transaction you attempt is scored live by a real LightGBM model. Approve: the money moves. Review: the victim is warned. Block: the number is burned.",
      "Reviews and blocks raise the security level. Each level changes the rules. It cools down if you lie low for 12 hours.",
      "Buy an inside tip to see what the model would say before you act. The fraud desk always shows you why it flagged you.",
      "When something risky gets through, it's logged as a finding: a real blind spot of that model.",
      "Week 4 is Patch Day: the model is upgraded with what players found. Your best trick may stop working."],
    goal: "Goal", cash: "Your cash", clock: "Game clock", left: "Time left", security: "Security level", model: "Model",
    levels: ["Calm", "Analysts alerted", "Blacklist", "Watchdog", "Lockdown"],
    tabs: { calls: "Calls", numbers: "Numbers", till: "Agent till", account: "Account" },
    leads: "Who to call", script: "Script", scripts: { apologetic: "Apologetic", urgent: "Urgent", official: "\"CleverPay agent\"" },
    believe: "believe you", amount: "Amount (FCFA)", toNumber: "Receiving number", call: "Call", tip: (c) => `Inside tip (${fcfa(c)})`,
    yourNumbers: "Your numbers", newSim: (c) => `New SIM (${fcfa(c)})`, market: "Rental market: old accounts", rent: "Rent", years: "years", tx: "transactions",
    cut: (p) => `owner keeps ${Math.round(p * 100)}%`, none: "None yet.",
    requests: "Requests", reqAmount: "Amount", targets: "Targets", spread: "Spread over", local: "Same town", national: "Everywhere", varied: "Varied",
    sendReq: "Send requests", switchTill: (c) => `Move to another till (${fcfa(c)})`,
    victim: "Victim", balance: "Balance", enterPin: "Fake agent call (5 days)", enterSim: "SIM swap (36 h)", usePin: "Use the leaked PIN",
    noVictim: "No account to work on yet. A believer might leak their PIN if you call as a \"CleverPay agent\".",
    send: "Transfer", warmup: (c) => `Warm up the phone (buy ${fcfa(c)} airtime)`, wait: "Wait", giveUp: "Give up",
    desk: "Fraud desk", lastCheck: "Last check", noCheck: "Nothing scored yet. Your first move will show up here.",
    score: "fraud score", review: "review", block: "block", approve: "approve", factors: "What pushed the score",
    intel: "Inside tip", intelFor: "If you did that now:", would: { approve: "would pass", review: "would be reviewed", block: "would be blocked" },
    feed: "What happened", rival: "rival",
    brief: "Briefing", start: "Start", goalK: "Profit goal", daysK: "Time", cashK: "Your cash", modelK: "Model on duty",
    result: { time_up: "Time's up", caught: "Caught", quit: "You walked away", noticed: "The owner noticed" },
    profit: "Profit", beatRival: (r) => `You beat ${r}!`, lostRival: (r, v) => `${r} made ${v}.`,
    newFindings: "Blind spots found this chapter", next: "Next chapter", retry: "Try again", moveOn: "Move on (0 stars)", toTitle: "Title screen", finish: "See the final report",
    goalMissed: "Goal missed. Try this chapter again: your cash goes back to what it was at the start.",
    report: "Final report", totalStars: "Stars", findingsAll: "Everything the model missed", protect: "How real people protect themselves",
    download: "Download your attempts (JSON) for retraining", again: "Play again", labLink: "Explore the model in the Model Lab",
    errors: { no_cash: "Not enough cash.", too_many: "You already have 5 working numbers.", over: "This chapter is over.", wrong_mission: "Not available in this chapter.",
      no_victim: "No account to work on yet.", not_in: "Get into the account first.", burned: "That number is burned.", not_yours: "That's not your number.",
      no_offers: "No accounts for rent right now.", no_lead: "Pick someone to call." },
    personas: { retired: "retired", trader: "trader", student: "student", teacher: "teacher" }, wealth: { comfortable: "comfortable", getting_by: "getting by", tight: "short of money" },
    mute: ["Sound on", "Sound off"], hours: "h", daysShort: "d", needNumber: "All your numbers are burned: buy a SIM or rent an account in the Numbers tab.",
    reactions: { firstBlock: "Blocked. Look at the fraud desk: it tells you exactly what gave you away.", firstFinding: "That got through. Note what you did: that's a blind spot.",
      highHeat: "Security level 3. Lie low or change your approach.", leak: "A PIN! Open the Account tab." },
    reactionsUw: { firstBlock: "Blocked. The machine always says why. Read it.", firstFinding: "Ha. It didn't see that one. Remember it.",
      highHeat: "Too hot. Lie low before you burn us all.", leak: "We've got a PIN. Account tab, now." },
  },
  fr: {
    play: "Jouer", cont: (n, d) => `Continuer : chapitre ${n}, ${d}`, newGame: "Nouvelle campagne", story: "Choisissez votre histoire", difficulty: "Choisissez le modèle à affronter",
    redteam: ["Red team", "CleverPay vous engage pour casser son modèle anti-fraude avant le lancement."], underworld: ["Réseau Fantôme", "Une bande fictive. Le même vrai modèle. Une autre fin."],
    diffNote: { rookie: "Ne voit que la transaction. Presque aveugle.", analyst: "Connaît les habitudes de l'expéditeur.", expert: "Le modèle de production : les 33 signaux.", elite: "Réentraîné sur les angles morts trouvés par les joueurs." },
    caught: "fraude détectée", takeovers: "piratages", rented: "astuces comptes loués",
    howto: "Comment jouer", howtoItems: [
      "Chaque chapitre a un objectif de gain et une date limite. Chaque action prend du temps ; certaines coûtent de l'argent.",
      "Chaque transaction tentée est évaluée en direct par un vrai modèle LightGBM. Accepté : l'argent passe. Vérification : la victime est avertie. Blocage : le numéro est grillé.",
      "Vérifications et blocages font monter le niveau de sécurité. Chaque niveau change les règles. Il redescend si vous vous faites oublier 12 heures.",
      "Achetez un tuyau d'initié pour voir ce que dirait le modèle avant d'agir. La cellule anti-fraude vous montre toujours pourquoi elle vous a signalé.",
      "Quand quelque chose de risqué passe, c'est noté comme découverte : un vrai angle mort de ce modèle.",
      "La semaine 4, c'est le jour du correctif : le modèle est mis à jour avec ce que les joueurs ont trouvé. Votre meilleure astuce peut cesser de marcher."],
    goal: "Objectif", cash: "Votre argent", clock: "Horloge", left: "Temps restant", security: "Niveau de sécurité", model: "Modèle",
    levels: ["Calme", "Analystes en alerte", "Liste noire", "Chien de garde", "Confinement"],
    tabs: { calls: "Appels", numbers: "Numéros", till: "Caisse", account: "Compte" },
    leads: "Qui appeler", script: "Discours", scripts: { apologetic: "Désolé", urgent: "Pressé", official: "« Agent CleverPay »" },
    believe: "vous croient", amount: "Montant (FCFA)", toNumber: "Numéro de réception", call: "Appeler", tip: (c) => `Tuyau d'initié (${fcfa(c)})`,
    yourNumbers: "Vos numéros", newSim: (c) => `Nouvelle SIM (${fcfa(c)})`, market: "Marché de location : vieux comptes", rent: "Louer", years: "ans", tx: "transactions",
    cut: (p) => `le titulaire garde ${Math.round(p * 100)} %`, none: "Aucun pour l'instant.",
    requests: "Demandes", reqAmount: "Montant", targets: "Cibles", spread: "Étalées sur", local: "Même ville", national: "Partout", varied: "Variés",
    sendReq: "Envoyer les demandes", switchTill: (c) => `Changer de caisse (${fcfa(c)})`,
    victim: "Victime", balance: "Solde", enterPin: "Faux appel d'agent (5 jours)", enterSim: "Changement de SIM (36 h)", usePin: "Utiliser le PIN obtenu",
    noVictim: "Pas encore de compte. Quelqu'un qui vous croit pourrait laisser fuiter son PIN si vous appelez en « agent CleverPay ».",
    send: "Transférer", warmup: (c) => `Réchauffer le téléphone (acheter ${fcfa(c)} de crédit)`, wait: "Attendre", giveUp: "Abandonner",
    desk: "Cellule anti-fraude", lastCheck: "Dernier contrôle", noCheck: "Rien d'évalué pour l'instant. Votre première action apparaîtra ici.",
    score: "score de fraude", review: "vérif.", block: "blocage", approve: "accepté", factors: "Ce qui a pesé",
    intel: "Tuyau d'initié", intelFor: "Si vous faisiez ça maintenant :", would: { approve: "passerait", review: "serait vérifié", block: "serait bloqué" },
    feed: "Ce qui s'est passé", rival: "rival",
    brief: "Briefing", start: "Commencer", goalK: "Objectif de gain", daysK: "Durée", cashK: "Votre argent", modelK: "Modèle en service",
    result: { time_up: "Temps écoulé", caught: "Pris", quit: "Abandon", noticed: "Le titulaire s'en est rendu compte" },
    profit: "Gain", beatRival: (r) => `Vous avez battu ${r} !`, lostRival: (r, v) => `${r} a fait ${v}.`,
    newFindings: "Angles morts trouvés dans ce chapitre", next: "Chapitre suivant", retry: "Réessayer", moveOn: "Passer (0 étoile)", toTitle: "Écran titre", finish: "Voir le rapport final",
    goalMissed: "Objectif manqué. Rejouez ce chapitre : votre argent revient à ce qu'il était au début.",
    report: "Rapport final", totalStars: "Étoiles", findingsAll: "Tout ce que le modèle n'a pas vu", protect: "Comment les vraies personnes se protègent",
    download: "Télécharger vos tentatives (JSON) pour le réentraînement", again: "Rejouer", labLink: "Explorer le modèle dans le Labo",
    errors: { no_cash: "Pas assez d'argent.", too_many: "Vous avez déjà 5 numéros actifs.", over: "Ce chapitre est terminé.", wrong_mission: "Indisponible dans ce chapitre.",
      no_victim: "Pas encore de compte.", not_in: "Entrez d'abord dans le compte.", burned: "Ce numéro est grillé.", not_yours: "Ce n'est pas votre numéro.",
      no_offers: "Aucun compte à louer pour l'instant.", no_lead: "Choisissez quelqu'un à appeler." },
    personas: { retired: "retraité·e", trader: "commerçant·e", student: "étudiant·e", teacher: "enseignant·e" }, wealth: { comfortable: "à l'aise", getting_by: "s'en sort", tight: "à court d'argent" },
    mute: ["Son activé", "Son coupé"], hours: "h", daysShort: "j", needNumber: "Tous vos numéros sont grillés : achetez une SIM ou louez un compte dans l'onglet Numéros.",
    reactions: { firstBlock: "Bloqué. Regardez la cellule anti-fraude : elle dit exactement ce qui vous a trahi.", firstFinding: "Ça, c'est passé. Notez ce que vous avez fait : c'est un angle mort.",
      highHeat: "Niveau de sécurité 3. Faites-vous oublier ou changez d'approche.", leak: "Un code PIN ! Ouvrez l'onglet Compte." },
    reactionsUw: { firstBlock: "Bloqué. La machine dit toujours pourquoi. Lis-la.", firstFinding: "Ha. Elle n'a pas vu celle-là. Retiens-la.",
      highHeat: "Trop chaud. Fais-toi oublier avant de tous nous griller.", leak: "On a un PIN. Onglet Compte, maintenant." },
  },
};
const U = () => UI[lang];
const S = () => STORY[campaign?.storyline ?? sel.storyline][lang];
const app = document.getElementById("app"), modal = document.getElementById("modal");

let world, models;
let campaign = null, chapter = null, attempt = 0, seenLog = 0, reacted = new Set(), handlerNotes = [];
const sel = { storyline: store.get("ld-story", "redteam"), difficulty: store.get("ld-diff", "expert") };
const ui = { tab: null, lead: null, script: "apologetic", amount: 5000, to: null, stealAmount: 5000, stealTo: null,
  count: 30, reqAmount: "varied", targets: "local", spread: "2h", error: "" };

chrome("play");
let screen = "title";
onLang(() => {
  if (screen === "play" && chapter) { chapter.lang = lang; renderPlay(); }
  else if (screen === "end") renderEnd();
  else renderTitle();
});

async function init() {
  try { [world, models] = await Promise.all([loadWorld(), loadModels()]); }
  catch (e) { app.innerHTML = `<p class="loading">Could not load the game data (${esc(e.message)}).</p>`; return; }
  const saved = store.get("ld-campaign");
  if (saved) { try { campaign = Campaign.fromJSON(JSON.parse(saved)); } catch { campaign = null; } }
  renderTitle();
}
const save = () => store.set("ld-campaign", JSON.stringify(campaign));

// -- title -----------------------------------------------------------------------------------------
function renderTitle() {
  chapter = null; screen = "title"; closeModal();
  const u = U(), st = STORY[sel.storyline][lang];
  const stat = (k) => {
    const m = models[k], a = m.test.adaptive.review, p = m.test.patched.review;
    const rented = Object.entries(p.recall_by_strategy).filter(([n]) => n.endsWith("/rented")).map(([, v]) => v);
    return `<div class="diff-stats"><span><b>${Math.round(a.recall * 100)}%</b> ${u.caught}</span><span><b>${Math.round((a.recall_by_scenario.account_takeover ?? 0) * 100)}%</b> ${u.takeovers}</span>
      <span><b>${Math.round((rented.reduce((x, y) => x + y, 0) / Math.max(rented.length, 1)) * 100)}%</b> ${u.rented}</span></div>`;
  };
  const canContinue = campaign && !campaign.done;
  app.innerHTML = `<section class="title-screen">
    <div><h1>${esc(st.title.split(" ")[0])} <span>${esc(st.title.split(" ").slice(1).join(" "))}</span></h1>
      <p class="lead">${esc(st.tagline)}</p><p class="muted">${esc(chromeNote())}</p>
      <div class="go-row">${canContinue ? `<button class="btn sun" id="continue">${esc(u.cont(campaign.chapterIndex + 1, models[campaign.difficulty].name))}</button>` : ""}
        <button class="btn ${canContinue ? "ghost" : "sun"}" id="new">${canContinue ? u.newGame : u.play}</button>
        ${campaign?.done ? `<button class="btn ghost" id="report">${u.report}</button>` : ""}
        <button class="icon-btn" id="mute">${muted ? u.mute[1] : u.mute[0]}</button></div></div>
    <div>${heroArt()}</div></section>
    <div class="pickers">
      <div><p class="pick-title">${u.story}</p><div class="cards">${["redteam", "underworld"].map((k) =>
        `<button class="card-pick ${sel.storyline === k ? "on" : ""}" data-story="${k}">${handlerPortrait(k, 52)}<div><b>${u[k][0]}</b><small>${esc(u[k][1])}</small></div></button>`).join("")}</div></div>
      <div><p class="pick-title">${u.difficulty}</p><div class="cards">${TIERS.map((k) =>
        `<button class="card-pick ${sel.difficulty === k ? "on" : ""}" data-diff="${k}"><div><b>${models[k].name}</b><small>${esc(u.diffNote[k])}</small>${stat(k)}</div></button>`).join("")}</div></div>
    </div>
    <details class="howto"><summary>${u.howto}</summary><ul>${u.howtoItems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>`;
  app.querySelectorAll("[data-story]").forEach((b) => b.addEventListener("click", () => { sel.storyline = b.dataset.story; store.set("ld-story", sel.storyline); play("click"); renderTitle(); }));
  app.querySelectorAll("[data-diff]").forEach((b) => b.addEventListener("click", () => { sel.difficulty = b.dataset.diff; store.set("ld-diff", sel.difficulty); play("click"); renderTitle(); }));
  app.querySelector("#new").addEventListener("click", () => {
    campaign = new Campaign({ storyline: sel.storyline, difficulty: sel.difficulty, seed: Math.floor(Math.random() * 1e9) });
    save(); showBriefing();
  });
  app.querySelector("#continue")?.addEventListener("click", showBriefing);
  app.querySelector("#report")?.addEventListener("click", renderEnd);
  app.querySelector("#mute").addEventListener("click", () => { setMuted(!muted); renderTitle(); });
}
const chromeNote = () => (lang === "en"
  ? "CleverPay is fictional. The fraud model is real: it runs in your browser, the same one the Model Lab explains."
  : "CleverPay est fictive. Le modèle anti-fraude est réel : il tourne dans votre navigateur, le même que celui expliqué dans le Labo.");

// -- briefing ------------------------------------------------------------------------------------------
function showBriefing() {
  const u = U(), st = S(), spec = CHAPTERS[campaign.chapterIndex];
  const [title, text] = st.chapters[spec.id];
  const key = campaign.modelKey(), prev = campaign.modelKey(campaign.chapterIndex - 1 >= 0 ? campaign.chapterIndex - 1 : 0);
  let patch = "";
  if (spec.patch) patch = campaign.difficulty === "elite" ? st.patchNoteElite : st.patchNote(models[TIERS[TIERS.indexOf(key) - 1] ?? key].name, models[key].name);
  else if (prev !== key) patch = st.patchNote(models[prev].name, models[key].name);
  openModal(`<div class="dialog"><div class="brief-head">${handlerPortrait(campaign.storyline, 72)}<div><b>${esc(st.handler)}</b><small>${esc(st.handlerRole)}</small></div></div>
    <p class="kicker">${u.brief}</p><h2>${esc(title)}</h2><p>${esc(text)}</p>
    ${patch ? `<div class="patch-note">${esc(patch)}</div>` : ""}
    <div class="facts"><div><div class="k">${u.goalK}</div><div class="v">${fcfa(spec.goal)}</div></div>
      <div><div class="k">${u.daysK}</div><div class="v">${spec.days} ${u.daysShort}</div></div>
      <div><div class="k">${u.cashK}</div><div class="v">${fcfa(campaign.cash)}</div></div>
      <div><div class="k">${u.modelK}</div><div class="v">${models[key].name}</div></div></div>
    <div class="go-row"><button class="btn sun" id="start">${u.start}</button><button class="btn ghost" id="title">${u.toTitle}</button></div></div>`);
  modal.querySelector("#start").addEventListener("click", () => { closeModal(); startChapter(); });
  modal.querySelector("#title").addEventListener("click", () => { closeModal(); renderTitle(); });
}

function startChapter() {
  attempt += 1;
  chapter = new Chapter(campaign, world, models, rng(campaign.seed + campaign.chapterIndex * 7919 + attempt * 104729));
  chapter.lang = lang;
  seenLog = 0; reacted = new Set(); handlerNotes = [];
  const kinds = chapter.spec.kinds;
  ui.tab = kinds.includes("refund") ? "calls" : kinds.includes("requests") ? "till" : "account";
  ui.lead = chapter.leads[0]?.account ?? null; ui.to = null; ui.stealTo = null; ui.error = "";
  handlerNotes.push(S().chapters[chapter.spec.id][1]);
  renderPlay();
}

// -- the game screen ------------------------------------------------------------------------------------
function renderPlay() {
  screen = "play";
  const c = chapter, u = U();
  const st = S();
  const keep = {};
  app.querySelectorAll(".screen input, .screen select").forEach((el) => { if (el.id) keep[el.id] = el.value; });
  // the bar runs to the rival's score; the tick marks your goal
  const goalPct = Math.max(0, Math.min(100, (c.profit / c.spec.rival) * 100));
  const lvl = c.level;
  const heat = Array.from({ length: 4 }, (_, i) => {
    const fill = Math.max(0, Math.min(1, (c.pips - i * 3) / 3));
    return `<i class="l${i + 1}"><span style="transform:scaleX(${fill})"></span></i>`;
  }).join("");
  const left = Math.max(0, c.deadline - c.now);
  app.innerHTML = `
    <div class="hud" id="hud">
      <div class="goal"><div class="k">${esc(st.chapters[c.spec.id][0])} · ${u.goal} ${fcfa(c.spec.goal)} FCFA</div>
        <div class="v" style="color:${c.profit >= c.spec.goal ? "var(--good)" : c.profit < 0 ? "var(--bad)" : ""}">${u.profit}: ${fcfa(c.profit)}</div>
        <div class="goalbar"><div class="fill" style="width:${goalPct}%"></div><div class="rival" style="left:${(c.spec.goal / c.spec.rival) * 100}%" data-label="${u.goal}"></div><div class="rival" style="left:calc(100% - 2px);background:var(--muted)" data-label="${esc(st.rival)} ${fcfa(c.spec.rival)}"></div></div></div>
      <div><div class="k">${u.cash}</div><div class="v">${fcfa(c.cash)}</div></div>
      <div><div class="k">${u.clock}</div><div class="v" style="font-size:15px">${clock(c.now)}</div></div>
      <div><div class="k">${u.left}</div><div class="v">${left >= DAY ? `${Math.floor(left / DAY)}${u.daysShort} ${Math.floor((left % DAY) / HOUR)}${u.hours}` : `${Math.floor(left / HOUR)}${u.hours} ${Math.floor((left % HOUR) / 60)}m`}</div></div>
      <div id="heatbox"><div class="k">${u.security}: ${lvl}</div><div class="heat">${heat}</div><div class="heat-label">${esc(u.levels[lvl])}</div></div>
    </div>
    <div class="board">
      <div class="phone"><div class="screen">
        <div class="bar"><span>CleverPay</span><span>${clock(c.now).slice(-5)}</span></div>
        ${tabsHtml()}
        <div id="tab">${tabHtml()}</div>
        <div class="err" id="err">${esc(ui.error)}</div>
        <div class="row3">${["1h", "6h", "1d"].map((d) => `<button class="pbtn alt" data-wait="${d}">${u.wait} ${d.replace("h", u.hours).replace("d", u.daysShort)}</button>`).join("")}</div>
        <button class="pbtn danger" id="giveup">${u.giveUp}</button>
      </div></div>
      <div class="desk">${deskHtml()}</div>
      <div class="panel feed"><h3>${u.feed}</h3><div class="msgs" id="msgs">${feedHtml()}</div></div>
    </div>`;
  Object.entries(keep).forEach(([id, v]) => { const el = document.getElementById(id); if (el && (el.tagName !== "SELECT" || [...el.options].some((o) => o.value === v))) el.value = v; });
  bindPlay();
}

const clock = (t) => {
  const d = new Date(chapter.net.start.getTime() + t * 1000);
  const wd = d.toLocaleDateString(lang === "fr" ? "fr-FR" : "en-GB", { weekday: "short", timeZone: "UTC" });
  return `${wd} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};

function tabsHtml() {
  const u = U(), kinds = chapter.spec.kinds;
  const tabs = [];
  if (kinds.includes("refund")) tabs.push("calls");
  if (kinds.includes("refund") || kinds.includes("takeover")) tabs.push("numbers");
  if (kinds.includes("requests")) tabs.push("till");
  if (kinds.includes("takeover")) tabs.push("account");
  if (!tabs.includes(ui.tab)) ui.tab = tabs[0];
  return `<div class="tabs">${tabs.map((t) => `<button data-tab="${t}" class="${ui.tab === t ? "on" : ""}">${u.tabs[t]}${t === "account" && chapter.victim && !chapter.entered ? " •" : ""}</button>`).join("")}</div>`;
}

function numbersSelect(id, value) {
  const usable = chapter.usable();
  return `<select id="${id}">${usable.map((o) => `<option value="${o.account}" ${o.account === value ? "selected" : ""}>${o.account}${o.rented ? ` ★ ${o.region}` : ""}</option>`).join("")}</select>`;
}

function tabHtml() {
  const c = chapter, u = U();
  if (ui.tab === "calls") {
    if (!c.leads.some((l) => l.account === ui.lead)) ui.lead = c.leads[0]?.account ?? null;
    const lead = c.leads.find((l) => l.account === ui.lead);
    return `<div class="pfield">${u.leads}</div>
      ${c.leads.map((l) => `<button class="leadcard ${l.account === ui.lead ? "on" : ""}" data-lead="${l.account}">${portrait({ seed: l.seed, female: l.female, persona: l.persona, size: 48 })}
        <div><b>${esc(l.name)}</b><small>${u.personas[l.persona]} · ${esc(l.region)} · ${u.wealth[l.wealth]}</small></div></button>`).join("")}
      <div class="pfield">${u.script}</div>
      <div class="opt">${Object.keys(SCRIPTS).map((s) => `<button data-script="${s}" class="${ui.script === s ? "on" : ""}">${u.scripts[s]}${lead ? `<small>${Math.round(c.belief(lead, s, ui.amount) * 100)}% ${u.believe}</small>` : ""}</button>`).join("")}</div>
      <div class="pfield">${u.amount}</div>
      <div class="opt four">${[2000, 5000, 15000, 30000].map((a) => `<button data-amount="${a}" class="${ui.amount === a ? "on" : ""}">${fcfa(a)}</button>`).join("")}</div>
      ${c.usable().length ? `<label class="pfield">${u.toNumber}${numbersSelect("call-to", ui.to)}</label>` : `<div class="err">${u.needNumber}</div>`}
      <div class="row2"><button class="pbtn" id="do-call" ${lead && c.usable().length ? "" : "disabled"}>${u.call}</button>
        <button class="pbtn sun" id="tip-call" ${lead && c.usable().length ? "" : "disabled"}>${u.tip(COSTS.intel)}</button></div>`;
  }
  if (ui.tab === "numbers") {
    return `<div class="pc"><div class="lbl">${u.yourNumbers}</div>${c.owned.length ? c.owned.map((o) => `<div class="acct ${o.burned ? "burned" : ""}"><span>${o.account}${o.rented ? `<span class="tag">★ ${esc(o.region)}</span>` : ""}</span><span>${fcfa(c.net.balance.get(o.account))}</span></div>`).join("") : `<div class="lbl">${u.none}</div>`}</div>
      <button class="pbtn alt" id="new-sim">${u.newSim(COSTS.sim)}</button>
      <div class="pfield">${u.market}</div>
      ${c.offers.map((o) => `<div class="offer"><div><b>${o.account}</b> · ${esc(o.region)}<small>${o.years.toFixed(1)} ${u.years} · ${o.activity} ${u.tx} · ${u.cut(COSTS.rentCut)}</small></div>
        <button data-rent="${o.account}">${u.rent} ${fcfa(Math.round(o.price * (c.level >= 2 ? 1.5 : 1)))}</button></div>`).join("")}`;
  }
  if (ui.tab === "till") {
    return `<div class="pc"><div class="lbl">Agent</div><b class="mono">${c.agent}</b> · ${esc(c.net.region.get(c.agent))}</div>
      <div class="pfield">${u.requests}</div><div class="opt">${[10, 30, 100].map((n) => `<button data-count="${n}" class="${ui.count === n ? "on" : ""}">${n}</button>`).join("")}</div>
      <div class="pfield">${u.reqAmount}</div><div class="opt">${[["5000", "5 000"], ["25000", "25 000"], ["varied", u.varied]].map(([v, l]) => `<button data-reqamount="${v}" class="${ui.reqAmount === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="pfield">${u.targets}</div><div class="opt two">${[["local", u.local], ["national", u.national]].map(([v, l]) => `<button data-targets="${v}" class="${ui.targets === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="pfield">${u.spread}</div><div class="opt">${["10m", "2h", "1d"].map((v) => `<button data-spread="${v}" class="${ui.spread === v ? "on" : ""}">${v.replace("d", u.daysShort).replace("h", u.hours)}</button>`).join("")}</div>
      <button class="pbtn" id="do-req">${u.sendReq}</button>
      <button class="pbtn alt" id="switch-till">${u.switchTill(COSTS.till)}</button>`;
  }
  // account (takeover)
  if (!c.victim) return `<div class="pc"><div class="lbl">${u.noVictim}</div></div>`;
  const v = c.victim;
  const head = `<div class="pc" style="display:grid;grid-template-columns:52px 1fr;gap:10px;align-items:center">${portrait({ seed: v.seed, female: v.female, persona: v.persona, size: 52 })}
    <div><div class="lbl">${u.victim} · ${u.personas[v.persona]} · ${esc(v.region)}</div><b>${esc(v.name)}</b><div class="mono" style="font-size:18px;font-weight:700">${fcfa(c.net.balance.get(v.account))} FCFA</div></div></div>`;
  if (!c.entered) {
    if (c.leakedFrom) return `${head}<button class="pbtn sun" id="enter-pin">${u.usePin}</button>`;
    return `${head}<div class="row2"><button class="pbtn" id="enter-pin">${u.enterPin}</button><button class="pbtn alt" id="enter-sim">${u.enterSim}</button></div>`;
  }
  return `${head}
    <label class="pfield">${u.amount}<input id="steal-amount" type="number" min="500" step="500" value="${ui.stealAmount}"></label>
    ${c.usable().length ? `<label class="pfield">${u.toNumber}${numbersSelect("steal-to", ui.stealTo)}</label>` : `<div class="err">${u.needNumber}</div>`}
    <div class="row2"><button class="pbtn" id="do-steal" ${c.usable().length ? "" : "disabled"}>${u.send}</button><button class="pbtn sun" id="tip-steal" ${c.usable().length ? "" : "disabled"}>${u.tip(COSTS.intel)}</button></div>
    <button class="pbtn alt" id="warmup">${u.warmup(COSTS.airtime)}</button>`;
}

function gauge(score, th) {
  return `<div class="gauge" style="--r:${(logPos(th.review) * 100).toFixed(1)}%;--b:${(logPos(th.block) * 100).toFixed(1)}%">
    <span class="sc" style="left:${(logPos(score) * 100).toFixed(1)}%">${pct(score)}</span><span class="needle" style="left:calc(${(logPos(score) * 100).toFixed(1)}% - 2px)"></span></div>
    <div class="scale"><span>0.01%</span><span>0.1%</span><span>1%</span><span>10%</span><span>100%</span></div>`;
}
function contribHtml(top) {
  const u = U();
  const max = Math.max(0.5, ...top.map((x) => Math.abs(x.contribution)));
  return `<div class="contrib"><div class="pick-title" style="margin:0">${u.factors}</div>${top.map((x) => `<div class="r"><div>${esc(LABELS[lang][x.feature])} <small>= ${esc(formatValue(x.feature, x.value, lang))}</small></div>
    <div><div class="bar ${x.contribution >= 0 ? "up" : "down"}" style="width:${Math.max(4, (Math.abs(x.contribution) / max) * 90)}px"></div></div></div>`).join("")}</div>`;
}

function deskHtml() {
  const c = chapter, u = U(), m = models[c.modelKey];
  const last = c.lastCheck;
  const check = last ? `<div class="verdict"><span class="d ${last.decision}">${u[last.decision] ?? last.decision}</span><span class="muted mono">${u.score} ${pct(last.score)} · ${fcfa(last.amount)} FCFA</span></div>
      ${gauge(last.score, last.thresholds)}
      ${last.reasons.length && last.decision !== "approve" ? `<ul style="margin:10px 0 0;padding-left:18px">${last.reasons.map((r) => `<li>${esc(r.text)}</li>`).join("")}</ul>` : ""}
      ${contribHtml(last.top)}` : `<p class="muted">${u.noCheck}</p>`;
  const intel = c.intel ? `<div class="panel intel"><span class="stamp">${u.intel.toUpperCase()}</span><p style="margin:0 0 4px">${u.intelFor} <b class="${c.intel.decision}" style="color:var(--${c.intel.decision === "approve" ? "good" : c.intel.decision === "review" ? "warn" : "bad"})">${u.would[c.intel.decision]}</b></p>
      ${gauge(c.intel.score, c.intel.thresholds)}${contribHtml(c.intel.top)}</div>` : "";
  return `<div class="panel"><div class="model-badge"><span class="dot"></span><div><b>${u.model}: ${m.name}${c.tighten < 1 ? " +" : ""}</b><div class="muted" style="font-size:13px">${esc(knowsShort(c.modelKey))}</div></div></div></div>
    <div class="panel check"><h3>${u.desk} · ${u.lastCheck}</h3>${check}</div>${intel}`;
}
const knowsShort = (k) => U().diffNote[k];

function feedHtml() {
  const c = chapter, st = S(), u = U();
  const lines = LINES[lang];
  const hp = handlerPortrait(campaign.storyline, 44);
  const notes = handlerNotes.map((n) => `<div class="handler-msg ${campaign.storyline === "underworld" ? "uw" : ""}">${hp}<div><b>${esc(st.handler)}</b>${esc(n)}</div></div>`).reverse();
  const items = c.log.filter((e) => e.kind !== "brief").map((e) => {
    let key = e.key;
    if (key === "received" && e.vars.cut) key = "received_cut";
    let text;
    if (e.kind === "finding") text = findingSentence(e.vars);
    else text = fill(lines[key] ?? key, e.vars, fcfa);
    return `<div class="msg ${e.kind}"><span class="t">${clock(e.t).slice(-5)}</span><span class="x">${esc(text)}</span></div>`;
  }).reverse();
  return [...notes.slice(0, 1), ...items, ...notes.slice(1)].join("");
}

function findingSentence(f) {
  const F = FINDINGS[lang];
  const list = f.signals.map((s) => F.signals[s]);
  const joined = list.length > 1 ? `${list.slice(0, -1).join(", ")} ${lang === "en" ? "and" : "et"} ${list.at(-1)}` : list[0];
  return F.sentence(F.how[f.how] ?? f.how, joined, models[f.model].name);
}

function bindPlay() {
  const $ = (s) => app.querySelector(s);
  app.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { ui.tab = b.dataset.tab; ui.error = ""; play("click"); renderPlay(); }));
  app.querySelectorAll("[data-lead]").forEach((b) => b.addEventListener("click", () => { ui.lead = b.dataset.lead; renderPlay(); }));
  app.querySelectorAll("[data-script]").forEach((b) => b.addEventListener("click", () => { ui.script = b.dataset.script; renderPlay(); }));
  app.querySelectorAll("[data-amount]").forEach((b) => b.addEventListener("click", () => { ui.amount = Number(b.dataset.amount); renderPlay(); }));
  app.querySelectorAll("[data-count]").forEach((b) => b.addEventListener("click", () => { ui.count = Number(b.dataset.count); renderPlay(); }));
  app.querySelectorAll("[data-reqamount]").forEach((b) => b.addEventListener("click", () => { ui.reqAmount = b.dataset.reqamount; renderPlay(); }));
  app.querySelectorAll("[data-targets]").forEach((b) => b.addEventListener("click", () => { ui.targets = b.dataset.targets; renderPlay(); }));
  app.querySelectorAll("[data-spread]").forEach((b) => b.addEventListener("click", () => { ui.spread = b.dataset.spread; renderPlay(); }));
  $("#call-to")?.addEventListener("change", (e) => { ui.to = e.target.value; });
  $("#steal-to")?.addEventListener("change", (e) => { ui.stealTo = e.target.value; });
  $("#steal-amount")?.addEventListener("input", (e) => { ui.stealAmount = Number(e.target.value); });
  const callPlan = () => ({ lead: ui.lead, script: ui.script, amount: ui.amount, to: $("#call-to").value });
  $("#do-call")?.addEventListener("click", () => { play("ring"); act(() => chapter.call(callPlan())); });
  $("#tip-call")?.addEventListener("click", () => act(() => chapter.buyIntel({ kind: "call", ...callPlan() })));
  const stealPlan = () => ({ to: $("#steal-to").value, amount: Math.max(500, Number($("#steal-amount").value) || 0) });
  $("#do-steal")?.addEventListener("click", () => act(() => chapter.steal(stealPlan())));
  $("#tip-steal")?.addEventListener("click", () => act(() => chapter.buyIntel({ kind: "steal", ...stealPlan() })));
  $("#warmup")?.addEventListener("click", () => act(() => chapter.warmup()));
  $("#enter-pin")?.addEventListener("click", () => act(() => chapter.enter("pin")));
  $("#enter-sim")?.addEventListener("click", () => act(() => chapter.enter("sim")));
  $("#new-sim")?.addEventListener("click", () => act(() => chapter.openNumber()));
  app.querySelectorAll("[data-rent]").forEach((b) => b.addEventListener("click", () => act(() => chapter.rentAccount(b.dataset.rent))));
  $("#do-req")?.addEventListener("click", () => act(() => chapter.requests({ count: ui.count, amount: ui.reqAmount, targets: ui.targets, spread: ui.spread })));
  $("#switch-till")?.addEventListener("click", () => act(() => chapter.switchTill()));
  app.querySelectorAll("[data-wait]").forEach((b) => b.addEventListener("click", () => act(() => chapter.wait(b.dataset.wait))));
  $("#giveup").addEventListener("click", () => act(() => chapter.giveUp()));
}

function act(fn) {
  ui.error = "";
  const levelBefore = chapter.level;
  try { fn(); } catch (e) {
    if (e instanceof GameError) ui.error = U().errors[e.code] ?? e.code;
    else { console.error(e); ui.error = e.message; }
  }
  // sounds and the handler's reactions to what just happened
  const fresh = chapter.log.slice(seenLog);
  seenLog = chapter.log.length;
  const R = campaign.storyline === "underworld" ? U().reactionsUw : U().reactions;
  const react = (k) => { if (!reacted.has(k)) { reacted.add(k); handlerNotes.push(R[k]); } };
  if (fresh.some((e) => e.key === "blocked" || e.key === "request_blocked" || e.key === "account_frozen")) { play("block"); react("firstBlock"); }
  else if (fresh.some((e) => e.kind === "review")) play("review");
  else if (fresh.some((e) => e.kind === "good" || (e.key === "batch" && e.vars.paid > 0))) play("cash");
  if (fresh.some((e) => e.kind === "finding")) react("firstFinding");
  if (fresh.some((e) => e.key === "pin_leaked")) { react("leak"); }
  if (chapter.level > levelBefore) { play("level"); if (chapter.level >= 3) react("highHeat"); }
  renderPlay();
  if (chapter.level > levelBefore) app.querySelector("#heatbox")?.classList.add("shake");
  if (chapter.over) setTimeout(showResult, 450);
}

// -- results -------------------------------------------------------------------------------------------
function showResult() {
  const c = chapter, u = U(), st = S(), r = c.result;
  const fresh = campaign.findings.filter((f) => f.chapter === c.spec.id && f.model === c.modelKey);
  play(r.met ? "win" : "lose");
  const last = campaign.chapterIndex === CHAPTERS.length - 1;
  openModal(`<div class="dialog"><div class="brief-head">${handlerPortrait(campaign.storyline, 64)}<div><b>${esc(st.handler)}</b><small>${esc(r.met ? st.win : st.lose)}</small></div></div>
    <p class="kicker">${esc(st.chapters[c.spec.id][0])}</p><h2>${u.result[r.outcome] ?? r.outcome}</h2>
    <div class="stars-row">${stars(r.stars)}</div>
    <div class="big" style="color:${r.met ? "var(--good)" : "var(--bad)"}">${fcfa(r.profit)} FCFA</div>
    <p class="muted">${u.goal}: ${fcfa(c.spec.goal)} · ${r.beatRival ? u.beatRival(st.rival) : u.lostRival(st.rival, fcfa(c.spec.rival))}</p>
    ${fresh.length ? `<h3 class="kicker" style="margin-top:14px">${u.newFindings}</h3><ul class="finding-list">${fresh.map((f) => `<li>${esc(findingSentence(f))}</li>`).join("")}</ul>` : ""}
    ${r.met ? "" : `<p>${u.goalMissed}</p>`}
    <div class="go-row">${r.met ? `<button class="btn sun" id="next">${last ? u.finish : u.next}</button>` : `<button class="btn sun" id="retry">${u.retry}</button><button class="btn ghost" id="moveon">${u.moveOn}</button>`}
      <button class="btn ghost" id="stay">${U().feed}</button><button class="btn ghost" id="title">${u.toTitle}</button></div></div>`);
  modal.querySelector("#next")?.addEventListener("click", () => {
    c.commit(); save(); closeModal(); chapter = null;
    if (campaign.done) renderEnd(); else showBriefing();
  });
  modal.querySelector("#retry")?.addEventListener("click", () => { closeModal(); startChapter(); });
  modal.querySelector("#moveon")?.addEventListener("click", () => {
    c.commit({ moveOn: true }); save(); closeModal(); chapter = null;
    if (campaign.done) renderEnd(); else showBriefing();
  });
  modal.querySelector("#stay").addEventListener("click", closeModal);
  modal.querySelector("#title").addEventListener("click", () => { closeModal(); renderTitle(); });
}

// -- the end ---------------------------------------------------------------------------------------------
function renderEnd() {
  screen = "end";
  const u = U(), st = S();
  const best = JSON.parse(store.get("ld-best", "{}"));
  const key = `${campaign.storyline}:${campaign.difficulty}`;
  if (!best[key] || campaign.totalStars() > best[key]) { best[key] = campaign.totalStars(); store.set("ld-best", JSON.stringify(best)); }
  app.innerHTML = `<section style="max-width:820px;padding:30px 0">
    <div class="brief-head">${handlerPortrait(campaign.storyline, 72)}<div><b>${esc(st.handler)}</b><small>${esc(st.handlerRole)}</small></div></div>
    <p class="kicker">${u.report} · ${models[campaign.difficulty].name}</p><h1 style="font-size:40px;margin:0 0 10px">${esc(st.endTitle)}</h1>
    <p style="font-size:17px;color:var(--soft)">${esc(st.endText)}</p>
    <div class="chapters-done">${CHAPTERS.map((ch, i) => `<div>${esc(st.chapters[ch.id][0].split("·")[0])}<div>${stars(campaign.results[i]?.stars ?? 0)}</div><div class="mono">${fcfa(campaign.results[i]?.profit ?? 0)}</div></div>`).join("")}</div>
    <p class="mono">${u.totalStars}: ${campaign.totalStars()} / 15 · ${u.cash}: ${fcfa(campaign.cash)} FCFA</p>
    <h2 style="margin-top:26px">${esc(st.findingsTitle)}</h2>
    ${campaign.findings.length ? `<ol class="finding-list">${campaign.findings.map((f) => `<li><b>${esc(st.findingLabel)}:</b> ${esc(findingSentence(f))}</li>`).join("")}</ol>` : `<p class="muted">${u.none}</p>`}
    <div class="tips"><b>${u.protect}</b><ul>${TIPS[lang].map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>
    <div class="go-row"><button class="btn" id="download">${u.download}</button><a class="btn ghost" href="./lab.html">${u.labLink}</a>
      <button class="btn sun" id="again">${u.again}</button></div>
  </section>`;
  app.querySelector("#download").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ storyline: campaign.storyline, difficulty: campaign.difficulty, findings: campaign.findings, attempts: campaign.attempts }, null, 1)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "cleverpay-attempts.json"; a.click();
  });
  app.querySelector("#again").addEventListener("click", () => { campaign = null; store.set("ld-campaign", ""); renderTitle(); });
}

function openModal(html) { modal.innerHTML = `<div class="modal">${html}</div>`; modal.querySelector("button")?.focus(); }
function closeModal() { modal.innerHTML = ""; }

init();
