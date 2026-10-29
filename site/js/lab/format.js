// Feature values in words, for the SHAP waterfall.
const dur = (h, lang) => {
  if (h >= 720) return lang === "en" ? "never / 30+ days" : "jamais / 30+ jours";
  if (h < 1.5) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} ${lang === "en" ? "days" : "jours"}`;
};
const money = (v, lang) => `${Math.round(v).toLocaleString(lang === "fr" ? "fr-FR" : "en-US")} FCFA`;
const yes = (v, lang) => (v >= 0.5 ? (lang === "en" ? "yes" : "oui") : (lang === "en" ? "no" : "non"));
const days = (v, lang) => (v < 2 ? dur(v * 24, lang) : `${Math.round(v)} ${lang === "en" ? "days" : "jours"}`);

export function formatValue(feature, v, lang) {
  switch (feature) {
    case "is_transfer": case "is_agent_request": case "empties_account": case "receiver_untracked": case "amount_is_round":
    case "device_new": case "recipient_new": case "agent_new_for_sender": case "region_mismatch":
      return yes(v, lang);
    case "log_amount": case "log_sender_balance_before": case "log_receiver_balance_before": case "log_sender_out_amount_24h":
      return money(Math.expm1(v), lang);
    case "amount_to_balance": case "receiver_stranger_share_7d": case "receiver_cashout_ratio_7d":
      return `${Math.round(Math.min(v, 1) * 100)}%`;
    case "agent_decline_rate_24h": return v.toFixed(2);
    case "hour": return `${String(Math.trunc(v)).padStart(2, "0")}:00`;
    case "sender_history": case "device_history": case "pair_history": case "receiver_history":
      return `${Math.round(Math.expm1(v))}×`;
    case "sender_age_days": case "receiver_age_days": return days(v, lang);
    case "hours_since_sender_last_tx": case "hours_since_device_first_seen": case "hours_since_sim_swap_or_pin_reset":
    case "hours_since_device_change":
      return dur(v, lang);
    case "amount_zscore": return v.toFixed(1);
    default: return String(Math.round(v * 100) / 100);
  }
}
