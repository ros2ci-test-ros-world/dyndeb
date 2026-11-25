# Copyright 2026 The ros2ci authors
# SPDX-License-Identifier: Apache-2.0

"""dyndeb-generate: write the debian directory of a ROS package."""

import argparse
import os
import sys

from . import manifest
from . import render

EXIT_OK = 0
EXIT_ERROR = 1
# Some rosdep keys have no package on this platform. Told apart from
# other errors because trying again will not fix it, and because the
# answer may be that this platform does not get this package.
EXIT_UNRESOLVED = 3


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='dyndeb-generate',
        description='Write the debian directory of a ROS package from its package.xml. '
                    'Build dependencies are resolved through rosdep, from the rules a '
                    'previous "rosdep update" fetched.')
    parser.add_argument('package_dir', help='the directory that holds package.xml')
    parser.add_argument('--rosdistro', default=os.environ.get('ROS_DISTRO'),
                        help='the ROS distribution; default: $ROS_DISTRO')
    parser.add_argument('--revision', default='1',
                        help='which build of this version this is; default: 1')
    parser.add_argument('--force', action='store_true',
                        help='replace a debian directory that is already there')
    arguments = parser.parse_args(argv)
    if not arguments.rosdistro:
        parser.error('--rosdistro is required when ROS_DISTRO is not set')

    package_dir = os.path.abspath(arguments.package_dir)
    debian_dir = os.path.join(package_dir, 'debian')
    if os.path.exists(debian_dir) and not arguments.force:
        print('error: %s already exists' % debian_dir, file=sys.stderr)
        return EXIT_ERROR

    try:
        from .resolve import Resolver
        resolver = Resolver(arguments.rosdistro)
        package = manifest.load(package_dir, arguments.rosdistro)
        files = render.render(package, package_dir, arguments.rosdistro, resolver.os_version,
                              arguments.revision, resolver)
        # The install-time dependencies are written during the build, by
        # dh_rosdep. They are resolved here as well, and thrown away, so
        # that a key with no package is found before the build is run.
        manifest.relations(manifest.run_dependencies(package), resolver)
    except manifest.UnresolvedKeys as e:
        print('error: these rosdep keys do not resolve to a package:', file=sys.stderr)
        for key, reason in e.problems:
            print('  %s: %s' % (key, reason), file=sys.stderr)
        return EXIT_UNRESOLVED
    except manifest.PackagingError as e:
        print('error: %s' % e, file=sys.stderr)
        return EXIT_ERROR

    for path, text in sorted(files.items()):
        target = os.path.join(debian_dir, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w') as f:
            f.write(text)
        os.chmod(target, 0o755 if render.executable(path) else 0o644)
    print('wrote %s for %s %s' % (debian_dir, manifest.debian_name(package.name, arguments.rosdistro),
                                  package.version))
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
