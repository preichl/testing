#!/usr/bin/python3

# todo env

from subprocess import call
from tempfile import mkdtemp
from os import chdir
from os.path import basename, splitext, join

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    import os
    DEVNULL = open(os.devnull, 'wb')


# Some wrappers
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

def make():
    ret = call(['make'])
    if ret == 0:
        return True
    return False

def install():
    ret = call(['make', 'install'])
    if ret == 0:
        return True
    return False

def unpack(file):
    ret = call(['tar', 'xjf', file])
    if ret == 0:
        return True
    return False

def configure(params):
    ret = call(['./configure'] + params)
    if ret == 0:
        return True
    return False


class Project:
    """A class encapsulating getting and building project"""
    # HACK
    pre_inst_dir = '/tmp/usr/local/'

    def __init__(self, name, url, dependencies):
        self.name = name
        self.url = url
        self.dependencies = dependencies
        self.ready = False

    def get_arch_name(self):
        return basename(self.url)

    def get_unpack_dir(self):
        arch = self.get_arch_name()
        return arch[:arch.find('.tar')]

    def get_install_dir(self):
        return join(Project.pre_inst_dir, self.name)

    def configure(self):
        params = ['--prefix={0}'.format(self.get_install_dir())]
        for d in self.dependencies:
            params.append('--with-{0}={1}'.format(d.name, d.get_install_dir()))
        return configure(params)

    def download(self):
        print("Downloading {0} from {1}".format(self.name, self.url))
        return download(self.url)

    def unpack(self):
        print("Unpacking {0}".format(self.get_arch_name()))
        return unpack(self.get_arch_name())


class ProjectBuilder:
    """Resolves project dependencies and builds projects"""

    def __init__(self, projects):
        self.projects = projects

    def _get_next(self):
        for p in self.projects:
            if not p.ready and all(d.ready for d in p.dependencies):
                return p
        return None

    def _build_proj(self, proj):
        # HACK
        #proj.download()
        #proj.unpack()
        print(proj.get_arch_name())
        print(proj.get_unpack_dir())
        chdir(proj.get_unpack_dir())
        print('changed')
        proj.configure()
        make()
        install()
        chdir(tmp_dir)

    def build_all(self):
        proj = self._get_next()
        while proj:
            self._build_proj(proj)
            proj.ready = True
            proj = self._get_next()

        if not all(proj.ready for proj in self.projects):
            print("Failed to resolve projects")


#######################################################################
# Dependency stage
print("Check and install required packages")
pkg_to_check = ['wget', 'gcc', 'bzip2', 'pcre-devel']
for pkg in pkg_to_check:
    if not pkg_is_installed(pkg):
        print('{0} is not installed.'.format(pkg))
        ret = pkg_install(pkg)
        print('Result {0}.'.format(ret))
    else:
        print('{0} is installed.'.format(pkg))

#######################################################################
# Download & unpack stage

tmp_dir = mkdtemp()
# HACK
tmp_dir = '/tmp/tmp5cfkyq1h'
print("Changing to {0}".format(tmp_dir))
chdir(tmp_dir)

apr = Project(name='apr',
              url='http://apache.miloslavbrada.cz/apr/apr-1.5.2.tar.bz2',
              dependencies=[])
apr_util = Project(name='apr-util',
                   url='http://apache.miloslavbrada.cz/apr/apr-util-1.5.4.tar.bz2',
                   dependencies=[apr])
apache = Project(name='apache',
                 url='http://apache.miloslavbrada.cz/httpd/httpd-2.4.25.tar.bz2',
                 dependencies=[apr, apr_util])

# todo mod cluster


pBuild = ProjectBuilder([apache, apr, apr_util])
pBuild.build_all()
