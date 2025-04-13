import pytest
from tion_btle.scenarist import Scenarist, Scenario


@pytest.fixture
def scenarist(tmp_path):
    db_path = tmp_path / "test_scenarios.db"
    return Scenarist(db_path=str(db_path))


def test_create_scenario(scenarist):
    """Test creating a new scenario"""
    scenario_id = scenarist.create_scenario(
        Scenario(
            id=0,
            name="Night Mode",
            trigger_type="time",
            trigger_params={"time": "23:00"},
            action_params={"devices": ["all"], "state": "off"},
        )
    )
    assert scenario_id == 1

    scenarios = scenarist.get_scenarios()
    assert len(scenarios) == 1
    assert scenarios[0].name == "Night Mode"
    assert scenarios[0].trigger_type == "time"


def test_get_scenario(scenarist):
    """Test retrieving a single scenario"""
    scenario_id = scenarist.create_scenario(
        Scenario(
            id=0,
            name="CO2 Control",
            trigger_type="sensor",
            trigger_params={"sensor": "co2", "threshold": 1000},
            action_params={"devices": ["living-room"], "fan_speed": 4},
        )
    )

    scenario = scenarist.get_scenario(scenario_id)
    assert scenario is not None
    assert scenario.name == "CO2 Control"
    assert scenario.trigger_params["threshold"] == 1000


def test_update_scenario(scenarist):
    """Test updating a scenario"""
    scenario_id = scenarist.create_scenario(
        Scenario(
            id=0,
            name="Original Name",
            trigger_type="time",
            trigger_params={"time": "09:00"},
            action_params={"devices": ["all"], "state": "on"},
        )
    )

    updated = scenarist.update_scenario(
        scenario_id, name="Updated Name", trigger_params={"time": "10:00"}
    )
    assert updated

    scenario = scenarist.get_scenario(scenario_id)
    assert scenario.name == "Updated Name"
    assert scenario.trigger_params["time"] == "10:00"


def test_delete_scenario(scenarist):
    """Test deleting a scenario"""
    scenario_id = scenarist.create_scenario(
        Scenario(
            id=0,
            name="Test Scenario",
            trigger_type="time",
            trigger_params={"time": "12:00"},
            action_params={"devices": ["all"], "state": "on"},
        )
    )

    deleted = scenarist.delete_scenario(scenario_id)
    assert deleted

    scenarios = scenarist.get_scenarios()
    assert len(scenarios) == 0

    all_scenarios = scenarist.get_scenarios(active_only=False)
    assert len(all_scenarios) == 1
    assert not all_scenarios[0].is_active
