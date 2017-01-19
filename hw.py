#!/usr/bin/python3

# todo env

from glob import glob
from sys import exit
from subprocess import call
from tempfile import mkdtemp, NamedTemporaryFile
from os import chdir, getcwd, makedirs
from os.path import basename, splitext, join, isfile, pardir, exists

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    import os
    DEVNULL = open(os.devnull, 'wb')


use_tmp_dir = False


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


def cmd(command, params=[], sout=DEVNULL):
    print('{0} {1}'.format(command, ' '.join(params)))
    ret = call([command] + params, stdout=sout)
    if ret != 0:
        print('Returned [{0}]'.format(ret))
    return ret


def cmd_checked(command, params=[], sout=DEVNULL):
    if cmd(command, params, sout) != 0:
        print('It failed! Bye!')
        exit(0)


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
        return cmd('./configure', params)

    def download(self):
        print("Downloading {0} from {1}".format(self.name, self.url))
        return cmd('wget', ['--quiet', self.url])

    def unpack(self):
        print("Unpacking {0}".format(self.get_arch_name()))
        return cmd('tar', ['xjf', self.get_arch_name()])


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
        if not isfile(proj.get_arch_name()):
            proj.download()
        proj.unpack()
        chdir(proj.get_unpack_dir())
        proj.configure()
        cmd_checked('make')
        cmd_checked('make', ['install'])
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
pkg_to_check = ['wget', 'gcc', 'bzip2', 'pcre-devel', 'git',
                'autoconf', 'libtool', 'patch']
# HACK
#pkg_to_check = []
for pkg in pkg_to_check:

    if not pkg_is_installed(pkg):
        print('{0} is not installed.'.format(pkg))
        ret = pkg_install(pkg)
        print('Result {0}.'.format(ret))
    else:
        print('{0} is installed.'.format(pkg))

#######################################################################
# Download & unpack stage

if use_tmp_dir:
    tmp_dir = mkdtemp()
else:
    tmp_dir = getcwd()

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

# HACK
pBuild = ProjectBuilder([apache, apr, apr_util])
pBuild.build_all()

######################################
# Get, build and install mod_cluster
######################################

cmd('git', ['clone', 'https://github.com/modcluster/mod_cluster.git'])
chdir('mod_cluster')
cmd('git', ['checkout', 'origin/1.3.x', '-b', '1.3.x'])
chdir('native')

for mod in ['mod_proxy_cluster', 'mod_manager', 'mod_cluster_slotmem', 'advertise']:
    print('Building mod: {0}'.format(mod))
    chdir(mod)
    cmd_checked('./buildconf')
    cmd_checked('./configure',
                ['--with-apxs={0}'.format(join(apache.get_install_dir(), 'bin/apxs'))])
    cmd_checked('make')
    cmd_checked('libtool',
                ['--finish', join(apache.get_install_dir(), 'modules')])

    # `make install' does nothing; do `cp' instead
    cmd_checked('cp', glob('*.so') + [join(apache.get_install_dir(), 'modules')], )
    chdir(pardir)

# Get mod_cluster config file
url = 'https://gist.githubusercontent.com/Karm/85cf36a52a8c203accce/raw/a41ecc90fea1f2b3bb880e79fa67fb6c7f61cf68/mod_cluster.conf'
extra_conf_path = join(apache.get_install_dir(), 'conf/extra/', basename(url))
cmd_checked('wget', ['--quiet', url, '-O', extra_conf_path])

# Update mod_cluster config file
cache_dir = join(apache.get_install_dir(), 'cache')
if not exists(cache_dir):
    makedirs(cache_dir)
cmd_checked('sed',
            ['-i',
             's@MemManagerFile /opt/DU/httpd-build/cache/mod_cluster@MemManagerFile {0}@'
             .format(join(cache_dir, 'mod_cluster')),
             extra_conf_path])

# Update apache config file
conf_path = join(apache.get_install_dir(), 'conf/httpd.conf')
diff_text =\
            """
115c115
< #LoadModule proxy_module modules/mod_proxy.so
---
> LoadModule proxy_module modules/mod_proxy.so
453a454,455
>  
> Include conf/extra/mod_cluster.conf
"""
diff_file = NamedTemporaryFile('w')
diff_file.write(diff_text)
diff_file.flush()
cmd('patch', [conf_path, diff_file.name], sout=None)

# Set firewall
cmd_checked('firewall-cmd', ['--add-service=http', '--permanent'])
cmd_checked('firewall-cmd', ['--add-port=6666/tcp', '--permanent'])

# (re)Start apache
cmd_checked(join(apache.get_install_dir(), 'bin', 'apachectl'), ['restart'])
