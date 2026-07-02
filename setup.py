from setuptools import setup, find_packages

setup(
    name="netdeploy",
    version="1.0.0",
    description="Automated Network Provisioning Platform",
    author="Thandava Sai Rohith Achanta",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "psycopg2-binary",
        "celery",
        "redis",
        "pydantic",
        "gitpython",
        "netmiko",
        "pyyaml",
    ],
)
