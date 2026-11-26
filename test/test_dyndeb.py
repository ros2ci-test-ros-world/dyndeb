# Copyright 2026 The ros2ci authors
# SPDX-License-Identifier: Apache-2.0

import datetime
import os

from dyndeb import dh_rosdep
from dyndeb import manifest
from dyndeb import render

import pytest

PACKAGE_XML = '''<?xml version="1.0"?>
<package format="3">
  <name>my_tool</name>
  <version>1.2.3</version>
  <description>
    A tool for tests. It does <b>nothing</b>
    at all.
  </description>
  <maintainer email="a.b@example.invalid">A. B, Jr.</maintainer>
  <license>Apache-2.0</license>
  %(extra)s
  <export><build_type>%(build_type)s</build_type></export>
</package>
'''

NOW = datetime.datetime(2026, 11, 25, 12, 0, 0, tzinfo=datetime.timezone.utc)

RULES = {
    'python3-setuptools': ['python3-setuptools'],
    'python3-pytest': ['python3-pytest'],
    'two': ['libtwo-dev', 'libtwo1'],
    'ros_workspace': ['ros-rolling-ros-workspace'],
    'other_pkg': ['ros-rolling-other-pkg'],
}


def resolver(key):
    return RULES[key]


def make_package(tmp_path, extra='', build_type='ament_python', name=None):
    text = PACKAGE_XML % {'extra': extra, 'build_type': build_type}
    if name:
        text = text.replace('my_tool', name)
    (tmp_path / 'package.xml').write_text(text)
    return manifest.load(str(tmp_path), 'rolling')


def rendered(tmp_path, **kwargs):
    package = make_package(tmp_path, **kwargs)
    return render.render(package, str(tmp_path), 'rolling', 'resolute', 1, resolver, now=NOW)


def field(control, name):
    for line in control.splitlines():
        if line.startswith(name + ': '):
            return line[len(name) + 2:]
    return None


def test_names():
    assert manifest.debian_name('rcl_interfaces', 'rolling') == 'ros-rolling-rcl-interfaces'


def test_dependencies_by_kind(tmp_path):
    package = make_package(tmp_path, extra='''
        <buildtool_depend>python3-setuptools</buildtool_depend>
        <build_depend>two</build_depend>
        <exec_depend>other_pkg</exec_depend>
        <buildtool_export_depend>python3-setuptools</buildtool_export_depend>
        <test_depend>python3-pytest</test_depend>''')
    keys = lambda dependencies: sorted(d.key for d in dependencies)  # noqa: E731
    assert keys(manifest.build_dependencies(package)) == ['python3-setuptools', 'ros_workspace', 'two']
    assert keys(manifest.run_dependencies(package)) == ['other_pkg', 'python3-setuptools', 'ros_workspace']
    assert keys(manifest.test_dependencies(package)) == ['python3-pytest']


def test_depend_tag_counts_for_build_and_run(tmp_path):
    package = make_package(tmp_path, extra='<depend>two</depend>')
    assert 'two' in [d.key for d in manifest.build_dependencies(package)]
    assert 'two' in [d.key for d in manifest.run_dependencies(package)]


@pytest.mark.parametrize('name', manifest.WITHOUT_ROS_WORKSPACE)
def test_no_ros_workspace_for_what_it_is_built_from(tmp_path, name):
    package = make_package(tmp_path, name=name)
    assert manifest.build_dependencies(package) == []
    assert manifest.run_dependencies(package) == []


def test_conditions_are_decided_for_ros_2(tmp_path):
    package = make_package(tmp_path, extra='''
        <exec_depend condition="$ROS_VERSION == 1">ros_one_only</exec_depend>
        <exec_depend condition="$ROS_VERSION == 2">other_pkg</exec_depend>
        <exec_depend condition="$ROS_DISTRO == rolling">two</exec_depend>
        <exec_depend condition="$ROS_DISTRO == humble">humble_only</exec_depend>''')
    assert sorted(d.key for d in manifest.run_dependencies(package)) == ['other_pkg', 'ros_workspace', 'two']


def test_relations_are_sorted_and_carry_versions(tmp_path):
    package = make_package(tmp_path, extra='''
        <exec_depend version_gte="2.0" version_lt="3">two</exec_depend>
        <exec_depend>other_pkg</exec_depend>''')
    assert manifest.relations(manifest.run_dependencies(package), resolver) == [
        'libtwo-dev (<< 3)', 'libtwo-dev (>= 2.0)', 'libtwo1 (<< 3)', 'libtwo1 (>= 2.0)',
        'ros-rolling-other-pkg', 'ros-rolling-ros-workspace']


def test_every_unresolved_key_is_reported(tmp_path):
    package = make_package(tmp_path, extra='''
        <exec_depend>missing_one</exec_depend>
        <exec_depend>two</exec_depend>
        <exec_depend>missing_two</exec_depend>''')
    with pytest.raises(manifest.UnresolvedKeys) as raised:
        manifest.relations(manifest.run_dependencies(package), resolver)
    assert sorted(key for key, _ in raised.value.problems) == ['missing_one', 'missing_two']


def test_control(tmp_path):
    files = rendered(tmp_path, extra='''
        <url type="website">https://example.invalid/my_tool</url>
        <buildtool_depend>python3-setuptools</buildtool_depend>
        <build_depend>two</build_depend>
        <exec_depend>other_pkg</exec_depend>
        <test_depend>python3-pytest</test_depend>
        <test_depend>two</test_depend>
        <conflict>other_pkg</conflict>''')
    control = files['control']
    assert field(control, 'Source') == 'ros-rolling-my-tool'
    assert field(control, 'Package') == 'ros-rolling-my-tool'
    assert field(control, 'Maintainer') == '"A. B, Jr." <a.b@example.invalid>'
    assert field(control, 'Homepage') == 'https://example.invalid/my_tool'
    # The tools first. What only the tests need, which includes what the
    # package needs to run, is left out of a build without tests.
    assert field(control, 'Build-Depends') == (
        'debhelper-compat (= 13), dh-python, python3-all, python3-setuptools, '
        'libtwo-dev, libtwo1, python3-pytest <!nocheck>, ros-rolling-other-pkg <!nocheck>, '
        'ros-rolling-ros-workspace')
    # Install-time dependencies are not decided here.
    assert field(control, 'Depends') == '${python3:Depends}, ${misc:Depends}, ${ros:Depends}'
    assert field(control, 'Conflicts') == 'ros-rolling-other-pkg'
    assert field(control, 'Replaces') is None
    assert 'Description: A tool for tests.\n It does nothing at all.\n' in control


def test_default_homepage(tmp_path):
    assert field(rendered(tmp_path)['control'], 'Homepage') == 'https://index.ros.org/p/my_tool/#rolling'


def test_unresolved_build_dependency_stops_rendering(tmp_path):
    with pytest.raises(manifest.UnresolvedKeys):
        rendered(tmp_path, extra='<build_depend>missing</build_depend>')


def test_unsupported_build_type(tmp_path):
    with pytest.raises(manifest.PackagingError, match='not supported'):
        rendered(tmp_path, build_type='catkin')


def test_bad_revision(tmp_path):
    package = make_package(tmp_path)
    with pytest.raises(manifest.PackagingError, match='revision'):
        render.render(package, str(tmp_path), 'rolling', 'resolute', '1; rm', resolver, now=NOW)


def test_changelog_without_upstream_changelog(tmp_path):
    changelog = rendered(tmp_path)['changelog']
    assert changelog.startswith('ros-rolling-my-tool (1.2.3-1resolute) resolute; urgency=high\n\n  * Autogenerated')
    assert changelog.endswith(' -- "A. B, Jr." <a.b@example.invalid>  Wed, 25 Nov 2026 12:00:00 +0000\n')


def test_changelog_from_upstream_changelog(tmp_path):
    (tmp_path / 'CHANGELOG.rst').write_text('''\
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Changelog for package my_tool
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1.2.3 (2026-07-13)
------------------
* Fixed the thing
* Contributors: Someone

1.2.2 (2026-01-02)
------------------
* Older change
''')
    changelog = rendered(tmp_path)['changelog']
    assert '  * Fixed the thing\n  * Contributors: Someone\n' in changelog
    assert 'Older change' not in changelog
    assert changelog.endswith('  Mon, 13 Jul 2026 00:00:00 +0000\n')


def test_rules(tmp_path):
    rules = rendered(tmp_path)['rules']
    assert rules.startswith('#!/usr/bin/make -f\n')
    assert '--prefix "/opt/ros/rolling"' in rules
    assert '--install-scripts "\\$$base/bin"' in rules
    assert 'export ROS_DISTRO=rolling\n' in rules
    # Without ros_workspace's setup file, the modules under the prefix
    # still have to be found.
    assert 'ROS_PYTHON_DIR = /opt/ros/rolling/lib/$(PYTHON3_VERSION)/site-packages\n' in rules
    assert 'ROS_PYTHONPATH = export PYTHONPATH="$(ROS_PYTHON_DIR)$${PYTHONPATH:+:$$PYTHONPATH}"\n' in rules
    assert '; else $(ROS_PYTHONPATH); fi\n' in rules
    assert '&& python3 setup.py -q egg_info && python3 -m pytest ' in rules
    assert '\texecute_before_dh_gencontrol' not in rules
    assert 'execute_before_dh_gencontrol:\n\tdh_rosdep\n' in rules
    assert '@' not in rules.replace('$@', '')
    assert render.executable('rules') and not render.executable('control')


def test_rules_for_ament_cmake(tmp_path):
    files = rendered(tmp_path, build_type='ament_cmake', extra='<build_depend>two</build_depend>')
    rules = files['rules']
    assert '\tdh $@ -v --buildsystem=cmake --builddirectory=$(BUILD_DIR)\n' in rules
    assert ('\t\t-DCMAKE_INSTALL_PREFIX="/opt/ros/rolling" \\\n'
            '\t\t-DAMENT_PREFIX_PATH="/opt/ros/rolling" \\\n'
            '\t\t-DCMAKE_PREFIX_PATH="/opt/ros/rolling" \\\n'
            '\t\t$(BUILD_TESTING_ARG)\n') in rules
    assert 'ctest --output-on-failure \\\n' in rules
    assert '$(BUILD_DIR)/test_results' in rules
    assert '/opt/ros/rolling/opt/my_tool/lib/\n' in rules
    assert 'execute_before_dh_gencontrol:\n\tdh_rosdep\n' in rules
    assert '@' not in rules.replace('$@', '')
    control = files['control']
    # No Python tools for a CMake package, and its libraries' own
    # dependencies instead of Python's.
    assert field(control, 'Build-Depends') == (
        'debhelper-compat (= 13), libtwo-dev, libtwo1, ros-rolling-ros-workspace')
    assert field(control, 'Depends') == '${shlibs:Depends}, ${misc:Depends}, ${ros:Depends}'


def test_rules_for_cmake(tmp_path):
    rules = rendered(tmp_path, build_type='cmake')['rules']
    assert 'AMENT_PREFIX_PATH' not in rules
    assert 'ctest --output-on-failure --output-junit "$(ROS_TEST_RESULTS_DIR)/ctest.xml" \\\n' in rules
    assert '$(BUILD_DIR)/test_results' not in rules
    assert '/opt/ros/rolling/lib/${DEB_HOST_MULTIARCH}\n' in rules
    assert '@' not in rules.replace('$@', '')


def test_rules_leave_install_scripts_to_setup_cfg(tmp_path):
    (tmp_path / 'setup.cfg').write_text('[install]\ninstall_scripts=$base/lib/my_tool\n')
    assert '--install-scripts' not in rendered(tmp_path)['rules']


def test_copyright_includes_a_license_file(tmp_path):
    (tmp_path / 'LICENSE').write_text('Line one\n\nLine three\n')
    files = rendered(tmp_path, extra='<license file="LICENSE">BSD-3-Clause</license>')
    assert 'License: BSD-3-Clause\n Line one\n .\n Line three\n' in files['copyright']
    assert 'License: Apache-2.0\n See the repository' in files['copyright']


def test_missing_license_file(tmp_path):
    with pytest.raises(manifest.PackagingError, match='license file'):
        rendered(tmp_path, extra='<license file="NOPE">BSD-3-Clause</license>')


def test_binary_package(tmp_path):
    control = tmp_path / 'control'
    control.write_text('Source: ros-rolling-a\n\nPackage: ros-rolling-a\nArchitecture: any\n')
    assert dh_rosdep.binary_package(str(control)) == 'ros-rolling-a'
    control.write_text('Source: a\n\nPackage: a\n\nPackage: a-dev\n')
    with pytest.raises(manifest.PackagingError):
        dh_rosdep.binary_package(str(control))


def test_set_variable_keeps_other_variables(tmp_path):
    path = str(tmp_path / 'p.substvars')
    with open(path, 'w') as f:
        f.write('misc:Depends=\nros:Depends=old\n')
    dh_rosdep.set_variable(path, 'ros:Depends', 'a, b (>= 1)')
    assert open(path).read() == 'misc:Depends=\nros:Depends=a, b (>= 1)\n'
    os.remove(path)
    dh_rosdep.set_variable(path, 'ros:Depends', '')
    assert open(path).read() == 'ros:Depends=\n'
