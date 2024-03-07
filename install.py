import os
import sys

from subprocess import Popen, check_output, PIPE

requirements = open(os.path.join(os.path.dirname(__file__), "requirements.txt")).read().split("\n")

installed_packages = check_output(
    [sys.executable, "-m", "pip", "list"],
    universal_newlines=True
).split("\n")

installed_packages = set([package.split(" ")[0].lower() for package in installed_packages if package.strip()])

for requirement in requirements:
    if requirement.lower() not in installed_packages:
        print(f"Installing requirements...")
        Popen([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], stdout=PIPE, stderr=PIPE, cwd=os.path.dirname(__file__)).communicate()
        print(f"Installed.")
        break
