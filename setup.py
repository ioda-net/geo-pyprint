#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import os

from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand


here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.rst')) as f:
    README = f.read()


requires = [
    'paste',
    'pyramid',
    'pyramid_debugtoolbar',
    'pyramid_tm',
    'secretary',
    'waitress',
]

setup(
    name='geo-pyprint',
    version='0.0',
    description='geo-pyprint',
    long_description=README,
    classifiers=[
    "Programming Language :: Python",
    "Framework :: Pyramid",
    "Topic :: Internet :: WWW/HTTP",
    "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
    ],
    author='Ioda-Net Sàrl',
    author_email='contact@ioda-net.ch',
    url='https://github.com:ioda-net/geo-pyprint.git',
    keywords='web wsgi bfg pylons pyramid',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    test_suite='geopyprint',
    install_requires=requires,
    entry_points="""\
    [paste.app_factory]
    main = geopyprint:main
    """,
)

