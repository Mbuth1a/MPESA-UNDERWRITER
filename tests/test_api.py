import os
import time
import pytest
from fastapi.testclient import TestClient
from main import app, REPORT_DIR, cleanup_old_reports

client = TestClient(app)


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "M-Pesa Underwriter" in response.text
    assert "uploadForm" in response.text


def test_download_security_path_traversal():
    # Attempt directory traversal
    response = client.get("/download/../../etc/passwd")
    assert response.status_code in [400, 404]


def test_download_invalid_filename():
    response = client.get("/download/invalid_script.exe")
    assert response.status_code == 400


def test_download_nonexistent_report():
    response = client.get("/download/report_1234567890ab.pdf")
    assert response.status_code == 404


def test_analyze_invalid_extension():
    # Attempt uploading non-pdf file
    files = {"pdf_file": ("test.txt", b"plain text content", "text/plain")}
    data = {"password": "123"}
    response = client.post("/analyze", files=files, data=data)
    assert response.status_code == 400
    assert "PDF statement" in response.json()["error"]


def test_cleanup_old_reports_function():
    # Create a dummy report file in REPORT_DIR
    dummy_path = os.path.join(REPORT_DIR, "report_testcleanup01.pdf")
    with open(dummy_path, "wb") as f:
        f.write(b"%PDF-1.4 dummy content")

    # Manually backdate the modification time by 3 hours (10800 seconds)
    three_hours_ago = time.time() - 10800
    os.utime(dummy_path, (three_hours_ago, three_hours_ago))

    assert os.path.exists(dummy_path)

    # Run cleanup with 1 hour threshold (3600 seconds)
    cleanup_old_reports(max_age_seconds=3600)

    # Verify the aged report was deleted
    assert not os.path.exists(dummy_path)
