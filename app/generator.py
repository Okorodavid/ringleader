"""Deterministic synthetic dataset: a population of ordinary accounts, a few planted fraud rings,
and benign households that share a device and an address but behave normally.

The generator produces two things:
  * rows  - the nodes and edges that get loaded into FalkorDB
  * truth - which accounts belong to which ring (never loaded into the graph; used only by evals)

Everything is derived from one integer seed so tests and evals are reproducible.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FIRST = ["Ada", "Bayo", "Chidi", "Dara", "Emeka", "Funke", "Gbenga", "Hauwa", "Ife", "Jide", "Kemi", "Lola",
         "Musa", "Ngozi", "Obi", "Pelumi", "Ruth", "Sade", "Tunde", "Uche", "Victor", "Wale", "Yemi", "Zara",
         "Amara", "Bola", "Chuka", "Dayo", "Ebuka", "Femi"]
LAST = ["Okafor", "Adeyemi", "Bello", "Eze", "Ibrahim", "Okoro", "Balogun", "Nwosu", "Lawal", "Abubakar",
        "Olawale", "Mohammed", "Onyeka", "Afolabi", "Umar", "Chukwu", "Ogunleye", "Yusuf", "Nnamdi", "Sanusi"]
CITIES = ["Lagos", "Abuja", "Ibadan", "Kano", "Enugu", "Port Harcourt", "Benin City", "Jos"]
STREETS = ["Awolowo Rd", "Broad St", "Allen Ave", "Adeola Odeku", "Herbert Macaulay", "Aminu Kano Cres",
           "Ogui Rd", "Sapele Rd", "Ahmadu Bello Way", "Opebi Rd"]
OS = ["Android 14", "Android 13", "iOS 17", "iOS 18", "Windows 11", "macOS 15"]
ISSUERS = ["GTB", "Zenith", "Access", "UBA", "First Bank", "Kuda"]
MERCHANTS = [("m_jumia", "Jumia", "ecommerce"), ("m_konga", "Konga", "ecommerce"), ("m_bolt", "Bolt", "transport"),
             ("m_mtn", "MTN Airtime", "telecom"), ("m_glo", "Glo Airtime", "telecom"), ("m_shoprite", "Shoprite", "grocery"),
             ("m_netflix", "Netflix", "subscription"), ("m_dstv", "DStv", "subscription"), ("m_chicken", "Chicken Republic", "food"),
             ("m_filmhouse", "Filmhouse", "entertainment"), ("m_crypto_x", "QuickCoin Exchange", "crypto"),
             ("m_giftcards", "GiftCardHub", "giftcards"), ("m_electronics", "Slot Electronics", "electronics")]
RISKY_MERCHANTS = ["m_crypto_x", "m_giftcards", "m_electronics"]

EPOCH = datetime(2026, 9, 1, tzinfo=timezone.utc)


@dataclass
class Dataset:
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    edges: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    truth: dict[str, Any] = field(default_factory=dict)

    def add_node(self, label: str, props: dict[str, Any]) -> None:
        self.nodes.setdefault(label, []).append(props)

    def add_edge(self, rel: str, src: str, dst: str, props: dict[str, Any] | None = None) -> None:
        self.edges.setdefault(rel, []).append({"src": src, "dst": dst, **(props or {})})

    def counts(self) -> dict[str, int]:
        out = {f"node:{k}": len(v) for k, v in self.nodes.items()}
        out.update({f"edge:{k}": len(v) for k, v in self.edges.items()})
        return out


def _ts(rng: random.Random, start: datetime, max_days: float) -> str:
    return (start + timedelta(seconds=rng.random() * max_days * 86400)).isoformat()


class Builder:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.ds = Dataset()
        self.n_acc = 0
        self.n_dev = 0
        self.n_phone = 0
        self.n_addr = 0
        self.n_card = 0
        self.n_ip = 0
        self.n_tx = 0
        for mid, name, cat in MERCHANTS:
            self.ds.add_node("Merchant", {"id": mid, "name": name, "category": cat})

    # ---- identifier factories -------------------------------------------------
    def account(self, created: datetime, country: str = "NG") -> str:
        self.n_acc += 1
        aid = f"acc_{self.n_acc:04d}"
        name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
        email = name.lower().replace(" ", ".") + f"{self.n_acc}@example.com"
        self.ds.add_node("Account", {
            "id": aid, "name": name, "email": email, "created_at": created.isoformat(),
            "country": country, "status": "active", "kyc_level": self.rng.choice([1, 2, 2, 3]),
        })
        return aid

    def device(self) -> str:
        self.n_dev += 1
        did = f"dev_{self.n_dev:04d}"
        self.ds.add_node("Device", {"id": did, "fingerprint": f"fp{self.rng.getrandbits(40):010x}", "os": self.rng.choice(OS)})
        return did

    def phone(self) -> str:
        self.n_phone += 1
        num = f"+23480{self.rng.randint(10000000, 99999999)}"
        self.ds.add_node("Phone", {"id": num, "number": num})
        return num

    def address(self) -> str:
        self.n_addr += 1
        aid = f"addr_{self.n_addr:04d}"
        self.ds.add_node("Address", {
            "id": aid, "street": f"{self.rng.randint(1, 180)} {self.rng.choice(STREETS)}", "city": self.rng.choice(CITIES),
        })
        return aid

    def card(self) -> str:
        self.n_card += 1
        cid = f"card_{self.n_card:04d}"
        self.ds.add_node("Card", {"id": cid, "last4": f"{self.rng.randint(0, 9999):04d}", "issuer": self.rng.choice(ISSUERS),
                                  "bin": f"{self.rng.randint(400000, 559999)}"})
        return cid

    def ip(self) -> str:
        self.n_ip += 1
        addr = f"{self.rng.randint(41, 197)}.{self.rng.randint(0, 255)}.{self.rng.randint(0, 255)}.{self.rng.randint(1, 254)}"
        self.ds.add_node("IP", {"id": addr, "addr": addr})
        return addr

    def link(self, acc: str, rel: str, ident: str, created: datetime, count: int = 1) -> None:
        first = _ts(self.rng, created, 2)
        self.ds.add_edge(rel, acc, ident, {"first_seen": first, "last_seen": _ts(self.rng, created, 30), "count": count})

    def tx(self, src: str, dst: str | None, merchant: str | None, amount: float, when: datetime, status: str = "settled") -> str:
        self.n_tx += 1
        tid = f"tx_{self.n_tx:05d}"
        self.ds.add_node("Transaction", {"id": tid, "amount": round(amount, 2), "currency": "NGN", "ts": when.isoformat(), "status": status})
        self.ds.add_edge("SENT", src, tid)
        if dst:
            self.ds.add_edge("TO", tid, dst)
        if merchant:
            self.ds.add_edge("AT", tid, merchant)
        return tid

    # ---- population patterns ---------------------------------------------------
    def ordinary_account(self) -> str:
        created = EPOCH - timedelta(days=self.rng.randint(30, 900))
        acc = self.account(created)
        self.link(acc, "USED_DEVICE", self.device(), created, count=self.rng.randint(5, 300))
        if self.rng.random() < 0.25:  # a second device, laptop plus phone
            self.link(acc, "USED_DEVICE", self.device(), created, count=self.rng.randint(1, 40))
        self.link(acc, "HAS_PHONE", self.phone(), created)
        self.link(acc, "LIVES_AT", self.address(), created)
        self.link(acc, "OWNS_CARD", self.card(), created)
        for _ in range(self.rng.randint(1, 3)):
            self.link(acc, "LOGGED_FROM", self.ip(), created, count=self.rng.randint(1, 80))
        base = EPOCH - timedelta(days=30)
        for _ in range(self.rng.randint(3, 14)):
            m = self.rng.choice(MERCHANTS[:10])[0]
            self.tx(acc, None, m, self.rng.lognormvariate(8.5, 0.8), base + timedelta(days=self.rng.random() * 30))
        return acc

    def household(self, size: int) -> list[str]:
        """Benign: family members share one address and one tablet, and send each other small transfers."""
        created = EPOCH - timedelta(days=self.rng.randint(200, 900))
        shared_addr = self.address()
        shared_tablet = self.device()
        members = []
        for _ in range(size):
            acc = self.account(created + timedelta(days=self.rng.randint(0, 120)))
            self.link(acc, "LIVES_AT", shared_addr, created)
            self.link(acc, "USED_DEVICE", shared_tablet, created, count=self.rng.randint(2, 30))
            self.link(acc, "USED_DEVICE", self.device(), created, count=self.rng.randint(20, 300))
            self.link(acc, "HAS_PHONE", self.phone(), created)
            self.link(acc, "OWNS_CARD", self.card(), created)
            self.link(acc, "LOGGED_FROM", self.ip(), created, count=self.rng.randint(5, 100))
            members.append(acc)
        base = EPOCH - timedelta(days=30)
        for acc in members:
            for _ in range(self.rng.randint(3, 10)):
                m = self.rng.choice(MERCHANTS[:10])[0]
                self.tx(acc, None, m, self.rng.lognormvariate(8.3, 0.7), base + timedelta(days=self.rng.random() * 30))
            # small transfers between family members, both directions over months
            other = self.rng.choice([m for m in members if m != acc])
            for _ in range(self.rng.randint(1, 3)):
                self.tx(acc, other, None, self.rng.uniform(2000, 25000), base + timedelta(days=self.rng.random() * 30))
        return members

    def ring(self, name: str, size: int, pattern: str) -> dict[str, Any]:
        """Planted fraud ring. Members share devices, phones and cards in a dense overlapping pattern,
        and money fans in from the members to one cash-out account that spends it at crypto or gift-card merchants."""
        created = EPOCH - timedelta(days=self.rng.randint(4, 12))  # bust-out: all accounts are new
        pool_dev = [self.device() for _ in range(max(2, size // 3))]
        pool_phone = [self.phone() for _ in range(max(2, size // 3))]
        pool_card = [self.card() for _ in range(max(1, size // 4))]
        pool_ip = [self.ip() for _ in range(2)]
        addr = self.address() if pattern == "same_address" else None
        members: list[str] = []
        for i in range(size):
            acc = self.account(created + timedelta(hours=self.rng.randint(0, 72)))
            members.append(acc)
            # every member touches at least one shared device and one shared phone, chosen so the ring is connected
            self.link(acc, "USED_DEVICE", pool_dev[i % len(pool_dev)], created, count=self.rng.randint(3, 25))
            if self.rng.random() < 0.6:
                self.link(acc, "USED_DEVICE", pool_dev[(i + 1) % len(pool_dev)], created, count=self.rng.randint(1, 10))
            self.link(acc, "HAS_PHONE", pool_phone[(i // 2) % len(pool_phone)], created)
            if i % 3 == 0 or self.rng.random() < 0.4:
                self.link(acc, "OWNS_CARD", pool_card[i % len(pool_card)], created)
            else:
                self.link(acc, "OWNS_CARD", self.card(), created)
            self.link(acc, "LIVES_AT", addr or self.address(), created)
            self.link(acc, "LOGGED_FROM", pool_ip[i % 2], created, count=self.rng.randint(2, 40))
        # cash-out account: slightly older, receives from every member, spends at risky merchants
        cashout = self.account(created - timedelta(days=self.rng.randint(20, 60)))
        self.link(cashout, "USED_DEVICE", pool_dev[0], created, count=self.rng.randint(5, 40))
        self.link(cashout, "HAS_PHONE", self.phone(), created)
        self.link(cashout, "OWNS_CARD", self.card(), created)
        self.link(cashout, "LIVES_AT", self.address(), created)
        self.link(cashout, "LOGGED_FROM", pool_ip[0], created, count=self.rng.randint(5, 60))
        start = created + timedelta(days=1)
        for acc in members:
            for _ in range(self.rng.randint(2, 5)):
                self.tx(acc, cashout, None, self.rng.uniform(40000, 250000), start + timedelta(hours=self.rng.random() * 60))
            if self.rng.random() < 0.5:  # a bit of camouflage spending
                self.tx(acc, None, self.rng.choice(MERCHANTS[:10])[0], self.rng.lognormvariate(8, 0.6), start + timedelta(hours=self.rng.random() * 60))
        for _ in range(self.rng.randint(4, 9)):
            self.tx(cashout, None, self.rng.choice(RISKY_MERCHANTS),
                    self.rng.uniform(150000, 900000), start + timedelta(hours=24 + self.rng.random() * 72))
        return {"name": name, "pattern": pattern, "members": members, "cashout": cashout,
                "shared": {"devices": pool_dev, "phones": pool_phone, "cards": pool_card, "ips": pool_ip}}


def build(seed: int = 7, ordinary: int = 360, households: int = 4) -> Dataset:
    b = Builder(seed)
    for _ in range(ordinary):
        b.ordinary_account()
    hh = [b.household(b.rng.randint(3, 5)) for _ in range(households)]
    rings = [
        b.ring("ring_alpha", 9, "shared_devices"),
        b.ring("ring_bravo", 6, "same_address"),
        b.ring("ring_charlie", 12, "shared_devices"),
        b.ring("ring_delta", 5, "shared_devices"),
    ]
    # a handful of organic cross-links so the graph is not trivially partitioned
    accounts = [a["id"] for a in b.ds.nodes["Account"]]
    for _ in range(25):
        a, c = b.rng.sample(accounts[:ordinary], 2)
        b.tx(a, c, None, b.rng.uniform(1000, 60000), EPOCH - timedelta(days=b.rng.random() * 30))
    b.ds.truth = {
        "seed": seed,
        "rings": rings,
        "households": hh,
        "ring_member_ids": sorted({m for r in rings for m in r["members"]} | {r["cashout"] for r in rings}),
        "household_ids": sorted({m for h in hh for m in h}),
    }
    return b.ds


def write(ds: Dataset, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rows.json").write_text(json.dumps({"nodes": ds.nodes, "edges": ds.edges}, indent=1))
    (out_dir / "ground_truth.json").write_text(json.dumps(ds.truth, indent=1))
    (out_dir / "counts.json").write_text(json.dumps(ds.counts(), indent=1, sort_keys=True))


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    ds = build(seed)
    out = Path(__file__).resolve().parent.parent / "data" / "generated"
    write(ds, out)
    print(json.dumps(ds.counts(), indent=1, sort_keys=True))
    print(f"rings={len(ds.truth['rings'])} ring_accounts={len(ds.truth['ring_member_ids'])} households={len(ds.truth['household_ids'])}")
