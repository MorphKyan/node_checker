import os
import zipfile
import subprocess

def build_frontend():
    print("Building frontend locally...")
    result = subprocess.run("npm run build", cwd="frontend", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print("Frontend build failed:")
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError("Frontend build failed")
    print("Frontend build completed successfully.")

def create_archive(zip_filename="node_checker.zip"):
    exclude_dirs = {
        ".git", ".github", "venv", ".pytest_cache", "__pycache__", 
        "node_modules", "cache", "result", "data", "inputs", "dist-cache"
    }
    exclude_files = {
        "xray-latest.zip", "sing-box-latest.zip", "xray.exe", 
        "sing-box.exe", "node_checker.zip", "api_server.out.log", "api_server.err.log"
    }
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk('.'):
            # Prune directories starting with dot or in excluded list
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
            for file in files:
                if file.startswith(".env") or file in exclude_files or file.endswith('.pyc') or file.endswith('.log'):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, '.')
                zipf.write(file_path, arcname)
    print(f"Created archive: {zip_filename}")

def deploy():
    import paramiko

    host = os.environ["DEPLOY_HOST"]
    username = os.environ["DEPLOY_USER"]
    port = int(os.environ.get("DEPLOY_PORT", "22"))
    zip_filename = "node_checker.zip"
    remote_zip_path = f"/tmp/{zip_filename}"
    remote_deploy_dir = "/root/node-checker"

    build_frontend()
    create_archive(zip_filename)
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    try:
        ssh.connect(hostname=host, port=port, username=username,
                    password=os.environ.get("DEPLOY_PASSWORD"))
        with ssh.open_sftp() as sftp:
            sftp.put(zip_filename, remote_zip_path)

        commands = [
            f"mkdir -p {remote_deploy_dir} /mnt/cache/appdata/node-checker",
            f"unzip -o {remote_zip_path} -d {remote_deploy_dir}",
            f"rm -f {remote_zip_path}",
            f"cd {remote_deploy_dir} && docker compose build",
            f"cd {remote_deploy_dir} && docker compose up -d --no-build --wait --wait-timeout 90",
        ]
        for cmd in commands:
            print(f"Running: {cmd}")
            _, stdout, stderr = ssh.exec_command(cmd)
            output = stdout.read().decode("utf-8")
            error = stderr.read().decode("utf-8")
            if stdout.channel.recv_exit_status() != 0:
                raise RuntimeError(f"Deployment command failed: {cmd}\n{output}\n{error}")
            print(output)
    finally:
        ssh.close()
        if os.path.exists(zip_filename):
            os.remove(zip_filename)
    print("Deployment completed successfully!")


if __name__ == "__main__":
    deploy()
