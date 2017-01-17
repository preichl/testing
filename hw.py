#!/usr/bin/python3

from subprocess import call, DEVNULL


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

print("Check and install equired packages")
pkg_to_check = ['wget', 'gcc']
for pkg in pkg_to_check:
    if not pkg_is_installed(pkg):
        print('{0} is not installed.'.format(pkg))
        ret = pkg_install(pkg)
        print('Result {0}.'.format(ret))
    else:
        print('{0} is installed.'.format(pkg))
