import copy
import ldap
import ldap.modlist
import time

from collections import OrderedDict
from exceptions import Exception
from random import shuffle


# An exception class for erroring-out
#  on unknown hosts
class UNKNOWN_HOST(Exception):
  pass


class Provisor(object):

  def __init__(self, **kwargs):
    prop_defaults = {
        "uri": None,
        "user": None,
        "password": None,
        "user_base": None,
        "group_base": None,
        "servers_base": None,
        "ca_certfile": "/etc/ssl/certs/ca-certificates.crt",
        "default_shell": "/bin/bash",
        "min_uid": 3000,
        "max_uid": 1000000,
        "excluded_uids": [65534]
    }

    for (prop, default) in prop_defaults.iteritems():
        setattr(self, prop, kwargs.get(prop, default))

    ldap.set_option(ldap.OPT_X_TLS_CACERTFILE, self.ca_certfile)
    self.con = ldap.initialize(self.uri)
    self.con = ldap.ldapobject.ReconnectLDAPObject(
        self.uri,
        retry_max=10,
        retry_delay=5
    )
    self.con.set_option(ldap.OPT_X_TLS_DEMAND, True)
    self.con.start_tls_s()
    self.con.simple_bind_s(self.user, self.password)

  """ Does not work, dont know why """
  def whoami(self):
    return self.con.whoami_s()

  def list_users(self):
    users = []
    results = self.con.search_s(self.user_base, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ("uid",), 0)
    for r in results:
      for attrs in r[1]:
        users.append(r[1][attrs][0])
    return tuple(users)

  def list_privateports(self):
    port_maps = []
    results = self.con.search_s(user_base, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ("uid","uidNumber","host",), 0)
    for result in results:
      uid = int(r[1]['uidNumber'][0])
      username = r[1]['uid'][0]
      hostname = r[1]['host'][0].split('.')[0]
      port_maps.append({"username": username, "uid": uid, "hostname": hostname})
    return tuple(port_maps)


  def server_stats(self):
    stats = OrderedDict()
    server_list = self.servers()
    user_results = self.con.search_s(
        self.user_base,
        ldap.SCOPE_ONELEVEL,
        '(objectClass=*)',
        ("host",),
        0
    )
    for server in server_list:
      stats[server['cn']] = stats.get(server['cn'], OrderedDict())
      stats[server['cn']]['ip'] = server['ipHostNumber']
      stats[server['cn']]['location'] = server['l']
      stats[server['cn']]['currentUsers'] = stats[server['cn']].get('currentUsers', 0)
      stats[server['cn']]['maxUsers'] = server['maxUsers']
    for r in user_results:
      for attrs in r[1]:
        host = r[1][attrs][0]
        if host in stats:
            stats[host]['currentUsers'] = stats[host].get('currentUsers', 0) + 1

    return stats

  def servers(self):
    servers = []
    results = self.con.search_s(
        self.servers_base,
        ldap.SCOPE_ONELEVEL,
        '(objectClass=*)', ("cn", "maxUsers", "l", "ipHostNumber"),
        0
    )
    for r in results:
        server = {}
        for attr in r[1]:
            server[attr] = r[1][attr][0]
        servers.append(server)
    shuffle(servers)
    return servers

  def list_servers(self):
    return map(lambda x: x['cn'], self.servers())

  def list_groups(self):
    groups = []
    results = self.con.search_s(self.group_base, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ("cn",), 0)
    for r in results:
      for attrs in r[1]:
        groups.append(r[1][attrs][0])
    return tuple(groups)

  def group_exists(self, group):
    try:
      if self.con.compare_s("cn={0},{1}".format(group, self.group_base), "cn", group) == 1:
        return True
      else:
        return False
    except ldap.NO_SUCH_OBJECT:
      return False

  def user_exists(self, user):
    try:
      if self.con.compare_s("uid={0},{1}".format(user, self.user_base), "uid", user) == 1:
        return True
      else:
        return False
    except ldap.NO_SUCH_OBJECT:
      return False

  """ Returns the next uid for use """
  def next_uid(self):
    uids = []
    results = self.con.search_s(self.user_base, ldap.SCOPE_ONELEVEL, '(objectClass=*)', ("uidNumber",), 0)
    for r in results:
      for attrs in r[1]:
        uids.append(int(r[1][attrs][0]))
    uids.sort()
    for u in range(self.min_uid, self.max_uid, 1):
      if u in uids or u in self.excluded_uids:
        continue
      return u

  def add_group(self, groupname, gid):
    assert(gid >= self.min_uid)
    assert(gid <= self.max_uid)

    ml = {
        'objectClass': [ 'top', 'posixGroup' ],
        'cn': [ groupname ],
        'gidNumber': [ str(gid) ],
    }
    ml = ldap.modlist.addModlist(ml)
    self.con.add_s("cn={0},{1}".format(groupname, self.group_base), ml)

  def del_group(self, groupname):
    self.con.delete_s("cn={0},{1}".format(groupname, self.group_base))

  def is_group_member(self, group, user):
    try:
      if self.con.compare_s("cn={0},{1}".format(group, self.group_base), "memberUid", user) == 1:
        return True
      else:
        return False
    except ldap.NO_SUCH_OBJECT:
      return False

  def list_group_members(self, group):
    members = []
    results = self.con.search_s("cn={0},{1}".format(group, self.group_base),
                                ldap.SCOPE_BASE, '(objectClass=*)', ("memberUid",), 0)
    for r in results:
      for attrs in r[1]:
        for e in r[1][attrs]:
          members.append(e)
    return members

  def add_group_member(self, group, user):
    ml = { 'memberUid': [ user ] }
    ml = ldap.modlist.modifyModlist({}, ml, ignore_oldexistent=1)
    self.con.modify_s("cn={0},{1}".format(group, self.group_base), ml)

  def del_group_member(self, group, user):
    old = self.con.search_s("cn={0},{1}".format(group, self.group_base),
                            ldap.SCOPE_BASE, '(objectClass=*)', ("memberUid",), 0)
    old = old[0][1]
    new = copy.deepcopy(old)
    new['memberUid'].remove(user)
    ml = ldap.modlist.modifyModlist(old, new)
    self.con.modify_s("cn={0},{1}".format(group, self.group_base), ml)

  """ Attempt to modify a users entry """
  def modify_user(self, username, pubkeys=None,
                  shell=None, homedir=None,
                  lastchange=None, nextchange=None, warning=None,
                  raw_passwd=None, hostname=None, name=None):
    old = self.get_user(username)
    new = copy.deepcopy(old)

    if 'shadowAccount' not in new['objectClass']:
      new['objectClass'].append('shadowAccount')

    if 'inetLocalMailRecipient' not in new['objectClass']:
      new['objectClass'].append('inetLocalMailRecipient')

    if pubkeys:
      if 'sshPublicKey' in new:
        del(new['sshPublicKey'])
      new['sshPublicKey'] = pubkeys

    if shell:
      if 'loginShell' in new:
        del(new['loginShell'])
      new['loginShell'] = [ str(shell) ]

    if name:
      if 'cn' in new:
        del(new['cn'])
      new['cn'] = [ str(name) ]

    if homedir:
      if 'homeDirectory' in new:
        del(new['homeDirectory'])
      new['homeDirectory'] = [ str(homedir) ]

    if raw_passwd:
      password = '{crypt}' + raw_passwd
      if 'userPassword' in new:
        del(new['userPassword'])
      new['userPassword'] = [ str(password) ]

      if 'shadowLastChange' in new:
        del(new['shadowLastChange'])
      new['shadowLastChange'] = [ str(int(time.time() / 86400)) ]

    if lastchange:
      if 'shadowLastChange' in new:
        del(new['shadowLastChange'])
      new['shadowLastChange'] = [ str(int(time.time() / 86400)) ]

    if 'shadowInactive' not in new:
      new['shadowInactive'] = [ '99999' ]

    if 'shadowExpire' not in new:
      new['shadowExpire'] = [ '99999']

    if hostname:
      if hostname not in self.list_servers():
        raise UNKNOWN_HOST(hostname)
      if 'host' in new:
        del(new['host'])
      new['host'] = str(hostname)
      if 'mailRoutingAddress' in new:
        del(new['mailRoutingAddress'])
      new['mailRoutingAddress'] = [ '{0}@hashbang.sh'.format(username) ]
      if 'mailHost' in new:
        del(new['mailHost'])
      new['mailHost'] = [ 'smtp:{0}'.format(hostname) ]

    ml = ldap.modlist.modifyModlist(old, new)
    self.con.modify_s("uid={0},{1}".format(username, self.user_base), ml)

  """ Get User details """
  def get_user(self, username):
    user = self.con.search_s("uid={0},{1}".format(username, self.user_base),
                             ldap.SCOPE_BASE, '(objectClass=*)', ("*",), 0)[0][1]
    return user

  """ Adds a user, takes a number of optional defaults but the username and public key are required """
  def add_user(self, username, pubkey, hostname,
               shell=None, homedir=None, uid=None,
               lastchange=-1, nextchange=99999, warning=7, raw_passwd=None):

    if not homedir:
      homedir = "/home/{0}".format(username)

    if hostname not in self.list_servers():
      raise UNKNOWN_HOST(hostname)

    if uid is None:
      uid = self.next_uid()
    else:
      assert(uid >= self.min_uid)
      assert(uid <= self.max_uid)

    gid = uid

    if lastchange < 0:
      lastchange = int(time.time() / 86400)

    ml = {
        'objectClass': [ 'account',
                         'inetLocalMailRecipient',
                         'ldapPublicKey',
                         'posixAccount',
                         'shadowAccount',
                         'top' ],
        'uid': [ username ],
        'cn': [ username],
        'uidNumber': [ str(uid) ],
        'gidNumber': [ str(gid) ],
        'loginShell': [ shell or self.default_shell ],
        'homeDirectory': [ homedir ],
        'shadowLastChange': [ str(lastchange) ],
        'shadowMax': [ str(nextchange) ],
        'shadowWarning': [ str(warning) ],
        'shadowInactive': [ str(99999) ],
        'shadowExpire': [ str(99999) ],
        'userPassword': [ '{crypt}!' ],
        'sshPublicKey': [ str(pubkey) ],
        'host': [ str(hostname) ],
        'mailRoutingAddress': [ '{0}@hashbang.sh'.format(username) ],
        'mailHost': [ str('smtp:' + hostname) ],
    }

    ml = ldap.modlist.addModlist(ml)
    self.con.add_s("uid={0},{1}".format(username, self.user_base), ml)
    self.add_group(username, gid)

  def del_user(self, username):
    self.con.delete_s("uid={0},{1}".format(username, self.user_base))

  def __del__(self):
    self.con.unbind_s()
