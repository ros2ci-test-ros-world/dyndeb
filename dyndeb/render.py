# Copyright 2026 The ros2ci authors
# SPDX-License-Identifier: Apache-2.0

"""
The contents of a debian directory for one ROS package.

What is written follows what bloom's templates write, so that a package
built from it is laid out like the one build.ros2.org publishes. Two
things differ on purpose:

* install-time dependencies are not in the control file. It holds
  ``${ros:Depends}``, which ``dh_rosdep`` fills in during the build;
* the rules file runs the package's tests itself and leaves their results
  as JUnit XML files, and a failing test does not stop the build. Whoever
  runs the build reads the results and decides what a failure means.

There is one set of rules for ``ament_python`` packages and one for the
two CMake build types, ``ament_cmake`` and ``cmake``, as in bloom.
"""

import configparser
import datetime
import email.utils
import os
import re

from . import manifest

# The debhelper compatibility level the rules are written for.
DEBHELPER_COMPAT = 13

STANDARDS_VERSION = '4.7.0'


def render(package, package_dir, rosdistro, os_version, revision, resolver, now=None):
    """
    Return the files of the debian directory, as a dict of path to text.

    ``os_version`` is the release's code name, such as ``resolute``.
    ``revision`` counts the builds of this version. ``resolver`` resolves
    rosdep keys; see ``manifest.relations``. ``now`` dates a changelog
    entry that the package's own changelog has no date for.
    """
    build_type = package.get_build_type()
    if build_type not in manifest.SUPPORTED_BUILD_TYPES:
        raise manifest.PackagingError(
            'build type %r is not supported; supported: %s'
            % (build_type, ', '.join(manifest.SUPPORTED_BUILD_TYPES)))
    if not re.match(r'^[0-9][0-9A-Za-z.+~]*$', package.version):
        raise manifest.PackagingError('version %r cannot be a Debian version' % package.version)
    if not re.match(r'^[0-9]+$', str(revision)):
        raise manifest.PackagingError('the revision must be a whole number, not %r' % (revision,))
    if not package.maintainers:
        raise manifest.PackagingError('package.xml names no maintainer')

    name = manifest.debian_name(package.name, rosdistro)
    prefix = '/opt/ros/' + rosdistro
    version = '%s-%s%s' % (package.version, revision, os_version)
    now = now or datetime.datetime.now(datetime.timezone.utc)

    if build_type == 'ament_python':
        rules = _rules_ament_python(package, prefix, rosdistro, package_dir)
    else:
        rules = _rules_cmake(package, prefix, rosdistro, build_type)
    return {
        'control': _control(package, name, rosdistro, resolver, build_type),
        'rules': rules,
        'changelog': _changelog(package, package_dir, name, version, os_version, now),
        'copyright': _copyright(package, package_dir),
        'source/format': '3.0 (quilt)\n',
    }


def executable(path):
    """Whether a rendered file has to be executable."""
    return path == 'rules'


# -- control -----------------------------------------------------------


def _person(person):
    # The name is quoted, as bloom does it, so that a comma or a dot in it
    # cannot be read as part of the address syntax.
    name = person.name or ''
    if name and not name.startswith('"'):
        name = '"%s"' % name
    return '%s <%s>' % (name, person.email) if person.email else name


def _plain(text):
    """Text from package.xml on one line, without markup."""
    text = re.sub(r'<.*?>', '', text or '')
    return re.sub(r'\s+', ' ', text).strip()


def _description(text):
    """A synopsis line, and the rest as one paragraph."""
    text = _plain(text)
    first, separator, rest = text.partition('. ')
    if not separator or not rest.strip():
        return text
    return '%s.\n %s' % (first, rest.strip())


def _homepage(package, rosdistro):
    for url in package.urls:
        if url.type == 'website':
            return str(url)
    return 'https://index.ros.org/p/%s/#%s' % (package.name, rosdistro)


def _control(package, name, rosdistro, resolver, build_type):
    build = manifest.relations(manifest.build_dependencies(package), resolver)
    # Left out of a build that is told not to run tests, by the nocheck
    # build profile.
    # A package's tests run the package, so what it needs to run has to
    # be installed for them too.
    for_tests = (manifest.relations(manifest.test_dependencies(package), resolver)
                 + manifest.relations(manifest.run_dependencies(package), resolver))
    test = [entry + ' <!nocheck>' for entry in sorted(set(for_tests)) if entry not in build]
    tools = ['debhelper-compat (= %d)' % DEBHELPER_COMPAT]
    if build_type == 'ament_python':
        tools += ['dh-python', 'python3-all', 'python3-setuptools']
        own_depends = '${python3:Depends}'
    else:
        own_depends = '${shlibs:Depends}'
    build_depends = tools + [entry for entry in sorted(set(build) | set(test)) if entry not in tools]

    lines = [
        'Source: ' + name,
        'Section: misc',
        'Priority: optional',
        'Maintainer: ' + _person(package.maintainers[0]),
        'Build-Depends: ' + ', '.join(build_depends),
        'Homepage: ' + _homepage(package, rosdistro),
        'Standards-Version: ' + STANDARDS_VERSION,
        'Rules-Requires-Root: no',
        '',
        'Package: ' + name,
        'Architecture: any',
        'Depends: %s, ${misc:Depends}, ${ros:Depends}' % own_depends,
    ]
    for field, dependencies in (('Conflicts', manifest.conflicts(package)),
                                ('Replaces', manifest.replaces(package))):
        entries = manifest.relations(dependencies, resolver)
        if entries:
            lines.append('%s: %s' % (field, ', '.join(entries)))
    lines.append('Description: ' + _description(package.description))
    return '\n'.join(lines) + '\n'


# -- rules -------------------------------------------------------------

_RULES_HEADER = '''\
#!/usr/bin/make -f
# Generated from package.xml by dyndeb. Do not edit.

export DH_VERBOSE=1
# As bloom's rules have it: no hardening flags for the linker, and the
# -DNDEBUG that a release build of a ROS package expects.
export LDFLAGS=
export PKG_CONFIG_PATH=@PREFIX@/lib/pkgconfig
export DEB_CXXFLAGS_MAINT_APPEND=-DNDEBUG

# What dh_rosdep resolves the install-time dependencies for.
export ROS_DISTRO=@ROSDISTRO@
export ROS_VERSION=2
export ROS_PYTHON_VERSION=3

DEB_HOST_GNU_TYPE ?= $(shell dpkg-architecture -qDEB_HOST_GNU_TYPE)

# Where the tests leave their results, as JUnit XML files.
ROS_TEST_RESULTS_DIR ?= $(CURDIR)/.ros_test_results

# The packages this one depends on are installed under @PREFIX@. Their
# setup file puts them on the paths the build and the tests search. That
# file belongs to ros_workspace, and the few packages ros_workspace is
# itself built from are built before it exists. For them the Python
# modules under @PREFIX@ are put on the path directly, which is what
# bloom's RPM macros do. bloom's Debian rules have no such case, and the
# release repositories of those packages carry it as a patch.
PYTHON3_VERSION = $(shell py3versions -d)
ROS_PYTHON_DIR = @PREFIX@/lib/$(PYTHON3_VERSION)/site-packages
ROS_PYTHONPATH = export PYTHONPATH="$(ROS_PYTHON_DIR)$${PYTHONPATH:+:$$PYTHONPATH}"
ROS_SETUP = if [ -f "@PREFIX@/setup.sh" ]; then . "@PREFIX@/setup.sh"; else $(ROS_PYTHONPATH); fi
'''

_RULES_AMENT_PYTHON = '''
export PYBUILD_INSTALL_ARGS=--prefix "@PREFIX@" \\
\t--install-lib "\\$$base/lib/{interpreter}/site-packages"@INSTALL_SCRIPTS@

%:
\tdh $@ -v --buildsystem=pybuild --with python3 --builddirectory=.obj-$(DEB_HOST_GNU_TYPE)

override_dh_auto_configure:
\t$(ROS_SETUP) && dh_auto_configure

override_dh_auto_build:
\t$(ROS_SETUP) && dh_auto_build

# The tests run the way colcon runs them: pytest, from the top of the
# source tree, with the package's metadata written there first. Without
# it a test cannot find what the package registers about itself, such as
# its entry points. A failing test is recorded and does not stop the build.
override_dh_auto_test:
ifeq (,$(filter nocheck,$(DEB_BUILD_OPTIONS)))
\tmkdir -p "$(ROS_TEST_RESULTS_DIR)"
\t$(ROS_SETUP) && python3 setup.py -q egg_info && python3 -m pytest -p no:cacheprovider \\
\t\t--junit-xml="$(ROS_TEST_RESULTS_DIR)/pytest.xml" \\
\t\t-o junit_suite_name=@NAME@ \\
\t\t|| echo "-- tests failed or could not run; the build goes on"
endif

override_dh_auto_install:
\t$(ROS_SETUP) && dh_auto_install

override_dh_shlibdeps:
\t$(ROS_SETUP) && dh_shlibdeps -l$(CURDIR)/debian/@PACKAGE@@PREFIX@/lib/

execute_before_dh_gencontrol:
\tdh_rosdep
'''


def _rules_ament_python(package, prefix, rosdistro, package_dir):
    # setup.cfg may already say where scripts go; saying it twice with
    # different answers is an error. bloom checks the same way.
    install_scripts = ' \\\n\t--install-scripts "\\$$base/bin"'
    setup_cfg = os.path.join(package_dir, 'setup.cfg')
    if os.path.isfile(setup_cfg):
        parser = configparser.ConfigParser()
        try:
            parser.read([setup_cfg])
        except configparser.Error:
            pass
        else:
            if parser.has_option('install', 'install-scripts') or parser.has_option('install', 'install_scripts'):
                install_scripts = ''
    text = _RULES_HEADER + _RULES_AMENT_PYTHON
    for marker, value in (('@INSTALL_SCRIPTS@', install_scripts),
                          ('@PREFIX@', prefix),
                          ('@ROSDISTRO@', rosdistro),
                          ('@PACKAGE@', manifest.debian_name(package.name, rosdistro)),
                          ('@NAME@', package.name)):
        text = text.replace(marker, value)
    return text


_RULES_CMAKE = '''
# For packages that install libraries into the multiarch directory.
export DEB_HOST_MULTIARCH := $(shell dpkg-architecture -qDEB_HOST_MULTIARCH)

BUILD_DIR = .obj-$(DEB_HOST_GNU_TYPE)

ifneq (,$(filter nocheck,$(DEB_BUILD_OPTIONS)))
BUILD_TESTING_ARG = -DBUILD_TESTING=OFF
endif

%:
\tdh $@ -v --buildsystem=cmake --builddirectory=$(BUILD_DIR)

override_dh_auto_configure:
\t$(ROS_SETUP) && dh_auto_configure -- \\
\t\t-DCMAKE_INSTALL_PREFIX="@PREFIX@" \\@AMENT_PREFIX_PATH@
\t\t-DCMAKE_PREFIX_PATH="@PREFIX@" \\
\t\t$(BUILD_TESTING_ARG)

override_dh_auto_build:
\t$(ROS_SETUP) && dh_auto_build

# The tests run the way colcon runs them: ctest, in the build directory.
# A failing test is recorded and does not stop the build.
override_dh_auto_test:
ifeq (,$(filter nocheck,$(DEB_BUILD_OPTIONS)))
\tmkdir -p "$(ROS_TEST_RESULTS_DIR)"
\t$(ROS_SETUP) && cd $(BUILD_DIR) && ctest --output-on-failure@CTEST_RESULTS@ \\
\t\t|| echo "-- tests failed or could not run; the build goes on"@COLLECT_RESULTS@
endif

override_dh_auto_install:
\t$(ROS_SETUP) && dh_auto_install

override_dh_shlibdeps:
\t$(ROS_SETUP) && dh_shlibdeps -l$(CURDIR)/debian/@PACKAGE@@PREFIX@/lib/:$(CURDIR)/debian/@PACKAGE@@PREFIX@/@EXTRA_LIB@

execute_before_dh_gencontrol:
\tdh_rosdep
'''

# A test of an ament_cmake package writes its own result file under
# test_results in the build directory, with every test case in it. Those
# are what colcon reports, so they are what is kept: one file per test,
# named by its path.
_COLLECT_AMENT_RESULTS = '''
\tif [ -d $(BUILD_DIR)/test_results ]; then cd $(BUILD_DIR)/test_results && \\
\t\tfind . -name '*.xml' | while read -r f; do \\
\t\t\tcp "$$f" "$(ROS_TEST_RESULTS_DIR)/$$(echo "$$f" | sed 's|^\\./||; s|/|__|g')"; \\
\t\tdone; fi'''


def _rules_cmake(package, prefix, rosdistro, build_type):
    if build_type == 'ament_cmake':
        values = (
            ('@AMENT_PREFIX_PATH@', '\n\t\t-DAMENT_PREFIX_PATH="@PREFIX@" \\'),
            ('@CTEST_RESULTS@', ''),
            ('@COLLECT_RESULTS@', _COLLECT_AMENT_RESULTS),
            ('@EXTRA_LIB@', 'opt/%s/lib/' % package.name),
        )
    else:
        # A plain CMake package has only what ctest itself knows.
        values = (
            ('@AMENT_PREFIX_PATH@', ''),
            ('@CTEST_RESULTS@', ' --output-junit "$(ROS_TEST_RESULTS_DIR)/ctest.xml"'),
            ('@COLLECT_RESULTS@', ''),
            ('@EXTRA_LIB@', 'lib/${DEB_HOST_MULTIARCH}'),
        )
    text = _RULES_HEADER + _RULES_CMAKE
    for marker, value in values + (('@PREFIX@', prefix),
                                   ('@ROSDISTRO@', rosdistro),
                                   ('@PACKAGE@', manifest.debian_name(package.name, rosdistro))):
        text = text.replace(marker, value)
    return text


# -- changelog ---------------------------------------------------------


def _upstream_changes(package_dir):
    """The versions in the package's CHANGELOG.rst: (version, date, lines)."""
    path = os.path.join(package_dir, 'CHANGELOG.rst')
    if not os.path.isfile(path):
        return []
    try:
        from catkin_pkg.changelog import get_changelog_from_path
        changelog = get_changelog_from_path(path)
        entries = []
        for version, date, changes in changelog.foreach_version(reverse=True):
            lines = []
            for change in changes:
                lines.extend(str(change).splitlines())
            entries.append((str(version), date, lines))
        return entries
    except Exception:  # noqa: B902
        # A changelog that cannot be read must not stop a package from
        # being built. It gets the generated entry instead.
        return []


def _changelog(package, package_dir, name, version, os_version, now):
    entries = _upstream_changes(package_dir)
    current = [entry for entry in entries if entry[0] == package.version]
    if current:
        _, date, lines = current[0]
        if isinstance(date, datetime.datetime):
            when = date if date.tzinfo else date.replace(tzinfo=datetime.timezone.utc)
        elif isinstance(date, datetime.date):
            when = datetime.datetime(date.year, date.month, date.day, tzinfo=datetime.timezone.utc)
        else:
            when = now
    else:
        lines, when = [], now
    body = ['  ' + line.rstrip() if line.strip() else '' for line in lines]
    while body and not body[0]:
        body.pop(0)
    while body and not body[-1]:
        body.pop()
    if not body:
        body = ['  * Autogenerated, no changelog for this version found in CHANGELOG.rst.']
    return '%s (%s) %s; urgency=high\n\n%s\n\n -- %s  %s\n' % (
        name, version, os_version, '\n'.join(body),
        _person(package.maintainers[0]), email.utils.format_datetime(when))


# -- copyright ---------------------------------------------------------


def _multiline(text):
    """Text as the continuation lines of a control field."""
    lines = [line.rstrip() for line in text.strip('\n').splitlines()]
    return '\n'.join(' ' + (line if line else '.') for line in lines)


def _copyright(package, package_dir):
    lines = [
        'Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/',
        'Upstream-Name: ' + package.name,
    ]
    for kind, field in (('bugtracker', 'Upstream-Contact'), ('repository', 'Source')):
        urls = [str(url) for url in package.urls if url.type == kind]
        if urls:
            lines.append('%s: %s' % (field, urls[0]))
    for license in package.licenses:
        text = ' See the repository for the full license text.'
        license_file = getattr(license, 'file', None)
        if license_file:
            path = os.path.join(package_dir, license_file)
            if not os.path.isfile(path):
                raise manifest.PackagingError('license file %r is not in the package' % license_file)
            with open(path, errors='replace') as f:
                text = _multiline(f.read())
        lines += [
            '',
            'Files: *',
            'Copyright: See the file headers in the source for details',
            'License: ' + _plain(str(license)),
            text,
        ]
    return '\n'.join(lines) + '\n'
