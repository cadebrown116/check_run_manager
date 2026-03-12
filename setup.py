from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    install_requires = f.read().strip().split("\n") if f.readable() else []

setup(
    name="check_run_manager",
    version="0.0.1",
    description="Batch supplier check printing for ERPNext",
    author="AB Carter",
    author_email="it@abcarter.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
