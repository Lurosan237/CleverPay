// SHAP contributions -> sentences a person can read. Port of src/momofraud/serving/reasons.py.
import { CAP_HOURS, FEATURES } from "./features.js";

const duration = (hours, lang) => {
  const minutes = hours * 60;
  if (minutes < 90) return `${Math.max(1, pyRound(minutes))} min`;
  if (hours < 48) return `${pyRound(hours)} h`;
  return `${pyRound(hours / 24)} ${lang === "en" ? "days" : "jours"}`;
};
// Python rounds halves to even; match it so the sentences are identical
function pyRound(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}
const pct = (x) => `${pyRound(x * 100)}%`;
const t = (lang, en, fr) => (lang === "en" ? en : fr);
const pad2 = (n) => String(n).padStart(2, "0");

export const TEMPLATES = {
  device_new: (v, f, l) => (v >= 0.5 ? t(l, "First transaction from this phone on this account",
    "Première transaction depuis ce téléphone sur ce compte") : null),
  hours_since_device_first_seen: (v, f, l) => (v < 24 * 14 && (f.device_new ?? 0) < 0.5 ? t(l,
    `This phone was first used on the account ${duration(v, l)} ago`,
    `Ce téléphone est utilisé sur le compte depuis ${duration(v, l)} seulement`) : null),
  hours_since_sim_swap_or_pin_reset: (v, f, l) => (v < CAP_HOURS ? t(l, `PIN reset or SIM swap ${duration(v, l)} ago`,
    `Code PIN réinitialisé ou carte SIM changée il y a ${duration(v, l)}`) : null),
  hours_since_device_change: (v, f, l) => (v < CAP_HOURS ? t(l, `Phone changed ${duration(v, l)} ago`,
    `Changement de téléphone il y a ${duration(v, l)}`) : null),
  recipient_new: (v, f, l) => (v >= 0.5 && (f.is_transfer ?? 1) >= 0.5 ? t(l, "First payment to this number",
    "Premier envoi vers ce numéro") : null),
  receiver_age_days: (v, f, l) => (v < 90 ? t(l, `Recipient account opened ${duration(v * 24, l)} ago`,
    `Compte du destinataire ouvert il y a ${duration(v * 24, l)}`) : null),
  receiver_stranger_share_7d: (v, f, l) => (v >= 0.3 ? t(l,
    `${pct(v)} of the money the recipient received this week came from people they don't know`,
    `${pct(v)} de l'argent reçu par le destinataire cette semaine vient d'inconnus`) : null),
  receiver_distinct_senders_7d: (v, f, l) => (v >= 4 ? t(l,
    `The recipient received money from ${Math.trunc(v)} different people this week`,
    `Le destinataire a reçu de l'argent de ${Math.trunc(v)} personnes différentes cette semaine`) : null),
  receiver_cashout_ratio_7d: (v, f, l) => (v >= 0.5 ? t(l,
    `The recipient withdrew ${pct(Math.min(v, 1))} of what they received this week`,
    `Le destinataire a retiré ${pct(Math.min(v, 1))} de ce qu'il a reçu cette semaine`) : null),
  receiver_in_count_24h: (v, f, l) => (v >= 3 ? t(l, `The recipient received ${Math.trunc(v)} transfers in the last 24 h`,
    `Le destinataire a reçu ${Math.trunc(v)} transferts en 24 h`) : null),
  agent_decline_rate_24h: (v, f, l) => (v >= 0.2 ? t(l,
    `Customers declined ${v >= 0.5 ? "most" : "many"} of this agent's withdrawal requests today`,
    `Les clients ont refusé ${v >= 0.5 ? "la plupart" : "beaucoup"} des demandes de retrait de cet agent aujourd'hui`) : null),
  agent_requests_1h: (v, f, l) => (v >= 5 ? t(l, `This agent sent ${Math.trunc(v)} withdrawal requests in the last hour`,
    `Cet agent a envoyé ${Math.trunc(v)} demandes de retrait dans la dernière heure`) : null),
  agent_new_for_sender: (v, f, l) => (v >= 0.5 ? t(l, "First withdrawal with this agent", "Premier retrait chez cet agent") : null),
  region_mismatch: (v, f, l) => (v >= 0.5 ? t(l, "The other party is in a different town", "L'autre partie est dans une autre ville") : null),
  empties_account: (v, f, l) => (v >= 0.5 ? t(l, "Empties the account", "Vide le compte") : null),
  amount_to_balance: (v, f, l) => (v >= 0.5 && (f.empties_account ?? 0) < 0.5 ? t(l, `Moves ${pct(Math.min(v, 1))} of the balance`,
    `Transfère ${pct(Math.min(v, 1))} du solde`) : null),
  amount_zscore: (v, f, l) => (v >= 2 ? t(l, "Much larger than this customer's usual amounts",
    "Bien plus élevé que les montants habituels de ce client") : null),
  hour: (v, f, l) => (v < 6 || v >= 22 ? t(l, `Unusual time of day (${pad2(Math.trunc(v))}:00)`, `Heure inhabituelle (${pad2(Math.trunc(v))}h)`) : null),
  sender_history: (v, f, l) => (Math.expm1(v) < 10 ? t(l, "Very little history on this account", "Très peu d'historique sur ce compte") : null),
  sender_out_count_24h: (v, f, l) => (v >= 4 ? t(l, `${Math.trunc(v)} outgoing transactions in the last 24 h`,
    `${Math.trunc(v)} opérations sortantes en 24 h`) : null),
  hours_since_sender_last_tx: (v, f, l) => (v >= 24 * 7 ? t(l, `First activity in ${duration(v, l)}`,
    `Première activité depuis ${duration(v, l)}`) : null),
};

// The strongest reasons this transaction looks risky. contributions/values: full FEATURES order.
export function reasons(contributions, values, lang = "en", top = 3, minContribution = 0.05) {
  const byName = Object.fromEntries(FEATURES.map((f, i) => [f, values[i]]));
  // Python's sorted() is stable: ties keep feature order
  const order = FEATURES.map((_, i) => i).sort((a, b) => contributions[b] - contributions[a] || a - b);
  const out = [];
  for (const i of order) {
    if (contributions[i] < minContribution || out.length >= top) break;
    const template = TEMPLATES[FEATURES[i]];
    const text = template ? template(values[i], byName, lang) : null;
    if (text) out.push({ feature: FEATURES[i], text, contribution: Math.round(contributions[i] * 1000) / 1000 });
  }
  return out;
}

// Plain-language names for every feature (Model Lab)
export const LABELS = {
  en: {
    is_transfer: "It's a transfer", is_agent_request: "Agent-initiated withdrawal", log_amount: "Amount",
    log_sender_balance_before: "Sender's balance", amount_to_balance: "Share of the balance moved",
    empties_account: "Empties the account", log_receiver_balance_before: "Receiver's balance",
    receiver_untracked: "Receiver is an agent or shop", amount_is_round: "Round amount", hour: "Hour of day",
    sender_history: "Sender's history", sender_age_days: "Sender account age", hours_since_sender_last_tx: "Time since sender's last activity",
    amount_zscore: "Unusual amount for this sender", sender_out_count_24h: "Sender's activity today",
    log_sender_out_amount_24h: "Sender's spending today", device_new: "Phone new to this account",
    device_history: "Times this phone was used", hours_since_device_first_seen: "How long this phone has been used",
    hours_since_sim_swap_or_pin_reset: "Time since SIM swap / PIN reset", hours_since_device_change: "Time since phone change",
    recipient_new: "First payment to this person", pair_history: "Past payments to this person",
    receiver_age_days: "Receiver account age", receiver_history: "Receiver's history",
    receiver_in_count_24h: "Transfers the receiver got today", receiver_distinct_senders_7d: "Different people paying the receiver",
    receiver_stranger_share_7d: "Receiver's money from strangers", receiver_cashout_ratio_7d: "How fast the receiver withdraws",
    agent_new_for_sender: "New agent for this customer", region_mismatch: "Different towns", agent_requests_1h: "Agent's requests this hour",
    agent_decline_rate_24h: "Agent's declined requests",
  },
  fr: {
    is_transfer: "C'est un transfert", is_agent_request: "Retrait initié par l'agent", log_amount: "Montant",
    log_sender_balance_before: "Solde de l'expéditeur", amount_to_balance: "Part du solde transférée",
    empties_account: "Vide le compte", log_receiver_balance_before: "Solde du destinataire",
    receiver_untracked: "Destinataire agent ou commerce", amount_is_round: "Montant rond", hour: "Heure",
    sender_history: "Historique de l'expéditeur", sender_age_days: "Âge du compte expéditeur", hours_since_sender_last_tx: "Temps depuis la dernière activité",
    amount_zscore: "Montant inhabituel pour ce client", sender_out_count_24h: "Activité du jour",
    log_sender_out_amount_24h: "Dépenses du jour", device_new: "Téléphone nouveau sur ce compte",
    device_history: "Utilisations de ce téléphone", hours_since_device_first_seen: "Ancienneté du téléphone",
    hours_since_sim_swap_or_pin_reset: "Temps depuis changement de SIM / PIN", hours_since_device_change: "Temps depuis changement de téléphone",
    recipient_new: "Premier envoi à cette personne", pair_history: "Envois passés à cette personne",
    receiver_age_days: "Âge du compte destinataire", receiver_history: "Historique du destinataire",
    receiver_in_count_24h: "Transferts reçus aujourd'hui", receiver_distinct_senders_7d: "Personnes différentes qui paient le destinataire",
    receiver_stranger_share_7d: "Argent reçu d'inconnus", receiver_cashout_ratio_7d: "Vitesse de retrait du destinataire",
    agent_new_for_sender: "Nouvel agent pour ce client", region_mismatch: "Villes différentes", agent_requests_1h: "Demandes de l'agent cette heure",
    agent_decline_rate_24h: "Demandes refusées de l'agent",
  },
};
