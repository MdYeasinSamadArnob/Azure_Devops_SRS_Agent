import base64

from srs_core.parsing.html_images import extract_embedded_images


def test_finds_azure_hosted_image():
    html = '<div><img src="https://dev.azure.com/myorg/proj/_apis/wit/attachments/abc?fileName=x.png"></div>'
    refs = extract_embedded_images(html, azure_org="myorg")
    assert len(refs) == 1
    assert refs[0].kind == "azure_hosted"


def test_finds_and_decodes_data_uri_image():
    payload = base64.b64encode(b"fake-png-bytes").decode()
    html = f'<img src="data:image/png;base64,{payload}">'
    refs = extract_embedded_images(html, azure_org="myorg")
    assert len(refs) == 1
    assert refs[0].kind == "data_uri"
    assert refs[0].decoded_bytes == b"fake-png-bytes"
    assert refs[0].content_type == "image/png"


def test_classifies_external_url():
    html = '<img src="https://example.com/diagram.png">'
    refs = extract_embedded_images(html, azure_org="myorg")
    assert refs[0].kind == "external"


def test_finds_multiple_images():
    html = '<img src="https://example.com/a.png"><p>text</p><img src="https://example.com/b.png">'
    refs = extract_embedded_images(html, azure_org="myorg")
    assert len(refs) == 2


def test_none_and_empty_return_empty_list():
    assert extract_embedded_images(None, azure_org="myorg") == []
    assert extract_embedded_images("", azure_org="myorg") == []


def test_malformed_data_uri_falls_back_to_external():
    html = '<img src="data:image/png;base64,not-valid-base64!!!">'
    refs = extract_embedded_images(html, azure_org="myorg")
    assert refs[0].kind == "external"
