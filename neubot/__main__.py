#
# Copyright (c) 2011-2012, 2015
#    Nexa Center for Internet & Society, Politecnico di Torino (DAUIN)
#    and Simone Basso <bassosimone@gmail.com>.
#
# This file is part of Neubot <http://www.neubot.org/>.
#
# Neubot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Neubot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Neubot.  If not, see <http://www.gnu.org/licenses/>.
#

""" Neubot server """

import getopt
import sys
import logging
import os
import signal

from .runtime.http_server import HTTP_SERVER
from .runtime.poller import POLLER

from .negotiate_server import NEGOTIATE_SERVER
from .config import CONFIG

from . import backend
from . import log
from .server_side_api import ServerSideAPI
from .runtime import utils_modules
from .runtime import utils_posix

from .globals import LOCALSTATEDIR
from .globals import ROOTDIR

SETTINGS = {
    "server.bittorrent": True,
    "server.daemonize": True,
    "server.datadir": LOCALSTATEDIR,
    "server.negotiate": True,
    "server.raw": True,
    "server.sapi": True,
    "server.speedtest": True,
}

USAGE = '''\
usage: neubot server [-dv] [-A address] [-b backend] [-D macro=value]
                     [-u user]

valid backends:
  mlab   Saves results as compressed json files (this is the default)
  neubot Saves results in sqlite3 database
  null   Do not save results but pretend to do so

valid defines:
  server.bittorrent Set to nonzero to enable BitTorrent server (default: 1)
  server.daemonize  Set to nonzero to run in the background (default: 1)
  server.datadir    Set data directory (default: LOCALSTATEDIR/neubot)
  server.negotiate  Set to nonzero to enable negotiate server (default: 1)
  server.raw        Set to nonzero to enable RAW server (default: 1)
  server.sapi       Set to nonzero to enable nagios API (default: 1)
  server.speedtest  Set to nonzero to enable speedtest server (default: 1)'''

VALID_MACROS = ('server.bittorrent', 'server.daemonize', 'server.datadir',
                'server.negotiate', 'server.raw',
                'server.sapi', 'server.speedtest')

def main(args):
    """ Starts the server module """

    if os.getuid() != 0:
        sys.exit('FATAL: you must be root')

    #
    # Historically Neubot runs on port 9773 and
    # 8080 but we would like to switch to port 80
    # in the long term period, because it's rare
    # that they filter it.
    #
    ports = (80, 8080, 9773)
    pidfile = "/var/run/neubot.pid"

    run(args, ports, pidfile)

def main_development(args):
    """ Development version of main """
    CONFIG["unpriv_user"] = os.environ["USER"]
    SETTINGS["server.datadir"] = os.getcwd()
    run(args, (8080, 9773), os.getcwd() + "/neubot.pid")

def run(args, ports, pidfile):
    """ Function that implements main """

    try:
        options, arguments = getopt.getopt(args[1:], 'A:b:D:du:v')
    except getopt.error:
        sys.exit(USAGE)
    if arguments:
        sys.exit(USAGE)

    address = ':: 0.0.0.0'
    for name, value in options:
        if name == '-A':
            address = value
        elif name == '-D':
            name, value = value.split('=', 1)
            if name not in VALID_MACROS:
                sys.exit(USAGE)
            if name != 'server.datadir':  # XXX
                value = int(value)
            SETTINGS[name] = value
        elif name == '-d':
            SETTINGS['server.daemonize'] = 0
        elif name == '-u':
            CONFIG["unpriv_user"] = value
        elif name == '-v':
            log.set_verbose()

    backend.setup(CONFIG["unpriv_user"], SETTINGS['server.datadir'])

    for name, value in SETTINGS.items():
        CONFIG[name] = value

    conf = CONFIG.copy()

    conf["address"] = address

    #
    # Configure our global HTTP server and make
    # sure that we don't provide filesystem access
    # even by mistake.
    #
    conf["http.server.rootdir"] = ""
    HTTP_SERVER.configure(conf)

    if conf["server.negotiate"]:
        HTTP_SERVER.register_child(NEGOTIATE_SERVER, '/negotiate/')
        HTTP_SERVER.register_child(NEGOTIATE_SERVER, '/collect/')

    for port in ports:
        HTTP_SERVER.listen((address, port))

    #
    # Start server-side API for Nagios plugin
    # to query the state of the server.
    # functionalities.
    #
    if conf["server.sapi"]:
        server = ServerSideAPI(POLLER)
        server.configure(conf)
        HTTP_SERVER.register_child(server, "/sapi")

    # Probe existing modules and ask them to attach to us
    utils_modules.modprobe(ROOTDIR + "/neubot", None, "server", {
        "http_server": HTTP_SERVER,
        "negotiate_server": NEGOTIATE_SERVER,
        "configuration": conf,
        "poller": POLLER
    })

    #
    # Go background and drop privileges,
    # then enter into the main loop.
    #
    if conf["server.daemonize"]:
        log.redirect()
        utils_posix.daemonize(pidfile=pidfile)

    sigterm_handler = lambda signo, frame: POLLER.break_loop()
    signal.signal(signal.SIGTERM, sigterm_handler)

    logging.info('Neubot server -- starting up')
    utils_posix.chuser(utils_posix.getpwnam(CONFIG["unpriv_user"]))
    POLLER.loop()

    logging.info('Neubot server -- shutting down')
    utils_posix.remove_pidfile(pidfile)
