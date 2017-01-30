#!/usr/bin/python3

# todo env

import sys
import os
from glob import glob
from subprocess import call, check_output
from tempfile import mkdtemp, NamedTemporaryFile
from os import chdir, getcwd, makedirs
from os.path import basename, splitext, join, isfile, pardir, exists
from socket import socket

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    import os
    DEVNULL = open(os.devnull, 'wb')


class Connection:
    """A simple connection class"""

    def __init__(self, server, port, path):
        self.server = server
        self.port = port
        self.path = path
        self.sc = None

    def send_req_get_body(self):
        addr = self.server, self.port
        req = "GET {0} HTTP/1.1\r\nHost: {1}\r\n".format(self.path,
                                                         self.server)

        if self.sc:
            req = req + 'Cookie: {0}\r\n'.format(self.sc)

        req = req + '\r\n'

        s = socket()
        r = s.connect(addr)
        req_len = s.send(req.encode())

        resp = s.recv(4096).decode()

        headers = True
        body = []

        for line in resp.split('\n'):
            if line == '\r':  # End of headers
                headers = False
            if headers:
                if line.find(':') != -1:
                    tmp = line.split(':')
                    name, value = tmp[0], tmp[1]
                    if name.lower() == 'set-cookie' and\
                       value.lower().find('expires=') == -1:
                        self.sc = value
            else:
                body.append(line)
        return body


def patch_file(path_to_file, patch_name, format=[]):
    with open(patch_name, 'r') as patch_file:
        patch_text = patch_file.read()
        # Patch may need to fill into templates
        if format:
            patch_text = patch_text.format(*format)

    with NamedTemporaryFile('w') as tmp_file:
        tmp_file.write(patch_text)
        tmp_file.flush()

        cmd('patch', [path_to_file, tmp_file.name], sout=None)


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


def cmd(command, params=[], sout=DEVNULL):
    print('{0} {1}'.format(command, ' '.join(params)))
    ret = call([command] + params, stdout=sout)
    if ret != 0:
        print('Returned [{0}]'.format(ret))
    return ret


def cmd_checked(command, params=[], sout=DEVNULL):
    if cmd(command, params, sout) != 0:
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

    def _build_proj(self, proj):
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

    work_dir = getcwd()

    pkgs_to_check = ['wget', 'gcc', 'bzip2', 'pcre-devel', 'git', 'maven',
                     'autoconf', 'libtool', 'patch']

    tmp_dir = mkdtemp()
    skip = False

    # Setting just for testing...
    pkgs_to_check = []
    tmp_dir = getcwd()
    Project.pre_inst_dir = join('/', 'tmp', 'usr', 'local')
    skip = True

    install_pkgs(pkgs_to_check)

    print("Changing to {0}".format(tmp_dir))
    chdir(tmp_dir)

    cmd('killall', ['java', 'httpd'])

    projects = prepare_autotools_projects(skip)
    prepare_mod_cluster(work_dir, projects['apache'])

    # Update apache config file
    conf_path = join(projects['apache'].get_install_dir(),
                     'conf', 'httpd.conf')
    patch_file(conf_path, join(work_dir, 'diffs', 'httpd_patch.diff'))

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
               join(work_dir, 'diffs', 'tomcat1_patch.diff'),
               format=[ip_address])

    apache_tomcat_inst_dir_1 = join(Project.pre_inst_dir, tomcat_dir)

    # Copy tomcat to the same directory as apache
    cmd('cp', ['-r', tomcat_dir, Project.pre_inst_dir])

    patch_file(join(tomcat_dir, 'conf', 'server.xml'),
               join(work_dir, 'diffs', 'tomcat2_patch.diff'),
               format=[ip_address])

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
    cmd_checked(join(projects['apache'].get_install_dir(),
                     'bin', 'apachectl'), ['start'])

    # join(apache_tomcat_inst_dir_1, 'pids', 'pid')
    # if not exists(basename(url)):
    #     cmd_checked('wget', ['--quiet', url, '-O', basename(url)])


    # Start tomcat
    cmd_checked(join(apache_tomcat_inst_dir_1, 'bin', 'catalina.sh'),
                ['start'])
    cmd_checked(join(apache_tomcat_inst_dir_2, 'bin', 'catalina.sh'),
                ['start'])

# # HACK

# opts = {
#     'url': 'http://{0}:6666/clusterbench/requestinfo'.format(get_ip4_address()),
#     'req_num': 10,
#     'print-response': True,
#     'print-request': False,
#     }
# conn = Connection(server=get_ip4_address(),
#                   port=6666,
#                   path='/clusterbench/requestinfo')

# route = None
# # Route is same for all the requests
# for i in range(10):
#     body = conn.send_req_get_body()

#     for line in body:
#         if line.find(':') != -1:
#             p = 'JVM route: '
#             if len(line) > len(p) and line[:len(p)] == p:
#                 tmp = line[len(p):]
#                 if route == None:
#                     route = tmp
#                 elif route != tmp:
#                     print('Unexpected route!')
#                     exit(1)



# #exit(0)
# # in progress - ignore
# import subprocess
# pl = subprocess.Popen(['ps', '-a', '-u', '-x'], stdout=subprocess.PIPE).communicate()[0]
# print(pl)
# exit(1)
