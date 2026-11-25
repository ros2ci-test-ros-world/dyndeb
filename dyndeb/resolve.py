# Copyright 2026 The ros2ci authors
# SPDX-License-Identifier: Apache-2.0

"""rosdep keys to Debian package names, through rosdep's own rules."""


class Resolver:
    """
    Answers which Debian packages provide a rosdep key.

    It reads the rules ``rosdep update`` fetched and never fetches any
    itself, so the caller decides which rules a build sees. The platform
    is the one rosdep detects, which ``ROS_OS_OVERRIDE`` can replace.
    """

    def __init__(self, rosdistro):
        # Imported here so that the rest of the package works, and can be
        # tested, where rosdep is not installed.
        from rosdep2 import create_default_installer_context
        from rosdep2.catkin_support import get_catkin_view

        context = create_default_installer_context()
        self.os_name, self.os_version = context.get_os_name_and_version()
        self.installer_keys = context.get_os_installer_keys(self.os_name)
        self.default_installer_key = context.get_default_os_installer_key(self.os_name)
        self.installer = context.get_installer(self.default_installer_key)
        self.view = get_catkin_view(rosdistro, self.os_name, self.os_version, update=False)

    def __call__(self, key):
        from rosdep2 import ResolutionError

        try:
            definition = self.view.lookup(key)
        except KeyError:
            raise LookupError('no rosdep rule for this key')
        try:
            installer_key, rule = definition.get_rule_for_platform(
                self.os_name, self.os_version, self.installer_keys, self.default_installer_key)
        except ResolutionError:
            raise LookupError('no rule for %s %s' % (self.os_name, self.os_version))
        if installer_key != self.default_installer_key:
            # A package can only depend on other packages. Something pip
            # would install cannot be named in a control file.
            raise LookupError('it is installed through %s, which a package cannot depend on' % installer_key)
        return self.installer.resolve(rule)
