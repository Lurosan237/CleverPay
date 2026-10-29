// Small hand-made SVG art: procedural portraits for the people in the game, the two handlers,
// and the title illustration. No images to download, no real people.
const SKIN = ["#8d5524", "#6b4423", "#a0673d", "#5a3a22", "#7a4a2a", "#c18a5a"];
const HAIR = ["#1b1310", "#2a1c14", "#3b2a20", "#111"];
const BG = { retired: "#2f4a3e", trader: "#4a3b22", student: "#2a3a55", teacher: "#4a2f45", handler: "#0f5a47", boss: "#2a1f1f" };
const WRAP = ["#e2742b", "#19b38a", "#c83e4d", "#f2a33a", "#6bb6ff", "#9b59b6"];

function rand(seed) {
  let a = seed >>> 0;
  return () => { a = (a * 1664525 + 1013904223) >>> 0; return a / 4294967296; };
}

export function portrait({ seed = 1, female = false, persona = "trader", size = 56 } = {}) {
  const r = rand(seed);
  const pick = (list) => list[Math.floor(r() * list.length)];
  const skin = pick(SKIN), hair = pick(HAIR), bg = BG[persona] ?? "#333";
  const glasses = persona === "retired" || r() < 0.15;
  const wrap = female && r() < 0.55 ? pick(WRAP) : null;
  const grey = persona === "retired";
  const hairColor = grey ? "#bdb6ad" : hair;
  const parts = [`<rect width="64" height="64" rx="14" fill="${bg}"/>`];
  parts.push(`<path d="M10 64c2-14 11-20 22-20s20 6 22 20z" fill="${pick(["#e8e1d4", "#2d6a8f", "#8f2d56", "#3c7a3c", "#c9a13b", "#5c4d8f"])}"/>`);
  parts.push(`<rect x="27" y="37" width="10" height="9" rx="3" fill="${skin}"/>`);
  if (!wrap && female) parts.push(`<ellipse cx="32" cy="27" rx="16" ry="17" fill="${hairColor}"/>`);
  parts.push(`<ellipse cx="32" cy="28" rx="12" ry="14" fill="${skin}"/>`);
  if (wrap) {
    parts.push(`<path d="M18 26c0-12 7-17 14-17s14 5 14 17c-3-4-8-6-14-6s-11 2-14 6z" fill="${wrap}"/>`);
    parts.push(`<path d="M40 12c6-3 9 2 6 6-2-2-4-4-6-6z" fill="${wrap}"/>`);
  } else if (!female) {
    parts.push(`<path d="M20 24c0-9 6-12 12-12s12 3 12 12c-2-4-6-5-12-5s-10 1-12 5z" fill="${hairColor}"/>`);
  } else {
    parts.push(`<path d="M20 24c1-8 6-11 12-11s11 3 12 11c-4-3-8-4-12-4s-8 1-12 4z" fill="${hairColor}"/>`);
  }
  parts.push(`<circle cx="27.5" cy="29" r="1.6" fill="#1a1a1a"/><circle cx="36.5" cy="29" r="1.6" fill="#1a1a1a"/>`);
  parts.push(`<path d="M28 35.5c2.5 2 5.5 2 8 0" stroke="#3a2015" stroke-width="1.6" fill="none" stroke-linecap="round"/>`);
  if (glasses) parts.push(`<g fill="none" stroke="#e8e1d4" stroke-width="1.3"><circle cx="27.5" cy="29" r="3.6"/><circle cx="36.5" cy="29" r="3.6"/><path d="M31.1 29h1.8"/></g>`);
  if (!female && r() < 0.35) parts.push(`<path d="M26 37c3 4 9 4 12 0-1 5-11 5-12 0z" fill="${hairColor}" opacity=".85"/>`);
  return `<svg viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true">${parts.join("")}</svg>`;
}

export function handlerPortrait(storyline, size = 64) {
  if (storyline === "underworld") {
    return `<svg viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true"><rect width="64" height="64" rx="14" fill="${BG.boss}"/>
      <path d="M8 64c3-15 12-21 24-21s21 6 24 21z" fill="#141414"/><path d="M26 43l6 10 6-10z" fill="#c83e4d"/>
      <rect x="27" y="36" width="10" height="9" rx="3" fill="#5a3a22"/><ellipse cx="32" cy="27" rx="12" ry="14" fill="#5a3a22"/>
      <path d="M17 21c2-10 10-12 15-12s13 2 15 12z" fill="#0c0c0c"/><rect x="14" y="19" width="36" height="4" rx="2" fill="#0c0c0c"/>
      <rect x="22" y="26" width="8" height="5" rx="2" fill="#0a0a0a"/><rect x="34" y="26" width="8" height="5" rx="2" fill="#0a0a0a"/>
      <path d="M30 28.5h4" stroke="#0a0a0a" stroke-width="1.5"/><path d="M28 36c3 1.5 5 1.5 8 0" stroke="#2a1510" stroke-width="1.6" fill="none"/></svg>`;
  }
  return `<svg viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true"><rect width="64" height="64" rx="14" fill="${BG.handler}"/>
    <path d="M8 64c3-15 12-21 24-21s21 6 24 21z" fill="#e8e1d4"/><path d="M24 44h16l-8 9z" fill="#19b38a"/>
    <rect x="27" y="36" width="10" height="9" rx="3" fill="#7a4a2a"/><ellipse cx="32" cy="28" rx="12" ry="14" fill="#7a4a2a"/>
    <path d="M17 26c0-13 7-18 15-18s15 5 15 18c-3-5-9-7-15-7s-12 2-15 7z" fill="#f2a33a"/><path d="M42 10c7-3 10 3 6 7-2-3-4-5-6-7z" fill="#e2742b"/>
    <g fill="none" stroke="#111" stroke-width="1.4"><rect x="23" y="26" width="7.5" height="5.5" rx="2"/><rect x="33.5" y="26" width="7.5" height="5.5" rx="2"/><path d="M30.5 28.5h3"/></g>
    <path d="M28 35.5c2.5 1.6 5.5 1.6 8 0" stroke="#3a2015" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>`;
}

// Title illustration: a phone over a city at dusk
export function heroArt() {
  const towers = [[20, 70], [48, 95], [80, 60], [110, 120], [150, 85], [185, 140], [225, 75], [255, 110], [290, 65], [320, 100], [355, 80]];
  return `<svg viewBox="0 0 400 240" class="hero-art" aria-hidden="true">
    <defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1c2a4a"/><stop offset=".6" stop-color="#8a3d3a"/><stop offset="1" stop-color="#f2a33a"/></linearGradient>
    <linearGradient id="scr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#19b38a"/><stop offset="1" stop-color="#0f5a47"/></linearGradient></defs>
    <rect width="400" height="240" rx="18" fill="url(#sky)"/><circle cx="300" cy="150" r="34" fill="#ffcf7a" opacity=".9"/>
    ${towers.map(([x, h]) => `<rect x="${x}" y="${240 - h}" width="${26}" height="${h}" fill="#0d1210"/>${Array.from({ length: Math.floor(h / 18) }, (_, i) =>
      `<rect x="${x + 6}" y="${240 - h + 8 + i * 18}" width="5" height="6" fill="${(x + i) % 3 ? "#f2a33a" : "#1b2420"}" opacity=".8"/><rect x="${x + 15}" y="${240 - h + 8 + i * 18}" width="5" height="6" fill="${(x * i) % 4 ? "#1b2420" : "#f2a33a"}" opacity=".8"/>`).join("")}`).join("")}
    <g transform="translate(150 28) rotate(-8)"><rect width="96" height="180" rx="16" fill="#0a0d0c" stroke="#2c3531" stroke-width="2"/>
      <rect x="7" y="12" width="82" height="156" rx="10" fill="url(#scr)"/><text x="48" y="54" text-anchor="middle" font-family="Space Grotesk, sans-serif" font-weight="700" font-size="15" fill="#04261c">CleverPay</text>
      <rect x="18" y="70" width="60" height="10" rx="5" fill="#04261c" opacity=".35"/><rect x="18" y="88" width="44" height="10" rx="5" fill="#04261c" opacity=".35"/>
      <rect x="18" y="118" width="60" height="22" rx="8" fill="#f2a33a"/><text x="48" y="133" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="700" font-size="10" fill="#2b1600">SEND</text></g>
    <g transform="translate(262 40)"><rect width="104" height="44" rx="12" fill="#ef5a4c"/><text x="52" y="27" text-anchor="middle" font-family="JetBrains Mono, monospace" font-weight="700" font-size="13" fill="#fff">BLOCKED 97%</text></g>
  </svg>`;
}

export function stars(n, max = 3) {
  return Array.from({ length: max }, (_, i) => `<svg viewBox="0 0 24 24" width="30" height="30" class="star ${i < n ? "on" : ""}" style="animation-delay:${i * 0.18}s" aria-hidden="true"><path d="M12 2l3 6.6 7.2.8-5.4 4.9 1.5 7.1L12 17.8 5.7 21.4l1.5-7.1L1.8 9.4 9 8.6z"/></svg>`).join("");
}
