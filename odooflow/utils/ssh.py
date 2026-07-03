import os
import tarfile
import tempfile
from pathlib import Path
from typing import Optional, Set
import paramiko
import hashlib


def resolve_remote_path(sftp, path: str) -> str:
    """
    Resolves remote path (supports ~, relative, absolute).
    """
    if path.startswith("~"):
        home = sftp.normalize(".")
        return path.replace("~", home, 1)
    elif not path.startswith("/"):
        home = sftp.normalize(".")
        return f"{home}/{path}"
    else:
        return path


def compress_directory(source_dir: Path, exclude_dirs: Optional[Set[str]] = None) -> Path:
    """
    Compress a directory into a .tar.gz archive in a cross-platform safe temp location.
    """
    exclude_dirs = exclude_dirs or set()
    print(f"🔧 Compressing directory: {source_dir}")
    archive_fd, archive_path = tempfile.mkstemp(suffix=".tar.gz")
    os.close(archive_fd)

    with tarfile.open(archive_path, "w:gz") as tar:
        for root, dirs, files in os.walk(source_dir):
            rel_root = Path(root).relative_to(source_dir)
            if any(part in exclude_dirs for part in rel_root.parts):
                continue
            for file in files:
                file_path = Path(root) / file
                arcname = Path(source_dir.name) / rel_root / file
                tar.add(file_path, arcname=str(arcname).replace("\\", "/"))

    print(f"✅ Compression complete: {archive_path}")
    return Path(archive_path)


def upload_directory_via_ssh(
    local_path: Path,
    remote_user: str,
    remote_host: str,
    remote_path: str,
    port: int = 22,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
    exclude_dirs: Optional[Set[str]] = None,
    strict_host_key_checking: bool = False,
    post_exec_cmd: Optional[str] = None,
    on_post_exec=None,
):
    """
    Uploads a local directory to a remote server via SSH by compressing it and extracting it remotely.
    Cross-platform compatible.

    If `post_exec_cmd` is provided, it is executed over the same SSH connection after a successful
    extract/cleanup (and before the connection is closed). `on_post_exec(stdout, stderr, exit_status)`
    is an optional callback that receives the command's streams and exit status for custom reporting.
    """
    exclude_dirs = exclude_dirs or set()
    local_path = Path(local_path).resolve()
    archive_name = f"{local_path.name}.tar.gz"

    print(f"🔐 Connecting to {remote_user}@{remote_host}:{port} ...")
    ssh = paramiko.SSHClient()

    if strict_host_key_checking:
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if key_path:
        key_path = os.path.expanduser(key_path)
        pkey = paramiko.RSAKey.from_private_key_file(key_path)
        ssh.connect(remote_host, port=port, username=remote_user, pkey=pkey)
    else:
        ssh.connect(remote_host, port=port, username=remote_user, password=password)

    sftp = ssh.open_sftp()
    resolved_remote_path = resolve_remote_path(sftp, remote_path)
    print(f"📁 Remote path resolved to: {resolved_remote_path}")

    # Step 1: Compress local directory
    archive_path = compress_directory(local_path, exclude_dirs)

    try:
        # Step 2: Upload archive
        remote_archive = f"{resolved_remote_path}/{archive_name}"
        print(f"📤 Uploading archive to remote: {remote_archive}")
        sftp.put(str(archive_path), remote_archive)
        print(f"✅ Upload complete.")

        # Step 3: Extract archive on remote server
        print(f"📦 Extracting archive on remote server ...")
        extract_cmd = f"mkdir -p {resolved_remote_path} && tar -xzf {remote_archive} -C {resolved_remote_path}"
        stdin, stdout, stderr = ssh.exec_command(extract_cmd)
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError(stderr.read().decode())
        print(f"✅ Extraction complete.")

        # Step 4: Remove remote archive
        print(f"🧹 Cleaning up remote archive ...")
        ssh.exec_command(f"rm -f {remote_archive}")
        print(f"✅ Remote cleanup complete.")

        # Step 5: Optionally run a post-upload command on the remote host
        if post_exec_cmd:
            print(f"⚙️  Running post-upload command: {post_exec_cmd}")
            stdin, stdout, stderr = ssh.exec_command(post_exec_cmd)
            exit_status = stdout.channel.recv_exit_status()
            out_text = stdout.read().decode()
            err_text = stderr.read().decode()
            if on_post_exec:
                on_post_exec(out_text, err_text, exit_status)
            elif exit_status != 0:
                raise RuntimeError(err_text or f"Post-upload command failed with exit status {exit_status}")
            print(f"✅ Post-upload command complete.")

    finally:
        # Step 6: Clean up local archive
        print(f"🧼 Removing temporary local archive ...")
        if archive_path.exists():
            archive_path.unlink()
        print(f"✅ Local cleanup complete.")

        sftp.close()
        ssh.close()
        print(f"🔒 SSH connection closed.")
