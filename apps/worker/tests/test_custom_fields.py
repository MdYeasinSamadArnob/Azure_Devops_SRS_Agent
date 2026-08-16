from srs_core.parsing.custom_fields import extract_content_fields


def test_extracts_custom_content_fields():
    raw_fields = {
        "System.Title": "Some Epic",
        "System.Description": "handled elsewhere, excluded",
        "Microsoft.VSTS.Common.AcceptanceCriteria": "handled elsewhere, excluded",
        "Custom.BusinessRules": "<ul><li>Rule one</li><li>Rule two</li></ul>",
        "Custom.ClassDiagram": '<div><img src="https://dev.azure.com/org/proj/x.png"></div>',
        "Custom.DevelopmentWorkItem": "Yes",  # short picklist answer — excluded
    }

    fields = extract_content_fields(raw_fields)
    names = {f.reference_name for f in fields}

    assert "Custom.BusinessRules" in names
    assert "Custom.ClassDiagram" in names
    assert "Custom.DevelopmentWorkItem" not in names  # too short
    assert "System.Description" not in names  # explicitly excluded
    assert "System.Title" not in names  # not a content field


def test_excludes_system_and_identity_fields():
    raw_fields = {
        "System.AssignedTo": {"displayName": "Someone"},
        "System.CreatedDate": "2026-01-01T00:00:00Z",
        "WEF_ABC123_Kanban.Column": "In Progress",
        "Microsoft.VSTS.Scheduling.Effort": 3.0,
    }
    assert extract_content_fields(raw_fields) == []


def test_humanizes_field_labels():
    raw_fields = {"Custom.ContainerDiagram": "some substantial content here for the test"}
    fields = extract_content_fields(raw_fields)
    assert fields[0].label == "Container Diagram"


def test_humanizes_acronym_field_labels_without_splitting_the_acronym():
    """Regression test: found live against this org's process template, which
    has an all-caps `Custom.ERD` field — the naive "insert a space before
    every capital letter" humanizer split it into "E R D" instead of leaving
    the acronym intact, and mangled "Custom.UISourceCode" into
    "U I Source Code" instead of "UI Source Code".
    """
    raw_fields = {
        "Custom.ERD": "some substantial content here for the test",
        "Custom.UISourceCode": "some substantial content here for the test",
    }
    fields = {f.reference_name: f.label for f in extract_content_fields(raw_fields)}
    assert fields["Custom.ERD"] == "ERD"
    assert fields["Custom.UISourceCode"] == "UI Source Code"


def test_deterministic_ordering():
    raw_fields = {
        "Custom.ZField": "substantial content here for testing purposes",
        "Custom.AField": "substantial content here for testing purposes",
    }
    fields = extract_content_fields(raw_fields)
    assert [f.reference_name for f in fields] == ["Custom.AField", "Custom.ZField"]
