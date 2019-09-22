def drop_privileges(uid_name='nobody', gid_name='nogroup'):
    import grp, pwd, os, resource
    if os.getuid() != 0:  # not root. #yolo
        return

    running_uid = pwd.getpwnam(uid_name).pw_uid
    running_gid = grp.getgrnam(gid_name).gr_gid

    os.setgroups([])
    os.setgid(running_gid)
    os.setuid(running_uid)
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def getch():
    import sys, termios, tty
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def validate_pubkey(value):
    import base64
    if len(value) > 8192 or len(value) < 80:
      raise ValueError("Expected length to be between 80 and 8192 characters")

    value = value.replace("\"", "").replace("'", "").replace("\\\"", "")
    value = value.split(' ')
    types = [ 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384',
              'ecdsa-sha2-nistp521', 'ssh-rsa', 'ssh-dss', 'ssh-ed25519' ]
    options = [ 'cert-authority' ]
    valid = value[0] in types or (value[0] in options and value[1] in types)
    if not valid:
        raise ValueError(
            "Expected " + ', '.join(types[:-1]) + ', or ' + types[-1]
        )

    try:
        base64.decodestring(bytes(value[1]))
    except TypeError:
        raise ValueError("Expected string of base64 encoded data")

    return "%s %s" % (value[0], value[1])


def validate_username(value):
    import re
    from reserved import RESERVED_USERNAMES

    # Regexp must be kept in sync with
    #  https://github.com/hashbang/hashbang.sh/blob/master/src/hashbang.sh#L186-196
    if re.compile(r"^[a-z][a-z0-9]{,30}$").match(value) is None:
        raise ValueError('Username is invalid')

    if value in RESERVED_USERNAMES:
        raise ValueError('Username is reserved')

    return value
