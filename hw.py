#!/usr/bin/python3

# todo env

from subprocess import call, DEVNULL
from tempfile import mkdtemp
from os import chdir
from os.path import basename


def pkg_is_installed(name):
    ret = call(['dnf', 'list', 'installed', name],
               stdout=DEVNULL, stderr=DEVNULL)
    if ret == 0:
        return True
    return False


def pkg_install(pkg):
    ret = call(['dnf', 'install', pkg])
    if ret == 0:
        return True
    return False


def download(url):
    ret = call(['wget', '--quiet',  url])
    if ret == 0:
        return True
    return False


def unpack(file):
    ret = call(['tar', 'xjf', file])
    if ret == 0:
        return True
    return False

# Dependency stage
print("Check and install required packages")
pkg_to_check = ['wget', 'gcc', 'bzip2']
for pkg in pkg_to_check:
    if not pkg_is_installed(pkg):
        print('{0} is not installed.'.format(pkg))
        ret = pkg_install(pkg)
        print('Result {0}.'.format(ret))
    else:
        print('{0} is installed.'.format(pkg))

# Download & unpack stage
tmp_dir = mkdtemp()
print("Changing to {0}".format(tmp_dir))
chdir(tmp_dir)

# todo mod cluster
proj = {'apache': 'http://apache.miloslavbrada.cz/httpd/httpd-2.4.25.tar.bz2',
        'apr': 'http://apache.miloslavbrada.cz/apr/apr-1.5.2.tar.bz2',
        'apr-util': 'http://apache.miloslavbrada.cz/apr/apr-util-1.5.4.tar.bz2'
        }

for p in proj:
    print("Downloading {0} from {1}".format(p, proj[p]))
    download(proj[p])

for p in proj:
    arch = basename(proj[p])
    print("Unpacking {0}".format(arch))
    unpack(arch)
