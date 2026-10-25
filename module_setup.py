import io
import json
import os
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

from settings import settings


_setup_lock = threading.Lock()


def setup_core() -> None:
    """Prepare the selected proxy core for Windows amd64 when it is missing."""
    if settings.PROXY_CORE == "xray":
        name, path, repository, asset_suffix = "xray", settings.XRAY_PATH, "XTLS/Xray-core", "windows-64.zip"
    else:
        name, path, repository, asset_suffix = "sing-box", settings.SING_BOX_PATH, "SagerNet/sing-box", "windows-amd64.zip"
    with _setup_lock:
        if os.path.exists(path) or shutil.which(path) or shutil.which(name):
            return
        try:
            request = urllib.request.Request(
                f"https://api.github.com/repos/{repository}/releases/latest",
                headers={"User-Agent": "node-checker"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                release = json.load(response)
            asset = next(asset for asset in release["assets"] if asset["name"].endswith(asset_suffix))
            with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as response:
                archive_data = response.read()
            with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
                member = next(member for member in archive.namelist() if member.rsplit("/", 1)[-1] == f"{name}.exe")
                executable = archive.read(member)
            destination = Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".download")
            try:
                temporary.write_bytes(executable)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            print(f"[Setup] Installed {name} to {path}")
        except Exception as error:
            raise RuntimeError(f"Failed to prepare {name}: {error}") from error


if __name__ == "__main__":
    setup_core()
