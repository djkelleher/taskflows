import zipfile
from pathlib import Path

from taskflows.files.gdrive import (
    GoogleDrive,
    get_folder_id_helper,
    get_gdrive_id_from_path,
)


class QueryCaptureService:
    def __init__(self, files_response=None):
        self.queries = []
        self.files_response = files_response or {"files": []}

    def files(self):
        return self

    def list(self, q, **kwargs):
        self.queries.append(q)
        return self

    def execute(self):
        return self.files_response


class FakeDrive(GoogleDrive):
    def __init__(self, entries=None):
        super().__init__()
        self.entries = entries or {}
        self.uploaded_name = None

    def download_file(
        self, file_id, local_path, overwrite=True, max_retries=3, retry_delay=1
    ):
        with zipfile.ZipFile(local_path, "w") as zip_file:
            for name, content in self.entries.items():
                zip_file.writestr(name, content)
        return True

    def get_file_info(self, file_id):
        return {"name": "archive.zip"}

    def upload(self, files, folder_id="root", folder_path=None, overwrite=False):
        self.uploaded_name = Path(files).name
        return ["uploaded-id"]


def test_gdrive_extract_blocks_zip_path_traversal(tmp_path):
    drive = FakeDrive({"../escape.txt": "bad"})

    extracted = drive.extract_and_download("zip-id", tmp_path / "out")

    assert extracted == []
    assert not (tmp_path / "escape.txt").exists()


def test_gdrive_compress_and_upload_uses_requested_zip_name(tmp_path):
    source = tmp_path / "data.txt"
    source.write_text("content")
    drive = FakeDrive()

    file_id = drive.compress_and_upload([source], "bundle")

    assert file_id == "uploaded-id"
    assert drive.uploaded_name == "bundle.zip"


def test_gdrive_folder_lookup_escapes_query_literals():
    service = QueryCaptureService({"files": [{"id": "folder-id"}]})

    assert get_folder_id_helper(service, ["Client's \\ Reports"]) == "folder-id"
    assert "Client\\'s \\\\ Reports" in service.queries[0]


def test_gdrive_search_escapes_query_literals():
    service = QueryCaptureService()
    drive = GoogleDrive()
    drive._service = service

    assert drive.search_files("Client's \\ Reports", folder_id="parent'id") == []

    query = service.queries[0]
    assert "Client\\'s \\\\ Reports" in query
    assert "parent\\'id" in query


def test_get_gdrive_id_from_path_handles_trailing_slashes():
    assert get_gdrive_id_from_path("gdrive://folder-id/file-id/") == "file-id"
    assert get_gdrive_id_from_path("gdrive://folder-id/") == "folder-id"
    assert get_gdrive_id_from_path("not-gdrive://folder-id") is None
