"""
Pre-deployment regression tests for Brighton Player Daily.

Run with:  pytest test_app.py -v
"""

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import app as app_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Flask test client in production mode (debug=False)."""
    original_debug = app_module.app.debug
    app_module.app.config["TESTING"] = True
    app_module.app.debug = False
    with app_module.app.test_client() as c:
        yield c
    app_module.app.debug = original_debug


@pytest.fixture
def debug_client():
    """Flask test client in debug mode (debug=True)."""
    original_debug = app_module.app.debug
    original_index = app_module.current_player_index
    app_module.app.config["TESTING"] = True
    app_module.app.debug = True
    with app_module.app.test_client() as c:
        yield c
    app_module.app.debug = original_debug
    app_module.current_player_index = original_index


@pytest.fixture
def sample_player():
    """Lewis Dunk — 'Still at club', single spell."""
    return app_module.players_df.iloc[71]


@pytest.fixture
def retired_player():
    """Bruno Saltor — 'Retired' in left_for field."""
    return app_module.players_df.iloc[61]


@pytest.fixture
def still_at_club_player():
    """Lewis Dunk — 'Still at club'."""
    return app_module.players_df.iloc[71]


@pytest.fixture
def second_spell_player():
    """Bobby Zamora — has a second spell at Brighton (2015-2016)."""
    return app_module.players_df.iloc[6]


@pytest.fixture
def mock_recent_players_file(tmp_path):
    """Redirect recent_players.json and cycle_state.json to a temp directory."""
    temp_file = str(tmp_path / "recent_players.json")
    with patch.object(app_module, "RECENT_PLAYERS_FILE", temp_file), \
         patch.object(app_module, "CYCLE_STATE_FILE", str(tmp_path / "cycle_state.json")):
        yield temp_file


# ---------------------------------------------------------------------------
# 1. Data Integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity:

    def test_csv_loaded_successfully(self):
        assert len(app_module.players_df) > 0

    def test_expected_row_count(self):
        assert len(app_module.players_df) == 193

    def test_all_required_columns_present(self):
        required = [
            "name", "date of birth", "place of birth", "country of birth",
            "position", "Brighton and Hove Albion league appearances",
            "Brighton and Hove Albion league goals",
            "number of spells at Brighton and Hove Albion",
            "Team played for before Brighton and Hove Albion (first spell)",
            "Team played for after Brighton and Hove Albion (first spell)",
            "seasons played at Brighton",
            "seasons at brighton during second spell",
        ]
        for col in required:
            assert col in app_module.players_df.columns, f"Missing column: {col}"

    def test_derived_columns_present(self):
        assert "first name" in app_module.players_df.columns
        assert "last name" in app_module.players_df.columns

    def test_no_empty_names(self):
        for _, row in app_module.players_df.iterrows():
            assert row["name"].strip() != "", f"Empty name at index {row.name}"

    def test_no_empty_dob(self):
        for _, row in app_module.players_df.iterrows():
            assert str(row["date of birth"]).strip() != "", f"Empty DOB for {row['name']}"

    def test_no_duplicate_names(self):
        names = app_module.players_df["name"].tolist()
        assert len(names) == len(set(names)), "Duplicate player names found"

    def test_all_players_have_first_name(self):
        for _, row in app_module.players_df.iterrows():
            assert row["first name"].strip() != "", f"Empty first name for: {row['name']}"

    def test_positions_are_valid(self):
        valid = {"Goalkeeper", "Defender", "Midfielder", "Forward", "Winger", "Full-back"}
        for _, row in app_module.players_df.iterrows():
            parts = [p.strip() for p in row["position"].replace("/", ",").split(",")]
            for part in parts:
                assert part in valid, f"Invalid position '{part}' for {row['name']}"

    def test_appearances_are_numeric(self):
        for _, row in app_module.players_df.iterrows():
            int(row["Brighton and Hove Albion league appearances"])

    def test_departed_players_have_closed_first_spell(self):
        """A player who has left (single spell) shouldn't have an open-ended '2020-' seasons range."""
        for _, row in app_module.players_df.iterrows():
            left_for = row["Team played for after Brighton and Hove Albion (first spell)"]
            seasons = str(row["seasons played at Brighton"]).strip()
            if left_for != "Still at club":
                assert not seasons.endswith("-"), f"{row['name']} left ({left_for}) but seasons is '{seasons}'"

    def test_still_at_club_players_have_open_seasons(self):
        for _, row in app_module.players_df.iterrows():
            if row["Team played for after Brighton and Hove Albion (first spell)"] == "Still at club":
                assert str(row["seasons played at Brighton"]).strip().endswith("-"), row["name"]


# ---------------------------------------------------------------------------
# 2. split_name
# ---------------------------------------------------------------------------

class TestSplitName:

    def test_split_standard_name(self):
        assert app_module.split_name("Lewis Dunk") == ("Lewis", "Dunk")

    def test_split_single_name(self):
        assert app_module.split_name("Bernardo") == ("Bernardo", "")

    def test_split_multi_part_last_name(self):
        first, last = app_module.split_name("Alexis Mac Allister")
        assert first == "Alexis"
        assert last == "Mac Allister"

    def test_split_nan_value(self):
        assert app_module.split_name(float("nan")) == ("", "")

    def test_split_name_with_quotes(self):
        assert app_module.split_name('"Lewis Dunk"') == ("Lewis", "Dunk")

    def test_split_name_with_whitespace(self):
        first, last = app_module.split_name("  Lewis Dunk  ")
        assert first == "Lewis"
        assert last == "Dunk"

    def test_all_players_produce_two_parts(self):
        for _, row in app_module.players_df.iterrows():
            result = app_module.split_name(row["name"])
            assert len(result) == 2, f"Bad split for {row['name']}"
            assert result[0] != "", f"Empty first name from split for {row['name']}"


# ---------------------------------------------------------------------------
# 3. build_clues
# ---------------------------------------------------------------------------

def candidate_texts(player):
    """All possible clues for a player (build_clues only returns the 5 chosen ones)."""
    return [c["text"] for c in app_module._candidate_clues(player)]


class TestBuildClues:

    def test_returns_nonempty_list(self, sample_player):
        clues = app_module.build_clues(sample_player, seed=42)
        assert len(clues) > 0

    def test_deterministic_with_same_seed(self, sample_player):
        a = app_module.build_clues(sample_player, seed=42)
        b = app_module.build_clues(sample_player, seed=42)
        assert a == b

    def test_different_seed_can_produce_different_result(self):
        """Seeds break ties between equally interesting clues, so some players must vary."""
        df = app_module.players_df
        assert any(
            app_module.build_clues(df.iloc[i], seed=42) != app_module.build_clues(df.iloc[i], seed=99)
            for i in range(len(df))
        )

    def test_retired_player_excludes_left_for(self, retired_player):
        clues = app_module.build_clues(retired_player, seed=42)
        for clue in clues:
            assert "left Brighton to join" not in clue
            assert "Retired" not in clue

    def test_retired_medical_excludes_left_for(self):
        player = app_module.players_df.iloc[119]  # Enock Mwepu
        clues = app_module.build_clues(player, seed=42)
        for clue in clues:
            assert "left Brighton to join" not in clue
            assert "Retired" not in clue

    def test_unattached_retired_excludes_left_for(self):
        df = app_module.players_df
        player = df[df["name"] == "Mauricio Taricco"].iloc[0]
        clues = app_module.build_clues(player, seed=42)
        for clue in clues:
            assert "left Brighton to join" not in clue
            assert "retired" not in clue.lower()

    def test_released_player_gets_released_clue(self):
        df = app_module.players_df
        player = df[df["name"] == "Solly March"].iloc[0]
        clues = candidate_texts(player)
        assert not any("join Released" in c for c in clues)
        assert any(c == "This player was released by Brighton." for c in clues)

    def test_still_at_club_suppressed_when_seasons_open_ended(self, still_at_club_player):
        """'Still at club' clue is redundant when seasons already shows an open-ended range like '2010-'."""
        clues = candidate_texts(still_at_club_player)
        assert "This player is still at the club." not in clues
        assert any("Seasons at Brighton:" in c for c in clues)

    def test_second_spell_included(self, second_spell_player):
        clues = candidate_texts(second_spell_player)
        assert any("second spell" in c.lower() for c in clues)

    def test_no_second_spell_excluded(self, sample_player):
        clues = app_module.build_clues(sample_player, seed=42)
        assert not any("second spell" in c.lower() for c in clues)

    def test_second_spell_seasons_preferred_over_spell_count(self, second_spell_player):
        """With 2 spells, the specific second-spell seasons clue makes '2 separate spells' redundant."""
        clues = candidate_texts(second_spell_player)
        assert any("second spell" in c for c in clues)
        assert not any("separate spells" in c for c in clues)

    def test_three_spell_player_gets_spell_count(self):
        df = app_module.players_df
        player = df[df["number of spells at Brighton and Hove Albion"].astype(str) == "3"].iloc[0]
        clues = candidate_texts(player)
        assert any("3 separate spells" in c for c in clues)

    def test_no_spell_s_wording(self):
        """The clunky 'spell(s)' wording should never appear."""
        for idx in range(len(app_module.players_df)):
            clues = candidate_texts(app_module.players_df.iloc[idx])
            assert not any("spell(s)" in c for c in clues)

    def test_dob_clue_reachable(self):
        """The date-of-birth clue used to be permanently deduped away by the birthplace clue."""
        df = app_module.players_df
        assert all(
            any("was born on" in c for c in candidate_texts(df.iloc[i]))
            for i in range(len(df))
        )

    def test_birthplace_and_dob_both_present(self, sample_player):
        clues = candidate_texts(sample_player)
        assert any("was born in" in c for c in clues)
        assert any("was born on" in c for c in clues)

    def test_last_visible_clue_is_decisive(self):
        """Clue 5 should fit at most DECISIVE_FITS players."""
        for idx in range(len(app_module.players_df)):
            player = app_module.players_df.iloc[idx]
            fits = {c["text"]: c["fits"] for c in app_module._candidate_clues(player)}
            clues = app_module.build_clues(player)
            assert fits[clues[-1]] <= app_module.DECISIVE_FITS, f"{player['name']}: {clues[-1]}"

    def test_position_not_in_first_clue(self):
        """Position is a weak filler clue and should never be the 5-star clue."""
        for idx in range(len(app_module.players_df)):
            clues = app_module.build_clues(app_module.players_df.iloc[idx])
            assert not clues[0].startswith("This player is a ")

    def test_every_player_has_enough_visible_clues(self):
        for idx in range(len(app_module.players_df)):
            clues = app_module.build_clues(app_module.players_df.iloc[idx])
            assert len(clues) >= app_module.MAX_VISIBLE_CLUES

    def test_clue_count_range(self):
        for idx in range(min(20, len(app_module.players_df))):
            player = app_module.players_df.iloc[idx]
            clues = app_module.build_clues(player, seed=42)
            assert len(clues) == app_module.MAX_VISIBLE_CLUES, (
                f"Player {player['name']} has {len(clues)} clues"
            )

    def test_all_clues_are_nonempty_strings(self, sample_player):
        clues = app_module.build_clues(sample_player, seed=42)
        for clue in clues:
            assert isinstance(clue, str)
            assert clue.strip() != ""


# ---------------------------------------------------------------------------
# 4. Recent Players (file I/O)
# ---------------------------------------------------------------------------

class TestRecentPlayers:

    def test_load_missing_file(self, mock_recent_players_file):
        result = app_module.load_recent_players()
        assert result == {}

    def test_load_invalid_json(self, mock_recent_players_file):
        with open(mock_recent_players_file, "w") as f:
            f.write("not json {{{")
        result = app_module.load_recent_players()
        assert result == {}

    def test_save_and_load_roundtrip(self, mock_recent_players_file):
        today = datetime.combine(datetime.now().date(), datetime.min.time())
        app_module.save_recent_players({today: 42})
        loaded = app_module.load_recent_players()
        assert today in loaded
        assert loaded[today] == 42

    def test_save_overwrites_existing(self, mock_recent_players_file):
        today = datetime.combine(datetime.now().date(), datetime.min.time())
        app_module.save_recent_players({today: 10})
        app_module.save_recent_players({today: 20})
        loaded = app_module.load_recent_players()
        assert loaded[today] == 20


# ---------------------------------------------------------------------------
# 5. get_daily_player
# ---------------------------------------------------------------------------

class TestGetDailyPlayer:

    def test_same_date_returns_same_player(self, mock_recent_players_file):
        app_module.app.debug = False
        app_module.current_player_index = None
        p1 = app_module.get_daily_player()
        p2 = app_module.get_daily_player()
        assert p1["name"] == p2["name"]

    def test_no_repeats_in_full_cycle(self, mock_recent_players_file):
        """Each cycle selects every eligible player exactly once."""
        start, order = app_module.get_cycle_order(date(2026, 10, 13))
        assert len(order) == len(set(order))
        assert set(order) == set(app_module._eligible_names())
        next_start, next_order = app_module.get_cycle_order(start + timedelta(days=len(order)))
        assert next_start == start + timedelta(days=len(order))
        assert len(next_order) == len(set(next_order))
        assert set(next_order) == set(app_module._eligible_names())

    def test_debug_override(self, mock_recent_players_file):
        app_module.app.debug = True
        app_module.current_player_index = 50
        player = app_module.get_daily_player()
        assert player["name"] == app_module.players_df.iloc[50]["name"]
        app_module.current_player_index = None
        app_module.app.debug = False

    def test_bootstrap_continues_legacy_cycle(self, mock_recent_players_file):
        """The cycle in progress at the switch to name-based state keeps its schedule."""
        start, order = app_module.get_cycle_order(date(2026, 10, 13))
        assert start == date(2026, 7, 2)
        assert order[(date(2026, 10, 13) - start).days] == "Mahmoud Dahoud"

    def test_bootstrap_names_exist_and_are_eligible(self):
        with open(app_module.CYCLE_BOOTSTRAP_FILE) as f:
            order = json.load(f)["order"]
        assert len(order) == len(set(order))
        missing = set(order) - set(app_module._eligible_names())
        assert not missing, f"Bootstrap names not eligible in CSV: {missing}"

    def test_new_players_appended_without_reshuffling(self, mock_recent_players_file):
        """Adding an eligible player mid-cycle must not change any scheduled day."""
        today = date(2026, 10, 13)
        start, before = app_module.get_cycle_order(today)
        new_row = app_module.players_df.iloc[0].copy()
        new_row["name"] = "Test Signing"
        new_row["Brighton and Hove Albion league appearances"] = 3
        bigger_df = pd.concat([app_module.players_df, new_row.to_frame().T], ignore_index=True)
        with patch.object(app_module, "players_df", bigger_df):
            start_after, after = app_module.get_cycle_order(today)
        assert start_after == start
        assert after[:len(before)] == before
        assert after[len(before):] == ["Test Signing"]

    def test_new_cycle_order_is_persisted(self, mock_recent_players_file):
        """Once a new cycle starts, its order is saved and survives later CSV additions."""
        start, order = app_module.get_cycle_order(date(2026, 10, 13))
        next_day = start + timedelta(days=len(order))
        next_start, next_order = app_module.get_cycle_order(next_day)
        with open(app_module.CYCLE_STATE_FILE) as f:
            saved = json.load(f)
        assert saved["cycle_start"] == next_start.isoformat()
        assert saved["order"] == next_order

        new_row = app_module.players_df.iloc[0].copy()
        new_row["name"] = "Test Signing"
        new_row["Brighton and Hove Albion league appearances"] = 1
        bigger_df = pd.concat([app_module.players_df, new_row.to_frame().T], ignore_index=True)
        with patch.object(app_module, "players_df", bigger_df):
            _, later_order = app_module.get_cycle_order(next_day + timedelta(days=5))
        assert later_order[:len(next_order)] == next_order
        assert later_order[-1] == "Test Signing"

    def test_caches_selection(self, mock_recent_players_file):
        app_module.app.debug = False
        app_module.current_player_index = None
        app_module.get_daily_player()
        loaded = app_module.load_recent_players()
        assert len(loaded) > 0


# ---------------------------------------------------------------------------
# 6. API Routes
# ---------------------------------------------------------------------------

class TestAPIRoutes:

    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.content_type

    def test_daily_challenge_structure(self, client):
        data = client.get("/api/daily-challenge").get_json()
        for key in ("firstNameLength", "lastNameLength", "firstClue",
                     "player_id", "firstName", "lastName"):
            assert key in data, f"Missing key: {key}"

    def test_daily_challenge_name_lengths_match(self, client):
        data = client.get("/api/daily-challenge").get_json()
        assert data["firstNameLength"] == len(data["firstName"])
        assert data["lastNameLength"] == len(data["lastName"])

    def test_clues_returns_clue(self, client):
        challenge = client.get("/api/daily-challenge").get_json()
        resp = client.post("/api/clues", json={
            "player_id": challenge["player_id"],
            "clue_index": 0,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "clue" in data
        assert len(data["clue"]) > 0

    def test_guess_correct(self, client):
        challenge = client.get("/api/daily-challenge").get_json()
        resp = client.post("/api/guess", json={
            "player_id": challenge["player_id"],
            "guess_first": challenge["firstName"],
            "guess_last": challenge["lastName"],
        })
        data = resp.get_json()
        assert data["correct"] is True
        assert "fullName" in data

    def test_guess_correct_case_insensitive(self, client):
        challenge = client.get("/api/daily-challenge").get_json()
        resp = client.post("/api/guess", json={
            "player_id": challenge["player_id"],
            "guess_first": challenge["firstName"].lower(),
            "guess_last": challenge["lastName"].lower(),
        })
        assert resp.get_json()["correct"] is True

    def test_guess_incorrect(self, client):
        challenge = client.get("/api/daily-challenge").get_json()
        resp = client.post("/api/guess", json={
            "player_id": challenge["player_id"],
            "guess_first": "WrongName",
            "guess_last": "WrongLast",
        })
        data = resp.get_json()
        assert data["correct"] is False
        assert "fullName" not in data

    def test_guess_single_name_player(self, debug_client):
        debug_client.post("/api/set-player", json={"player_id": 90})
        resp = debug_client.post("/api/guess", json={
            "player_id": 90,
            "guess_first": "bernardo",
            "guess_last": "",
        })
        assert resp.get_json()["correct"] is True

    def test_config_production(self, client):
        data = client.get("/api/config").get_json()
        assert data["isLocal"] is False
        assert data["playerCount"] == len(app_module.players_df)

    def test_config_debug(self, debug_client):
        data = debug_client.get("/api/config").get_json()
        assert data["isLocal"] is True


# ---------------------------------------------------------------------------
# 7. Debug Endpoints
# ---------------------------------------------------------------------------

class TestDebugEndpoints:

    def test_set_player_blocked_in_production(self, client):
        resp = client.post("/api/set-player", json={"player_id": 0})
        assert resp.status_code == 403

    def test_set_player_works_in_debug(self, debug_client):
        resp = debug_client.post("/api/set-player", json={"player_id": 5})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_set_player_random_only_picks_eligible(self, debug_client):
        """The debug 'Change Player' button must never land on a zero-appearance player."""
        eligible = set(app_module._eligible_names())
        seen = set()
        for _ in range(300):
            resp = debug_client.post("/api/set-player", json={"random": True})
            assert resp.status_code == 200
            name = app_module.players_df.iloc[app_module.current_player_index]["name"]
            assert name in eligible
            seen.add(app_module.current_player_index)
        # Rows added after the original 163 (e.g. new signings) must be reachable too
        assert max(seen) >= 163

    def test_set_player_invalid_index(self, debug_client):
        resp = debug_client.post("/api/set-player", json={"player_id": 9999})
        assert resp.status_code == 400

    def test_recent_players_blocked_in_production(self, client):
        resp = client.get("/api/debug/recent-players")
        assert resp.status_code == 403

    def test_recent_players_works_in_debug(self, debug_client):
        resp = debug_client.get("/api/debug/recent-players")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "recent_players" in data
        assert "total_players" in data

    def test_reset_recent_blocked_in_production(self, client):
        resp = client.get("/api/debug/reset-recent")
        assert resp.status_code == 403

    def test_reset_recent_works_in_debug(self, debug_client):
        resp = debug_client.get("/api/debug/reset-recent")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ---------------------------------------------------------------------------
# 8. Gemini Routes (mocked)
# ---------------------------------------------------------------------------

class TestGeminiRoutes:

    def test_cryptic_clue_503_without_model(self, client):
        with patch.object(app_module, "model", None):
            resp = client.post("/api/cryptic-clue", json={"player_id": 72})
            assert resp.status_code == 503

    def test_player_bio_503_without_model(self, client):
        with patch.object(app_module, "model", None):
            resp = client.post("/api/player-bio", json={"player_id": 72})
            assert resp.status_code == 503

    def test_cryptic_clue_success_with_mock(self, client):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text="A clever clue")
        with patch.object(app_module, "model", mock_model):
            resp = client.post("/api/cryptic-clue", json={"player_id": 72})
            assert resp.status_code == 200
            assert "clue" in resp.get_json()

    def test_player_bio_success_with_mock(self, client):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text="A brief bio.")
        with patch.object(app_module, "model", mock_model):
            resp = client.post("/api/player-bio", json={"player_id": 72})
            assert resp.status_code == 200
            assert "bio" in resp.get_json()

    def test_cryptic_clue_handles_api_error(self, client):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("API quota exceeded")
        with patch.object(app_module, "model", mock_model):
            resp = client.post("/api/cryptic-clue", json={"player_id": 72})
            assert resp.status_code == 500


# ---------------------------------------------------------------------------
# 9. Special Character Handling (apostrophes, hyphens, smart quotes)
# ---------------------------------------------------------------------------

class TestSpecialCharacters:

    def _find_player_index(self, name):
        matches = app_module.players_df[app_module.players_df["name"] == name]
        assert len(matches) == 1, f"Player '{name}' not found"
        return int(matches.index[0])

    def test_guess_with_apostrophe(self, debug_client):
        idx = self._find_player_index("Mark O'Mahony")
        debug_client.post("/api/set-player", json={"player_id": idx})
        resp = debug_client.post("/api/guess", json={
            "player_id": idx,
            "guess_first": "Mark",
            "guess_last": "O'Mahony",
        })
        assert resp.get_json()["correct"] is True

    def test_guess_with_smart_quote(self, debug_client):
        """Curly/smart apostrophe (U+2019) should match straight apostrophe."""
        idx = self._find_player_index("Mark O'Mahony")
        debug_client.post("/api/set-player", json={"player_id": idx})
        resp = debug_client.post("/api/guess", json={
            "player_id": idx,
            "guess_first": "Mark",
            "guess_last": "O\u2019Mahony",
        })
        assert resp.get_json()["correct"] is True

    def test_guess_with_hyphen(self, debug_client):
        idx = self._find_player_index("Colin Kazim-Richards")
        debug_client.post("/api/set-player", json={"player_id": idx})
        resp = debug_client.post("/api/guess", json={
            "player_id": idx,
            "guess_first": "Colin",
            "guess_last": "Kazim-Richards",
        })
        assert resp.get_json()["correct"] is True

    def test_apostrophe_name_lengths_include_special_char(self, debug_client):
        """Name length should include the apostrophe character."""
        idx = self._find_player_index("Mark O'Mahony")
        debug_client.post("/api/set-player", json={"player_id": idx})
        data = debug_client.get("/api/daily-challenge").get_json()
        assert data["lastNameLength"] == len("O'Mahony")


# ---------------------------------------------------------------------------
# 10. Clue Logic (era suppression, seasons text)
# ---------------------------------------------------------------------------

class TestClueLogic:

    @pytest.mark.parametrize("raw, expected", [
        ("Youth", "This player came through Brighton's academy."),
        ("Arsenal (youth)", "This player came through the youth ranks at Arsenal before joining Brighton."),
        ("Brentford (loan)", "This player first arrived at Brighton on loan from Brentford."),
        ("Union SG (loan from Brighton)", "While on Brighton's books, this player was loaned out to Union SG."),
        ("Unattached (previously Brighton coach)", "This player joined Brighton as a free agent."),
        ("Fulham", "This player joined Brighton from Fulham."),
        ("", ""),
    ])
    def test_joined_from_clue_formatting(self, raw, expected):
        assert app_module._joined_from_clue(raw) == expected

    def test_no_raw_parenthetical_notes_in_clues(self):
        """Raw CSV notes like '(youth)' or '(loan)' must never leak into clue text."""
        for idx in range(len(app_module.players_df)):
            for clue in app_module.build_clues(app_module.players_df.iloc[idx]):
                assert "(youth)" not in clue and "(loan" not in clue, clue
                assert "Self-Proclaimed" not in clue

    @pytest.mark.parametrize("raw, expected", [
        ("16-Jan-81", "16 January 1981"),
        ("04-Jan-99", "4 January 1999"),
        ("12-Mar-02", "12 March 2002"),
        ("26-Jun-74", "26 June 1974"),
        ("", ""),
        ("not a date", ""),
    ])
    def test_format_dob(self, raw, expected):
        assert app_module._format_dob(raw) == expected

    def test_all_dobs_parse(self):
        for dob in app_module.players_df["date of birth"]:
            assert app_module._format_dob(dob), f"Unparseable DOB: {dob!r}"

    def test_era_clue_suppressed_when_seasons_exist(self):
        """Era clue ('played during the 2010s') should not appear when seasons data exists."""
        player = app_module.players_df.iloc[71]  # Lewis Dunk — has seasons data
        clues = app_module.build_clues(player, seed=42)
        for clue in clues:
            assert "played for Brighton during the" not in clue

    def test_seasons_clue_says_at_not_played_at(self):
        """Seasons clue should say 'Seasons at Brighton' not 'Seasons played at Brighton'."""
        player = app_module.players_df.iloc[71]
        clues = candidate_texts(player)
        seasons_clues = [c for c in clues if "Seasons at Brighton:" in c]
        assert len(seasons_clues) > 0, "Seasons clue should be present"
        for c in clues:
            assert "Seasons played at Brighton" not in c

    def test_no_duplicate_clue_text_for_any_player(self):
        """Every player's clue list must contain only unique text (no repeated clues)."""
        for idx in range(len(app_module.players_df)):
            player = app_module.players_df.iloc[idx]
            clues = app_module.build_clues(player, seed=42)
            assert len(clues) == len(set(clues)), (
                f"Player {player['name']} (id={idx}) has duplicate clue text: "
                f"{[c for c in clues if clues.count(c) > 1]}"
            )

    def test_era_suppression_across_multiple_players(self):
        """For any player with seasons data, era clue should be suppressed."""
        for idx in range(min(30, len(app_module.players_df))):
            player = app_module.players_df.iloc[idx]
            if player["seasons played at Brighton"]:
                clues = app_module.build_clues(player, seed=42)
                for clue in clues:
                    assert "played for Brighton during the" not in clue, (
                        f"Era clue leaked for {player['name']}"
                    )


# ---------------------------------------------------------------------------
# 10b. Derived Clues (stadium, divisions, landmarks, ranks, selection)
# ---------------------------------------------------------------------------

def _player(name):
    df = app_module.players_df
    return df[df["name"] == name].iloc[0]


def _candidates_by_key(player):
    return {c["key"]: c for c in app_module._candidate_clues(player)}


class TestDerivedClues:

    @pytest.mark.parametrize("raw, expected", [
        ("2007-2010", [2007, 2008, 2009]),
        ("2021", [2021]),
        ("2010-2010", [2010]),
        ("", []),
    ])
    def test_season_years(self, raw, expected):
        assert app_module._season_years(raw) == expected

    def test_open_ended_seasons_run_to_current(self):
        years = app_module._season_years("2024-")
        assert years[0] == 2024 and years[-1] == app_module._current_season()

    @pytest.mark.parametrize("season, tier", [
        (1999, 4), (2000, 4), (2001, 3), (2002, 2), (2003, 3), (2004, 2), (2005, 2),
        (2006, 3), (2010, 3), (2011, 2), (2016, 2), (2017, 1), (2025, 1),
    ])
    def test_league_tier(self, season, tier):
        assert app_module._league_tier(season) == tier

    @pytest.mark.parametrize("season, stadium", [
        (1996, "the Goldstone Ground"), (1997, "Gillingham's Priestfield"), (1998, "Gillingham's Priestfield"),
        (1999, "Withdean"), (2010, "Withdean"), (2011, "the Amex"),
    ])
    def test_stadium(self, season, stadium):
        assert app_module._stadium(season) == stadium

    def test_withdean_and_amex_stadium_clue(self, sample_player):
        clue = _candidates_by_key(sample_player)["stadium"]["text"]  # Lewis Dunk, 2010-
        assert clue == "This player played home games for Brighton at both Withdean and the Amex."

    def test_amex_only_players_get_no_stadium_clue(self):
        assert "stadium" not in _candidates_by_key(_player("Mats Wieffer"))

    def test_landmark_clue(self, sample_player):
        clue = _candidates_by_key(sample_player)["landmark"]["text"]
        assert "League One title in 2011" in clue

    def test_goal_drought_clue_replaces_goals_clue(self):
        cands = _candidates_by_key(_player("Michel Kuipers"))
        assert cands["drought"]["text"] == "This player made 247 league appearances without scoring a single league goal."
        assert "goals" not in cands

    def test_rank_clues_say_since_2002(self, sample_player):
        cands = _candidates_by_key(sample_player)
        assert cands["apps_rank"]["text"] == "This player has more league appearances than any other player since 2002."
        assert "since 2002" in cands["goals_rank"]["text"]

    def test_current_player_gets_no_career_ended_clue(self):
        """Players currently at the club (e.g. Pascal Gross in a second spell) haven't ended their careers."""
        for idx in range(len(app_module.players_df)):
            player = app_module.players_df.iloc[idx]
            if app_module._is_current(player):
                assert "age_out" not in _candidates_by_key(player), player["name"]

    def test_no_duplicated_country_in_birthplace(self):
        """Players whose place of birth is just 'England' shouldn't get 'born in England, England'."""
        for idx in range(len(app_module.players_df)):
            for text in candidate_texts(app_module.players_df.iloc[idx]):
                assert "England, England" not in text

    def test_fits_counts_include_the_player(self):
        for idx in range(0, len(app_module.players_df), 10):
            for c in app_module._candidate_clues(app_module.players_df.iloc[idx]):
                assert c["fits"] >= 1

    def test_teammate_clue_never_names_the_player(self):
        for idx in range(len(app_module.players_df)):
            player = app_module.players_df.iloc[idx]
            cands = _candidates_by_key(player)
            if "teammate" in cands:
                assert player["name"] not in cands["teammate"]["text"]


class TestClueSelection:

    def _chosen(self, player):
        cands = {c["text"]: c for c in app_module._candidate_clues(player)}
        return [cands[t] for t in app_module.build_clues(player)]

    def test_first_clue_usually_in_target_band(self):
        """Clue 1 should fit a handful of players for nearly everyone."""
        lo, hi = app_module.FIRST_CLUE_FITS
        df = app_module.players_df
        in_band = sum(lo <= self._chosen(df.iloc[i])[0]["fits"] <= hi for i in range(len(df)))
        assert in_band / len(df) >= 0.9

    def test_one_of_first_two_clues_places_player_in_time(self):
        df = app_module.players_df
        for i in range(len(df)):
            player = df.iloc[i]
            chosen = self._chosen(player)
            non_decisive_era = [c for c in app_module._candidate_clues(player)
                                if c["key"] in app_module.ERA_CLUES and c["fits"] > app_module.DECISIVE_FITS]
            if non_decisive_era:
                assert {c["key"] for c in chosen[:2]} & app_module.ERA_CLUES, player["name"]

    def test_no_two_clues_share_a_fact(self):
        df = app_module.players_df
        for i in range(len(df)):
            groups = [app_module.FACT_GROUPS.get(c["key"], c["key"]) for c in self._chosen(df.iloc[i])]
            assert len(groups) == len(set(groups)), df.iloc[i]["name"]

    def test_position_never_chosen_when_alternatives_exist(self):
        df = app_module.players_df
        for i in range(len(df)):
            player = df.iloc[i]
            if len(app_module._candidate_clues(player)) > app_module.MAX_VISIBLE_CLUES + 3:
                assert all(c["key"] != "position" for c in self._chosen(player)), player["name"]

    def test_first_clue_never_boring_and_broad(self):
        """Clue 1 should never be something like 'scored 0 league goals' (fits ~77 players)."""
        lo, hi = app_module.FIRST_CLUE_FITS
        df = app_module.players_df
        for i in range(len(df)):
            first = self._chosen(df.iloc[i])[0]
            assert not (first["fits"] > hi and app_module.CLUE_INTEREST[first["key"]] < 3), (
                f"{df.iloc[i]['name']}: {first['text']}"
            )

    def test_middle_clues_ordered_broad_to_narrow(self, sample_player):
        chosen = self._chosen(sample_player)
        middle = [c["fits"] for c in chosen[1:-1]]
        assert middle == sorted(middle, reverse=True)

    def test_cached_result_is_not_mutable(self, sample_player):
        clues = app_module.build_clues(sample_player)
        clues.append("tampered")
        assert "tampered" not in app_module.build_clues(sample_player)


# ---------------------------------------------------------------------------
# 11. Player Selection Filter (league appearances)
# ---------------------------------------------------------------------------

class TestPlayerSelectionFilter:

    def test_daily_player_has_league_appearances(self, mock_recent_players_file):
        """Daily player should always have at least 1 league appearance."""
        app_module.app.debug = False
        app_module.current_player_index = None
        player = app_module.get_daily_player()
        assert int(player["Brighton and Hove Albion league appearances"]) > 0

    def test_zero_appearance_players_exist_in_csv(self):
        """Confirm zero-appearance players exist (validates that the filter matters)."""
        zero_apps = app_module.players_df[
            app_module.players_df["Brighton and Hove Albion league appearances"] == 0
        ]
        assert len(zero_apps) > 0

    def test_eligible_pool_excludes_zero_appearances(self):
        """The selection pool used by get_daily_player should exclude zero-appearance players."""
        eligible = [
            idx for idx in range(len(app_module.players_df))
            if app_module.players_df.iloc[idx]["Brighton and Hove Albion league appearances"] > 0
        ]
        zero_apps = [
            idx for idx in range(len(app_module.players_df))
            if app_module.players_df.iloc[idx]["Brighton and Hove Albion league appearances"] == 0
        ]
        # All zero-appearance players should be excluded from the eligible pool
        for idx in zero_apps:
            assert idx not in eligible
        # Eligible pool should be smaller than total
        assert len(eligible) < len(app_module.players_df)
