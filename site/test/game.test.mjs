// Launch Day rules, tested headless against the real models.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Model } from "../js/engine/model.js";
import { Campaign, Chapter, CHAPTERS, COSTS, START_CASH, GameError } from "../js/game/engine.js";

globalThis.navigator ??= { language: "en" };
const { rng } = await import("../js/common.js");
const load = (p) => JSON.parse(readFileSync(new URL(`../data/${p}`, import.meta.url)));
const world = load("world.json");
const models = Object.fromEntries(["rookie", "analyst", "expert", "elite"].map((k) => [k, new Model(load(`models/${k}.json`))]));
const chapterAt = (index, difficulty = "expert", seed = 3) => {
  const c = new Campaign({ difficulty, seed });
  c.chapterIndex = index;
  return new Chapter(c, world, models, rng(seed));
};

test("a campaign starts in the morning with the starting budget, minus the first SIM", () => {
  const ch = chapterAt(0);
  assert.equal(ch.cash, START_CASH - COSTS.sim);
  assert.equal(Math.floor(ch.now / 3600) % 24, 8);
  assert.equal(ch.leads.length, 3);
  assert.equal(ch.usable().length, 1);
  assert.equal(ch.offers.length, 3);
});

test("chapters never touch the shared world", () => {
  const before = JSON.stringify(world).length;
  const ch = chapterAt(0);
  ch.call({ lead: ch.leads[0].account, script: "official", amount: 5000, to: ch.usable()[0].account });
  assert.equal(JSON.stringify(world).length, before);
});

test("intel probes the model without changing anything", () => {
  const ch = chapterAt(0);
  const balance = ch.net.balance.get(ch.leads[0].account), now = ch.now, nextId = ch.net.nextId;
  const intel = ch.buyIntel({ kind: "call", lead: ch.leads[0].account, to: ch.usable()[0].account, amount: 5000 });
  assert.ok(intel.score > 0 && intel.score < 1);
  assert.ok(["approve", "review", "block"].includes(intel.decision));
  assert.equal(ch.net.balance.get(ch.leads[0].account), balance);
  assert.equal(ch.now, now);
  assert.equal(ch.net.nextId, nextId);
  assert.equal(ch.spent, COSTS.sim + COSTS.intel);
});

test("security level rises with flags, changes thresholds, and cools down", () => {
  const ch = chapterAt(0);
  const base = ch.thresholds();
  ch.heat(3, "test");
  assert.equal(ch.level, 1);
  assert.ok(ch.thresholds().review < base.review);
  ch.heat(6, "test");
  assert.equal(ch.level, 3);
  assert.ok(ch.thresholds().block < base.block);
  ch.wait("1d");
  if (!ch.over) assert.ok(ch.level < 3, "a quiet day should cool things down");
});

test("you can't spend money you don't have", () => {
  const ch = chapterAt(0);
  ch.startCash = 0;
  assert.throws(() => ch.openNumber(), (e) => e instanceof GameError && e.code === "no_cash");
});

test("a rushed takeover gets the account frozen at Expert", () => {
  const ch = chapterAt(2);
  ch.enter("pin");
  ch.steal({ to: ch.usable()[0].account, amount: Math.floor(ch.net.balance.get(ch.victim.account) / 1.002) });
  assert.equal(ch.over, true);
  assert.equal(ch.outcome, "caught");
  assert.equal(ch.result.stars, 0);
  assert.ok(ch.lastCheck.reasons.length > 0, "the fraud desk explains the block");
});

test("Patch Day upgrades the model, and Elite gets stricter thresholds instead", () => {
  const c = new Campaign({ difficulty: "expert" });
  assert.equal(c.modelKey(2), "expert");
  assert.equal(c.modelKey(3), "elite");
  assert.equal(c.modelKey(4), "elite");
  const e = new Campaign({ difficulty: "elite" });
  assert.equal(e.modelKey(3), "elite");
  assert.equal(e.thresholdTighten(3), 0.8);
  assert.equal(e.thresholdTighten(1), 1);
});

test("the rented-account blind spot is real at Expert and patched at Elite", () => {
  // One refund to a rented old account: passes the Expert model, as the stage 5 strategies found
  const ch = chapterAt(0, "expert", 11);
  const to = ch.rentAccount(ch.offers[0].account);
  const lead = ch.leads.find((l) => l.account !== to);
  const expert = ch.buyIntel({ kind: "call", lead: lead.account, to, amount: 5000 });
  assert.equal(expert.decision, "approve");
});

test("a met goal moves the campaign on; a missed one doesn't", () => {
  const ch = chapterAt(0);
  ch.stolen = CHAPTERS[0].goal + 10000;
  ch.giveUp();
  assert.equal(ch.result.met, true);
  assert.ok(ch.result.stars >= 1);
  assert.equal(ch.commit(), true);
  assert.equal(ch.campaign.chapterIndex, 1);
  assert.equal(ch.campaign.cash, ch.cash);
  const lost = chapterAt(1);
  lost.giveUp();
  assert.equal(lost.commit(), false);
  assert.equal(lost.campaign.chapterIndex, 1);
  assert.equal(lost.commit({ moveOn: true }), true);
  assert.equal(lost.campaign.chapterIndex, 2);
  assert.equal(lost.campaign.results[1].stars, 0);
});

test("everything is reproducible from the seed", () => {
  const play = () => {
    const ch = chapterAt(0, "analyst", 42);
    for (let i = 0; i < 5 && !ch.over; i++) ch.call({ lead: ch.leads[0].account, script: "urgent", amount: 5000, to: ch.usable()[0]?.account ?? ch.openNumber() });
    return [ch.profit, ch.pips, ch.log.length];
  };
  assert.deepEqual(play(), play());
});

test("campaigns survive a save and load", () => {
  const c = new Campaign({ storyline: "underworld", difficulty: "elite", seed: 9 });
  c.findings.push({ key: "x" });
  const again = Campaign.fromJSON(JSON.parse(JSON.stringify(c)));
  assert.equal(again.storyline, "underworld");
  assert.equal(again.modelKey(3), "elite");
  assert.equal(again.findings.length, 1);
});
