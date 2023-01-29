import os

from setuptools import setup, find_packages

BASEDIR = os.path.abspath(os.path.dirname(__file__))

README_PATH = os.path.join(BASEDIR, 'README.md')
CHANGELOG_PATH = os.path.join(BASEDIR, 'CHANGELOG.md')
REQUIREMENTS_PATH = os.path.join(BASEDIR, 'requirements.txt')

README = ''
if os.path.exists(README_PATH):
    with open(README_PATH) as fobj:
        README = fobj.read()

CHANGELOG = ''
if os.path.exists(CHANGELOG_PATH):
    with open(CHANGELOG_PATH) as fobj:
        CHANGELOG = fobj.read()

REQUIREMENTS = []
DEPENDENCIES = []
if os.path.exists(REQUIREMENTS_PATH):
    with open(REQUIREMENTS_PATH) as fobj:
        for line in fobj.readlines():
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            if line.startswith('http://') or line.startswith('https://'):
                continue
            if line.startswith('-e'):
                DEPENDENCIES.append(line[2:].strip())
            else:
                REQUIREMENTS.append(line.strip())


setup(
    name='mist.orchestration',
    version='1.0',
    description='Mist orchestration plugin',
    long_description='%s\n\n%s' % (README, CHANGELOG),
    author='mist.io',
    author_email='info@mist.io',
    url='https://mist.io',
    packages=find_packages(BASEDIR),
    namespace_packages=['mist'],
    include_package_data=True,
    zip_safe=False,
    install_requires=REQUIREMENTS,
    dependency_links=DEPENDENCIES,
    tests_require=REQUIREMENTS,
)
