#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
import os

from setuptools import setup

PACKAGE = 'mastertickets'

extra = {} 
try:
    from trac.util.dist import get_l10n_cmdclass
    cmdclass = get_l10n_cmdclass()
    if cmdclass:
        extra['cmdclass'] = cmdclass
        extractors = [
            ('**.py',                'python', None),
            ('**/templates/**.html', 'genshi', None),
            ('**/templates/**.txt',  'genshi', {
                'template_class': 'genshi.template:NewTextTemplate',
            }),
        ]
        extra['message_extractors'] = {
            PACKAGE: extractors,
        }
except ImportError:
    pass

setup(
    name = 'EduTracMasterTickets',
    version = '3.3.1',
    packages = [PACKAGE],
    package_data = { PACKAGE: ['templates/*.html',
                               'locale/*/LC_MESSAGES/*.mo'] },

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
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    
    entry_points = {
        'trac.plugins': [
            'mastertickets.web_ui = mastertickets.web_ui',
            'mastertickets.api = mastertickets.api',
        ]
    },

    **extra
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
