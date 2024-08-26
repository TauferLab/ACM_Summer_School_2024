
import os,sys, tomli

BODY="""
[project]
name = "openvisuspy"
version = "{version}"
authors = [{ name="OpenVisus developers"},]
description = "openvisuspy"
readme = "README.md"
requires-python = ">=3.6"

[project.urls]
"Homepage" = "https://github.com/sci-visus/openvisuspy"
"Bug Tracker" = "https://github.com/sci-visus/openvisuspy"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
"""

# ////////////////////////////////////////////////////////////
if __name__=="__main__":
	with open("pyproject.toml", "rb") as f: config = tomli.load(f)
	old_version=config['project']['version']
	v=old_version.split('.')
	new_version=f"{v[0]}.{v[1]}.{int(v[2])+1}"
	body=BODY.replace("{version}",new_version)
	with open("pyproject.toml", "wt") as f: f.write(body)
	print(new_version)
	sys.exit(0)