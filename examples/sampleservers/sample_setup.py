#!/usr/bin/env python

#
# $Id$
#
# Author: Thilee Subramaniam
#
# Copyright 2012 Quantcast Corp.
#
# This file is part of Kosmos File System (KFS).
#
# Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.
#
"""
This script helps to set up a simple, local deployment of QFS.
You can write your own config file (start from ./sample_setup.cfg)
and run this script to install, uninstall or upgrade.

./sample_setup.py -c sample_setup.cfg -a install
    -c: config file
    -a: action (one of install, start, stop, uninstall)
    -b: distribution directory
    -s: source directory

The script sets up the servers' config files as follows.
(By default it installs all this in ~/qfsbase, set in the config file.)

meta-run-dir/checkpoints/
                        /logs/
                        /conf/MetaServer.prp
                        /metaserver.log
                        /metaserver.out

chunk-run-dir/chunkserver1/chunks/
                          /conf/ChunkServer.prp
                          /chunkserver.log
                          /chunkserver.out
             /chunkserver2/chunks/
                          /conf/ChunkServer.prp
                          /chunkserver.log
                          /chunkserver.out

webui-run-dir/docroot/
             /conf/WebUI.cfg
             /webui.log
"""

import sys, os, os.path, shutil, errno, signal, posix, re, socket
import ConfigParser
import subprocess
import getpass

from optparse import OptionParser, OptionGroup, IndentedHelpFormatter

class Globals():
    METASERVER  = 'metaserver'
    CHUNKSERVER = 'chunkserver'
    WEBSERVER   = 'qfsstatus.py'
    QFSTOOL     = None
    MKCERTS     = None

def get_size_in_bytes(str):
    if not str:
        return 0
    pos = 0
    while pos < len(str) and not str[pos].isalpha():
        pos = pos + 1
    if pos >= len(str):
        return int(str)
    val = int(str[0:pos])
    unit = str[pos]
    mul = 1
    if unit in ('k', 'K'):
        mul = 1000
    elif unit in ('m', 'M'):
        mul = 1000000
    elif unit in ('g', 'G'):
        mul = 1000000000
    return val * mul

def shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"

def check_binaries(releaseDir, sourceDir, authFlag):
    if not os.path.isfile(releaseDir + '/bin/metaserver'):
        sys.exit('Metaserver missing in build directory')
    Globals.METASERVER = releaseDir + '/bin/metaserver'

    if not os.path.isfile(releaseDir + '/bin/chunkserver'):
        sys.exit('Chunkserver missing in build directory')
    Globals.CHUNKSERVER = releaseDir + '/bin/chunkserver'

    if os.path.isfile(releaseDir + '/bin/tools/qfs'):
        Globals.QFSTOOL = releaseDir + '/bin/tools/qfs'

    if os.path.isfile(releaseDir + '/webui/qfsstatus.py'):
        Globals.WEBSERVER = releaseDir + '/webui/qfsstatus.py'
    elif os.path.isfile(sourceDir + '/webui/qfsstatus.py'):
        Globals.WEBSERVER = sourceDir + '/webui/qfsstatus.py'
    else:
        sys.exit('Webserver missing in build and source directories')
    if authFlag:
        mkcerts = sourceDir + '/src/test-scripts/qfsmkcerts.sh'
        if os.path.isfile(mkcerts):
            Globals.MKCERTS = mkcerts
        else:
            sys.exit('qfsmkcerts.sh missing in source directories')
    print 'Binaries presence checking - OK.'

def check_port(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('localhost', port))
        del s
    except socket.error, err:
        sys.exit('aborting, port %d already in use (%s)' % (port, str(err)))

def check_ports(config):
    portsToCheck = []
    portsToCheck.append(config.getint('metaserver', 'clientport'))
    portsToCheck.append(config.getint('metaserver', 'chunkport'))
    portsToCheck.append(config.getint('webui', 'webport'))
    for section in config.sections():
        if section.startswith('chunkserver'):
            portsToCheck.append(config.getint(section, 'chunkport'))
    for p in portsToCheck:
        check_port(p)


def kill_running_program_pid(binaryPath, runDir):
    if binaryPath == Globals.METASERVER:
        name = 'metaserver'
    elif binaryPath == Globals.CHUNKSERVER:
        name = 'chunkserver'
    elif binaryPath == Globals.WEBSERVER:
        name = 'webui'
    else:
        name = ''
    if 0 < len(name) and 0 < len(runDir):
        try:
            pidf = '%s/%s.pid' % (runDir, name)
            f = open(pidf, 'r')
            line = f.readline()
            f.close()
            os.unlink(pidf)
            pid = int(line.strip())
            os.kill(pid, signal.SIGTERM)
        except:
            pass
    else:
        kill_running_program(binaryPath)

def kill_running_program(binaryPath):
    if sys.platform in ('darwin', 'Darwin'):
        checkPath = os.path.split(binaryPath)[1]
        if not checkPath:
            return
        cmd = ('ps -ef | grep %s | grep %s | grep -v grep | awk \'{print $2}\''
               % (os.getlogin(), checkPath))
        res = subprocess.Popen(cmd, shell=True,
                               stdout=subprocess.PIPE).communicate()
        pids = res[0].split('\n')
        for pid in pids:
            if pid.strip() != '':
                os.kill(int(pid.strip()), signal.SIGTERM)
    else:
        if binaryPath.find('qfsstatus') >= 0:
            cmd = ('ps -ef | grep %s | grep /qfsbase/ | grep %s | grep -v grep | awk \'{print $2}\''
                   % (os.getlogin(), binaryPath))
            res = subprocess.Popen(cmd, shell=True,
                                   stdout=subprocess.PIPE).communicate()
            pids = res[0].split('\n')
            for pid in pids:
                if pid.strip() != '':
                    os.kill(int(pid.strip()), signal.SIGTERM)
            return

        pids = subprocess.Popen(['pidof', binaryPath],
                                stdout=subprocess.PIPE).communicate()
        for pid in pids[0].strip().split():
            os.kill(int(pid), signal.SIGTERM)


def run_command(cmd):
    return subprocess.check_call(cmd, shell=True)

def rm_tree(path):
    if '/qfsbase/' in path:
        shutil.rmtree(path)
    else:
        print >> sys.stderr, 'refusing to remove path %r' % path,
        print >> sys.stderr, 'because it does not contain /qfsbase/'

def duplicate_tree(src, dst):
    """Copy files & directories from SRC directory to DST directory.

    If DST does not exist, create it. If DST's children with same SRC
    children names exist then overwrite them.
    """
    if os.path.exists(dst) and not os.path.isdir(dst):
        sys.exit('Cannot duplicate directory to a non-directory')

    if not os.path.exists(dst):
        os.makedirs(dst)

    for li in os.listdir(src):
        srcPath = os.path.join(src, li)
        dstPath = os.path.join(dst, li)

        if os.path.isdir(dstPath):
            rm_tree(dstPath)
        else:
            if os.path.exists(dstPath):
                os.unlink(dstPath)

        if os.path.isdir(srcPath):
            shutil.copytree(srcPath, dstPath)
        else:
            shutil.copyfile(srcPath, dstPath)

def mkdir_p(dirname):
    try:
        os.makedirs(dirname)
    except OSError, err:
        if err.errno != errno.EEXIST:
            sys.exit('Failed to create directory')
        else:
            if not os.path.isdir(dirname):
                sys.exit('% exists, but is not a directory!' % dirname)

def parse_command_line():
    action_keys = { 'install'   : True,
                    'start'     : True,
                    'stop'      : True,
                    'uninstall' : True }

    argv0Dir = os.path.dirname(sys.argv[0])

    defaultConfig = os.path.join(argv0Dir, 'sample_setup.cfg')
    defaultConfig = os.path.abspath(defaultConfig)

    defaultSrcDir = os.path.join(argv0Dir, '../..')
    defaultSrcDir = os.path.abspath(defaultSrcDir)

    #defaultRelDir = os.path.join(argv0Dir, '../../build/release')
    defaultRelDir = os.path.join(argv0Dir, '../../build/debug')
    defaultRelDir = os.path.abspath(defaultRelDir)

    if not os.path.exists(defaultRelDir):
        defaultRelDir = os.path.join(argv0Dir, '../..')
        defaultRelDir = os.path.abspath(defaultRelDir)

    formatter = IndentedHelpFormatter(max_help_position=50, width=120)
    usage = "usage: ./%prog [options] -a <ACTION>"
    parser = OptionParser(usage, formatter=formatter, add_help_option=False)

    parser.add_option('-c', '--config-file', action='store',
        default=defaultConfig, metavar='FILE', help='Setup config file.')

    parser.add_option('-a', '--action', action='store', default=None,
        metavar='ACTION', help='One of install, uninstall, or stop.')

    parser.add_option('-r', '--release-dir', action='store',
        default=defaultRelDir, metavar='DIR', help='QFS release directory.')

    parser.add_option('-s', '--source-dir', action='store',
        default=defaultSrcDir, metavar='DIR', help='QFS source directory.')

    parser.add_option('-u', '--auth', action='store_true',
        help="Configure QFS authentication.")

    parser.add_option('-h', '--help', action='store_true',
        help="Print this help message and exit.")

    actions = """
Actions:
  install   = setup meta and chunk server directories, restarting/starting them
  start     = start meta and chunk servers
  stop      = stop meta and chunk servers
  uninstall = remove meta and chunk server directories after stopping them"""

    sampleSession = """
Hello World example of a client session:
  # Install sample server setup, only needed once.
  %s/examples/sampleservers/sample_setup.py -a install
  PATH="%s:${PATH}"
  # Make temp directory.
  qfsshell -s localhost -p 20000 -q -- mkdir /qfs/tmp
  # Create file containing Hello World, Reed-Solomon encoded, replication 1.
  echo 'Hello World' \
| cptoqfs -s localhost -p 20000 -S -r 1 -k /qfs/tmp/helloworld -d -
  # Cat file content.
  qfscat -s localhost -p 20000 /qfs/tmp/helloworld
  # Stat file to see encoding (RS or not), replication level, mtime.
  qfsshell -s localhost -p 20000 -q -- stat /qfs/tmp/helloworld
  # Copy file locally to current directory.
  cpfromqfs -s localhost -p 20000 -k /qfs/tmp/helloworld -d ./helloworld
  # Remove file from QFS.
  qfsshell -s localhost -p 20000 -q -- rm /qfs/tmp/helloworld
  # Stop the server and remove the custom install.
  %s/examples/sampleservers/sample_setup.py -a stop
  %s/examples/sampleservers/sample_setup.py -a uninstall

Use qfs to manipulate files the same way you would use 'hadoop fs':
  # Set qfs command alias.
  alias qfs='%s/bin/tools/qfs -cfg ~/qfsbase/client/clidefault.prp'

  qfs -h
  qfs -stat /
  qfs -mkdir /some-dir
  qfs -ls /

  Did you notice how fast it is? :)

Run the following to test with hadoop:
    %s/src/test-scripts/qfshadoop.sh
"""

    # An install sets up all config files and (re)starts the servers.
    # An uninstall stops the servers and removes the config files.
    # A stop stops the servers.
    opts, args = parser.parse_args()
    sampleSession = sampleSession % (
        opts.source_dir,
        opts.release_dir,
        opts.source_dir,
        opts.source_dir,
        opts.release_dir,
        opts.source_dir
    )

    if opts.help:
        parser.print_help()
        print actions
        print sampleSession
        print
        posix._exit(0)

    e = []
    if not os.path.isfile(opts.config_file):
        e.append("specified 'config-file' does not exist: %s"
                 % opts.config_file)

    if not opts.action:
        e.append("'action' must be specified")
    elif not action_keys.has_key(opts.action):
        e.append("invalid 'action' specified: %s" % opts.action)

    if not os.path.isdir(opts.release_dir):
        e.append("specified 'release-dir' does not exist: %s"
                 % opts.release_dir)

    if not os.path.isdir(opts.source_dir):
        e.append("specified 'source-dir' does not exist: %s" % opts.source_dir)

    if len(e) > 0:
        parser.print_help()
        print actions
        print sampleSession
        print
        for error in e:
            print "*** %s" % error
        print
        posix._exit(1)

    return opts

def do_cleanup(config, doUninstall):
    if config.has_section('metaserver'):
        metaRunDir = config.get('metaserver', 'rundir')
        if metaRunDir:
            kill_running_program_pid(Globals.METASERVER, metaRunDir)
            if doUninstall and os.path.isdir(metaRunDir):
                rm_tree(metaRunDir)

    for section in config.sections():
        if section.startswith('chunkserver'):
            chunkRunDir = config.get(section, 'rundir')
            if chunkRunDir:
                kill_running_program_pid(Globals.CHUNKSERVER, chunkRunDir)
                if doUninstall and os.path.isdir(chunkRunDir):
                    rm_tree(chunkRunDir)

    if config.has_section('webui'):
        webDir = config.get('webui', 'rundir')
        if webDir:
            kill_running_program_pid(Globals.WEBSERVER, webDir)
            if doUninstall and os.path.isdir(webDir):
                rm_tree(webDir)
    if config.has_section('certs'):
        certsDir = config.get('certs', 'rundir')
        if doUninstall and os.path.isdir(certsDir):
            rm_tree(certsDir)
    if config.has_section('client'):
        clientDir = config.get('client', 'rundir')
        if doUninstall and os.path.isdir(clientDir):
            rm_tree(clientDir)
    if doUninstall:
        qfsbase = os.path.expanduser('~/qfsbase')
        if os.path.isdir(qfsbase) and not os.path.islink(qfsbase):
            os.rmdir(qfsbase)
        print 'Uninstall - OK.'
    else:
        print 'Stop servers - OK.'

def setup_directories(config, authFlag):
    if config.has_section('metaserver'):
        metaRunDir = config.get('metaserver', 'rundir')
        if metaRunDir:
            mkdir_p(metaRunDir);
            mkdir_p(metaRunDir + '/conf')
            mkdir_p(metaRunDir + '/checkpoints')
            mkdir_p(metaRunDir + '/logs')

    for section in config.sections():
        if section.startswith('chunkserver'):
            chunkRunDir = config.get(section, 'rundir')
            chunkDirs = config.get(section, 'chunkdirs')
            chunkDirsList = chunkDirs.split(' ')  
            if chunkRunDir:
                mkdir_p(chunkRunDir);
                mkdir_p(chunkRunDir + '/conf')
                if len(chunkDirsList) > 0:
                    for cd in chunkDirsList:
                        mkdir_p(cd)
                else:
                    mkdir_p(chunkRunDir + '/chunkdir')

    if config.has_section('client'):
        clientDir = config.get('client', 'rundir')
        if clientDir:
            mkdir_p(clientDir)

    if config.has_section('webui'):
        webDir = config.get('webui', 'rundir')
        if webDir:
            mkdir_p(webDir);
            mkdir_p(webDir + '/conf')
            mkdir_p(webDir + '/docroot')
    print 'Setup directories - OK.'


def check_directories(config):
    metaRunDir = None
    webDir = None
    if config.has_section('metaserver'):
        metaRunDir = config.get('metaserver', 'rundir')
    if config.has_section('webui'):
        webDir = config.get('webui', 'rundir')
    if not metaRunDir or not webDir:
        sys.exit('Malformed config file.')
    if not os.path.exists(metaRunDir) or not os.path.exists(webDir): 
        sys.exit('Cannot start without install. Please run with "-a install" first.')
    print 'Check directories - OK.'


def setup_config_files(config, authFlag):
    if config.has_section('client'):
        clientDir = config.get('client', 'rundir')
    else:
        clientDir = None
    if authFlag:
        if 'certs' not in config.sections():
            sys.exit('Required metaserver certs not found in config')
        certsDir =  config.get('certs', 'rundir')
        if not certsDir:
            sys.exit('Required certs certsdir not found in config')
        defaultUser = getpass.getuser()
        if run_command('%s %s meta root %s' % (
                shell_quote(Globals.MKCERTS),
                shell_quote(certsDir),
                shell_quote(defaultUser))) != 0:
            sys.exit('Create X509 certs failure')
        if clientDir:
            clientFile = open(clientDir + '/client.prp', 'w')
            print >> clientFile, 'client.auth.X509.X509PemFile = %s/%s.crt' % (certsDir, defaultUser)
            print >> clientFile, 'client.auth.X509.PKeyPemFile = %s/%s.key' % (certsDir, defaultUser)
            print >> clientFile, 'client.auth.X509.CAFile      = %s/qfs_ca/cacert.pem' % certsDir
            clientFile.close()
    if clientDir:
        defaultConfig = clientDir + '/clidefault.prp'
        clientFile = open(defaultConfig, 'w')
        print >> clientFile, 'fs.default = qfs://localhost:20000'
        if authFlag:
            print >> clientFile, 'client.auth.X509.X509PemFile = %s/%s.crt' % (certsDir, defaultUser)
            print >> clientFile, 'client.auth.X509.PKeyPemFile = %s/%s.key' % (certsDir, defaultUser)
            print >> clientFile, 'client.auth.X509.CAFile      = %s/qfs_ca/cacert.pem' % certsDir
        clientFile.close()

    if 'metaserver' not in config.sections():
        sys.exit('Required metaserver section not found in config')
    metaRunDir = config.get('metaserver', 'rundir')
    if not metaRunDir:
        sys.exit('Required metaserver rundir not found in config')

    metaserverHostname = config.get('metaserver', 'hostname')
    metaserverClientPort = config.getint('metaserver', 'clientport')
    metaserverChunkPort = config.getint('metaserver', 'chunkport')
    clusterKey = config.get('metaserver', 'clusterkey')

    # Metaserver.
    metaFile = open(metaRunDir + '/conf/MetaServer.prp', 'w')
    print >> metaFile, 'metaServer.clientPort = %d' % metaserverClientPort
    print >> metaFile, 'metaServer.chunkServerPort = %d' % metaserverChunkPort
    print >> metaFile, 'metaServer.clusterKey = %s' % clusterKey
    print >> metaFile, 'metaServer.cpDir = %s/checkpoints' % metaRunDir
    print >> metaFile, 'metaServer.logDir = %s/logs' % metaRunDir
    print >> metaFile, 'metaServer.fileSystemIdRequired = 0'
    print >> metaFile, 'metaServer.deleteChunkOnFsIdMismatch = 1'
    print >> metaFile, 'metaServer.recoveryInterval = 1'
    #subrata: add start
    print >> metaFile, 'metaServer.serverDownReplicationDelay = 15'
    print >> metaFile, 'metaServer.chunkServer.replicationTimeout = 3600'
    print >> metaFile, 'metaServer.chunkServer.requestTimeout = 3600'
    #subrata: add end
    print >> metaFile, 'metaServer.msgLogWriter.logLevel = DEBUG'
    print >> metaFile, 'metaServer.msgLogWriter.maxLogFileSize = 1e6'
    print >> metaFile, 'metaServer.msgLogWriter.maxLogFiles = 10'
    print >> metaFile, 'metaServer.minChunkservers = 1'
    print >> metaFile, 'metaServer.clientThreadCount = 4'
    print >> metaFile, 'metaServer.rootDirUser = %d' % os.getuid()
    print >> metaFile, 'metaServer.rootDirGroup = %d' % os.getgid()
    print >> metaFile, 'metaServer.rootDirMode = 0777'
    print >> metaFile, 'metaServer.pidFile = %s/metaserver.pid' % metaRunDir
    if authFlag:
        print >> metaFile, 'metaServer.clientAuthentication.X509.X509PemFile = %s/meta.crt' % certsDir
        print >> metaFile, 'metaServer.clientAuthentication.X509.PKeyPemFile = %s/meta.key' % certsDir
        print >> metaFile, 'metaServer.clientAuthentication.X509.CAFile      = %s/qfs_ca/cacert.pem' % certsDir
        print >> metaFile, 'metaServer.clientAuthentication.whiteList        = %s root' % defaultUser
        print >> metaFile, 'metaServer.CSAuthentication.X509.X509PemFile     = %s/meta.crt' % certsDir
        print >> metaFile, 'metaServer.CSAuthentication.X509.PKeyPemFile     = %s/meta.key' % certsDir
        print >> metaFile, 'metaServer.CSAuthentication.X509.CAFile          = %s/qfs_ca/cacert.pem' % certsDir
        print >> metaFile, 'metaServer.CSAuthentication.blackList            = none'
    metaFile.close()

    # Chunkservers.
    for section in config.sections():
        if section.startswith('chunkserver'):
            chunkClientPort = config.getint(section, 'chunkport')
            chunkDirs = config.get(section, 'chunkdirs')
            chunkRunDir = config.get(section, 'rundir')
            if chunkRunDir:
                if authFlag:
                    if run_command('%s %s chunk%d' % (
                            shell_quote(Globals.MKCERTS),
                            shell_quote(certsDir),
                            chunkClientPort)) != 0:
                        sys.exit('Create X509 failure')
                chunkFile = open(chunkRunDir + '/conf/ChunkServer.prp', 'w')
                print >> chunkFile, 'chunkServer.metaServer.hostname = %s' % metaserverHostname
                print >> chunkFile, 'chunkServer.metaServer.port = %d' % metaserverChunkPort
                print >> chunkFile, 'chunkServer.clientPort = %d' % chunkClientPort
                print >> chunkFile, 'chunkServer.clusterKey = %s' % clusterKey
                print >> chunkFile, 'chunkServer.rackId = 0'
                print >> chunkFile, 'chunkServer.chunkDir = %s' % chunkDirs
                print >> chunkFile, 'chunkServer.diskIo.crashOnError = 1'
                print >> chunkFile, 'chunkServer.abortOnChecksumMismatchFlag = 1'
                print >> chunkFile, 'chunkServer.msgLogWriter.logLevel = DEBUG'
                print >> chunkFile, 'chunkServer.msgLogWriter.maxLogFileSize = 1e6'
                print >> chunkFile, 'chunkServer.msgLogWriter.maxLogFiles = 2'
                print >> chunkFile, 'chunkServer.pidFile = %s/chunkserver.pid' % chunkRunDir
                print >> chunkFile, 'chunkServer.clientThreadCount = 0'
                #print >> chunkFile, 'chunkServer.doNotUseLRUCacheFlag = 1'   #subrata : this is to control whether in memory cache will be used or not
                if authFlag:
                    print >> chunkFile, 'chunkserver.meta.auth.X509.X509PemFile = %s/chunk%d.crt' % (certsDir, chunkClientPort)
                    print >> chunkFile, 'chunkserver.meta.auth.X509.PKeyPemFile = %s/chunk%d.key' % (certsDir, chunkClientPort)
                    print >> chunkFile, 'chunkserver.meta.auth.X509.CAFile      = %s/qfs_ca/cacert.pem' % certsDir
                chunkFile.close()

    # Webserver.
    if 'webui' not in config.sections():
        return
    webDir = config.get('webui', 'rundir')
    if not webDir:
        return
    webFile = open(webDir + '/conf/WebUI.cfg', 'w')
    print >> webFile, '[webserver]'
    print >> webFile, 'webServer.metaserverHost = %s' % metaserverHostname
    print >> webFile, 'webServer.metaserverPort = %d' % metaserverClientPort
    print >> webFile, 'webServer.host = 0.0.0.0'
    print >> webFile, 'webServer.port = %d' % config.getint('webui', 'webport')
    print >> webFile, 'webServer.docRoot = %s/docroot' % webDir
    print >> webFile, 'webServer.allmachinesfn = /dev/null'
    print >> webFile, 'webServer.displayPorts = True'
    print >> webFile, 'webServer.pidFile = %s/webui.pid' % webDir
    print >> webFile, '[chunk]'
    print >> webFile, 'refreshInterval = 5'
    print >> webFile, 'currentSize = 30'
    print >> webFile, 'currentSpan = 10'
    print >> webFile, 'hourlySize = 30'
    print >> webFile, 'hourlySpan =120'
    print >> webFile, 'daylySize = 24'
    print >> webFile, 'daylySpan = 3600'
    print >> webFile, 'monthlySize = 30'
    print >> webFile, 'monthlySpan = 86400'
    print >> webFile, 'displayPorts = True'
    print >> webFile, 'predefinedHeaders = Buffer-usec-wait-avg&D-Timer-overrun-count&D-Timer-overrun-sec&XMeta-server-location&Client-active&D-Buffer-req-denied-bytes&D-CPU-sys&D-CPU-user&D-Disk-read-bytes&D-Disk-read-count&D-Disk-write-bytes&D-Disk-write-count&Write-appenders&D-Disk-read-errors&D-Disk-write-errors&XMeta-location'
    print >> webFile, 'predefinedChunkDirHeaders = Chunks&Dev-id&Read-bytes&D-Read-bytes&Read-err&D-Read-err&Read-io&D-Read-io&D-Read-time-microsec&Read-timeout&Space-avail&Space-util-pct&Started-ago&Stopped-ago&Write-bytes&D-Write-bytes&Write-err&D-Write-err&Write-io&D-Write-io&D-Write-time-microsec&Write-timeout&Chunk-server&Chunk-dir'
    webFile.close()
    print 'Setup config files - OK.'

def copy_files(config, sourceDir):
    # Currently, only the web CSS stuff need be copied.
    if 'webui' in config.sections():
        webDir = config.get('webui', 'rundir')
        if webDir:
            webDst = webDir + '/docroot'
            webSrc = sourceDir + '/webui/files'
            duplicate_tree(webSrc, webDst)

def start_servers(config, whichServers, createNewFsFlag, authFlag):
    startMeta  = whichServers in ('meta', 'all')
    startChunk = whichServers in ('chunk', 'all')
    startWeb   = whichServers in ('web', 'all')
    errors = 0

    if startMeta:
        startWeb = True
        metaRunDir = config.get('metaserver', 'rundir')
        kill_running_program_pid(Globals.METASERVER, metaRunDir)
        if metaRunDir:
            metaConf = metaRunDir + '/conf/MetaServer.prp'
            metaLog  = metaRunDir + '/MetaServer.log'
            metaOut  = metaRunDir + '/MetaServer.out'
            if createNewFsFlag and \
                    not os.listdir(metaRunDir + '/checkpoints') and \
                    not os.listdir(metaRunDir + '/logs'):
                command = '%s -c %s > %s 2>&1' % (
                                shell_quote(Globals.METASERVER),
                                shell_quote(metaConf),
                                shell_quote(metaOut))
                if run_command(command) > 0:
                    print '*** metaserver failed create empty file system'
                    errors = errors + 1
            if errors == 0:
                command = '%s %s %s > %s 2>&1 &' % (
                                        shell_quote(Globals.METASERVER),
                                        shell_quote(metaConf),
                                        shell_quote(metaLog),
                                        shell_quote(metaOut))
		print command
                if run_command(command) > 0:
                    print '*** metaserver failed to start'
                    errors = errors + 1
                else:
                    print 'Meta server started, listening on %s:%d' %(
                        config.get('metaserver', 'hostname'),
                        config.getint('metaserver', 'clientport'))

    if startChunk:
        for section in config.sections():
            if section.startswith('chunkserver'):
                chunkRunDir = config.get(section, 'rundir')
                kill_running_program_pid(chunkRunDir, chunkRunDir)
                if chunkRunDir:
                    chunkConf = chunkRunDir + '/conf/ChunkServer.prp'
                    chunkLog  = chunkRunDir + '/ChunkServer.log'
                    chunkOut  = chunkRunDir + '/ChunkServer.out'
                    command = '%s %s %s > %s 2>&1 &' % (
                                            shell_quote(Globals.CHUNKSERVER),
                                            shell_quote(chunkConf),
                                            shell_quote(chunkLog),
                                            shell_quote(chunkOut))
		    print command
                    if run_command(command) > 0:
                        print '*** chunkserver failed to start'
                        errors = errors + 1

    if startWeb:
        webDir = config.get('webui', 'rundir')
        kill_running_program_pid(Globals.WEBSERVER, webDir)
        if webDir:
            webConf = webDir + '/conf/WebUI.cfg'
            webLog  = webDir + '/webui.log'
            command = '%s %s > %s 2>&1 &' % (
                shell_quote(Globals.WEBSERVER),
                shell_quote(webConf),
                shell_quote(webLog))
            if run_command(command) > 0:
                print '*** web ui failed to start'
                errors = errors + 1
            else:
                print 'Web ui  started: http://localhost:%d' % (
                   config.getint('webui', 'webport'))
    if errors > 0:
        print 'Started servers - FAILED.'
    else:
        print 'Started servers - OK.'
        defaultConfig=None
        if config.has_section('client'):
            clientDir = config.get('client', 'rundir')
            if authFlag and os.path.isfile(clientDir + '/client.prp'):
                print 'QFS authentication required.'
            defaultConfig = clientDir + '/clidefault.prp'
            if os.path.isfile(defaultConfig):
                print 'Default QFS client configuration file: %s' % defaultConfig
        if createNewFsFlag and Globals.QFSTOOL:
            if defaultConfig:
                cfgOpt =  " -cfg %s" % shell_quote(defaultConfig)
            command = '%s%s -mkdir %s' % (
                shell_quote(Globals.QFSTOOL),
                cfgOpt,
                shell_quote('/user/' + getpass.getuser()),
            )
            print 'Creating default user directory by executing:\n%s' % command
            if run_command(command) != 0:
                print '*** failed to created user directory'
            else:
                print '- OK.'

# Need to massage the ~ in the config file paths. Otherwise a directory
# with name "~" would get created at $CWD.
def parse_config(configFile):
    config = ConfigParser.ConfigParser()
    config.read(configFile);
    for section in config.sections():
        dir = config.get(section, 'rundir')
        config.set(section, 'rundir', os.path.expanduser(dir))
        if section.startswith('chunkserver'):
            dir = config.get(section, 'chunkdirs')
            dirstowrite = []
            dirs = dir.split(' ')
            for d in dirs:
                dirstowrite.append(os.path.expanduser(d))
            config.set(section, 'chunkdirs', ' '.join(dirstowrite))
    return config

if __name__ == '__main__':
    opts = parse_command_line()
    config = parse_config(opts.config_file)

    if opts.action in ('uninstall', 'stop'):
        do_cleanup(config, opts.action == 'uninstall')
        posix._exit(0)

    check_binaries(opts.release_dir, opts.source_dir, opts.auth)
    check_ports(config)
    if opts.action == 'install':
        setup_directories(config, opts.auth)
        setup_config_files(config, opts.auth)
        copy_files(config, opts.source_dir)
    elif opts.action == 'start':
        check_directories(config)
    start_servers(config, 'all', opts.action == 'install', opts.auth)
