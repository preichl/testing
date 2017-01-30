#!/usr/bin/python3

# todo env

import sys
import os
import http.cookiejar
from os import chdir, getcwd, makedirs, kill
from os.path import basename, splitext, join, isfile, pardir, exists, dirname
from glob import glob
from subprocess import call, check_output, DEVNULL
from tempfile import mkdtemp, NamedTemporaryFile
from socket import socket
from signal import SIGKILL
from urllib.request import (urlopen, build_opener, install_opener,
                            HTTPCookieProcessor, Request)
from time import sleep
from urllib.error import HTTPError


def touch(fname):
    if exists(fname):
        os.utime(fname, None)
    else:
        open(fname, 'a').close()


def patch_file(file_to_patch, patch_name, template=[]):
    with open(patch_name, 'r') as diff_file:
        diff_text = diff_file.read()
        # Patch may need to fill into templates
        if template:
            diff_text = diff_text.format(*template)

    with NamedTemporaryFile('w') as tmp_file:
        tmp_file.write(diff_text)
        tmp_file.flush()

        cmd('patch', [file_to_patch, tmp_file.name], sout=None)


# Some wrappers
def get_ip4_address():
    command = r"""ip addr | grep 'state UP' -A2 | tail -n1 | awk '{print $2}' | cut -f1  -d'/'"""
    output = check_output(command, shell=True).decode('UTF-8')
    if output and output[-1] == '\n':
        output = output[:-1]
    return output


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


def cmd(command, params=[], sout=DEVNULL, env=None):
    print('{0} {1}'.format(command, ' '.join(params)))
    ret = call([command] + params, stdout=sout, env=env)
    if ret != 0:
        print('Returned [{0}]'.format(ret))
    return ret


def cmd_checked(command, params=[], sout=DEVNULL, env=None):
    if cmd(command, params, sout, env) != 0:
        print('It failed! Bye!')
        sys.exit(0)


class Project:
    """A class encapsulating getting and building project"""
    # HACK
    pre_inst_dir = '/tmp'

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

    def build_all(self):
        def build_proj(proj):
            if not isfile(proj.get_arch_name()):
                proj.download()
            proj.unpack()
            chdir(proj.get_unpack_dir())
            proj.configure()
            cmd_checked('make')
            cmd_checked('make', ['install'])

        proj = self._get_next()
        while proj:
            build_proj(proj)
            proj.ready = True
            proj = self._get_next()

        if not all(proj.ready for proj in self.projects):
            print("Failed to resolve projects")


def install_pkgs(pkgs_to_check):
    print("Check and install required packages")
    for pkg in pkgs_to_check:

        if not pkg_is_installed(pkg):
            print('{0} is not installed.'.format(pkg))
            ret = pkg_install(pkg)
            print('Result {0}.'.format(ret))
        else:
            print('{0} is installed.'.format(pkg))


def prepare_autotools_projects(skip=False):
    apr = Project(name='apr',
                  url='http://apache.miloslavbrada.cz/apr/apr-1.5.2.tar.bz2',
                  dependencies=[])
    apr_util = Project(name='apr-util',
                       url='http://apache.miloslavbrada.cz/apr/apr-util-1.5.4.tar.bz2',  # noqa
                       dependencies=[apr])
    apache = Project(name='apache',
                     url='http://apache.miloslavbrada.cz/httpd/httpd-2.4.25.tar.bz2',  # noqa
                     dependencies=[apr, apr_util])

    if not skip:
        pBuild = ProjectBuilder([apache, apr, apr_util])
        pBuild.build_all()

    return {'apache': apache}


def prepare_mod_cluster(work_dir, apache):
    ######################################
    # get, patch, build and install mod_cluster
    ######################################
    cmd('git', ['clone', 'https://github.com/modcluster/mod_cluster.git'])
    chdir('mod_cluster')
    cmd('git', ['checkout', 'origin/1.3.x', '-b', '1.3.x'])
    chdir('native')

    # Patching mod_cluster version to show apache banner
    # chdir('mod_manager')
    patch_file(join('mod_manager', 'mod_manager.c'),
               join(work_dir, 'diffs', 'banner_patch.diff'))
    # chdir(pardir)

    # build & install
    for mod in ['mod_proxy_cluster',
                'mod_manager',
                'mod_cluster_slotmem',
                'advertise']:
        print('Building mod: {0}'.format(mod))
        chdir(mod)
        cmd_checked('./buildconf')
        cmd_checked('./configure',
                    ['--with-apxs={0}'.format(join(apache.get_install_dir(),
                                                   'bin', 'apxs'))])
        cmd_checked('make')
        cmd_checked('libtool',
                    ['--finish', join(apache.get_install_dir(), 'modules')])

        # `make install' does nothing; do `cp' instead
        cmd_checked('cp',
                    glob('*.so') + [join(apache.get_install_dir(), 'modules')])
        chdir(pardir)

    # Get mod_cluster config file
    url = 'https://gist.githubusercontent.com/Karm/85cf36a52a8c203accce/raw/a41ecc90fea1f2b3bb880e79fa67fb6c7f61cf68/mod_cluster.conf'  # noqa
    # Don't get the file again if it's already around
    if not exists(basename(url)):
        cmd_checked('wget', ['--quiet', url, '-O', basename(url)])
    extra_conf_path = join(apache.get_install_dir(),
                           'conf', 'extra', basename(url))
    cmd_checked('cp', [basename(url), extra_conf_path])

    # Update mod_cluster config file
    cache_dir = join(apache.get_install_dir(), 'cache')
    if not exists(cache_dir):
        makedirs(cache_dir)
    cmd_checked('sed',
                ['-i',
                 's@MemManagerFile /opt/DU/httpd-build/cache/mod_cluster@MemManagerFile {0}@'  # noqa
                 .format(join(cache_dir, 'mod_cluster')),
                 extra_conf_path])

    # Move from mod_cluster/native to mod_cluster and build it's java libraries
    chdir(pardir)
    cmd_checked('mvn', ['package', '-DskipTests'])


if __name__ == '__main__':

    WORK_DIR = getcwd()

    PKGS_TO_CHECK = ['wget', 'gcc', 'bzip2', 'pcre-devel', 'git', 'maven',
                     'autoconf', 'libtool', 'patch']

    TMP_DIR = mkdtemp()
    SKIP = False

    # Setting just for testing...
    PKGS_TO_CHECK = []
    TMP_DIR = getcwd()
    Project.pre_inst_dir = join('/', 'tmp', 'usr', 'local')
    #SKIP = True

    install_pkgs(PKGS_TO_CHECK)

    print("Changing to {0}".format(TMP_DIR))
    chdir(TMP_DIR)

    cmd('killall', ['java', 'httpd'])

    PROJECTS = prepare_autotools_projects(SKIP)
    chdir(TMP_DIR)
    prepare_mod_cluster(WORK_DIR, PROJECTS['apache'])

    # Update apache config file
    conf_path = join(PROJECTS['apache'].get_install_dir(),
                     'conf', 'httpd.conf')
    patch_file(conf_path, join(WORK_DIR, 'diffs', 'httpd_patch.diff'))

    # Get and build jboss logging
    chdir(pardir)
    cmd('git', ['clone', 'https://github.com/jboss-logging/jboss-logging.git'])
    chdir('jboss-logging')
    cmd_checked('mvn', ['package', '-DskipTests'])

    chdir(pardir)

    # Get and build clusterbench
    cmd('git', ['clone', 'https://github.com/Karm/clusterbench.git'])
    chdir('clusterbench')
    cmd('git', ['checkout', 'origin/simplified-and-pure', '-b', 'sp'])
    cmd('mvn', ['clean', 'install', '-Pee6', '-DskipTests'])

    chdir(pardir)

    # Get and unpack tomcat
    turl = 'https://archive.apache.org/dist/tomcat/tomcat-7/v7.0.73/bin/apache-tomcat-7.0.73.tar.gz'  # noqa
    if not exists(basename(turl)):
        cmd('wget', ['--quiet', turl])
    cmd('tar', ['xzf', basename(turl)])
    tomcat_dir = splitext(splitext(basename(turl))[0])[0]

    # Install mod_cluster and jboss logging into tomcat
    cmd_checked('cp', [
        join('mod_cluster', 'container', 'tomcat8', 'target',
             'mod_cluster-container-tomcat8-1.3.6.Final-SNAPSHOT.jar'),
        join('mod_cluster', 'container', 'catalina-standalone', 'target',
             'mod_cluster-container-catalina-standalone-1.3.6.Final-SNAPSHOT.jar'),  # noqa
        join('mod_cluster', 'container', 'catalina', 'target',
             'mod_cluster-container-catalina-1.3.6.Final-SNAPSHOT.jar'),
        join('mod_cluster', 'core', 'target',
             'mod_cluster-core-1.3.6.Final-SNAPSHOT.jar'),
        join('mod_cluster', 'container-spi', 'target',
             'mod_cluster-container-spi-1.3.6.Final-SNAPSHOT.jar'),
        join('jboss-logging', 'target',
             'jboss-logging-3.3.1.Final-SNAPSHOT.jar'),
        join(tomcat_dir, 'lib')])

    # Install clusterbench into tomcat
    cmd_checked('cp', [join('clusterbench', 'clusterbench-ee6-web',
                            'target', 'clusterbench.war'),
                       join(tomcat_dir, 'webapps')])

    ip_address = get_ip4_address()

    patch_file(join(tomcat_dir, 'conf', 'server.xml'),
               join(WORK_DIR, 'diffs', 'tomcat1_patch.diff'),
               template=[ip_address, 'tomcat1'])

    apache_tomcat_inst_dir_1 = join(Project.pre_inst_dir, tomcat_dir)

    # Copy tomcat to the same directory as apache
    cmd('cp', ['-r', tomcat_dir, Project.pre_inst_dir])

    patch_file(join(tomcat_dir, 'conf', 'server.xml'),
               join(WORK_DIR, 'diffs', 'tomcat2_patch.diff'),
               template=[ip_address, 'tomcat1', 'tomcat2'])

    apache_tomcat_inst_dir_2 = join(Project.pre_inst_dir, 'at2')
    if not exists(apache_tomcat_inst_dir_2):
        makedirs(apache_tomcat_inst_dir_2)

    # Copy 2nd tomcat to the same directory as apache
    chdir(tomcat_dir)
    cmd('cp', ['-r'] + glob('*') + [apache_tomcat_inst_dir_2])
    chdir(pardir)

    # Set firewall - just for now
    cmd_checked('firewall-cmd', ['--add-service=http'])
    cmd_checked('firewall-cmd', ['--add-port=6666/tcp'])
    cmd_checked('firewall-cmd', ['--add-port=8009/tcp'])
    cmd_checked('firewall-cmd', ['--add-port=8080/tcp'])
    cmd_checked('firewall-cmd', ['--add-port=8081/tcp'])
    cmd_checked('firewall-cmd', ['--add-port=23364/tcp'])
    cmd_checked('firewall-cmd', ['--add-port=23364/udp'])

    cmd('setenforce', ['0'])

    # (re)Start apache
    cmd_checked(join(PROJECTS['apache'].get_install_dir(),
                     'bin', 'apachectl'), ['start'])

    APACHE1_TOMCAT_PID_PATH = join(apache_tomcat_inst_dir_1, 'pids', 'pid')
    APACHE2_TOMCAT_PID_PATH = join(apache_tomcat_inst_dir_2, 'pids', 'pid')

    if not exists(dirname(APACHE1_TOMCAT_PID_PATH)):
        makedirs(dirname(APACHE1_TOMCAT_PID_PATH))
    if not exists(dirname(APACHE2_TOMCAT_PID_PATH)):
        makedirs(dirname(APACHE2_TOMCAT_PID_PATH))

    touch(APACHE1_TOMCAT_PID_PATH)
    touch(APACHE2_TOMCAT_PID_PATH)

    # Start tomcat
    cmd_checked(join(apache_tomcat_inst_dir_1, 'bin', 'catalina.sh'),
                ['start'],
                env={**dict(os.environ), 'CATALINA_PID': APACHE1_TOMCAT_PID_PATH})
    cmd_checked(join(apache_tomcat_inst_dir_2, 'bin', 'catalina.sh'),
                ['start'],
                env={**dict(os.environ), 'CATALINA_PID': APACHE2_TOMCAT_PID_PATH})


    def get_jvm_route(f):
        data = f.read().decode('utf-8')
        fields = {}
        for line in data.split('\n'):
            idx = line.find(':')
            if idx != -1 and line[:idx].strip() == 'JVM route':
                return line[idx+1:].strip()
        return None


    CLUSTERBENCH_URL = 'http://{0}:6666/clusterbench/requestinfo'\
                       .format(ip_address)
    # Use session cookie
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    install_opener(opener)
    
    req = Request(url=CLUSTERBENCH_URL)

    TIMEOUT = 120
    # Be sure that server is up    
    for i in range(TIMEOUT):
        #with urlopen(req) as f:
        try:
            f = urlopen(req)
            if f.getcode() == 200:
                jvm_route = get_jvm_route(f)
                f.close()
                break
        except HTTPError as e:
            sleep(1)
            print('Waiting for server...{0} - {1}'.format(TIMEOUT-i, e.code))
    else:
        assert False, "Server is not up."

    for i in range(5):
        with urlopen(req) as f:
            assert f.getcode() == 200
            # session cookies do work
            assert get_jvm_route(f) == jvm_route

    # kill tomcat
    if jvm_route == 'tomcat1':
        fname = APACHE1_TOMCAT_PID_PATH
        exp_jvm_route = 'tomcat2'
    else:
        fname = APACHE2_TOMCAT_PID_PATH
        exp_jvm_route = 'tomcat1'

    with open(fname, 'r') as f:
        pid = int(f.read())
        kill(pid, SIGKILL)

    # check that new tomcat is used
    with urlopen(req) as f:
        assert f.getcode() == 200
        assert get_jvm_route(f) == exp_jvm_route
