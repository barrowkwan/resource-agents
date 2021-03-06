#
# Copyright (c) 2016 Red Hat, Inc, Oyvind Albrigtsen
#                    All Rights Reserved.
#
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
# 

import sys, os, logging, syslog

argv=sys.argv
env=os.environ

#
# 	Common variables for the OCF Resource Agents supplied by
# 	heartbeat.
#

OCF_SUCCESS=0
OCF_ERR_GENERIC=1
OCF_ERR_ARGS=2
OCF_ERR_UNIMPLEMENTED=3
OCF_ERR_PERM=4
OCF_ERR_INSTALLED=5
OCF_ERR_CONFIGURED=6
OCF_NOT_RUNNING=7

# Non-standard values.
#
# OCF does not include the concept of master/slave resources so we
#   need to extend it so we can discover a resource's complete state.
#
# OCF_RUNNING_MASTER:  
#    The resource is in "master" mode and fully operational
# OCF_FAILED_MASTER:
#    The resource is in "master" mode but in a failed state
# 
# The extra two values should only be used during a probe.
#
# Probes are used to discover resources that were started outside of
#    the CRM and/or left behind if the LRM fails.
# 
# They can be identified in RA scripts by checking for:
#   [ "${__OCF_ACTION}" = "monitor" -a "${OCF_RESKEY_CRM_meta_interval}" = "0" ]
# 
# Failed "slaves" should continue to use: OCF_ERR_GENERIC
# Fully operational "slaves" should continue to use: OCF_SUCCESS
#
OCF_RUNNING_MASTER=8
OCF_FAILED_MASTER=9


## Own logger handler that uses old-style syslog handler as otherwise
## everything is sourced from /dev/syslog
class SyslogLibHandler(logging.StreamHandler):
	"""
	A handler class that correctly push messages into syslog
	"""
	def emit(self, record):
		syslog_level = {
			logging.CRITICAL:syslog.LOG_CRIT,
			logging.ERROR:syslog.LOG_ERR,
			logging.WARNING:syslog.LOG_WARNING,
			logging.INFO:syslog.LOG_INFO,
			logging.DEBUG:syslog.LOG_DEBUG,
			logging.NOTSET:syslog.LOG_DEBUG,
		}[record.levelno]

		msg = self.format(record)

		# syslog.syslog can not have 0x00 character inside or exception
		# is thrown
		syslog.syslog(syslog_level, msg.replace("\x00","\n"))
		return


OCF_RESOURCE_INSTANCE = env.get("OCF_RESOURCE_INSTANCE")

OCF_ACTION = env.get("__OCF_ACTION")
if OCF_ACTION is None and len(argv) == 2:
	OCF_ACTION = argv[1]

HA_DEBUG = env.get("HA_debug", 0)
HA_DATEFMT = env.get("HA_DATEFMT", "%b %d %T ")
HA_LOGFACILITY = env.get("HA_LOGFACILITY")
HA_LOGFILE = env.get("HA_LOGFILE")
HA_DEBUGLOG = env.get("HA_DEBUGLOG")

logging.basicConfig()
log = logging.getLogger(os.path.basename(argv[0]))
log.setLevel(logging.DEBUG)

## add logging to stderr
if sys.stdout.isatty():
	seh = logging.StreamHandler(stream=sys.stderr)
	if HA_DEBUG == 0:
		seh.setLevel(logging.WARNING)
	sehformatter = logging.Formatter('%(filename)s(%(OCF_RESOURCE_INSTANCE)s)[%(process)s]:\t%(asctime)s%(levelname)s: %(message)s', datefmt=HA_DATEFMT)
	seh.setFormatter(sehformatter)
	log.addHandler(seh)

## add logging to syslog
if HA_LOGFACILITY:
	slh = SyslogLibHandler()
	if HA_DEBUG == 0:
		slh.setLevel(logging.WARNING)
	slhformatter = logging.Formatter('%(levelname)s: %(message)s')
	slh.setFormatter(slhformatter)
	log.addHandler(slh)

## add logging to file
if HA_LOGFILE:
	lfh = logging.FileHandler(HA_LOGFILE)
	if HA_DEBUG == 0:
		lfh.setLevel(logging.WARNING)
	lfhformatter = logging.Formatter('%(filename)s(%(OCF_RESOURCE_INSTANCE)s)[%(process)s]:\t%(asctime)s%(levelname)s: %(message)s', datefmt=HA_DATEFMT)
	lfh.setFormatter(lfhformatter)
	log.addHandler(lfh)

## add debug logging to file
if HA_DEBUGLOG and HA_LOGFILE != HA_DEBUGLOG:
	dfh = logging.FileHandler(HA_DEBUGLOG)
	if HA_DEBUG == 0:
		dfh.setLevel(logging.WARNING)
	dfhformatter = logging.Formatter('%(filename)s(%(OCF_RESOURCE_INSTANCE)s)[%(process)s]:\t%(asctime)s%(levelname)s: %(message)s', datefmt=HA_DATEFMT)
	dfh.setFormatter(dfhformatter)
	log.addHandler(dfh)

logger = logging.LoggerAdapter(log, {'OCF_RESOURCE_INSTANCE': OCF_RESOURCE_INSTANCE})


def ocf_exit_reason(msg):
	"""
	Print exit error string to stderr.

	Allows the OCF agent to provide a string describing
	why the exit code was returned.
	"""
	cookie = env.get("OCF_EXIT_REASON_PREFIX", "ocf-exit-reason:")
	sys.stderr.write("{}{}\n".format(cookie, msg))
	sys.stderr.flush()
	logger.error(msg)


def have_binary(name):
	"""
	True if binary exists, False otherwise.
	"""
	def _access_check(fn):
		return (os.path.exists(fn) and
				os.access(fn, os.F_OK | os.X_OK) and
				not os.path.isdir(fn))
	if _access_check(name):
		return True
	path = env.get("PATH", os.defpath).split(os.pathsep)
	seen = set()
	for dir in path:
		dir = os.path.normcase(dir)
		if dir not in seen:
			seen.add(dir)
			name2 = os.path.join(dir, name)
			if _access_check(name2):
				return True
	return False


def is_true(val):
	"""
	Convert an OCF truth value to a
	Python boolean.
	"""
	return val in ("yes", "true", "1", 1, "YES", "TRUE", "ja", "on", "ON", True)


def is_probe():
	"""
	A probe is defined as a monitor operation
	with an interval of zero. This is called
	by Pacemaker to check the status of a possibly
	not running resource.
	"""
	return (OCF_ACTION == "monitor" and
			env.get("OCF_RESKEY_CRM_meta_interval", "") == "0")


def get_parameter(name, default=None):
	"""
	Extract the parameter value from the environment
	"""
	return env.get("OCF_RESKEY_{}".format(name), default)


class Parameter(object):
	def __init__(self, name, shortdesc, longdesc, content_type, unique, required, default):
		self.name = name
		self.shortdesc = shortdesc
		self.longdesc = longdesc
		self.content_type = content_type
		self.unique = unique
		self.required = required
		self.default = default

	def __str__(self):
		ret = '<parameter name="' + self.name + '"'
		if self.unique:
			ret += ' unique="1"'
		if self.required:
			ret += ' required="1"'
		ret += ">\n"
		ret += '<longdesc lang="en">' + self.longdesc + '</longdesc>' + "\n"
		ret += '<shortdesc lang="en">' + self.shortdesc + '</shortdesc>' + "\n"
		ret += '<content type="' + self.content_type + '"'
		if self.default is not None:
			ret += ' default="{}"'.format(self.default)
		ret += " />\n"
		ret += "</parameter>\n"
		return ret


class Action(object):
	def __init__(self, name, timeout, interval, depth):
		self.name = name
		self.timeout = timeout
		self.interval = interval
		self.depth = depth

	def __str__(self):
		def opt(s, name, var):
			if var is not None:
				if type(var) == int:
					var = "{}s".format(var)
				return s + ' {}="{}"'.format(name, var)
			return s
		ret = '<action name="{}"'.format(self.name)
		ret = opt(ret, "timeout", self.timeout)
		ret = opt(ret, "interval", self.interval)
		ret = opt(ret, "depth", self.depth)
		ret += " />\n"
		return ret


class Metadata(object):
	"""
	Metadata XML generator helper.
	"""

	def __init__(self, name, shortdesc, longdesc):
		self.name = name
		self.shortdesc = shortdesc
		self.longdesc = longdesc
		self.parameters = []
		self.actions = []

	def add_parameter(self, name, shortdesc="", longdesc="", content_type="string", unique=False, required=False, default=None):
		for param in self.parameters:
			if param.name == name:
				raise ValueError("Parameter {} defined twice in metadata".format(name))
		self.parameters.append(Parameter(name=name,
										 shortdesc=shortdesc,
										 longdesc=longdesc,
										 content_type=content_type,
										 unique=unique,
										 required=required,
										 default=default))
		return self

	def add_action(self, name, timeout=None, interval=None, depth=None):
		self.actions.append(Action(name=name,
								   timeout=timeout,
								   interval=interval,
								   depth=depth))
		return self

	def __str__(self):
		return """<?xml version="1.0"?>
<!DOCTYPE resource-agent SYSTEM "ra-api-1.dtd">
<resource-agent name="{name}">
<version>1.0</version>
<longdesc lang="en">
{longdesc}
</longdesc>
<shortdesc lang="en">{shortdesc}</shortdesc>

<parameters>
{parameters}
</parameters>

<actions>
{actions}
</actions>

</resource-agent>
""".format(name=self.name,
		   longdesc=self.longdesc,
		   shortdesc=self.shortdesc,
		   parameters="".join(str(p) for p in self.parameters),
		   actions="".join(str(a) for a in self.actions))


def run(metadata, handlers):
	"""
	Main loop implementation for resource agents.
	Does not return.

	Arguments:

	metadata: Metadata structure generated by ocf.Metadata

	handlers: Dict of action name to handler function.

	Handler functions can take parameters as arguments,
	the run loop will read parameter values from the
	environment and pass to the handler.
	"""
	import inspect

	def check_required_params():
		for p in metadata.parameters:
			if p.required and get_parameter(p.name) is None:
				ocf_exit_reason("{}: Required parameter not set".format(p.name))
				sys.exit(OCF_ERR_CONFIGURED)

	def call_handler(func):
		if hasattr(inspect, 'signature'):
			params = inspect.signature(func).parameters.keys()
		else:
			params = inspect.getargspec(func).args
		def default_for_parameter(paramname):
			for meta in metadata.parameters:
				if meta.name == paramname:
					return meta.default
			return None
		arglist = [get_parameter(p, default_for_parameter(p)) for p in params]
		rc = func(*arglist)
		if rc is None:
			rc = OCF_SUCCESS
		return rc

	if OCF_ACTION is None:
		ocf_exit_reason("No action argument set")
		sys.exit(OCF_ERR_UNIMPLEMENTED)
	if OCF_ACTION in ('meta-data', 'usage', 'methods'):
		sys.stdout.write(str(metadata) + "\n")
		sys.exit(OCF_SUCCESS)

	check_required_params()
	if OCF_ACTION in handlers:
		rc = call_handler(handlers[OCF_ACTION])
		sys.exit(rc)
	sys.exit(OCF_ERR_UNIMPLEMENTED)


if __name__ == "__main__":
	import unittest

	class TestMetadata(unittest.TestCase):
		def test_noparams_noactions(self):
			m = Metadata("foo", shortdesc="shortdesc", longdesc="longdesc")
			self.assertEqual("""<?xml version="1.0"?>
<!DOCTYPE resource-agent SYSTEM "ra-api-1.dtd">
<resource-agent name="foo">
<version>1.0</version>
<longdesc lang="en">
longdesc
</longdesc>
<shortdesc lang="en">shortdesc</shortdesc>

<parameters>

</parameters>

<actions>

</actions>

</resource-agent>
""", str(m))

		def test_params_actions(self):
			m = Metadata("foo", shortdesc="shortdesc", longdesc="longdesc")
			m.add_parameter("testparam")
			m.add_action("start")
			self.assertEqual(str(m.actions[0]), '<action name="start" />\n')

	unittest.main()
