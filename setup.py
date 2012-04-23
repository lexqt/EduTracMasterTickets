#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
import os

from setuptools import setup

setup(
    name = 'EduTracMasterTickets',
    version = '3.3.0',
    packages = ['mastertickets'],
    package_data = { 'mastertickets': ['templates/*.html', 'htdocs/*.js', 'htdocs/*.css' ] },

    author = 'Noah Kantrowitz, Aleksey A. Porfirov',
    author_email = 'lexqt@yandex.ru',
    description = 'Provides support for ticket dependencies and master tickets.',
    long_description = open(os.path.join(os.path.dirname(__file__), 'README')).read(),
    license = 'BSD',
    keywords = 'trac plugin ticket dependencies master',
    url = 'https://github.com/lexqt/EduTracMasterTickets',
    classifiers = [
        'Framework :: Trac',
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    
    install_requires = ['Trac>=0.12'],

    entry_points = {
        'trac.plugins': [
            'mastertickets.web_ui = mastertickets.web_ui',
            'mastertickets.api = mastertickets.api',
        ]
    }
)

#### AUTHORS ####
## Author of original MasterTicketsPlugin:
## Noah Kantrowitz
## noah@coderanger.net
##
## Author of EduTrac adaptation, fixes and enhancements:
## Aleksey A. Porfirov
## lexqt@yandex.ru
## github: lexqt
