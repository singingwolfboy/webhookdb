# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from setuptools import setup, Command, find_packages


def is_requirement(line):
    line = line.strip()
    # Skip blank lines, comments, and editable installs
    return not (
        line == '' or
        line.startswith('-r') or
        line.startswith('#') or
        line.startswith('-e') or
        line.startswith('git+')
    )


def get_requirements(path):
    with open(path) as f:
        lines = f.readlines()
    return [l.strip() for l in lines if is_requirement(l)]


setup(
    name="GithubDB",
    version="0.0.1",
    description="Replicates Github's database via HTTP webhooks",
    long_description=open('README.rst').read(),
    author="David Baumgold",
    author_email="david@davidbaumgold.com",
    url="https://github.com/singingwolfboy/githubdb",
    packages=find_packages(),
    install_requires=get_requirements("requirements.txt"),
    license='AGPL',
    classifiers=(
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Framework :: Flask',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
    ),
    zip_safe=False,
)
