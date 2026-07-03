import platform
import typer
from pathlib import Path
from typing import Optional
import subprocess


DEFAULT_COMMENT = "odooflow"

def generate_ssh_key(
    key_name: str = typer.Option(),
    output_dir: Optional[str] = typer.Option(),
    overwrite: bool = typer.Option(),
    passphrase: Optional[str] = typer.Option(None, help="Passphrase for the SSH key"),
):
    typer.secho("🔐 Generating SSH key pair...", fg="cyan")

    home = Path.home()
    ssh_dir = Path(output_dir).expanduser() if output_dir else home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)

    private_key_path = ssh_dir / key_name
    public_key_path = ssh_dir / f"{key_name}.pub"

    if private_key_path.exists() or public_key_path.exists():
        if not overwrite:
            typer.secho(f"❌ Key files already exist at {private_key_path}.", fg="red")
            typer.secho("Use --overwrite to replace them.", fg="yellow")
            raise typer.Exit()

    os_name = platform.system()

    try:
        if os_name in ["Linux", "Darwin", "Windows"]:
            # Use ssh-keygen if available
            command = [
                "ssh-keygen",
                "-t", "rsa",
                "-b", "4096",
                "-f", str(private_key_path),
                "-C", DEFAULT_COMMENT,
                "-N", passphrase if passphrase else "",
            ]
            subprocess.run(command, check=True)
        else:
            typer.secho(f"❌ Unsupported OS: {os_name}", fg="red")
            raise typer.Exit()

        typer.secho(f"✅ SSH key pair generated:", fg="green")
        typer.echo(f"🔑 Private key: {private_key_path}")
        typer.echo(f"🔓 Public key: {public_key_path}")

    except FileNotFoundError:
        typer.secho("❌ ssh-keygen not found on your system. Please install OpenSSH.", fg="red")
    except subprocess.CalledProcessError as e:
        typer.secho(f"❌ Failed to generate SSH key: {e}", fg="red")
