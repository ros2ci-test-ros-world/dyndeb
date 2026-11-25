# Copyright 2026 The ros2ci authors
# SPDX-License-Identifier: Apache-2.0

"""What a package.xml says, in the terms Debian packaging needs."""

import os

from catkin_pkg.package import parse_package

# The build types there is a debian/rules for.
SUPPORTED_BUILD_TYPES = ('ament_python',)

# Every ROS 2 package depends on ros_workspace, which sets up the
# environment under /opt/ros. These are the packages ros_workspace itself
# is built from, which cannot depend on it. bloom has the same rule.
WITHOUT_ROS_WORKSPACE = ('ament_cmake_core', 'ament_package', 'ros_workspace')

# package.xml version attributes, as Debian relations.
RELATIONS = (
    ('version_lt', '<<'),
    ('version_lte', '<='),
    ('version_eq', '='),
    ('version_gte', '>='),
    ('version_gt', '>>'),
)


class PackagingError(Exception):
    """The package cannot be packaged as it stands."""


class UnresolvedKeys(PackagingError):
    """Some rosdep keys have no Debian package on this platform."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__('; '.join('%s: %s' % item for item in problems))


class Dependency:
    """One rosdep key, with the version limits package.xml put on it."""

    def __init__(self, key, relations=()):
        self.key = key
        self.relations = tuple(relations)

    @classmethod
    def from_xml(cls, dependency):
        relations = []
        for attribute, relation in RELATIONS:
            version = getattr(dependency, attribute, None)
            if version is not None:
                relations.append((relation, version))
        return cls(dependency.name, relations)


def load(package_dir, rosdistro):
    """Read package.xml, with its conditions decided for a ROS 2 distribution."""
    package = parse_package(os.path.join(package_dir, 'package.xml'))
    package.evaluate_conditions({
        'ROS_VERSION': '2',
        'ROS_DISTRO': rosdistro,
        'ROS_PYTHON_VERSION': '3',
    })
    return package


def _active(dependencies):
    return [Dependency.from_xml(d) for d in dependencies if d.evaluated_condition is not False]


def _with_ros_workspace(package, dependencies):
    if package.name not in WITHOUT_ROS_WORKSPACE:
        dependencies.append(Dependency('ros_workspace'))
    return dependencies


def build_dependencies(package):
    """What has to be installed to build the package."""
    return _with_ros_workspace(package, _active(package.build_depends + package.buildtool_depends))


def test_dependencies(package):
    """What has to be installed as well to run its tests."""
    return _active(package.test_depends)


def run_dependencies(package):
    """What has to be installed wherever the built package is."""
    return _with_ros_workspace(package, _active(package.run_depends + package.buildtool_export_depends))


def conflicts(package):
    return _active(package.conflicts)


def replaces(package):
    return _active(package.replaces)


def debian_name(name, rosdistro):
    """The Debian package a ROS package becomes."""
    return 'ros-%s-%s' % (rosdistro, name.replace('_', '-'))


def relations(dependencies, resolver):
    """
    Turn rosdep keys into the entries of a Debian relationship field.

    ``resolver`` takes a key and returns the names of the Debian packages
    that provide it, or raises ``KeyError`` or ``LookupError`` with the
    reason it cannot. Every key is tried before anything is reported, so
    that one run names all the keys that are missing.
    """
    entries = set()
    problems = []
    for dependency in dependencies:
        try:
            names = resolver(dependency.key)
        except LookupError as e:
            problems.append((dependency.key, str(e).strip('\'"') or 'no rule'))
            continue
        for name in names:
            if dependency.relations:
                for relation, version in dependency.relations:
                    entries.add('%s (%s %s)' % (name, relation, version))
            else:
                entries.add(name)
    if problems:
        raise UnresolvedKeys(problems)
    return sorted(entries)
