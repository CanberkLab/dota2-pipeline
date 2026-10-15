"""A tiny local imitation of the OpenDota endpoints this project uses.

Lets you run and test the whole pipeline offline (and in CI) without hitting the
real API. Data is SYNTHETIC: hero strengths and pick rates are random but fixed,
so win rates differ between heroes; a few percent of records are deliberately
dirty, and some records use the legacy 'a,b,c' string format for team lists.

    python -m dota_pipeline.mock_api --port 8099 --size 5000
"""
from __future__ import annotations

import argparse
import json
import math
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_MATCH_ID = 8_000_000_000
BASE_START_TIME = 1_760_000_000  # Oct 2025
MATCH_SPACING_SECONDS = 20

HEROES = [
    (1, "antimage", "Anti-Mage", "agi", "Melee", ["Carry", "Escape", "Nuker"]),
    (2, "axe", "Axe", "str", "Melee", ["Initiator", "Durable", "Disabler"]),
    (3, "bane", "Bane", "all", "Ranged", ["Support", "Disabler", "Nuker"]),
    (4, "bloodseeker", "Bloodseeker", "agi", "Melee", ["Carry", "Disabler", "Nuker"]),
    (5, "crystal_maiden", "Crystal Maiden", "int", "Ranged", ["Support", "Disabler", "Nuker"]),
    (6, "drow_ranger", "Drow Ranger", "agi", "Ranged", ["Carry", "Disabler", "Pusher"]),
    (7, "earthshaker", "Earthshaker", "str", "Melee", ["Support", "Initiator", "Disabler"]),
    (8, "juggernaut", "Juggernaut", "agi", "Melee", ["Carry", "Pusher", "Escape"]),
    (9, "mirana", "Mirana", "agi", "Ranged", ["Carry", "Support", "Escape"]),
    (10, "morphling", "Morphling", "agi", "Ranged", ["Carry", "Escape", "Durable"]),
    (11, "nevermore", "Shadow Fiend", "agi", "Ranged", ["Carry", "Nuker"]),
    (12, "phantom_lancer", "Phantom Lancer", "agi", "Melee", ["Carry", "Escape", "Pusher"]),
    (13, "puck", "Puck", "int", "Ranged", ["Initiator", "Disabler", "Escape"]),
    (14, "pudge", "Pudge", "str", "Melee", ["Disabler", "Initiator", "Durable"]),
    (15, "razor", "Razor", "agi", "Ranged", ["Carry", "Durable", "Nuker"]),
    (16, "sand_king", "Sand King", "all", "Melee", ["Initiator", "Disabler", "Support"]),
    (17, "storm_spirit", "Storm Spirit", "int", "Ranged", ["Carry", "Escape", "Nuker"]),
    (18, "sven", "Sven", "str", "Melee", ["Carry", "Disabler", "Initiator"]),
    (19, "tiny", "Tiny", "str", "Melee", ["Carry", "Nuker", "Pusher"]),
    (20, "vengefulspirit", "Vengeful Spirit", "all", "Ranged", ["Support", "Initiator", "Disabler"]),
    (21, "windrunner", "Windranger", "all", "Ranged", ["Carry", "Support", "Disabler"]),
    (22, "zuus", "Zeus", "int", "Ranged", ["Nuker"]),
    (23, "kunkka", "Kunkka", "str", "Melee", ["Carry", "Support", "Disabler"]),
    (25, "lina", "Lina", "all", "Ranged", ["Support", "Carry", "Nuker"]),
    (26, "lion", "Lion", "int", "Ranged", ["Support", "Disabler", "Nuker"]),
    (27, "shadow_shaman", "Shadow Shaman", "int", "Ranged", ["Support", "Pusher", "Disabler"]),
    (28, "slardar", "Slardar", "str", "Melee", ["Carry", "Durable", "Initiator"]),
    (29, "tidehunter", "Tidehunter", "str", "Melee", ["Initiator", "Durable", "Disabler"]),
    (30, "witch_doctor", "Witch Doctor", "int", "Ranged", ["Support", "Nuker", "Disabler"]),
    (31, "lich", "Lich", "int", "Ranged", ["Support", "Nuker"]),
]
HERO_IDS = [h[0] for h in HEROES]

_rng = random.Random(42)
STRENGTH = {hid: _rng.gauss(0, 0.12) for hid in HERO_IDS}       # hidden hero power
POPULARITY = {hid: _rng.lognormvariate(0, 0.5) for hid in HERO_IDS}
RANK_MEDAL_WEIGHTS = [8, 14, 18, 20, 16, 12, 8, 2]               # Herald .. Immortal


def heroes_payload() -> list[dict]:
    return [
        {"id": i, "name": f"npc_dota_hero_{n}", "localized_name": ln,
         "primary_attr": attr, "attack_type": atk, "roles": roles}
        for i, n, ln, attr, atk, roles in HEROES
    ]


def make_match(index: int) -> dict:
    """Deterministic: the same index always yields the same match (higher index = newer)."""
    r = random.Random(index)
    picked: list[int] = []
    while len(picked) < 10:
        hid = r.choices(HERO_IDS, weights=[POPULARITY[h] for h in HERO_IDS])[0]
        if hid not in picked:
            picked.append(hid)
    radiant, dire = picked[:5], picked[5:]

    edge = sum(STRENGTH[h] for h in radiant) - sum(STRENGTH[h] for h in dire) + 0.03
    radiant_win = r.random() < 1 / (1 + math.exp(-edge * 1.5))

    medal = r.choices(range(1, 9), weights=RANK_MEDAL_WEIGHTS)[0]
    avg_rank = medal * 10 + r.choice([1, 2, 3, 4, 5]) + (0.5 if r.random() < 0.3 else 0)
    duration = int(min(max(r.gauss(2350, 650), 900), 5400))

    match = {
        "match_id": BASE_MATCH_ID + index,
        "match_seq_num": 7_000_000_000 + index,
        "radiant_win": radiant_win,
        "start_time": BASE_START_TIME + index * MATCH_SPACING_SECONDS,
        "duration": duration,
        "lobby_type": 7,
        "game_mode": 22,
        "avg_rank_tier": avg_rank,
        "num_rank_tier": r.randint(3, 10),
        "cluster": r.choice([111, 133, 152, 183, 223]),
        "radiant_team": radiant,
        "dire_team": dire,
    }

    roll = r.random()  # a few percent of dirty records
    if roll < 0.010:
        match["dire_team"] = dire[:4]                    # wrong team size
    elif roll < 0.015:
        match["duration"] = 0                            # broken duration
    elif roll < 0.025:
        match["avg_rank_tier"] = None                    # unranked match
    elif roll < 0.028:
        match["dire_team"] = dire[:4] + [radiant[0]]     # same hero on both teams

    if index % 17 == 0:                                  # legacy string format
        match["radiant_team"] = ",".join(map(str, match["radiant_team"]))
        match["dire_team"] = ",".join(map(str, match["dire_team"]))
    return match


def _handler_factory(size: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep output quiet
            pass

        def _send(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/heroes":
                return self._send(heroes_payload())
            if url.path == "/publicMatches":
                upper = int(query["less_than_match_id"][0]) if "less_than_match_id" in query else None
                min_rank = int(query["min_rank"][0]) if "min_rank" in query else None
                top = size - 1
                if upper is not None:
                    top = min(top, upper - BASE_MATCH_ID - 1)
                out = []
                for idx in range(top, -1, -1):
                    m = make_match(idx)
                    if min_rank is not None and (m["avg_rank_tier"] or 0) < min_rank:
                        continue
                    out.append(m)
                    if len(out) == 100:
                        break
                return self._send(out)
            self._send({"error": "not found"}, 404)

    return Handler


def start_mock_server(size: int = 5000, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start the mock API in a background thread. Returns (server, base_url)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler_factory(size))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--size", type=int, default=5000, help="number of matches in the fake universe")
    args = parser.parse_args()
    srv, url = start_mock_server(args.size, args.port)
    print(f"Mock OpenDota API on {url}  (Ctrl+C to stop)")
    threading.Event().wait()
