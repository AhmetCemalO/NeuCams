#!/usr/bin/env python
# Install script for labcams.
# Joao Couto - March 2017
import os
from os.path import join as pjoin
from setuptools import setup, find_packages
from setuptools.command.install import install

with open("readme-pip.md", "r") as fh:
    longdescription = fh.read()

setup(
    name = 'labcams',
    version = '1.0',
    author = 'Adrien Philippon',
    author_email = 'philippon.adrien@gmail.com',
    description = (longdescription),
    long_description = longdescription,
    license = 'GPL',
    packages = find_packages(),
    entry_points = {
        'console_scripts': [
            'labcams = python_code.__main__:main',
        ]
    },
)


