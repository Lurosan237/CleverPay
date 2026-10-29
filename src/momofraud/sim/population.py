"""The simulated population: customers, agents, merchants, mules and scammers.

Accounts are integer indices internally. Only customers and mules have tracked
balances; agents, merchants and external payers (banks, employers) are treated like
PaySim's merchants: their balances are not part of the data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from momofraud.sim.config import PROFILES, REGIONS, SimConfig

KINDS = ("customer", "mule", "scammer", "agent", "merchant", "external")
SPECIAL_PAYEES = ("AIRTIME", "ELECTRICITY", "TV")


@dataclass
class Population:
    names: list[str]
    kind: np.ndarray            # index into KINDS
    profile: np.ndarray         # index into PROFILES (customers and aged mules), -1 otherwise
    region: np.ndarray          # index into REGIONS
    opened_day: np.ndarray      # account opening day relative to the start (negative = before)
    tracked: np.ndarray         # True if the balance is recorded
    initial_balance: np.ndarray
    wealth: np.ndarray          # scales amounts and starting balance (same person, same means)
    activity: np.ndarray        # scales how often the person transacts
    contacts: list[np.ndarray]  # for customers: the people they usually send money to
    home_agents: list[np.ndarray]
    customers: np.ndarray       # indices of ordinary customers
    agents: np.ndarray
    rogue_agents: np.ndarray
    shops: np.ndarray
    payee: dict[str, int]       # AIRTIME / ELECTRICITY / TV accounts
    external: int               # banks and employers (salary payments)
    fresh_mules: np.ndarray     # recently opened, no history of their own
    aged_mules: np.ndarray      # recruited real people, with normal activity
    scammers: np.ndarray        # receive "wrong transfer" refunds (naive strategy)

    @property
    def profile_names(self) -> list[str]:
        return list(PROFILES)

    @property
    def region_names(self) -> list[str]:
        return list(REGIONS)


def build_population(cfg: SimConfig, rng: np.random.Generator) -> Population:
    names: list[str] = []
    kind: list[int] = []
    profile: list[int] = []
    region: list[int] = []
    opened: list[int] = []

    region_ids = np.arange(len(REGIONS))
    region_p = np.array(list(REGIONS.values()))
    region_p = region_p / region_p.sum()
    profile_p = np.array([p.share for p in PROFILES.values()])
    profile_p = profile_p / profile_p.sum()

    def add(prefix: str, k: str, prof: int, reg: int, day: int) -> int:
        index = len(names)
        # Phone-number-like ids: 9 digits starting with 6, like Cameroonian mobile numbers.
        # index * 7919 (a prime) mod 10^8 is a bijection, so ids are unique but not sequential.
        names.append(f"6{index * 7919 % 100_000_000:08d}" if prefix == "6" else f"{prefix}{index:06d}")
        kind.append(KINDS.index(k))
        profile.append(prof)
        region.append(reg)
        opened.append(day)
        return index

    # Customers: accounts opened up to ~5 years before the simulation starts
    customer_profiles = rng.choice(len(PROFILES), size=cfg.n_users, p=profile_p)
    customer_regions = rng.choice(region_ids, size=cfg.n_users, p=region_p)
    customer_age = rng.integers(30, 5 * 365, size=cfg.n_users)
    customers = np.array([
        add("6", "customer", int(p), int(r), -int(a))
        for p, r, a in zip(customer_profiles, customer_regions, customer_age, strict=True)
    ])

    # Agents, spread by region in proportion to customers
    n_agents = max(len(REGIONS), cfg.n_users // cfg.users_per_agent)
    agent_regions = rng.choice(region_ids, size=n_agents, p=region_p)
    agents = np.array([add("A", "agent", -1, int(r), -int(rng.integers(100, 3000))) for r in agent_regions])
    # In small worlds there may be few agents: at most half of them are rogue
    rogue_agents = rng.choice(agents, size=min(cfg.fraud.rogue_agents, len(agents) // 2), replace=False)

    shop_regions = rng.choice(region_ids, size=cfg.n_shops, p=region_p)
    shops = np.array([add("M", "merchant", -1, int(r), -1000) for r in shop_regions])
    payee = {name: add("M", "merchant", -1, 0, -5000) for name in SPECIAL_PAYEES}
    external = add("B", "external", -1, 0, -5000)

    # Mules. Fresh ones are opened shortly before they are used (set when first used);
    # aged ones are ordinary-looking accounts with a profile and their own traffic.
    n_fresh = cfg.fraud.mules // 2
    fresh_mules = np.array([
        add("6", "mule", -1, int(rng.choice(region_ids, p=region_p)), cfg.days + 1) for _ in range(n_fresh)
    ])
    aged_mules = np.array([
        add("6", "mule", int(rng.choice(len(PROFILES), p=profile_p)), int(rng.choice(region_ids, p=region_p)),
            -int(rng.integers(200, 1500)))
        for _ in range(cfg.fraud.mules - n_fresh)
    ])
    scammers = np.array([
        add("6", "scammer", -1, int(rng.choice(region_ids, p=region_p)), -int(rng.integers(5, 40)))
        for _ in range(10)
    ])

    n = len(names)
    kind_arr = np.array(kind, dtype=np.int8)
    profile_arr = np.array(profile, dtype=np.int8)
    tracked = np.isin(kind_arr, [KINDS.index("customer"), KINDS.index("mule"), KINDS.index("scammer")])

    wealth = rng.lognormal(0, 0.4, size=n)
    activity = rng.lognormal(0, 0.5, size=n)
    initial = np.zeros(n)
    for p_index, prof in enumerate(PROFILES.values()):
        members = np.where((profile_arr == p_index) & tracked)[0]
        initial[members] = np.round(
            prof.initial_balance * wealth[members] * rng.lognormal(0, 0.5, size=len(members)), -1
        )

    region_arr = np.array(region, dtype=np.int8)
    contacts = _build_contacts(rng, customers, aged_mules, region_arr, n)
    home_agents = _assign_home_agents(rng, region_arr, agents, n)

    return Population(
        names=names, kind=kind_arr, profile=profile_arr, region=region_arr,
        opened_day=np.array(opened, dtype=np.int32), tracked=tracked, initial_balance=initial,
        wealth=wealth, activity=activity,
        contacts=contacts, home_agents=home_agents, customers=customers, agents=agents,
        rogue_agents=rogue_agents, shops=shops, payee=payee, external=external,
        fresh_mules=fresh_mules, aged_mules=aged_mules, scammers=scammers,
    )


def _build_contacts(rng, customers, aged_mules, region, n) -> list[np.ndarray]:
    """Each person sends money to a small circle: mostly people from the same town,
    plus some family elsewhere (urban-to-rural remittances)."""
    people = np.concatenate([customers, aged_mules])
    by_region = {r: people[region[people] == r] for r in np.unique(region[people])}
    contacts: list[np.ndarray] = [np.empty(0, dtype=np.int64)] * n
    for person in people:
        size = int(rng.integers(3, 13))
        local_pool = by_region[region[person]]
        n_local = int(round(size * 0.7))
        chosen = np.concatenate([
            rng.choice(local_pool, size=n_local),
            rng.choice(people, size=size - n_local),
        ])
        contacts[person] = np.unique(chosen[chosen != person])
    return contacts


def _assign_home_agents(rng, region, agents, n) -> list[np.ndarray]:
    agents_by_region = {r: agents[region[agents] == r] for r in np.unique(region[agents])}
    home: list[np.ndarray] = [agents[:1]] * n
    for person in range(n):
        pool = agents_by_region.get(region[person])
        if pool is None or len(pool) == 0:
            pool = agents
        home[person] = rng.choice(pool, size=min(2, len(pool)), replace=False)
    return home
