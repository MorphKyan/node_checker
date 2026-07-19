import os
import zipfile
import paramiko
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
        "node_modules", "cache", "result", "data"
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
                if file in exclude_files or file.endswith('.pyc') or file.endswith('.log'):
                    continue
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, '.')
                zipf.write(file_path, arcname)
    print(f"Created archive: {zip_filename}")

def deploy():
    host = "192.168.1.200"
    port = 22
    username = "root"
    password = "home14259598"
    zip_filename = "node_checker.zip"
    remote_zip_path = f"/tmp/{zip_filename}"
    remote_deploy_dir = "/root/node-checker"

    try:
        build_frontend()
    except Exception as e:
        print(f"Aborting deployment: {e}")
        return

    create_archive(zip_filename)

    print(f"Connecting to {host}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port, username, password)
    except Exception as e:
        print(f"SSH Connection failed: {e}")
        return

    print("Uploading archive...")
    sftp = ssh.open_sftp()
    sftp.put(zip_filename, remote_zip_path)
    sftp.close()

    print("Executing remote commands...")
    commands = [
        f"mkdir -p {remote_deploy_dir}",
        f"mkdir -p /mnt/cache/appdata/node-checker",
        f"apt-get update && apt-get install -y unzip || yum install -y unzip || true",
        f"unzip -o {remote_zip_path} -d {remote_deploy_dir}",
        f"rm -f {remote_zip_path}",
        f"docker rm -f node-checker || true",
        f"cd {remote_deploy_dir} && (docker compose down || docker-compose down || true)",
        f"cd {remote_deploy_dir} && (docker compose up --build -d || docker-compose up --build -d)"
    ]

    for cmd in commands:
        print(f"Running: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        out_text = stdout.read().decode('utf-8')
        err_text = stderr.read().decode('utf-8')
        if out_text:
            print(f"STDOUT:\n{out_text}")
        if err_text:
            print(f"STDERR:\n{err_text}")
        print(f"Exit code: {exit_status}\n")

    ssh.close()
    
    # Remove local zip
    if os.path.exists(zip_filename):
        os.remove(zip_filename)
    print("Deployment completed successfully!")

if __name__ == "__main__":
    deploy()
