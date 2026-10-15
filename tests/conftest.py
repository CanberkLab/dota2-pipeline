import pytest

from dota_pipeline import ingest


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    """Replays a list of responses and records the calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def make_client():
    def _make(responses, **kwargs):
        session = FakeSession(responses)
        sleeps = []
        client = ingest.OpenDotaClient(
            base_url="http://api.test", session=session, min_interval=0,
            sleep=sleeps.append, **kwargs,
        )
        client.sleeps = sleeps
        client.session_ref = session
        return client

    return _make


def match(match_id, **overrides):
    base = {
        "match_id": match_id, "match_seq_num": match_id, "start_time": 1_760_000_000 + match_id,
        "duration": 2400, "radiant_win": True, "avg_rank_tier": 55, "num_rank_tier": 6,
        "game_mode": 22, "lobby_type": 7, "cluster": 111,
        "radiant_team": [1, 2, 3, 4, 5], "dire_team": [6, 7, 8, 9, 10],
    }
    base.update(overrides)
    return base
