# Copyright 2026 The ros2ci authors
# SPDX-License-Identifier: Apache-2.0

"""
dh_rosdep: work out a ROS package's install-time dependencies.

A debhelper command, run from debian/rules before dh_gencontrol. It reads
package.xml in the current directory, resolves what the package needs at
run time through rosdep, and records the answer as the substitution
variable ``ros:Depends`` for the binary package. The control file refers
to it as ``${ros:Depends}``.

The dependencies are therefore decided when the package is built, from
the rosdep rules the build was given, and not when the source package was
made.
"""

import os
import re
import sys

from . import manifest

VARIABLE = 'ros:Depends'


def binary_package(control_path):
    """The name of the one binary package a control file describes."""
    with open(control_path) as f:
        names = re.findall(r'^Package:\s*(\S+)\s*$', f.read(), flags=re.MULTILINE)
    if len(names) != 1:
        raise manifest.PackagingError(
            'debian/control describes %d binary packages; dh_rosdep handles exactly one' % len(names))
    return names[0]


def set_variable(path, name, value):
    """Set one variable in a substvars file, keeping the others."""
    lines = []
    if os.path.isfile(path):
        with open(path) as f:
            lines = [line for line in f.read().splitlines() if not line.startswith(name + '=')]
    lines.append('%s=%s' % (name, value))
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def main(argv=None):
    # debhelper commands are passed options meant for all of them. This
    # one has none of its own and works on the one package there is.
    rosdistro = os.environ.get('ROS_DISTRO')
    if not rosdistro:
        print('dh_rosdep: ROS_DISTRO is not set', file=sys.stderr)
        return 1
    try:
        from .resolve import Resolver
        name = binary_package(os.path.join('debian', 'control'))
        package = manifest.load('.', rosdistro)
        depends = manifest.relations(manifest.run_dependencies(package), Resolver(rosdistro))
    except manifest.UnresolvedKeys as e:
        print('dh_rosdep: these rosdep keys do not resolve to a package:', file=sys.stderr)
        for key, reason in e.problems:
            print('  %s: %s' % (key, reason), file=sys.stderr)
        return 3
    except (manifest.PackagingError, OSError) as e:
        print('dh_rosdep: %s' % e, file=sys.stderr)
        return 1
    value = ', '.join(depends)
    set_variable(os.path.join('debian', name + '.substvars'), VARIABLE, value)
    print('dh_rosdep: %s=%s' % (VARIABLE, value))
    return 0


if __name__ == '__main__':
    sys.exit(main())
