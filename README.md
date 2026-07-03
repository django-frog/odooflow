# 🌀 Odooflow CLI

**OdooFlow CLI** is a command-line interface tool designed to streamline the development workflow for Odoo projects. It helps clone Odoo modules (and their dependencies), handles GitLab lookups, and provides bounded recursive cloning via a configurable depth.

## 🚀 Features

- Clone an Odoo module by Git URL
- Recursively resolve and clone dependencies up to a configurable depth
- Smart skip of Odoo core modules
- Branch selection for cloning
- Post-push command execution on the remote server
- Built-in SSH key generation
- Helpful and colorful CLI output
- Built using [Typer](https://typer.tiangolo.com/) and Python 3.7+

---

## 📦 Installation & first-run setup

```bash
git clone https://github.com/anomalyco/odooflow-cli.git
cd odooflow-cli
pip install .
```

Or install directly from source for development (with test/lint extras):

```bash
pip install -e .[dev]
```

Install from PyPI (once published):

```bash
pip install odooflow-cli
```

### First-run wizard

After installing, configure odooflow with your GitLab access token:

```bash
odooflow setup
```

The wizard writes `~/.odooflowrc` (with `chmod 600` permissions), prompting for:

1. **GitLab access token** — kept private in the rc file; typed input is masked.
2. **GitLab URL** — defaults to the bundled one, override for self-hosted.
3. **Core modules** — comma-separated list, used to skip framework deps.

If you don't have a token yet, create one at *GitLab → Preferences → Access Tokens* with scopes `api`, `read_api`, and `write_repository`.

Prefer environment variables? You can skip the rc entirely:

```bash
export ODOOFLOW_ACCESS_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
  odooflow clone <your-module-url>
```

---

## 🛠️ Usage

Once installed, you can use the CLI by running:

```bash
odooflow --help
```

### Available Commands:

- **`setup`**: Interactive wizard for first-run configuration (`~/.odooflowrc`).
- **`init`**: Initialize the Odoo module environment file and sync metadata with manifest
- **`sync-env`**: Sync the environment file from manifest
- **`config`**: Update or show OdooFlow CLI configuration
- **`clone`**: Clone a module and its dependencies from a git repository
- **`remote`**: Manage remote connections for Git and deployment server
- **`ssh-keygen`**: Generate a secure SSH key pair
- **`push`**: Push the current Git branch and upload the project to the test server

### Clone Command Options:

| Flag           | Description                                                                                            |
|----------------|--------------------------------------------------------------------------------------------------------|
| `--url`        | Full HTTP URL of the module repo                                                                       |
| `--branch`/`-b`| (Optional) Git branch to clone from                                                                    |
| `--depth`/`-d` | Max dependency depth to clone. `1` clones only the target module, `2` clones target + immediate deps, etc. (default: `1`) |

### Push Command Options:

| Flag            | Description                                                                 |
|-----------------|-----------------------------------------------------------------------------|
| `--remote-only` | Skip Git push and only upload to server                                     |
| `--exec`        | Custom shell command to execute on the server after pushing                 |

### 🔍 Examples:

Clone a single module:

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git
```

Clone with specific branch:

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git --branch 17.0
```

Clone target + immediate dependencies (depth 2):

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git --depth 2
```

Clone the full dependency tree (depth 5):

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git --depth 5
```

Push current branch to Git and upload to the configured server:

```bash
odooflow push
```

Push and execute a custom command on the remote server after upload:

```bash
odooflow push --exec "sudo systemctl restart odoo"
```

Skip Git push, only upload to server:

```bash
odooflow push --remote-only
```

---

## 📁 Project Structure

```
odooflow/
├── odooflow/
│   ├── __init__.py
│   ├── cli.py
│   ├── config_manager.py
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── clone_module.py
│   │   ├── config.py
│   │   ├── init_module_env.py
│   │   ├── keygen.py
│   │   ├── push.py
│   │   ├── remote.py
│   │   └── sync_env.py
│   └── utils/
│       ├── env.py
│       └── ssh.py
├── tests/
├── README.md
├── requirements.txt
├── pyproject.toml
└── LICENSE
```

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request with any improvements, bug fixes, or new features.

1. Fork the repository
2. Create a new branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## 📝 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## WISH-LIST:

Move this CLI into fully-integrated Odoo environment, using Odoo, users can create issues, add the amount of details, then sync these issues with Odooflow.

We can do integration with any code agent to help developers to achieve these issues

same thing for pipelines, I think it will be amazing if developers can build pipelines using Odoo, then apply the same pipelines using Odooflow.

I have many things in my head, I will back soon to this project.

## 👨‍💻 Author

Made with ❤️ by Mohammad A. Hamdan

---
