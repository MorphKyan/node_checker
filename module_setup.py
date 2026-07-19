import urllib.request
import json
import zipfile
import os
import shutil

from settings import settings

def setup_singbox():
    """Download and extract the latest sing-box for Windows amd64."""
    if (os.path.exists(settings.SING_BOX_PATH) or 
            shutil.which(settings.SING_BOX_PATH) or 
            shutil.which("sing-box")):
        print(f"[Setup] sing-box already exists or is available in PATH. Skipping download.")
        return

    print("[Setup] Fetching latest sing-box release info...")
    url = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"[Setup] Failed to fetch release info: {e}")
        return

    download_url = None
    for asset in data.get('assets', []):
        if 'windows-amd64.zip' in asset.get('name', ''):
            download_url = asset['browser_download_url']
            break

    if not download_url:
        print("[Setup] Could not find windows-amd64.zip in the latest release.")
        return

    zip_path = "sing-box-latest.zip"
    print(f"[Setup] Downloading {download_url} to {zip_path}...")
    
    try:
        urllib.request.urlretrieve(download_url, zip_path)
    except Exception as e:
        print(f"[Setup] Download failed: {e}")
        return
        
    print("[Setup] Extracting...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # zip contains a folder like sing-box-1.x.x-windows-amd64/sing-box.exe
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('sing-box.exe'):
                    file_info.filename = os.path.basename(file_info.filename)
                    zip_ref.extract(file_info, ".")
                    break
        print(f"[Setup] Extracted successfully to {settings.SING_BOX_PATH}")
    except Exception as e:
        print(f"[Setup] Extraction failed: {e}")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

def setup_xray():
    """Download and extract the latest Xray-core for Windows amd64."""
    if (os.path.exists(settings.XRAY_PATH) or 
            shutil.which(settings.XRAY_PATH) or 
            shutil.which("xray")):
        print(f"[Setup] xray already exists or is available in PATH. Skipping download.")
        return

    print("[Setup] Fetching latest xray release info...")
    url = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"[Setup] Failed to fetch release info: {e}")
        return

    download_url = None
    for asset in data.get('assets', []):
        # We need Xray-windows-64.zip
        if 'windows-64.zip' in asset.get('name', ''):
            download_url = asset['browser_download_url']
            break

    if not download_url:
        print("[Setup] Could not find windows-64.zip in the latest release.")
        return

    zip_path = "xray-latest.zip"
    print(f"[Setup] Downloading {download_url} to {zip_path}...")
    
    try:
        urllib.request.urlretrieve(download_url, zip_path)
    except Exception as e:
        print(f"[Setup] Download failed: {e}")
        return
        
    print("[Setup] Extracting...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.filename.endswith('xray.exe'):
                    file_info.filename = os.path.basename(file_info.filename)
                    zip_ref.extract(file_info, ".")
                    break
        print(f"[Setup] Extracted successfully to {settings.XRAY_PATH}")
    except Exception as e:
        print(f"[Setup] Extraction failed: {e}")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

if __name__ == "__main__":
    setup_singbox()
    setup_xray()
