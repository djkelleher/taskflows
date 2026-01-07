import ast
import fnmatch
import io
import logging
import os
import pathlib
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import cached_property
from io import BytesIO
from pathlib import Path
from typing import Callable, List, Literal, Optional, Sequence, Tuple, Union

import googleapiclient.errors
import pandas as pd
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload
from pydantic import Field
from pydantic_settings import BaseSettings
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive as PyDriveGoogleDrive

from .extensions import file_extensions_re
from .utils import logger

PathT = Union[str, Path]

# Google Drive MIME types
GDRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GDRIVE_SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"

# Google Drive scopes
SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_folder_id_helper(service, folder_path: List[str]) -> str:
    """Get folder ID from a folder path list."""
    parent_id = "root"
    for folder_name in folder_path:
        query = f"name='{folder_name}' and '{parent_id}' in parents and mimeType='{GDRIVE_FOLDER_MIME_TYPE}' and trashed=false"
        results = service.files().list(q=query, fields="files(id)").execute()
        items = results.get("files", [])
        if not items:
            raise FileNotFoundError(
                f"Folder '{folder_name}' not found in parent '{parent_id}'"
            )
        parent_id = items[0]["id"]
    return parent_id


def create_gdrive_folder_helper(
    service, folder_name: str, parent_folder_id: str = "root"
) -> str:
    """Create a folder and return its ID."""
    file_metadata = {
        "name": folder_name,
        "mimeType": GDRIVE_FOLDER_MIME_TYPE,
        "parents": [parent_folder_id],
    }
    folder = service.files().create(body=file_metadata, fields="id").execute()
    return folder.get("id")


class GoogleDriveCfg(BaseSettings):
    """Google Drive configuration. Variables will be loaded from environment variables if set."""

    model_config = {"env_prefix": "GDRIVE_"}

    credentials_file: Optional[str] = Field(
        default=None, description="Path to credentials JSON file"
    )
    token_file: Optional[str] = Field(
        default="token.json", description="Path to token file"
    )
    scopes: List[str] = Field(default=SCOPES, description="OAuth scopes")


def is_gdrive_path(path: PathT) -> bool:
    """Returns True if `path` is a Google Drive path."""
    return str(path).startswith("gdrive://")


def get_gdrive_id_from_path(path: str) -> Optional[str]:
    """Extract Google Drive file/folder ID from a gdrive:// path."""
    if not is_gdrive_path(path):
        return None
    # Format: gdrive://file_id or gdrive://folder_id/file_id
    path = path.replace("gdrive://", "")
    return path.split("/")[-1] if path else None


class GoogleDrive:
    """Enhanced Google Drive client with PyDrive integration.

    This class provides comprehensive Google Drive functionality by combining:
    - Google Drive API v3 for core operations
    - PyDrive for simplified operations and legacy compatibility
    - Advanced features like bulk operations, sync, and file management

    Key improvements over basic implementations:
    - Dual API support (Google Drive API + PyDrive)
    - Bulk upload/download with parallel processing
    - Folder synchronization with conflict resolution
    - Enhanced file metadata and revision history
    - Google Workspace document creation (Docs, Sheets)
    - File watching and change detection
    - Duplicate file detection
    - Storage quota monitoring
    - File tree visualization
    - Comments and collaboration features
    - Robust error handling and logging

    PyDrive-specific features added:
    - String content upload/download
    - Stream-based operations
    - File starring and metadata manipulation
    - Simplified authentication flow
    - Enhanced file revision tracking
    """

    def __init__(self, config: Optional[GoogleDriveCfg] = None) -> None:
        """Initialize Google Drive client.

        Args:
            config: Google Drive configuration. If None, uses default settings.
        """
        self.config = config or GoogleDriveCfg()
        self._service = None
        self._pydrive_client = None

    def authenticate(self) -> None:
        """Authenticate with Google Drive API."""
        creds = None

        if not self.config.credentials_file:
            raise ValueError(
                "No credentials file specified. Set GDRIVE_CREDENTIALS_FILE environment variable."
            )

        # Check if credentials file is a service account
        with open(self.config.credentials_file) as f:
            creds_data = json.load(f)

        if creds_data.get("type") == "service_account":
            # Service account authentication
            creds = ServiceAccountCredentials.from_service_account_file(
                self.config.credentials_file, scopes=self.config.scopes
            )
        else:
            # OAuth credentials authentication
            # Load existing token if available
            if os.path.exists(self.config.token_file):
                creds = Credentials.from_authorized_user_file(
                    self.config.token_file, self.config.scopes
                )

            # If no valid credentials, authenticate
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.config.credentials_file, self.config.scopes
                    )
                    creds = flow.run_local_server(port=0)

                # Save credentials for next run
                with open(self.config.token_file, "w") as token:
                    token.write(creds.to_json())

        self._service = build("drive", "v3", credentials=creds)

    @cached_property
    def service(self):
        """Get authenticated Google Drive service."""
        if self._service is None:
            self.authenticate()
        return self._service

    @cached_property
    def pydrive_client(self):
        """Get PyDrive client for compatibility with existing code."""
        if self._pydrive_client is None:
            gauth = GoogleAuth()
            # This will open a web browser for authentication on the first run.
            # It will create a settings.yaml file to store credentials.
            # For subsequent runs, it will use the saved credentials.
            gauth.LocalWebserverAuth()
            self._pydrive_client = PyDriveGoogleDrive(gauth)
        return self._pydrive_client

    def upload(
        self,
        files: PathT | Sequence[PathT],
        folder_id: str = "root",
        folder_path: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> List[str]:
        """Upload local file(s) to Google Drive.

        Args:
            files: Local file or files to upload
            folder_id: Google Drive folder ID to upload to
            folder_path: Path to folder (alternative to folder_id)
            overwrite: Whether to overwrite existing files

        Returns:
            List of uploaded file IDs
        """
        if folder_path:
            folder_id = self.get_folder_id(folder_path)

        if isinstance(files, (str, Path)):
            files = [files]

        uploaded_files = []

        for file_path in files:
            file_path = Path(file_path)

            if not file_path.exists():
                logger.warning(f"File not found: {file_path}")
                continue

            # Check if file already exists
            if not overwrite:
                existing_files = self.list_files(folder_id, pattern=file_path.name)
                if existing_files:
                    logger.info(f"File {file_path.name} already exists. Skipping.")
                    continue

            # Upload file
            file_metadata = {"name": file_path.name, "parents": [folder_id]}

            media = MediaFileUpload(str(file_path), resumable=True)

            try:
                uploaded_file = (
                    self.service.files()
                    .create(body=file_metadata, media_body=media, fields="id,name")
                    .execute()
                )

                uploaded_files.append(uploaded_file.get("id"))
                logger.info(
                    f"Uploaded {file_path.name} to Google Drive (ID: {uploaded_file.get('id')})"
                )

            except Exception as e:
                logger.error(f"Failed to upload {file_path}: {e}")

        return uploaded_files

    def download_file(
        self,
        file_id: str,
        local_path: PathT,
        overwrite: bool = True,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> bool:
        """Download a file from Google Drive.

        Args:
            file_id: Google Drive file ID
            local_path: Local path to save file
            overwrite: Whether to overwrite existing file
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries

        Returns:
            True if successful, False otherwise
        """
        local_path = Path(local_path)

        if local_path.exists() and not overwrite:
            logger.info(f"File {local_path} already exists. Skipping download.")
            return True

        # Create directory if it doesn't exist
        local_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_retries + 1):
            try:
                # Get file metadata
                file_metadata = self.service.files().get(fileId=file_id).execute()

                # Download file
                request = self.service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)

                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        logger.debug(
                            f"Download progress: {int(status.progress() * 100)}%"
                        )

                # Save to local file
                with open(local_path, "wb") as f:
                    f.write(fh.getvalue())

                file_size = local_path.stat().st_size
                logger.info(f"Downloaded {file_metadata['name']} ({file_size} bytes)")
                return True

            except Exception as e:
                logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                if local_path.exists():
                    local_path.unlink()  # Remove potentially corrupted file

                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"Failed to download file after {max_retries + 1} attempts"
                    )
                    return False

        return False

    def download_files(
        self,
        folder_id: str,
        local_dir: PathT,
        pattern: Optional[str] = None,
        overwrite: bool = True,
    ) -> List[str]:
        """Download all files from a Google Drive folder.

        Args:
            folder_id: Google Drive folder ID
            local_dir: Local directory to save files
            pattern: File name pattern to match
            overwrite: Whether to overwrite existing files

        Returns:
            List of downloaded file paths
        """
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        files = self.list_files(folder_id, pattern=pattern)
        downloaded_files = []

        for file_info in files:
            file_id = file_info["id"]
            file_name = file_info["name"]
            local_path = local_dir / file_name

            if self.download_file(file_id, local_path, overwrite):
                downloaded_files.append(str(local_path))

        return downloaded_files

    def read_file(self, file_id: str) -> BytesIO:
        """Read file content from Google Drive.

        Args:
            file_id: Google Drive file ID

        Returns:
            File content as BytesIO
        """
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        return fh

    def delete_file(self, file_id: str, if_exists: bool = True) -> bool:
        """Delete a file from Google Drive.

        Args:
            file_id: Google Drive file ID
            if_exists: Don't raise error if file doesn't exist

        Returns:
            True if successful, False otherwise
        """
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"Deleted file with ID: {file_id}")
            return True
        except Exception as e:
            if if_exists and "not found" in str(e).lower():
                logger.warning(f"File not found: {file_id}")
                return False
            logger.error(f"Failed to delete file {file_id}: {e}")
            return False

    def delete_files(
        self,
        folder_id: str,
        pattern: Optional[str] = None,
        if_exists: bool = True,
    ) -> int:
        """Delete files from a Google Drive folder.

        Args:
            folder_id: Google Drive folder ID
            pattern: File name pattern to match
            if_exists: Don't raise error if files don't exist

        Returns:
            Number of files deleted
        """
        files = self.list_files(folder_id, pattern=pattern)
        deleted_count = 0

        for file_info in files:
            if self.delete_file(file_info["id"], if_exists):
                deleted_count += 1

        return deleted_count

    def move_file(
        self,
        file_id: str,
        new_parent_id: str,
        old_parent_id: Optional[str] = None,
    ) -> bool:
        """Move a file to a different folder.

        Args:
            file_id: Google Drive file ID
            new_parent_id: New parent folder ID
            old_parent_id: Old parent folder ID (if known)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current parents if not provided
            if old_parent_id is None:
                file_metadata = (
                    self.service.files().get(fileId=file_id, fields="parents").execute()
                )
                old_parent_id = ",".join(file_metadata.get("parents", []))

            # Move file
            self.service.files().update(
                fileId=file_id,
                addParents=new_parent_id,
                removeParents=old_parent_id,
                fields="id,parents",
            ).execute()

            logger.info(f"Moved file {file_id} to folder {new_parent_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to move file {file_id}: {e}")
            return False

    def copy_file(
        self,
        file_id: str,
        new_parent_id: str,
        new_name: Optional[str] = None,
    ) -> Optional[str]:
        """Copy a file to a different folder.

        Args:
            file_id: Google Drive file ID
            new_parent_id: New parent folder ID
            new_name: New file name (optional)

        Returns:
            New file ID if successful, None otherwise
        """
        try:
            body = {"parents": [new_parent_id]}
            if new_name:
                body["name"] = new_name

            copied_file = (
                self.service.files()
                .copy(fileId=file_id, body=body, fields="id,name")
                .execute()
            )

            logger.info(f"Copied file {file_id} to folder {new_parent_id}")
            return copied_file.get("id")

        except Exception as e:
            logger.error(f"Failed to copy file {file_id}: {e}")
            return None

    def exists(self, file_id: str) -> bool:
        """Check if a file exists in Google Drive.

        Args:
            file_id: Google Drive file ID

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.service.files().get(fileId=file_id).execute()
            return True
        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 404:
                return False
            logger.error(f"Failed to check if file exists {file_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking file existence {file_id}: {e}")
            return False

    def file_size(self, file_id: str) -> int:
        """Get file size in bytes.

        Args:
            file_id: Google Drive file ID

        Returns:
            File size in bytes, 0 if file doesn't exist or error occurs
        """
        try:
            file_metadata = (
                self.service.files().get(fileId=file_id, fields="size").execute()
            )
            return int(file_metadata.get("size", 0))
        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"File not found: {file_id}")
                return 0
            logger.error(f"Failed to get file size for {file_id}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error getting file size {file_id}: {e}")
            return 0

    def get_folder_id(self, folder_path: List[str]) -> str:
        """Get folder ID from folder path.

        Args:
            folder_path: List of folder names representing the path

        Returns:
            Folder ID
        """
        return get_folder_id_helper(self.service, folder_path)

    def create_folder(
        self,
        folder_name: str,
        parent_folder_id: str = "root",
    ) -> str:
        """Create a new folder in Google Drive.

        Args:
            folder_name: Name of the new folder
            parent_folder_id: Parent folder ID

        Returns:
            New folder ID
        """
        return create_gdrive_folder_helper(self.service, folder_name, parent_folder_id)

    def list_files(
        self,
        folder_id: str = "root",
        pattern: Optional[str] = None,
        include_folders: bool = False,
        return_type: Literal["dict", "id", "name"] = "dict",
    ) -> List[Union[dict, str]]:
        """List files in a Google Drive folder.

        Args:
            folder_id: Google Drive folder ID
            pattern: File name pattern to match
            include_folders: Whether to include folders
            return_type: What to return ('dict', 'id', 'name')

        Returns:
            List of files based on return_type
        """
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            if not include_folders:
                query += f" and mimeType != '{GDRIVE_FOLDER_MIME_TYPE}'"

            results = (
                self.service.files()
                .list(
                    q=query,
                    fields="files(id,name,mimeType,size,modifiedTime)",
                    orderBy="name",
                )
                .execute()
            )

            files = results.get("files", [])

            # Filter by pattern if provided
            if pattern:
                files = [f for f in files if fnmatch.fnmatch(f["name"], pattern)]

            # Return based on type
            if return_type == "id":
                return [f["id"] for f in files]
            elif return_type == "name":
                return [f["name"] for f in files]
            else:
                return files

        except Exception as e:
            logger.error(f"Failed to list files in folder {folder_id}: {e}")
            return []

    def list_folders(
        self,
        folder_id: str = "root",
        pattern: Optional[str] = None,
        return_type: Literal["dict", "id", "name"] = "dict",
    ) -> List[Union[dict, str]]:
        """List folders in a Google Drive folder.

        Args:
            folder_id: Google Drive folder ID
            pattern: Folder name pattern to match
            return_type: What to return ('dict', 'id', 'name')

        Returns:
            List of folders based on return_type
        """
        try:
            query = f"'{folder_id}' in parents and trashed=false and mimeType='{GDRIVE_FOLDER_MIME_TYPE}'"

            results = (
                self.service.files()
                .list(
                    q=query,
                    fields="files(id,name,mimeType,modifiedTime)",
                    orderBy="name",
                )
                .execute()
            )

            folders = results.get("files", [])

            # Filter by pattern if provided
            if pattern:
                folders = [f for f in folders if fnmatch.fnmatch(f["name"], pattern)]

            # Return based on type
            if return_type == "id":
                return [f["id"] for f in folders]
            elif return_type == "name":
                return [f["name"] for f in folders]
            else:
                return folders

        except Exception as e:
            logger.error(f"Failed to list folders in folder {folder_id}: {e}")
            return []

    def is_folder(self, file_id: str) -> bool:
        """Check if a file ID represents a folder.

        Args:
            file_id: Google Drive file ID

        Returns:
            True if it's a folder, False otherwise
        """
        try:
            file_metadata = (
                self.service.files().get(fileId=file_id, fields="mimeType").execute()
            )
            return file_metadata.get("mimeType") == GDRIVE_FOLDER_MIME_TYPE
        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 404:
                logger.warning(f"File not found: {file_id}")
                return False
            logger.error(f"Failed to check if file is folder {file_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking folder status {file_id}: {e}")
            return False

    def get_file_info(self, file_id: str) -> Optional[dict]:
        """Get file metadata.

        Args:
            file_id: Google Drive file ID

        Returns:
            File metadata dict or None
        """
        try:
            return (
                self.service.files()
                .get(
                    fileId=file_id, fields="id,name,mimeType,size,modifiedTime,parents"
                )
                .execute()
            )
        except Exception as e:
            logger.error(f"Failed to get file info for {file_id}: {e}")
            return None

    def search_files(
        self,
        query: str,
        folder_id: Optional[str] = None,
        include_folders: bool = False,
    ) -> List[dict]:
        """Search for files in Google Drive.

        Args:
            query: Search query
            folder_id: Restrict search to specific folder
            include_folders: Whether to include folders in results

        Returns:
            List of matching files
        """
        try:
            search_query = f"name contains '{query}' and trashed=false"

            if folder_id:
                search_query += f" and '{folder_id}' in parents"

            if not include_folders:
                search_query += f" and mimeType != '{GDRIVE_FOLDER_MIME_TYPE}'"

            results = (
                self.service.files()
                .list(
                    q=search_query,
                    fields="files(id,name,mimeType,size,modifiedTime)",
                    orderBy="name",
                )
                .execute()
            )

            return results.get("files", [])

        except Exception as e:
            logger.error(f"Failed to search files: {e}")
            return []

    def df_from_files(self, file_ids: Sequence[str]) -> pd.DataFrame:
        """Create a DataFrame from Google Drive files.

        Args:
            file_ids: List of Google Drive file IDs (should be CSV/Excel files)

        Returns:
            Combined DataFrame from all files
        """
        if isinstance(file_ids, str):
            file_ids = [file_ids]

        dataframes = []

        for file_id in file_ids:
            try:
                # Get file info to determine type
                file_info = self.get_file_info(file_id)
                if not file_info:
                    continue

                file_name = file_info["name"]
                file_content = self.read_file(file_id)

                # Determine file type and read accordingly
                if file_name.endswith(".csv"):
                    df = pd.read_csv(file_content)
                elif file_name.endswith((".xlsx", ".xls")):
                    df = pd.read_excel(file_content)
                elif file_name.endswith(".parquet"):
                    df = pd.read_parquet(file_content)
                else:
                    logger.warning(f"Unsupported file type: {file_name}")
                    continue

                dataframes.append(df)

            except Exception as e:
                logger.error(f"Failed to read file {file_id}: {e}")

        if not dataframes:
            return pd.DataFrame()

        # Combine all DataFrames
        return pd.concat(dataframes, ignore_index=True)

    def get_shared_drive_id(self, shared_drive_name: str) -> Optional[str]:
        """Get shared drive ID by name.

        Args:
            shared_drive_name: Name of the shared drive

        Returns:
            Shared drive ID or None if not found
        """
        try:
            results = self.service.drives().list().execute()
            drives = results.get("drives", [])

            for drive in drives:
                if drive["name"] == shared_drive_name:
                    return drive["id"]

            return None

        except Exception as e:
            logger.error(f"Failed to get shared drive ID: {e}")
            return None

    def list_shared_drives(self) -> List[dict]:
        """List all shared drives accessible to the user.

        Returns:
            List of shared drive information
        """
        try:
            results = self.service.drives().list().execute()
            return results.get("drives", [])
        except Exception as e:
            logger.error(f"Failed to list shared drives: {e}")
            return []

    def get_file_permissions(self, file_id: str) -> List[dict]:
        """Get file permissions.

        Args:
            file_id: Google Drive file ID

        Returns:
            List of permission information
        """
        try:
            results = self.service.permissions().list(fileId=file_id).execute()
            return results.get("permissions", [])
        except Exception as e:
            logger.error(f"Failed to get file permissions: {e}")
            return []

    def share_file(
        self,
        file_id: str,
        email: str,
        role: Literal["reader", "writer", "commenter"] = "reader",
        notify: bool = True,
    ) -> bool:
        """Share a file with a user.

        Args:
            file_id: Google Drive file ID
            email: Email address to share with
            role: Permission level
            notify: Whether to send notification email

        Returns:
            True if successful, False otherwise
        """
        try:
            permission = {"type": "user", "role": role, "emailAddress": email}

            self.service.permissions().create(
                fileId=file_id, body=permission, sendNotificationEmail=notify
            ).execute()

            logger.info(f"Shared file {file_id} with {email} as {role}")
            return True

        except Exception as e:
            logger.error(f"Failed to share file {file_id}: {e}")
            return False

    def make_file_public(self, file_id: str) -> bool:
        """Make a file publicly accessible.

        Args:
            file_id: Google Drive file ID

        Returns:
            True if successful, False otherwise
        """
        try:
            permission = {"type": "anyone", "role": "reader"}

            self.service.permissions().create(fileId=file_id, body=permission).execute()

            logger.info(f"Made file {file_id} publicly accessible")
            return True

        except Exception as e:
            logger.error(f"Failed to make file {file_id} public: {e}")
            return False

    def get_file_download_url(self, file_id: str) -> Optional[str]:
        """Get direct download URL for a file.

        Args:
            file_id: Google Drive file ID

        Returns:
            Download URL or None
        """
        try:
            file_info = self.get_file_info(file_id)
            if file_info:
                return f"https://drive.google.com/uc?id={file_id}&export=download"
            return None
        except Exception as e:
            logger.error(f"Failed to get download URL for {file_id}: {e}")
            return None

    def export_file(
        self,
        file_id: str,
        mime_type: str,
        local_path: PathT,
    ) -> bool:
        """Export a Google Workspace file to a different format.

        Args:
            file_id: Google Drive file ID
            mime_type: Target MIME type for export
            local_path: Local path to save exported file

        Returns:
            True if successful, False otherwise
        """
        try:
            request = self.service.files().export_media(
                fileId=file_id, mimeType=mime_type
            )
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            # Save to local file
            local_path = Path(local_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, "wb") as f:
                f.write(fh.getvalue())

            logger.info(f"Exported file {file_id} to {local_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export file {file_id}: {e}")
            return False

    def batch_operation(
        self,
        operation: Callable,
        items: Sequence[str],
        batch_size: int = 100,
        delay: float = 0.1,
    ) -> List[any]:
        """Perform batch operations on Google Drive files.

        Args:
            operation: Function to apply to each item
            items: List of file IDs or other items
            batch_size: Number of items to process in each batch
            delay: Delay between batches

        Returns:
            List of results from operations
        """
        results = []

        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]

            for item in batch:
                try:
                    result = operation(item)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Batch operation failed for {item}: {e}")
                    results.append(None)

            # Add delay between batches to avoid rate limiting
            if i + batch_size < len(items):
                time.sleep(delay)

        return results

    def get_file_revisions(self, file_id: str) -> List[dict]:
        """Get file revision history using PyDrive.

        Args:
            file_id: Google Drive file ID

        Returns:
            List of revision metadata dictionaries
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})
            revisions = pydrive_file.GetRevisions()
            return revisions
        except Exception as e:
            logger.error(f"Failed to get file revisions for {file_id}: {e}")
            return []

    def upload_string(
        self,
        content: str,
        filename: str,
        folder_id: str = "root",
        mime_type: str = "text/plain",
    ) -> Optional[str]:
        """Upload string content as a file to Google Drive using PyDrive.

        Args:
            content: String content to upload
            filename: Name for the file
            folder_id: Google Drive folder ID to upload to
            mime_type: MIME type of the content

        Returns:
            File ID if successful, None otherwise
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile(
                {
                    "title": filename,
                    "parents": [{"id": folder_id}],
                    "mimeType": mime_type,
                }
            )
            pydrive_file.SetContentString(content)
            pydrive_file.Upload()

            logger.info(
                f"Uploaded string content as {filename} (ID: {pydrive_file['id']})"
            )
            return pydrive_file["id"]

        except Exception as e:
            logger.error(f"Failed to upload string content: {e}")
            return None

    def upload_from_stream(
        self,
        stream: BytesIO,
        filename: str,
        folder_id: str = "root",
        mime_type: Optional[str] = None,
    ) -> Optional[str]:
        """Upload from a BytesIO stream using PyDrive.

        Args:
            stream: BytesIO stream containing file data
            filename: Name for the file
            folder_id: Google Drive folder ID to upload to
            mime_type: MIME type of the content

        Returns:
            File ID if successful, None otherwise
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile(
                {
                    "title": filename,
                    "parents": [{"id": folder_id}],
                    "mimeType": mime_type or "application/octet-stream",
                }
            )

            # Set content from stream
            stream.seek(0)
            pydrive_file.content = stream
            pydrive_file.Upload()

            logger.info(f"Uploaded stream as {filename} (ID: {pydrive_file['id']})")
            return pydrive_file["id"]

        except Exception as e:
            logger.error(f"Failed to upload from stream: {e}")
            return None

    def get_file_content_string(self, file_id: str) -> Optional[str]:
        """Get file content as a string using PyDrive.

        Args:
            file_id: Google Drive file ID

        Returns:
            File content as string or None
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})
            return pydrive_file.GetContentString()
        except Exception as e:
            logger.error(f"Failed to get file content string for {file_id}: {e}")
            return None

    def update_file_content(
        self,
        file_id: str,
        content: Union[str, bytes, BytesIO],
        mime_type: Optional[str] = None,
    ) -> bool:
        """Update file content using PyDrive.

        Args:
            file_id: Google Drive file ID
            content: New content (string, bytes, or BytesIO)
            mime_type: MIME type of the content

        Returns:
            True if successful, False otherwise
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})

            if isinstance(content, str):
                pydrive_file.SetContentString(content)
            elif isinstance(content, bytes):
                pydrive_file.content = BytesIO(content)
            elif isinstance(content, BytesIO):
                pydrive_file.content = content
            else:
                raise ValueError("Content must be str, bytes, or BytesIO")

            if mime_type:
                pydrive_file["mimeType"] = mime_type

            pydrive_file.Upload()
            logger.info(f"Updated file content for {file_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update file content for {file_id}: {e}")
            return False

    def create_google_doc(
        self,
        title: str,
        content: str = "",
        folder_id: str = "root",
    ) -> Optional[str]:
        """Create a new Google Doc using PyDrive.

        Args:
            title: Title of the document
            content: Initial content (plain text)
            folder_id: Google Drive folder ID to create in

        Returns:
            Document ID if successful, None otherwise
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile(
                {
                    "title": title,
                    "parents": [{"id": folder_id}],
                    "mimeType": "application/vnd.google-apps.document",
                }
            )

            if content:
                pydrive_file.SetContentString(content)

            pydrive_file.Upload()
            logger.info(f"Created Google Doc '{title}' (ID: {pydrive_file['id']})")
            return pydrive_file["id"]

        except Exception as e:
            logger.error(f"Failed to create Google Doc: {e}")
            return None

    def create_google_sheet(
        self,
        title: str,
        folder_id: str = "root",
    ) -> Optional[str]:
        """Create a new Google Sheet using PyDrive.

        Args:
            title: Title of the spreadsheet
            folder_id: Google Drive folder ID to create in

        Returns:
            Spreadsheet ID if successful, None otherwise
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile(
                {
                    "title": title,
                    "parents": [{"id": folder_id}],
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                }
            )

            pydrive_file.Upload()
            logger.info(f"Created Google Sheet '{title}' (ID: {pydrive_file['id']})")
            return pydrive_file["id"]

        except Exception as e:
            logger.error(f"Failed to create Google Sheet: {e}")
            return None

    def get_file_thumbnail(self, file_id: str) -> Optional[str]:
        """Get file thumbnail URL using PyDrive.

        Args:
            file_id: Google Drive file ID

        Returns:
            Thumbnail URL or None
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})
            pydrive_file.FetchMetadata()
            return pydrive_file.get("thumbnailLink")
        except Exception as e:
            logger.error(f"Failed to get thumbnail for {file_id}: {e}")
            return None

    def get_file_web_view_link(self, file_id: str) -> Optional[str]:
        """Get file web view link using PyDrive.

        Args:
            file_id: Google Drive file ID

        Returns:
            Web view link or None
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})
            pydrive_file.FetchMetadata()
            return pydrive_file.get("webViewLink")
        except Exception as e:
            logger.error(f"Failed to get web view link for {file_id}: {e}")
            return None

    def set_file_star(self, file_id: str, starred: bool = True) -> bool:
        """Star or unstar a file using PyDrive.

        Args:
            file_id: Google Drive file ID
            starred: True to star, False to unstar

        Returns:
            True if successful, False otherwise
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})
            pydrive_file["starred"] = starred
            pydrive_file.Upload()

            action = "starred" if starred else "unstarred"
            logger.info(f"File {file_id} {action}")
            return True

        except Exception as e:
            logger.error(f"Failed to set star status for {file_id}: {e}")
            return False

    def get_file_comments(self, file_id: str) -> List[dict]:
        """Get file comments using PyDrive.

        Args:
            file_id: Google Drive file ID

        Returns:
            List of comment dictionaries
        """
        try:
            # Use Google Drive API directly for comments
            results = self.service.comments().list(fileId=file_id).execute()
            return results.get("comments", [])
        except Exception as e:
            logger.error(f"Failed to get comments for {file_id}: {e}")
            return []

    def add_file_comment(self, file_id: str, comment: str) -> bool:
        """Add a comment to a file.

        Args:
            file_id: Google Drive file ID
            comment: Comment text

        Returns:
            True if successful, False otherwise
        """
        try:
            comment_body = {"content": comment}

            self.service.comments().create(fileId=file_id, body=comment_body).execute()

            logger.info(f"Added comment to file {file_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add comment to {file_id}: {e}")
            return False

    def list_file_changes(self, start_page_token: Optional[str] = None) -> dict:
        """List changes to files using Drive API.

        Args:
            start_page_token: Token for where to start listing changes

        Returns:
            Dictionary containing changes and next page token
        """
        try:
            if start_page_token:
                results = (
                    self.service.changes().list(pageToken=start_page_token).execute()
                )
            else:
                # Get start page token first
                response = self.service.changes().getStartPageToken().execute()
                start_page_token = response.get("startPageToken")
                results = (
                    self.service.changes().list(pageToken=start_page_token).execute()
                )

            return {
                "changes": results.get("changes", []),
                "nextPageToken": results.get("nextPageToken"),
                "newStartPageToken": results.get("newStartPageToken"),
            }

        except Exception as e:
            logger.error(f"Failed to list file changes: {e}")
            return {"changes": [], "nextPageToken": None, "newStartPageToken": None}

    def watch_file_changes(self, file_id: str, webhook_url: str) -> Optional[str]:
        """Watch for changes to a file.

        Args:
            file_id: Google Drive file ID
            webhook_url: URL to receive webhook notifications

        Returns:
            Channel ID if successful, None otherwise
        """
        try:
            import uuid

            channel_body = {
                "id": str(uuid.uuid4()),
                "type": "web_hook",
                "address": webhook_url,
            }

            result = (
                self.service.files().watch(fileId=file_id, body=channel_body).execute()
            )

            logger.info(f"Started watching file {file_id}")
            return result.get("id")

        except Exception as e:
            logger.error(f"Failed to watch file {file_id}: {e}")
            return None

    def stop_watching_file(self, channel_id: str, resource_id: str) -> bool:
        """Stop watching a file for changes.

        Args:
            channel_id: Channel ID from watch_file_changes
            resource_id: Resource ID from watch_file_changes

        Returns:
            True if successful, False otherwise
        """
        try:
            channel_body = {"id": channel_id, "resourceId": resource_id}

            self.service.channels().stop(body=channel_body).execute()
            logger.info(f"Stopped watching channel {channel_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop watching channel {channel_id}: {e}")
            return False

    def get_file_activity(self, file_id: str) -> List[dict]:
        """Get file activity (views, edits, etc.) using Drive Activity API.

        Note: This requires the Drive Activity API to be enabled and
        the drive.activity scope to be included.

        Args:
            file_id: Google Drive file ID

        Returns:
            List of activity records
        """
        try:
            # This would require the Drive Activity API
            # For now, we'll return an empty list with a warning
            logger.warning(
                "Drive Activity API not implemented. Enable Drive Activity API and add the required scope."
            )
            return []
        except Exception as e:
            logger.error(f"Failed to get file activity for {file_id}: {e}")
            return []

    def duplicate_file(
        self, file_id: str, new_title: Optional[str] = None
    ) -> Optional[str]:
        """Duplicate a file using PyDrive.

        Args:
            file_id: Google Drive file ID to duplicate
            new_title: Title for the duplicated file

        Returns:
            New file ID if successful, None otherwise
        """
        try:
            # Get original file info
            original_file = self.pydrive_client.CreateFile({"id": file_id})
            original_file.FetchMetadata()

            # Create a copy
            duplicate_file = self.pydrive_client.CreateFile(
                {
                    "title": new_title or f"Copy of {original_file['title']}",
                    "parents": original_file["parents"],
                }
            )

            # Copy the file
            duplicate_file.Upload()

            logger.info(f"Duplicated file {file_id} to {duplicate_file['id']}")
            return duplicate_file["id"]

        except Exception as e:
            logger.error(f"Failed to duplicate file {file_id}: {e}")
            return None

    def get_file_metadata_detailed(self, file_id: str) -> Optional[dict]:
        """Get detailed file metadata using PyDrive.

        Args:
            file_id: Google Drive file ID

        Returns:
            Detailed metadata dictionary or None
        """
        try:
            pydrive_file = self.pydrive_client.CreateFile({"id": file_id})
            pydrive_file.FetchMetadata()

            # PyDrive provides more detailed metadata
            return {
                "id": pydrive_file["id"],
                "title": pydrive_file["title"],
                "description": pydrive_file.get("description", ""),
                "mimeType": pydrive_file["mimeType"],
                "fileSize": pydrive_file.get("fileSize", 0),
                "createdDate": pydrive_file.get("createdDate"),
                "modifiedDate": pydrive_file.get("modifiedDate"),
                "lastViewedByMeDate": pydrive_file.get("lastViewedByMeDate"),
                "downloadUrl": pydrive_file.get("downloadUrl"),
                "webViewLink": pydrive_file.get("webViewLink"),
                "webContentLink": pydrive_file.get("webContentLink"),
                "thumbnailLink": pydrive_file.get("thumbnailLink"),
                "starred": pydrive_file.get("starred", False),
                "owners": pydrive_file.get("owners", []),
                "lastModifyingUser": pydrive_file.get("lastModifyingUser", {}),
                "shared": pydrive_file.get("shared", False),
                "parents": pydrive_file.get("parents", []),
                "md5Checksum": pydrive_file.get("md5Checksum"),
                "fileExtension": pydrive_file.get("fileExtension"),
                "copyable": pydrive_file.get("copyable", True),
                "writersCanShare": pydrive_file.get("writersCanShare", True),
                "editable": pydrive_file.get("editable", True),
                "version": pydrive_file.get("version", 0),
            }

        except Exception as e:
            logger.error(f"Failed to get detailed metadata for {file_id}: {e}")
            return None

    def bulk_upload(
        self,
        files: List[PathT],
        folder_id: str = "root",
        workers: int = 4,
        chunk_size: int = 1024 * 1024,
    ) -> List[str]:
        """Upload multiple files in parallel using PyDrive.

        Args:
            files: List of file paths to upload
            folder_id: Google Drive folder ID to upload to
            workers: Number of parallel workers
            chunk_size: Upload chunk size in bytes

        Returns:
            List of uploaded file IDs
        """

        def upload_single_file(file_path: PathT) -> Optional[str]:
            """Upload a single file."""
            try:
                file_path = Path(file_path)
                if not file_path.exists():
                    logger.warning(f"File not found: {file_path}")
                    return None

                pydrive_file = self.pydrive_client.CreateFile(
                    {"title": file_path.name, "parents": [{"id": folder_id}]}
                )
                pydrive_file.SetContentFile(str(file_path))
                pydrive_file.Upload()

                logger.info(f"Uploaded {file_path.name} (ID: {pydrive_file['id']})")
                return pydrive_file["id"]

            except Exception as e:
                logger.error(f"Failed to upload {file_path}: {e}")
                return None

        uploaded_ids = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_file = {
                executor.submit(upload_single_file, file_path): file_path
                for file_path in files
            }

            for future in as_completed(future_to_file):
                file_id = future.result()
                if file_id:
                    uploaded_ids.append(file_id)

        return uploaded_ids

    def bulk_download(
        self,
        file_ids: List[str],
        local_dir: PathT,
        workers: int = 4,
        preserve_structure: bool = True,
    ) -> List[str]:
        """Download multiple files in parallel.

        Args:
            file_ids: List of Google Drive file IDs
            local_dir: Local directory to save files
            workers: Number of parallel workers
            preserve_structure: Whether to preserve folder structure

        Returns:
            List of downloaded file paths
        """
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        def download_single_file(file_id: str) -> Optional[str]:
            """Download a single file."""
            try:
                file_info = self.get_file_info(file_id)
                if not file_info:
                    return None

                file_name = file_info["name"]
                local_path = local_dir / file_name

                if self.download_file(file_id, local_path):
                    return str(local_path)
                return None

            except Exception as e:
                logger.error(f"Failed to download {file_id}: {e}")
                return None

        downloaded_paths = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_id = {
                executor.submit(download_single_file, file_id): file_id
                for file_id in file_ids
            }

            for future in as_completed(future_to_id):
                file_path = future.result()
                if file_path:
                    downloaded_paths.append(file_path)

        return downloaded_paths

    def sync_folder(
        self,
        local_dir: PathT,
        remote_folder_id: str,
        direction: Literal["up", "down", "both"] = "both",
        delete_extra: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """Synchronize a local folder with a Google Drive folder.

        Args:
            local_dir: Local directory path
            remote_folder_id: Google Drive folder ID
            direction: Sync direction ('up', 'down', 'both')
            delete_extra: Whether to delete files not in source
            dry_run: If True, only report what would be done

        Returns:
            Dictionary with sync results
        """
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        # Get local files
        local_files = {}
        for file_path in local_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(local_dir)
                local_files[str(rel_path)] = {
                    "path": file_path,
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                }

        # Get remote files
        remote_files = {}
        for file_info in self.list_files(remote_folder_id):
            remote_files[file_info["name"]] = {
                "id": file_info["id"],
                "size": int(file_info.get("size", 0)),
                "modified": file_info.get("modifiedTime", ""),
            }

        sync_results = {
            "uploaded": [],
            "downloaded": [],
            "updated": [],
            "deleted_local": [],
            "deleted_remote": [],
            "errors": [],
        }

        def parse_gdrive_time(time_str: str) -> datetime:
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))

        # Upload new/changed files (up or both)
        if direction in ["up", "both"]:
            for rel_path, local_info in local_files.items():
                if dry_run:
                    print(f"Dry run: Checking local file {rel_path}")

                if rel_path not in remote_files:
                    if not dry_run:
                        try:
                            file_id = self.upload(local_info["path"], remote_folder_id)
                            sync_results["uploaded"].append(str(local_info["path"]))
                        except Exception as e:
                            sync_results["errors"].append(
                                {"file": str(local_info["path"]), "error": str(e)}
                            )
                    else:
                        sync_results["uploaded"].append(str(local_info["path"]))
                else:
                    remote_info = remote_files[rel_path]
                    local_mtime = datetime.fromtimestamp(
                        local_info["modified"], tz=timezone.utc
                    )
                    remote_mtime = parse_gdrive_time(remote_info["modified"])

                    if local_mtime > remote_mtime:
                        if not dry_run:
                            try:
                                # To update, we delete the old one and upload the new one
                                self.delete_file(remote_info["id"])
                                self.upload(local_info["path"], remote_folder_id)
                                sync_results["updated"].append(str(local_info["path"]))
                            except Exception as e:
                                sync_results["errors"].append(
                                    {"file": str(local_info["path"]), "error": str(e)}
                                )
                        else:
                            sync_results["updated"].append(str(local_info["path"]))

        # Download new/changed files (down or both)
        if direction in ["down", "both"]:
            for filename, remote_info in remote_files.items():
                if dry_run:
                    print(f"Dry run: Checking remote file {filename}")

                local_path = local_dir / filename
                if filename not in local_files:
                    if not dry_run:
                        try:
                            self.download_file(remote_info["id"], local_path)
                            sync_results["downloaded"].append(str(local_path))
                        except Exception as e:
                            sync_results["errors"].append(
                                {"file": str(local_path), "error": str(e)}
                            )
                    else:
                        sync_results["downloaded"].append(str(local_path))
                else:
                    local_info = local_files[filename]
                    local_mtime = datetime.fromtimestamp(
                        local_info["modified"], tz=timezone.utc
                    )
                    remote_mtime = parse_gdrive_time(remote_info["modified"])

                    if remote_mtime > local_mtime:
                        if not dry_run:
                            try:
                                self.download_file(
                                    remote_info["id"], local_path, overwrite=True
                                )
                                sync_results["updated"].append(str(local_path))
                            except Exception as e:
                                sync_results["errors"].append(
                                    {"file": str(local_path), "error": str(e)}
                                )
                        else:
                            sync_results["updated"].append(str(local_path))

        # Delete extra files
        if delete_extra:
            if direction in ["up", "both"]:
                # Delete remote files that are not present locally
                for filename, remote_info in remote_files.items():
                    if filename not in local_files:
                        if not dry_run:
                            try:
                                self.delete_file(remote_info["id"])
                                sync_results["deleted_remote"].append(filename)
                            except Exception as e:
                                sync_results["errors"].append(
                                    {"file": filename, "error": str(e)}
                                )
                        else:
                            sync_results["deleted_remote"].append(filename)

            if direction in ["down", "both"]:
                # Delete local files that are not present remotely
                for rel_path, local_info in local_files.items():
                    if rel_path not in remote_files:
                        if not dry_run:
                            try:
                                local_info["path"].unlink()
                                sync_results["deleted_local"].append(
                                    str(local_info["path"])
                                )
                            except Exception as e:
                                sync_results["errors"].append(
                                    {"file": str(local_info["path"]), "error": str(e)}
                                )
                        else:
                            sync_results["deleted_local"].append(
                                str(local_info["path"])
                            )

        return sync_results

    def get_storage_quota(self) -> dict:
        """Get Google Drive storage quota information.

        Returns:
            Dictionary with storage quota details
        """
        try:
            about = self.service.about().get(fields="storageQuota").execute()
            return about.get("storageQuota", {})
        except Exception as e:
            logger.error(f"Failed to get storage quota: {e}")
            return {}

    def get_file_tree(self, folder_id: str = "root", max_depth: int = 5) -> dict:
        """Get a tree structure of files and folders.

        Args:
            folder_id: Google Drive folder ID to start from
            max_depth: Maximum depth to traverse

        Returns:
            Dictionary representing the file tree
        """

        def build_tree(current_folder_id: str, depth: int = 0) -> dict:
            if depth > max_depth:
                return {}

            tree = {}
            try:
                items = self.list_files(current_folder_id, include_folders=True)
                for item in items:
                    if self.is_folder(item["id"]):
                        tree[item["name"]] = build_tree(item["id"], depth + 1)
                    else:
                        tree[item["name"]] = item["id"]
            except Exception as e:
                logger.error(
                    f"Failed to build tree for folder {current_folder_id}: {e}"
                )

            return tree

        return build_tree(folder_id)

    def find_duplicates(self, folder_id: str = "root") -> List[List[dict]]:
        """Find duplicate files (by name) in a folder."""
        files = self.list_files(folder_id, include_folders=False)

        from collections import defaultdict

        file_map = defaultdict(list)
        for f in files:
            file_map[f["name"]].append(f)

        duplicates = [
            file_list for file_list in file_map.values() if len(file_list) > 1
        ]
        return duplicates

    def create_shortcut(
        self,
        target_file_id: str,
        shortcut_name: str,
        folder_id: str = "root",
    ) -> Optional[str]:
        """Create a shortcut to a file using Google Drive API.

        Args:
            target_file_id: ID of the file to create shortcut for
            shortcut_name: Name for the shortcut
            folder_id: Folder to create shortcut in

        Returns:
            Shortcut ID if successful, None otherwise
        """
        try:
            shortcut_metadata = {
                "name": shortcut_name,
                "parents": [folder_id],
                "mimeType": GDRIVE_SHORTCUT_MIME_TYPE,
                "shortcutDetails": {"targetId": target_file_id},
            }

            shortcut = (
                self.service.files()
                .create(body=shortcut_metadata, fields="id,name")
                .execute()
            )

            logger.info(f"Created shortcut '{shortcut_name}' (ID: {shortcut['id']})")
            return shortcut["id"]

        except Exception as e:
            logger.error(f"Failed to create shortcut: {e}")
            return None

    def get_file_parents_chain(self, file_id: str) -> List[dict]:
        """Get the full parent chain for a file (path to root).

        Args:
            file_id: Google Drive file ID

        Returns:
            List of parent folder information from file to root
        """
        try:
            chain = []
            current_file_id = file_id

            while current_file_id and current_file_id != "root":
                file_info = self.get_file_info(current_file_id)
                if not file_info:
                    break

                chain.append(
                    {
                        "id": file_info["id"],
                        "name": file_info["name"],
                        "mimeType": file_info["mimeType"],
                    }
                )

                parents = file_info.get("parents", [])
                current_file_id = parents[0] if parents else None

            return chain

        except Exception as e:
            logger.error(f"Failed to get parent chain for {file_id}: {e}")
            return []

    def get_file_path(self, file_id: str) -> str:
        """Get the full path of a file from root.

        Args:
            file_id: Google Drive file ID

        Returns:
            Full path string (e.g., '/Folder1/Subfolder/file.txt')
        """
        try:
            chain = self.get_file_parents_chain(file_id)
            if not chain:
                return "/"

            # Reverse to get path from root to file
            path_parts = [item["name"] for item in reversed(chain)]
            return "/" + "/".join(path_parts)

        except Exception as e:
            logger.error(f"Failed to get path for {file_id}: {e}")
            return "/"

    def list_files_recursive(
        self,
        folder_id: str = "root",
        pattern: Optional[str] = None,
        max_depth: int = 10,
    ) -> List[dict]:
        """Recursively list all files in a folder and its subfolders.

        Args:
            folder_id: Google Drive folder ID
            pattern: File name pattern to match
            max_depth: Maximum recursion depth

        Returns:
            List of all files found recursively
        """
        all_files = []

        def recurse_folder(folder_id: str, depth: int = 0):
            if depth >= max_depth:
                return

            try:
                # Get files in current folder
                files = self.list_files(
                    folder_id, pattern=pattern, include_folders=False
                )
                for file_info in files:
                    file_info["depth"] = depth
                    file_info["path"] = self.get_file_path(file_info["id"])
                    all_files.append(file_info)

                # Get subfolders and recurse
                folders = self.list_folders(folder_id)
                for folder_info in folders:
                    recurse_folder(folder_info["id"], depth + 1)

            except Exception as e:
                logger.error(f"Failed to recurse folder {folder_id}: {e}")

        recurse_folder(folder_id)
        return all_files

    def backup_folder(
        self,
        folder_id: str,
        backup_name: Optional[str] = None,
        backup_parent_id: str = "root",
    ) -> Optional[str]:
        """Create a backup copy of an entire folder structure.

        Args:
            folder_id: Google Drive folder ID to backup
            backup_name: Name for the backup folder
            backup_parent_id: Where to create the backup

        Returns:
            Backup folder ID if successful, None otherwise
        """
        try:
            # Get original folder info
            folder_info = self.get_file_info(folder_id)
            if not folder_info:
                return None

            # Create backup folder
            backup_folder_name = (
                backup_name or f"Backup_{folder_info['name']}_{int(time.time())}"
            )
            backup_folder_id = self.create_folder(backup_folder_name, backup_parent_id)

            if not backup_folder_id:
                return None

            # Copy all files and subfolders
            self._copy_folder_recursive(folder_id, backup_folder_id)

            logger.info(
                f"Created backup of {folder_info['name']} (ID: {backup_folder_id})"
            )
            return backup_folder_id

        except Exception as e:
            logger.error(f"Failed to backup folder {folder_id}: {e}")
            return None

    def _copy_folder_recursive(self, source_folder_id: str, dest_folder_id: str):
        """Helper method to recursively copy folder contents."""
        try:
            # Copy all files
            files = self.list_files(source_folder_id, include_folders=False)
            for file_info in files:
                self.copy_file(file_info["id"], dest_folder_id)

            # Copy all subfolders
            folders = self.list_folders(source_folder_id)
            for folder_info in folders:
                new_subfolder_id = self.create_folder(
                    folder_info["name"], dest_folder_id
                )
                if new_subfolder_id:
                    self._copy_folder_recursive(folder_info["id"], new_subfolder_id)

        except Exception as e:
            logger.error(f"Failed to copy folder contents: {e}")

    def compress_and_upload(
        self,
        files: List[PathT],
        zip_name: str,
        folder_id: str = "root",
        compression_level: int = 6,
    ) -> Optional[str]:
        """Compress multiple files into a ZIP and upload to Google Drive.

        Args:
            files: List of local file paths to compress
            zip_name: Name for the ZIP file
            folder_id: Google Drive folder ID to upload to
            compression_level: ZIP compression level (0-9)

        Returns:
            Uploaded ZIP file ID if successful, None otherwise
        """
        try:
            import tempfile
            import zipfile

            # Create temporary ZIP file
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_zip:
                temp_zip_path = temp_zip.name

            # Create ZIP file
            with zipfile.ZipFile(
                temp_zip_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=compression_level,
            ) as zip_file:

                for file_path in files:
                    file_path = Path(file_path)
                    if file_path.exists():
                        zip_file.write(file_path, file_path.name)
                        logger.debug(f"Added {file_path.name} to ZIP")
                    else:
                        logger.warning(f"File not found: {file_path}")

            # Upload ZIP file
            zip_file_id = self.upload(temp_zip_path, folder_id=folder_id)

            # Clean up temporary file
            os.unlink(temp_zip_path)

            if zip_file_id:
                logger.info(f"Uploaded compressed file {zip_name} (ID: {zip_file_id})")
                return zip_file_id[0] if isinstance(zip_file_id, list) else zip_file_id

            return None

        except Exception as e:
            logger.error(f"Failed to compress and upload: {e}")
            return None

    def extract_and_download(
        self,
        zip_file_id: str,
        local_dir: PathT,
        extract_here: bool = True,
    ) -> List[str]:
        """Download a ZIP file and extract its contents.

        Args:
            zip_file_id: Google Drive ZIP file ID
            local_dir: Local directory to extract to
            extract_here: If True, extract to local_dir; if False, create subfolder

        Returns:
            List of extracted file paths
        """
        try:
            import tempfile
            import zipfile

            local_dir = Path(local_dir)
            local_dir.mkdir(parents=True, exist_ok=True)

            # Download ZIP file to temporary location
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_zip:
                temp_zip_path = temp_zip.name

            if not self.download_file(zip_file_id, temp_zip_path):
                return []

            # Extract ZIP file
            extracted_files = []

            with zipfile.ZipFile(temp_zip_path, "r") as zip_file:
                if extract_here:
                    extract_path = local_dir
                else:
                    # Create subfolder based on ZIP name
                    zip_info = self.get_file_info(zip_file_id)
                    folder_name = (
                        zip_info["name"].replace(".zip", "")
                        if zip_info
                        else "extracted"
                    )
                    extract_path = local_dir / folder_name
                    extract_path.mkdir(exist_ok=True)

                zip_file.extractall(extract_path)

                for member in zip_file.namelist():
                    extracted_path = extract_path / member
                    if extracted_path.is_file():
                        extracted_files.append(str(extracted_path))
                        logger.debug(f"Extracted {member}")

            # Clean up temporary ZIP file
            os.unlink(temp_zip_path)

            logger.info(f"Extracted {len(extracted_files)} files to {extract_path}")
            return extracted_files

        except Exception as e:
            logger.error(f"Failed to extract and download: {e}")
            return []
