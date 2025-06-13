from setuptools import setup, find_packages

setup(
    name="odooflow",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "typer[all]",
        "rich",
        "GitPython>=3.1.44",
        "requests>=2.32.3",
        "paramiko>=3.5.1",
        "tqdm>=4.67.1",
        "bcrypt>=4.3.0",
        "cryptography>=45.0.3",
        "PyNaCl>=1.5.0",
    ],
    entry_points={
        'console_scripts': [
            'odooflow=odooflow.cli:main',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",  # This tells users it's still under development
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",  # If you're using MIT
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
    ],
    python_requires='>=3.7',
)
