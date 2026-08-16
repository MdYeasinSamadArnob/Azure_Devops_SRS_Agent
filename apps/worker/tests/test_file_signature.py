from srs_core.security.file_signature import sniff_content_type


def test_sniffs_pdf_signature_over_generic_header():
    body = b"%PDF-1.4\n%..."
    assert sniff_content_type(body, "report.pdf", "application/octet-stream") == "application/pdf"


def test_sniffs_png_signature():
    body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert sniff_content_type(body, "diagram", "application/octet-stream") == "image/png"


def test_falls_back_to_filename_extension_when_signature_unknown():
    body = b"not a recognizable binary signature"
    assert sniff_content_type(body, "notes.pdf", "application/octet-stream") == "application/pdf"


def test_falls_back_to_header_when_nothing_else_matches():
    body = b"\x00\x01\x02"
    assert sniff_content_type(body, "data.notarealextension", "application/zip") == "application/zip"


def test_defaults_to_octet_stream_when_fully_unknown():
    body = b"\x00\x01\x02"
    assert sniff_content_type(body, "data", None) == "application/octet-stream"
