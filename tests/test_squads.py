import pytest

from app.football import squad_document, squad_payload

FETCHED_AT = "2026-09-30T10:00:00+07:00"


def raw_team(**overrides) -> dict:
    team = {
        "id": 57,
        "name": "Arsenal FC",
        "coach": {"id": 11, "name": "Mikel Arteta", "nationality": "Spain"},
        "squad": [
            {
                "id": 3189,
                "name": "Kepa Arrizabalaga",
                "position": "Goalkeeper",
                "dateOfBirth": "1994-10-03",
                "nationality": "Spain",
            },
            {
                "id": 4001,
                "name": "Martin Ødegaard",
                "position": "Midfielder",
                "dateOfBirth": "1998-12-17",
                "nationality": "Norway",
            },
        ],
    }
    team.update(overrides)
    return team


def test_squad_payload_maps_players_and_coach():
    squad = squad_payload(raw_team(), FETCHED_AT)
    assert squad["team_id"] == 57
    assert squad["team_name"] == "Arsenal FC"
    assert squad["coach"] == {"id": 11, "name": "Mikel Arteta", "nationality": "Spain"}
    assert squad["fetched_at"] == FETCHED_AT
    assert squad["players"][0] == {
        "id": 3189,
        "name": "Kepa Arrizabalaga",
        "position": "Goalkeeper",
        "date_of_birth": "1994-10-03",
        "nationality": "Spain",
    }


@pytest.mark.parametrize("squad", [[], None])
def test_squad_payload_is_none_when_squad_is_empty_or_null(squad):
    assert squad_payload(raw_team(squad=squad), FETCHED_AT) is None


def test_squad_payload_is_none_when_squad_key_is_missing():
    team = raw_team()
    del team["squad"]
    assert squad_payload(team, FETCHED_AT) is None


def test_squad_payload_skips_players_without_a_name():
    team = raw_team(squad=[{"id": 1, "name": ""}, {"id": 2, "name": "Bukayo Saka"}])
    squad = squad_payload(team, FETCHED_AT)
    assert [p["name"] for p in squad["players"]] == ["Bukayo Saka"]


@pytest.mark.parametrize("coach", [None, {}, {"id": 5, "name": ""}])
def test_squad_payload_coach_is_none_when_missing_or_nameless(coach):
    assert squad_payload(raw_team(coach=coach), FETCHED_AT)["coach"] is None


def test_squad_document_follows_the_contract_shape():
    document = squad_document(squad_payload(raw_team(), FETCHED_AT), "2026")
    assert document["doc_id"] == "players-2026-team-57"
    assert document["category"] == "player"
    assert document["origin"] == "football-data.org"
    assert document["season"] == "2026"
    assert document["matchweek"] is None
    assert document["team_ids"] == [57]
    assert document["date"] == "2026-09-30"
    assert document["fetched_at"] == FETCHED_AT
    assert document["url"] is None
    assert document["title"] == "Arsenal FC squad 2026"


def test_squad_document_has_one_heading_per_player_and_keeps_special_characters():
    text = squad_document(squad_payload(raw_team(), FETCHED_AT), "2026")["text"]
    assert text.startswith("Premier League 2026 squad: Arsenal FC. Coach: Mikel Arteta.")
    assert text.count("\n## ") == 2
    assert "## Martin Ødegaard" in text
    assert (
        "Team: Arsenal FC. Position: Midfielder. Date of birth: 1998-12-17. Nationality: Norway."
    ) in text


def test_squad_document_never_prints_none_for_missing_fields():
    team = raw_team(coach=None, squad=[{"id": 9, "name": "Trialist"}])
    text = squad_document(squad_payload(team, FETCHED_AT), "2026")["text"]
    assert "None" not in text
    assert "Coach:" not in text
    assert "Position: unknown. Date of birth: unknown. Nationality: unknown." in text
