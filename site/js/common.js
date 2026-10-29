// Shared page chrome: header, language, footer, data loading.
import { Network } from "./engine/network.js";
import { Model } from "./engine/model.js";

export const REPO = "https://github.com/Lurosan237/CleverPay";

const store = {
  get(k, d = null) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: fine */ } },
};
export { store };

export let lang = (() => {
  const saved = store.get("cp-lang");
  if (saved === "en" || saved === "fr") return saved;
  return (navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en";
})();
const listeners = [];
export function onLang(fn) { listeners.push(fn); }
export function setLang(l) {
  lang = l; store.set("cp-lang", l); document.documentElement.lang = l;
  document.querySelectorAll("[data-lang-btn]").forEach((b) => b.classList.toggle("on", b.dataset.langBtn === l));
  listeners.forEach((fn) => fn(l));
}

const NAV = {
  en: { home: "Home", lab: "Model Lab", play: "Launch Day", classic: "Classic", code: "Code" },
  fr: { home: "Accueil", lab: "Labo du modèle", play: "Launch Day", classic: "Classique", code: "Code" },
};
const DISCLAIMER = {
  en: "CleverPay is a fictional brand made up for this project. It is not affiliated with any real company. Every person, account and amount is simulated.",
  fr: "CleverPay est une marque fictive inventée pour ce projet. Elle n'est affiliée à aucune entreprise réelle. Toutes les personnes, comptes et montants sont simulés.",
};

export function chrome(active) {
  const header = document.createElement("header");
  header.className = "topbar";
  const footer = document.createElement("footer");
  footer.className = "site";
  const render = () => {
    const n = NAV[lang];
    header.innerHTML = `<div class="wrap">
      <a class="logo" href="./index.html"><span class="mark">C</span><span>CleverPay</span></a>
      <nav class="nav">${["home", "lab", "play", "classic"].map((k) =>
        `<a href="./${k === "home" ? "index" : k}.html" class="${k === active ? "on" : ""}">${n[k]}</a>`).join("")}
        <a href="${REPO}" target="_blank" rel="noopener">${n.code} ↗</a></nav>
      <div class="langs"><button data-lang-btn="en">EN</button><button data-lang-btn="fr">FR</button></div></div>`;
    header.querySelectorAll("[data-lang-btn]").forEach((b) => {
      b.classList.toggle("on", b.dataset.langBtn === lang);
      b.addEventListener("click", () => { setLang(b.dataset.langBtn); render(); });
    });
    footer.innerHTML = `<div class="wrap"><p>${DISCLAIMER[lang]}</p>
      <p>${lang === "en" ? "Everything runs in your browser: the same feature engine and LightGBM models as the Python code, checked by parity tests." :
        "Tout tourne dans votre navigateur : le même moteur de variables et les mêmes modèles LightGBM que le code Python, vérifiés par des tests de parité."}
      <a href="${REPO}" target="_blank" rel="noopener">GitHub</a></p></div>`;
  };
  render();
  document.body.prepend(header);
  document.body.append(footer);
  document.documentElement.lang = lang;
  return { disclaimer: () => DISCLAIMER[lang] };
}

// -- data -------------------------------------------------------------------------------------------
const cache = {};
async function json(path) {
  if (!cache[path]) {
    cache[path] = fetch(path).then((r) => { if (!r.ok) throw new Error(`${path}: ${r.status}`); return r.json(); });
  }
  return cache[path];
}
export const TIERS = ["rookie", "analyst", "expert", "elite"];
export async function loadModels(keys = TIERS) {
  const out = {};
  await Promise.all(keys.map(async (k) => { out[k] = new Model(await json(`./data/models/${k}.json`)); }));
  return out;
}
export async function loadWorld() { return json("./data/world.json"); }
export async function loadMetrics() { return json("./data/metrics.json"); }
export const freshNetwork = (world) => Network.fromSnapshot(world);

// -- small helpers ----------------------------------------------------------------------------------
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fcfa = (n) => (n == null ? "–" : Math.round(n).toLocaleString(lang === "fr" ? "fr-FR" : "en-US"));
export const pct = (p, digits) => {
  const v = p * 100;
  return (digits !== undefined ? v.toFixed(digits) : v < 1 ? v.toPrecision(2) : v.toFixed(1)) + "%";
};
// Seedable RNG (mulberry32)
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
// Position on a log scale from 0.01% to 100% (for score gauges)
export const logPos = (p) => Math.min(1, Math.max(0, (Math.log10(Math.max(p, 1e-4)) + 4) / 4));
