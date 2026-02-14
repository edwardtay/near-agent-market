from setuptools import setup
from pathlib import Path

long_description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="near-testing",
    version="0.1.0",
    description="Testing utilities for NEAR smart contracts -- MockRPC, test accounts, assertions, and sandbox support",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="NEAR Agent Market",
    license="MIT",
    url="https://github.com/near-agent-market/near-testing",
    py_modules=["near_testing"],
    python_requires=">=3.8",
    install_requires=[],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Testing",
    ],
    keywords="near blockchain smart-contract testing sandbox mock",
)
