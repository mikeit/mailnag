#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# mailnag.py
#
# Copyright 2011, 2012 Patrick Ulbrich <zulu99@gmx.net>
# Copyright 2011 Leighton Earl <leighton.earl@gmx.com>
# Copyright 2011 Ralf Hersel <ralf.hersel@gmx.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA.
#

import os
from gi.repository import GObject, GLib
import time
import signal
import traceback

from common.config import read_cfg, cfg_exists, cfg_folder
from common.utils import set_procname, is_online
from common.accountlist import AccountList
from daemon.mailchecker import MailChecker
from daemon.idlers import Idlers

mainloop = None
mailchecker = None
idlers = None


def read_config():
	if not cfg_exists():
		return None
	else:
		return read_cfg()


def write_pid():
	pid_file = os.path.join(cfg_folder, 'mailnag.pid')
	f = open(pid_file, 'w')
	f.write(str(os.getpid()))
	f.close()


def delete_pid():
	pid_file = os.path.join(cfg_folder, 'mailnag.pid')
	if os.path.exists(pid_file):
		os.remove(pid_file)


# Workaround: 
# sometimes gnomeshell's notification server (org.freedesktop.Notifications implementation)
# doesn't seem to be up immediately upon session start, so prevent Mailnag from crashing 
# by checking if the org.freedesktop.Notifications DBUS interface is available yet.
# See https://github.com/pulb/mailnag/issues/48
def wait_for_notification_server():	
	import dbus
	bus = dbus.SessionBus()
	
	while True:	
		try:		
			notify = bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
			iface = dbus.Interface(notify, 'org.freedesktop.Notifications')
			inf = iface.GetServerInformation()
			
			if inf[0] == u'gnome-shell':
				break
		except:
			pass
		
		print 'Waiting for GNOME-Shell notification server...'			
		time.sleep(5)


def wait_for_inet_connection():
	if not is_online():
		print 'Waiting for internet connection...'
		while not is_online():
			time.sleep(5)


def cleanup():
	# clean up resources
	if mailchecker != None:
		mailchecker.dispose()

	if idlers != None:
		idlers.dispose()
	
	delete_pid()


def sig_handler(signum, frame):
	if mainloop != None:
		mainloop.quit()


def main():
	global mainloop, mailchecker, idlers
	
	set_procname("mailnag")
	
	GObject.threads_init()
	
	signal.signal(signal.SIGTERM, sig_handler)
	
	try:
		# write Mailnag's process id to file
		write_pid()
		cfg = read_config()
		
		if (cfg == None):
			print 'Error: Cannot find configuration file. Please run mailnag_config first.'
			exit(1)
		
		wait_for_notification_server()		
		wait_for_inet_connection()
		
		accounts = AccountList()
		accounts.load_from_cfg(cfg, enabled_only = True)
		
		mailchecker = MailChecker(cfg)
		
		# immediate check, check *all* accounts
		try:		
			mailchecker.check(accounts)
		except:
			traceback.print_exc()
		
		idle_accounts = filter(lambda acc: acc.imap and acc.idle, accounts)
		non_idle_accounts = filter(lambda acc: (not acc.imap) or (acc.imap and not acc.idle), accounts)
		
		# start polling thread for POP3 accounts and
		# IMAP accounts without idle support
		if len(non_idle_accounts) > 0:
			def poll_func():
				try:
					mailchecker.check(non_idle_accounts)
				except:
					traceback.print_exc()
				return True
			
			check_interval = int(cfg.get('general', 'check_interval'))
			GObject.timeout_add_seconds(60 * check_interval, poll_func)
		
		# start idler threads for IMAP accounts with idle support
		if len(idle_accounts) > 0:
			def sync_func(account):
				try:
					mailchecker.check([account])
				except:
					traceback.print_exc()
			
			idlers = Idlers(idle_accounts, sync_func)
			idlers.run()
		
		mainloop = GObject.MainLoop()
		mainloop.run()
	except KeyboardInterrupt:
		pass # ctrl+c pressed
	finally:
		cleanup()


if __name__ == '__main__': main()
