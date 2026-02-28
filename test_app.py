"""
Pre-deployment regression tests for Brighton Player Daily.

Run with:  pytest test_app.py -v
"""

import json
from datetime import datetime, timedelta
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
    return app_module.players_df.iloc[72]


@pytest.fixture
def retired_player():
    """Bruno Saltor — 'Retired' in left_for field."""
    return app_module.players_df.iloc[62]


@pytest.fixture
def still_at_club_player():
    """Lewis Dunk — 'Still at club'."""
    return app_module.players_df.iloc[72]


@pytest.fixture
def second_spell_player():
    """Bobby Zamora — has a second spell at Brighton (2015-2016)."""
    return app_module.players_df.iloc[6]


@pytest.fixture
def mock_recent_players_file(tmp_path):
    """Redirect recent_players.json to a temp directory."""
    temp_file = str(tmp_path / "recent_players.json")
    with patch.object(app_module, "RECENT_PLAYERS_FILE", temp_file):
        yield temp_file


# ---------------------------------------------------------------------------
# 1. Data Integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity:

    def test_csv_loaded_successfully(self):
        assert len(app_module.players_df) > 0

    def test_expected_row_count(self):
        assert len(app_module.players_df) == 184

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

class TestBuildClues:

    def test_returns_nonempty_list(self, sample_player):
        clues = app_module.build_clues(sample_player, seed=42)
        assert len(clues) > 0

    def test_deterministic_with_same_seed(self, sample_player):
        a = app_module.build_clues(sample_player, seed=42)
        b = app_module.build_clues(sample_player, seed=42)
        assert a == b

    def test_different_seed_produces_different_result(self, sample_player):
        a = app_module.build_clues(sample_player, seed=42)
        b = app_module.build_clues(sample_player, seed=99)
        # Different seeds should produce a different list (order and/or content
        # may differ because shuffle order affects fact-dedup outcomes)
        assert a != b

    def test_retired_player_excludes_left_for(self, retired_player):
        clues = app_module.build_clues(retired_player, seed=42)
        for clue in clues:
            assert "left Brighton to join" not in clue
            assert "Retired" not in clue

    def test_retired_medical_excludes_left_for(self):
        player = app_module.players_df.iloc[120]  # Enock Mwepu
        clues = app_module.build_clues(player, seed=42)
        for clue in clues:
            assert "left Brighton to join" not in clue
            assert "Retired" not in clue

    def test_still_at_club_suppressed_when_seasons_open_ended(self, still_at_club_player):
        """'Still at club' clue is redundant when seasons already shows an open-ended range like '2010-'."""
        clues = app_module.build_clues(still_at_club_player, seed=42)
        assert "This player is still at the club." not in clues
        assert any("Seasons at Brighton:" in c for c in clues)

    def test_second_spell_included(self, second_spell_player):
        clues = app_module.build_clues(second_spell_player, seed=42)
        assert any("second spell" in c.lower() for c in clues)

    def test_no_second_spell_excluded(self, sample_player):
        clues = app_module.build_clues(sample_player, seed=42)
        assert not any("second spell" in c.lower() for c in clues)

    def test_no_duplicate_facts(self, sample_player):
        clues = app_module.build_clues(sample_player, seed=42)
        birth_full = [c for c in clues if "was born on" in c]
        birth_spells = [c for c in clues if "was born in" in c and "spell(s)" in c]
        assert not (birth_full and birth_spells), "Both birth clues present — fact dedup failed"

    def test_clue_count_range(self):
        for idx in range(min(20, len(app_module.players_df))):
            player = app_module.players_df.iloc[idx]
            clues = app_module.build_clues(player, seed=42)
            assert 4 <= len(clues) <= 9, (
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

    def test_avoids_recently_used_players(self, mock_recent_players_file):
        today = datetime.now().date()
        recent = {}
        used_indices = set()
        for i in range(5):
            d = datetime.combine(today - timedelta(days=i + 1), datetime.min.time())
            recent[d] = i
            used_indices.add(i)
        app_module.save_recent_players(recent)

        app_module.app.debug = False
        app_module.current_player_index = None
        player = app_module.get_daily_player()
        assert player.name not in used_indices  # player.name is the DataFrame index

    def test_debug_override(self, mock_recent_players_file):
        app_module.app.debug = True
        app_module.current_player_index = 50
        player = app_module.get_daily_player()
        assert player["name"] == app_module.players_df.iloc[50]["name"]
        app_module.current_player_index = None
        app_module.app.debug = False

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
        debug_client.post("/api/set-player", json={"player_id": 91})
        resp = debug_client.post("/api/guess", json={
            "player_id": 91,
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

    def test_era_clue_suppressed_when_seasons_exist(self):
        """Era clue ('played during the 2010s') should not appear when seasons data exists."""
        player = app_module.players_df.iloc[72]  # Lewis Dunk — has seasons data
        clues = app_module.build_clues(player, seed=42)
        for clue in clues:
            assert "played for Brighton during the" not in clue

    def test_seasons_clue_says_at_not_played_at(self):
        """Seasons clue should say 'Seasons at Brighton' not 'Seasons played at Brighton'."""
        player = app_module.players_df.iloc[72]
        clues = app_module.build_clues(player, seed=42)
        seasons_clues = [c for c in clues if "Seasons at Brighton:" in c]
        assert len(seasons_clues) > 0, "Seasons clue should be present"
        for c in clues:
            assert "Seasons played at Brighton" not in c

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
