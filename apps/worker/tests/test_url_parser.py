from srs_core.azure.url_parser import parse_azure_devops_url


def test_parses_org_root_backlog_url_with_team_after_backlogs():
    """This is the exact URL shape that triggered a whole-project import
    instead of the intended team/backlog scope: team appears AFTER
    _backlogs/backlog/, not before it.
    """
    url = (
        "https://dev.azure.com/erainfotechbd/ERA%20InfoTech%20Limited/"
        "_backlogs/backlog/Global%20Customer%20Information%20File-CIF/Epics"
    )
    parsed = parse_azure_devops_url(url)

    assert parsed.org == "erainfotechbd"
    assert parsed.project == "ERA InfoTech Limited"
    assert parsed.team == "Global Customer Information File-CIF"
    assert parsed.backlog_level == "Epics"
    assert parsed.work_item_id is None


def test_parses_team_context_backlog_url():
    """The other valid shape: team appears BEFORE _backlogs."""
    url = "https://dev.azure.com/myorg/MyProject/MyTeam/_backlogs/Stories"
    parsed = parse_azure_devops_url(url)

    assert parsed.org == "myorg"
    assert parsed.project == "MyProject"
    assert parsed.team == "MyTeam"
    assert parsed.backlog_level == "Stories"


def test_parses_single_work_item_url():
    url = "https://dev.azure.com/myorg/MyProject/_workitems/edit/12345"
    parsed = parse_azure_devops_url(url)

    assert parsed.work_item_id == 12345
    assert parsed.team is None
    assert parsed.backlog_level is None
