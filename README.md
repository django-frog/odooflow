# 🌀 Odooflow CLI

**Odooflow CLI** is a command-line interface tool designed to streamline the development workflow for Odoo projects. It helps clone Odoo modules (and their dependencies), handles GitLab lookups, and provides options for deep recursive cloning.

## 🚀 Features

- Clone an Odoo module by Git URL
- Recursively resolve and clone all dependencies
- Smart skip of Odoo core modules
- Branch selection for cloning
- Helpful and colorful CLI output
- Built using [Typer](https://typer.tiangolo.com/) and Python 3.9+

---

## 📦 Installation

```bash
git clone https://github.com/YOUR_USERNAME/odooflow-cli.git
cd odooflow-cli
pip install .
```

Or install directly from source for development:

```bash
pip install -e .
```

---

## 🛠️ Usage

Once installed, you can use the CLI by running:

```bash
odooflow clone --url <GIT_REPO_URL> [--branch <BRANCH>] [--deep]
```

### 🔹 Options:

| Flag        | Description                              |
|-------------|------------------------------------------|
| `--url`     | Full HTTP URL of the module repo         |
| `--branch`  | (Optional) Git branch to clone from      |
| `--deep`    | Recursively clone all dependencies       |

### 🔍 Examples:

Clone a single module:

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git
```

Clone with specific branch:

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git --branch 17.0
```

Clone deeply with dependencies:

```bash
odooflow clone --url https://gitlab.com/mygroup/my_odoo_module.git --deep
```

---

## 📁 Project Structure

```
odooflow-cli/
├── odooflow/
│   ├── __init__.py
│   ├── config.py
│   ├── utils.py
│   ├── gitlab.py
│   └── clone.py
├── tests/
├── README.md
├── pyproject.toml
└── setup.py
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

## 👨‍💻 Author

Made with ❤️ by Mohammad A. Hamdan

---
