#!/usr/bin/python3

# todo env

from glob import glob
from sys import exit
from subprocess import call, check_output
from tempfile import mkdtemp, NamedTemporaryFile
from os import chdir, getcwd, makedirs
from os.path import basename, splitext, join, isfile, pardir, exists

try:
    from subprocess import DEVNULL  # py3k
except ImportError:
    import os
    DEVNULL = open(os.devnull, 'wb')


use_tmp_dir = False


def patch_file(path_to_file, patch_text):
    patch_file = NamedTemporaryFile('w')
    patch_file.write(patch_text)
    patch_file.flush()
    cmd('patch', [path_to_file, patch_file.name])


# Some wrappers
def get_ip4_address():
    command=r"""ip addr | grep 'state UP' -A2 | tail -n1 | awk '{print $2}' | cut -f1  -d'/'"""
    output = check_output(command, shell=True).decode('UTF-8')
    if len(output) and output[-1] == '\n':
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
pkg_to_check = ['wget', 'gcc', 'bzip2', 'pcre-devel', 'git','maven',
                'autoconf', 'libtool', 'patch']
# HACK
pkg_to_check = []
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
# get, patch, build and install mod_cluster
######################################
cmd('git', ['clone', 'https://github.com/modcluster/mod_cluster.git'])
chdir('mod_cluster')
cmd('git', ['checkout', 'origin/1.3.x', '-b', '1.3.x'])
chdir('native')

# Patching mod_cluster version to show apache banner
banner_path =\
              """
2850c2850
<     ap_rvputs(r, "<h1>", MOD_CLUSTER_EXPOSED_VERSION, "</h1>", NULL);
---
>     ap_rvputs(r, "<h1>", ap_get_server_banner(), "</h1>", NULL);
"""
banner_path_file = NamedTemporaryFile('w')
banner_path_file.write(banner_path)
banner_path_file.flush()

chdir('mod_manager')
cmd('patch', ['mod_manager.c', banner_path_file.name])
chdir(pardir)

# build & install
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
    cmd_checked('cp', glob('*.so') + [join(apache.get_install_dir(), 'modules')])
    chdir(pardir)

# Get mod_cluster config file
url = 'https://gist.githubusercontent.com/Karm/85cf36a52a8c203accce/raw/a41ecc90fea1f2b3bb880e79fa67fb6c7f61cf68/mod_cluster.conf'
# Don't get the file again if it's already around
if not exists(basename(url)):
            cmd_checked('wget', ['--quiet', url, '-O', basename(url)])
extra_conf_path = join(apache.get_install_dir(), 'conf', 'extra', basename(url))
cmd_checked('cp', [basename(url), extra_conf_path])

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
123c123
< #LoadModule proxy_ajp_module modules/mod_proxy_ajp.so
---
> LoadModule proxy_ajp_module modules/mod_proxy_ajp.so
453a454,455
>  
> Include conf/extra/mod_cluster.conf
"""
diff_file = NamedTemporaryFile('w')
diff_file.write(diff_text)
diff_file.flush()
cmd('patch', [conf_path, diff_file.name], sout=None)

# Move from mod_cluster/native  to mod_cluster and build it's java libraries
chdir(pardir)
cmd_checked('mvn', ['package', '-DskipTests'])

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
#turl = 'http://apache.miloslavbrada.cz/tomcat/tomcat-7/v7.0.73/bin/apache-tomcat-7.0.73.tar.gz'
turl = 'https://archive.apache.org/dist/tomcat/tomcat-7/v7.0.73/bin/apache-tomcat-7.0.73.tar.gz'
if not exists(basename(turl)):
    cmd('wget', ['--quiet', turl])
cmd('tar', ['xzf', basename(turl)])
tomcat_dir = splitext(splitext(basename(turl))[0])[0]

# Install mod_cluster and jboss logging into tomcat
cmd('cp', [
    'mod_cluster/container/tomcat8/target/mod_cluster-container-tomcat8-1.3.6.Final-SNAPSHOT.jar',
    'mod_cluster/container/catalina-standalone/target/mod_cluster-container-catalina-standalone-1.3.6.Final-SNAPSHOT.jar',
    'mod_cluster/container/catalina/target/mod_cluster-container-catalina-1.3.6.Final-SNAPSHOT.jar',
    'mod_cluster/core/target/mod_cluster-core-1.3.6.Final-SNAPSHOT.jar',
    'mod_cluster/container-spi/target/mod_cluster-container-spi-1.3.6.Final-SNAPSHOT.jar',
    'jboss-logging/target/jboss-logging-3.3.1.Final-SNAPSHOT.jar',
    join(tomcat_dir, 'lib')])

# Install clusterbench into tomcat
cmd('cp', [join('clusterbench', 'clusterbench-ee6-web','target','clusterbench.war'),
           join(tomcat_dir, 'webapps')])

ip_address = get_ip4_address()

diff_1st_tomcat =\
                  """
34a35,38
>   <Listener className="org.jboss.modcluster.container.catalina.standalone.ModClusterListener"
>             stickySession="true"
>             stickySessionForce="false"
>             stickySessionRemove="true" />
73c77
<                redirectPort="8443" />
---
>                redirectPort="8443" address={0}/>
105c109
<     <Engine name="Catalina" defaultHost="localhost">
---
>     <Engine name="Catalina" defaultHost="localhost" jvmRoute="tomcat1">
""".format(ip_address)
patch_file(join(tomcat_dir, 'conf', 'server.xml'), diff_1st_tomcat)

apache_tomcat_inst_dir_1 =  join(Project.pre_inst_dir, tomcat_dir)

# Copy tomcat to the same directory as apache
cmd('cp', ['-r', tomcat_dir, Project.pre_inst_dir])


diff_2nd_tomcat =\
                  """
22c22
< <Server port="8005" shutdown="SHUTDOWN">
---
> <Server port="8006" shutdown="SHUTDOWN">
75c75
<     <Connector port="8080" protocol="HTTP/1.1"
---
>     <Connector port="8081" protocol="HTTP/1.1"
97c97
<     <Connector port="8009" protocol="AJP/1.3" redirectPort="8443" />
---
>     <Connector port="8010" protocol="AJP/1.3" redirectPort="8443" />
109c109
<     <Engine name="Catalina" defaultHost="localhost" jvmRoute="tomcat1">
---
>     <Engine name="Catalina" defaultHost="localhost" jvmRoute="tomcat2">
""".format(ip_address)

patch_file(join(tomcat_dir, 'conf', 'server.xml'), diff_2nd_tomcat)

#
apache_tomcat_inst_dir_2 =  join(Project.pre_inst_dir, 'at2')
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

# (re)Start apache
cmd_checked(join(apache.get_install_dir(), 'bin', 'apachectl'), ['restart'])

# Start tomcat
cmd_checked(join(apache_tomcat_inst_dir_1, 'bin', 'catalina.sh'), ['start'])
cmd_checked(join(apache_tomcat_inst_dir_2, 'bin', 'catalina.sh'), ['start'])

#remove
# 93c97
# <     <Connector port="8009" protocol="AJP/1.3" redirectPort="8443" />
# ---
# >     <Connector port="8009" protocol="AJP/1.3" redirectPort="8443" address="172.28.128.6"/>

# <     <Connector port="8009" protocol="AJP/1.3" redirectPort="8443" address="172.28.128.6"/>
# < 
# ---
# >     <Connector port="8010" protocol="AJP/1.3" redirectPort="8443" address="172.28.128.6"/>
#                   """
# 35c35,39
# < 
# ---
# >   <Listener className="org.jboss.modcluster.container.catalina.standalone.ModClusterListener"
# > 	    stickySession="true"
# > 	    stickySessionForce="false"
# > 	    stickySessionRemove="true"
# > 	    />
# 98c98
# <     <Connector port="8010" protocol="AJP/1.3" redirectPort="8443" />
# ---
# >     <Connector port="8010" protocol="AJP/1.3" redirectPort="8443" address={0} />
# 105c109
# <     <Engine name="Catalina" defaultHost="localhost">
# ---
# >     <Engine name="Catalina" defaultHost="localhost" jvmRoute="tomcat1">
# 22c22
# < <Server port="8005" shutdown="SHUTDOWN">
# ---
# > <Server port="8006" shutdown="SHUTDOWN">
# 39a40
# > 
# 75c76
# <     <Connector port="8080" protocol="HTTP/1.1 "
# ---
# >     <Connector port="8081" protocol="HTTP/1.1 "
# 97,98c98
# <     <Connector port="8009" protocol="AJP/1.3" redirectPort="8443" address={0} />
# < 
# ---
# >     <Connector port="8010" protocol="AJP/1.3" redirectPort="8443" address={0} />
# 109c109
# <     <Engine name="Catalina" defaultHost="localhost" jvmRoute="tomcat1">
# ---
# >     <Engine name="Catalina" defaultHost="localhost" jvmRoute="tomcat2">
